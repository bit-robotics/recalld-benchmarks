"""Recalld REST API memory providers for AMB."""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Any

import httpx

from ..models import Document
from .base import MemoryProvider
from .locomo_parse import doc_to_recalld_inputs

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://eu.recalld.ai"
REQUEST_TIMEOUT_S = 300.0
MAX_RETRIES = 5


def _env_bool(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _effective_k(requested_k: int) -> int:
    override = os.environ.get("RECALLD_TOP_K", "").strip()
    if override:
        try:
            return int(override)
        except ValueError:
            logger.warning("Invalid RECALLD_TOP_K=%r, using requested k=%d", override, requested_k)
    return requested_k


_ANSWER_CONTEXT_FACTS = "facts"
_ANSWER_CONTEXT_SOURCES = "sources"


def _int_field(value: Any) -> int:
    if isinstance(value, bool) or value is None:
        return 0
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _extract_credits(payload: dict[str, Any]) -> int | None:
    for key in ("credits_charged", "credits"):
        if key in payload:
            return _int_field(payload[key])
    return None


def _new_usage_bucket() -> dict[str, Any]:
    return {
        "input_tokens": 0,
        "output_tokens": 0,
        "credits": None,
        "per_model": {},
    }


def _merge_model_usage(
    target: dict[str, dict[str, int]],
    per_model: dict[str, Any],
) -> None:
    for model_id, usage in per_model.items():
        if not isinstance(usage, dict):
            continue
        row = target.setdefault(
            model_id,
            {"calls": 0, "input_tokens": 0, "output_tokens": 0},
        )
        row["calls"] += _int_field(usage.get("calls"))
        row["input_tokens"] += _int_field(usage.get("input_tokens"))
        row["output_tokens"] += _int_field(usage.get("output_tokens"))
        model_credits = _extract_credits(usage)
        if model_credits is not None:
            row["credits"] = row.get("credits", 0) + model_credits


def _merge_usage_buckets(target: dict[str, Any], source: dict[str, Any]) -> None:
    target["input_tokens"] += _int_field(source.get("input_tokens"))
    target["output_tokens"] += _int_field(source.get("output_tokens"))

    source_credits = source.get("credits")
    if source_credits is not None:
        current = target.get("credits")
        target["credits"] = (current or 0) + _int_field(source_credits)

    per_model = source.get("per_model")
    if isinstance(per_model, dict):
        _merge_model_usage(target["per_model"], per_model)


def _accumulate_usage_into(bucket: dict[str, Any], response: dict[str, Any]) -> None:
    usage = response.get("usage")
    if not isinstance(usage, dict):
        return

    bucket["input_tokens"] += _int_field(usage.get("input_tokens"))
    bucket["output_tokens"] += _int_field(usage.get("output_tokens"))

    response_credits = _extract_credits(response)
    if response_credits is not None:
        current = bucket.get("credits")
        bucket["credits"] = (current or 0) + response_credits

    per_model = usage.get("per_model")
    if isinstance(per_model, dict):
        _merge_model_usage(bucket["per_model"], per_model)


def _build_provider_usage(by_operation: dict[str, dict[str, Any]]) -> dict[str, Any]:
    total = _new_usage_bucket()
    per_operation: dict[str, Any] = {}
    for operation in sorted(by_operation):
        bucket = by_operation[operation]
        per_operation[operation] = {
            "input_tokens": bucket["input_tokens"],
            "output_tokens": bucket["output_tokens"],
            "credits": bucket.get("credits"),
            "per_model": dict(bucket["per_model"]),
        }
        _merge_usage_buckets(total, bucket)

    per_operation["total"] = {
        "input_tokens": total["input_tokens"],
        "output_tokens": total["output_tokens"],
        "credits": total.get("credits"),
        "per_model": dict(total["per_model"]),
    }
    return {
        "input_tokens": total["input_tokens"],
        "output_tokens": total["output_tokens"],
        "credits": total.get("credits"),
        "per_model": dict(total["per_model"]),
        "per_operation": per_operation,
    }


def _answer_context_mode() -> str:
    """RECALLD_ANSWER_CONTEXT selects API mode and answer prompt shape:
    'facts' (default) = extracted facts.
    'sources' = original source excerpts returned by the API.
    """
    mode = os.environ.get("RECALLD_ANSWER_CONTEXT", _ANSWER_CONTEXT_FACTS).strip().lower()
    if mode not in (_ANSWER_CONTEXT_FACTS, _ANSWER_CONTEXT_SOURCES):
        logger.warning("Invalid RECALLD_ANSWER_CONTEXT=%r, using %r", mode, _ANSWER_CONTEXT_FACTS)
        return _ANSWER_CONTEXT_FACTS
    return mode


class _RecalldBase(MemoryProvider):
    """Shared Recalld ingest/agent lifecycle for search and recall variants."""

    kind = "cloud"
    provider = "recalld"
    concurrency = 1

    _endpoint: str = "search"

    def __init__(self) -> None:
        self._api_key = ""
        self._base_url = DEFAULT_BASE_URL
        self._embedding_model = ""
        self._agents: dict[str, dict[str, str]] = {}
        self._map_path: Path | None = None
        self._keep_agents = False
        self._usage_by_operation: dict[str, dict[str, Any]] = {}

    def initialize(self) -> None:
        self._api_key = os.environ.get("RECALLD_API_KEY", "")
        self._base_url = os.environ.get("RECALLD_BASE_URL", DEFAULT_BASE_URL).rstrip("/")
        self._embedding_model = os.environ.get("RECALLD_EMBEDDING_MODEL", "")
        self._keep_agents = _env_bool("RECALLD_KEEP_BENCHMARK_AGENTS")
        if not self._api_key:
            raise ValueError("RECALLD_API_KEY is not set")
        if not self._embedding_model:
            raise ValueError(
                "RECALLD_EMBEDDING_MODEL is not set (e.g. gemini-embedding-002-vertex)"
            )

    def prepare(self, store_dir: Path, unit_ids: set[str] | None = None, reset: bool = True) -> None:
        store_dir.mkdir(parents=True, exist_ok=True)
        env_map = os.environ.get("RECALLD_AGENT_MAP_PATH", "").strip()
        self._map_path = Path(env_map) if env_map else store_dir / "recalld-agents.json"
        self._map_path.parent.mkdir(parents=True, exist_ok=True)
        if self._map_path.exists():
            self._agents = json.loads(self._map_path.read_text(encoding="utf-8"))
            logger.info("Loaded %d Recalld agent(s) from %s", len(self._agents), self._map_path)
        elif not reset:
            raise ValueError(
                f"--skip-ingestion requested, but no Recalld agent map exists at "
                f"{self._map_path.resolve()}"
            )
        else:
            self._agents = {}
        self._usage_by_operation = {}

    def get_provider_usage(self) -> dict[str, Any] | None:
        """Run-level usage from API responses (debug key required)."""
        if not self._usage_by_operation:
            return None
        return _build_provider_usage(self._usage_by_operation)

    def ingest(self, documents: list[Document]) -> None:
        if not documents:
            return
        # Documents in a unit-sequential ingest share the same user_id.
        user_id = documents[0].user_id or "default"
        container = self._get_or_create_agent(user_id)

        for doc in documents:
            inputs = doc_to_recalld_inputs(doc.content, doc.context, doc.timestamp)
            if not inputs:
                continue
            raw = self._request(
                "POST",
                f"/v1/agents/{container['agent_id']}/memory",
                {
                    "thread_id": container["thread_id"],
                    "inputs": inputs,
                },
            )
            if isinstance(raw, dict):
                self._accumulate_operation_usage("ingestion", raw)
            logger.debug("Ingested document %s into agent %s", doc.id, container["agent_id"])

    def retrieve(
        self,
        query: str,
        k: int = 10,
        user_id: str | None = None,
        query_timestamp: str | None = None,
    ) -> tuple[list[Document], dict | None]:
        uid = user_id or "default"
        container = self._agents.get(uid)
        if not container:
            logger.warning("No Recalld agent for user_id %r; ingest must run first", uid)
            return [], None

        limit = _effective_k(k)
        answer_mode = _answer_context_mode()
        body: dict[str, Any] = {
            "thread_id": container["thread_id"],
            "query": query,
            "limit": limit,
            "mode": answer_mode,
        }
        if query_timestamp:
            body["event_date"] = query_timestamp

        raw = self._request(
            "POST",
            f"/v1/agents/{container['agent_id']}/memory/{self._endpoint}",
            body,
        )
        if isinstance(raw, dict):
            self._accumulate_operation_usage(self._endpoint, raw)

        if answer_mode == _ANSWER_CONTEXT_SOURCES:
            sources = raw.get("sources", []) if isinstance(raw, dict) else []
            if not sources:
                logger.warning(
                    "Recalld %s returned 0 sources for user_id %r (query: %r)",
                    self._endpoint,
                    uid,
                    query[:80],
                )
            docs: list[Document] = []
            for source in sources:
                content = source.get("content", "")
                lines = [content]
                if source.get("event_date"):
                    lines.append(f"date: {source['event_date']}")
                if source.get("kind"):
                    lines.append(f"kind: {source['kind']}")
                docs.append(Document(id=str(source.get("id", "")), content="\n".join(lines)))
            answer_sources = []
            for source in sources:
                entry: dict[str, Any] = {"text": source.get("content", "")}
                if source.get("event_date"):
                    entry["event_date"] = source["event_date"]
                answer_sources.append(entry)
            return docs, {"sources": answer_sources}

        facts = raw.get("facts", []) if isinstance(raw, dict) else []
        if not facts:
            logger.warning(
                "Recalld %s returned 0 facts for user_id %r (query: %r)",
                self._endpoint,
                uid,
                query[:80],
            )

        docs = []
        for fact in facts:
            lines = [fact.get("text", "")]
            if fact.get("event_date"):
                lines.append(f"date: {fact['event_date']}")
            if fact.get("kind"):
                lines.append(f"kind: {fact['kind']}")
            docs.append(Document(id=str(fact.get("id", "")), content="\n".join(lines)))

        answer_facts = []
        for fact in facts:
            entry = {"text": fact.get("text", "")}
            for key in ("kind", "event_date", "referenced_at", "historical"):
                if fact.get(key):
                    entry[key] = fact[key]
            answer_facts.append(entry)
        return docs, {"facts": answer_facts}

    def cleanup(self) -> None:
        if self._keep_agents:
            logger.info(
                "RECALLD_KEEP_BENCHMARK_AGENTS=true, preserving %d agent(s)",
                len(self._agents),
            )
            return

        for uid, container in list(self._agents.items()):
            try:
                self._request("DELETE", f"/v1/agents/{container['agent_id']}")
                logger.info("Deleted Recalld agent %s (user_id=%s)", container["agent_id"], uid)
            except Exception as exc:
                logger.warning("Failed to delete agent %s: %s", container.get("agent_id"), exc)
        self._agents = {}
        if self._map_path and self._map_path.exists() and not os.environ.get("RECALLD_AGENT_MAP_PATH"):
            self._map_path.unlink(missing_ok=True)

    def _accumulate_operation_usage(self, operation: str, response: dict[str, Any]) -> None:
        bucket = self._usage_by_operation.setdefault(operation, _new_usage_bucket())
        _accumulate_usage_into(bucket, response)

    def _get_or_create_agent(self, user_id: str) -> dict[str, str]:
        existing = self._agents.get(user_id)
        if existing:
            return existing

        agent = self._request(
            "POST",
            "/v1/agents",
            {
                "name": f"amb-{user_id}"[:120],
                "description": "AMB benchmark container",
                "embedding_model": self._embedding_model,
            },
        )
        agent_id = agent["id"]
        thread = self._request("POST", f"/v1/agents/{agent_id}/threads", {})
        container = {"agent_id": agent_id, "thread_id": thread["id"]}
        self._agents[user_id] = container
        self._save_map()
        logger.debug("Created Recalld agent %s for user_id %s", agent_id, user_id)
        return container

    def _save_map(self) -> None:
        if self._map_path:
            self._map_path.write_text(json.dumps(self._agents, indent=2), encoding="utf-8")

    def _request(self, method: str, path: str, body: dict | None = None) -> dict[str, Any]:
        url = f"{self._base_url}{path}"
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        last_error: Exception | None = None

        with httpx.Client(timeout=REQUEST_TIMEOUT_S) as client:
            for attempt in range(MAX_RETRIES):
                try:
                    response = client.request(method, url, headers=headers, json=body)
                    if response.status_code == 429 or response.status_code >= 500:
                        retry_after = int(response.headers.get("retry-after", 0))
                        backoff = max(retry_after, 2 ** attempt * 2)
                        last_error = RuntimeError(f"{method} {path} -> {response.status_code}")
                        logger.warning(
                            "Recalld %s %s returned %s, retry %d/%d in %ds",
                            method,
                            path,
                            response.status_code,
                            attempt + 1,
                            MAX_RETRIES,
                            backoff,
                        )
                        time.sleep(backoff)
                        continue
                    if not response.is_success:
                        raise RuntimeError(
                            f"Recalld {method} {path} failed ({response.status_code}): "
                            f"{response.text}"
                        )
                    if response.status_code == 204 or not response.content:
                        return {}
                    return response.json()
                except RuntimeError:
                    raise
                except Exception as exc:
                    last_error = exc
                    backoff = 2 ** attempt * 2
                    logger.warning(
                        "Recalld %s %s error (%s), retry %d/%d in %ds",
                        method,
                        path,
                        exc,
                        attempt + 1,
                        MAX_RETRIES,
                        backoff,
                    )
                    time.sleep(backoff)

        raise RuntimeError(
            f"Recalld {method} {path} failed after {MAX_RETRIES} attempts: {last_error}"
        )


class RecalldMemoryProvider(_RecalldBase):
    name = "recalld"
    description = "Recalld REST API: fact extraction + vector search (POST /memory/search)."
    variant = "search"
    link = "https://recalld.ai"
    _endpoint = "search"


class RecalldRecallMemoryProvider(_RecalldBase):
    name = "recalld-recall"
    description = (
        "Recalld REST API: server-side LLM fact selection (POST /memory/recall). "
        "Use --mode rag: it returns selected facts, not a final answer."
    )
    variant = "recall"
    link = "https://recalld.ai"
    _endpoint = "recall"

    def direct_answer(
        self,
        query: str,
        user_id: str | None = None,
        query_timestamp: str | None = None,
    ) -> tuple[str, str, dict | None]:
        docs, raw = self.retrieve(
            query, k=10, user_id=user_id, query_timestamp=query_timestamp
        )
        if not docs:
            answer = "The information is not available in the memories."
            return answer, "", raw

        lines = [doc.content.split("\n")[0] for doc in docs]
        context = "\n".join(f"- {line}" for line in lines if line)
        answer = "\n".join(line for line in lines if line)
        return answer, context, raw

