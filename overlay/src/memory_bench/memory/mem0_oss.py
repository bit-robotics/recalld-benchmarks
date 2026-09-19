"""Mem0 OSS (self-hosted REST server) memory provider for AMB."""

from __future__ import annotations

import logging
import os
import time
from typing import Any

import httpx

from ..models import Document
from .base import MemoryProvider
from .locomo_parse import doc_to_mem0_messages

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "http://localhost:8888"
REQUEST_TIMEOUT_S = 300.0
MAX_RETRIES = 5


class Mem0OssMemoryProvider(MemoryProvider):
    """Talks to the open-source Mem0 REST server, NOT Mem0 cloud."""

    name = "mem0-oss"
    description = (
        "Mem0 OSS self-hosted server (Docker, default :8888). "
        "Written against server API v2.0.11."
    )
    kind = "cloud"
    provider = "mem0"
    variant = "oss"
    link = "https://github.com/mem0ai/mem0"
    concurrency = 2

    def __init__(self) -> None:
        self._base_url = DEFAULT_BASE_URL
        self._cleared_users: set[str] = set()

    def initialize(self) -> None:
        self._base_url = os.environ.get("MEM0_OSS_BASE_URL", DEFAULT_BASE_URL).rstrip("/")
        try:
            httpx.get(self._base_url, timeout=5.0)
        except Exception as exc:
            raise RuntimeError(
                f"Cannot reach Mem0 OSS server at {self._base_url}. "
                f"Start it first (see README), or set MEM0_OSS_BASE_URL."
            ) from exc
        logger.info("Initialized Mem0 OSS provider (base: %s)", self._base_url)

    def ingest(self, documents: list[Document]) -> None:
        if not documents:
            return

        user_ids = {doc.user_id or "default" for doc in documents}
        for uid in user_ids:
            if uid not in self._cleared_users:
                # A failed reset can contaminate the next run with old memories.
                self._request("DELETE", f"/memories?user_id={uid}")
                self._cleared_users.add(uid)

        for doc in documents:
            uid = doc.user_id or "default"
            messages = doc_to_mem0_messages(doc.content, doc.context, doc.timestamp)
            if not messages:
                continue
            metadata: dict[str, Any] = {"doc_id": doc.id}
            if doc.timestamp:
                metadata["date"] = doc.timestamp
            self._request(
                "POST",
                "/memories",
                {
                    "messages": messages,
                    "user_id": uid,
                    "metadata": metadata,
                },
            )
            logger.debug("Ingested document %s for user %s", doc.id, uid)

    def retrieve(
        self,
        query: str,
        k: int = 10,
        user_id: str | None = None,
        query_timestamp: str | None = None,
    ) -> tuple[list[Document], dict | None]:
        uid = user_id or "default"
        raw = self._request(
            "POST",
            "/search",
            {
                "query": query,
                "filters": {"user_id": uid},
                "top_k": k,
            },
        )
        entries = raw.get("results", raw) if isinstance(raw, dict) else raw
        if not isinstance(entries, list):
            entries = []

        if not entries:
            logger.warning(
                "Mem0 OSS search returned 0 results for user_id %r (query: %r)",
                uid,
                query[:80],
            )

        docs: list[Document] = []
        for entry in entries:
            lines = [entry.get("memory", "")]
            if entry.get("score") is not None:
                lines.append(f"score: {entry['score']:.3f}")
            if entry.get("created_at"):
                lines.append(f"created: {entry['created_at']}")
            meta = entry.get("metadata") or {}
            if meta:
                lines.append(f"metadata: {meta}")
            docs.append(
                Document(id=str(entry.get("id", "")), content="\n".join(lines))
            )

        return docs, raw if isinstance(raw, dict) else {"results": entries}

    def cleanup(self) -> None:
        for uid in list(self._cleared_users):
            try:
                self._request("DELETE", f"/memories?user_id={uid}")
            except Exception as exc:
                logger.warning("Failed to clear Mem0 OSS user %s: %s", uid, exc)
        self._cleared_users.clear()

    def _request(self, method: str, path: str, body: dict | None = None) -> Any:
        url = f"{self._base_url}{path}"
        headers = {"Content-Type": "application/json"}
        last_error: Exception | None = None

        with httpx.Client(timeout=REQUEST_TIMEOUT_S) as client:
            for attempt in range(MAX_RETRIES):
                try:
                    response = client.request(method, url, headers=headers, json=body)
                    if response.status_code == 429 or response.status_code >= 500:
                        backoff = 2 ** attempt * 2
                        last_error = RuntimeError(f"{method} {path} -> {response.status_code}")
                        logger.warning(
                            "Mem0 OSS %s %s returned %s, retry %d/%d in %ds",
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
                            f"Mem0 OSS {method} {path} failed ({response.status_code}): "
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
                        "Mem0 OSS %s %s error (%s), retry %d/%d in %ds",
                        method,
                        path,
                        exc,
                        attempt + 1,
                        MAX_RETRIES,
                        backoff,
                    )
                    time.sleep(backoff)

        raise RuntimeError(
            f"Mem0 OSS {method} {path} failed after {MAX_RETRIES} attempts: {last_error}"
        )
