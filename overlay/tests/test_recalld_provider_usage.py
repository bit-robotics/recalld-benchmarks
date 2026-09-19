"""Tests for Recalld provider usage aggregation."""

from __future__ import annotations

import json

from memory_bench.memory.recalld import (
    _RecalldBase,
    _accumulate_usage_into,
    _build_provider_usage,
    _new_usage_bucket,
)


class _StubRecalld(_RecalldBase):
    _endpoint = "recall"


def _usage_response(
    *,
    input_tokens: int,
    output_tokens: int,
    model: str = "test-model",
    calls: int = 1,
) -> dict:
    return {
        "usage": {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "per_model": {
                model: {
                    "calls": calls,
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                }
            },
        }
    }


def test_build_provider_usage_splits_by_operation() -> None:
    ingestion = _new_usage_bucket()
    _accumulate_usage_into(ingestion, _usage_response(input_tokens=1000, output_tokens=50))

    recall = _new_usage_bucket()
    _accumulate_usage_into(recall, _usage_response(input_tokens=200, output_tokens=10, calls=2))

    result = _build_provider_usage({"ingestion": ingestion, "recall": recall})

    assert result["input_tokens"] == 1200
    assert result["output_tokens"] == 60
    assert result["per_model"]["test-model"]["input_tokens"] == 1200
    assert result["per_model"]["test-model"]["calls"] == 3

    assert result["per_operation"]["ingestion"]["input_tokens"] == 1000
    assert result["per_operation"]["recall"]["input_tokens"] == 200
    assert result["per_operation"]["total"]["input_tokens"] == 1200
    assert result["per_operation"]["total"]["output_tokens"] == 60


def test_provider_accumulates_ingestion_and_retrieve_usage() -> None:
    provider = _StubRecalld()
    provider._agents = {"default": {"agent_id": "a1", "thread_id": "t1"}}

    def fake_request(method: str, path: str, body: dict | None = None) -> dict:
        if path.endswith("/memory") and method == "POST":
            return _usage_response(input_tokens=500, output_tokens=20)
        if path.endswith("/memory/recall"):
            return {
                **_usage_response(input_tokens=100, output_tokens=5),
                "facts": [{"id": "f1", "text": "fact"}],
            }
        return {}

    provider._request = fake_request  # type: ignore[method-assign]

    from memory_bench.models import Document

    # ingest() parses content as LoCoMo session turns, so it must be a JSON array.
    session = json.dumps([{"speaker": "Alice", "text": "hello"}])
    provider.ingest(
        [
            Document(
                id="d1",
                content=session,
                context="Conversation between Alice and Bob (2024-01-01)",
                user_id="default",
            )
        ]
    )
    provider.retrieve("query?", k=3, user_id="default")

    usage = provider.get_provider_usage()
    assert usage is not None
    assert usage["input_tokens"] == 600
    assert usage["per_operation"]["ingestion"]["input_tokens"] == 500
    assert usage["per_operation"]["recall"]["input_tokens"] == 100
    assert usage["per_operation"]["total"]["input_tokens"] == 600
