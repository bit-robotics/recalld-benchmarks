"""Tests for Recalld adapter answer-context mode."""

from __future__ import annotations

import json
import os
from unittest.mock import MagicMock, patch

import pytest

from memory_bench.memory.recalld import (
    _ANSWER_CONTEXT_FACTS,
    _ANSWER_CONTEXT_SOURCES,
    _RecalldBase,
    _answer_context_mode,
)


class _StubRecalld(_RecalldBase):
    _endpoint = "search"


def test_answer_context_mode_defaults_to_facts(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("RECALLD_ANSWER_CONTEXT", raising=False)
    assert _answer_context_mode() == _ANSWER_CONTEXT_FACTS


def test_answer_context_mode_sources(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RECALLD_ANSWER_CONTEXT", "sources")
    assert _answer_context_mode() == _ANSWER_CONTEXT_SOURCES


def test_retrieve_sends_mode_sources(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RECALLD_ANSWER_CONTEXT", "sources")
    provider = _StubRecalld()
    provider._agents = {"default": {"agent_id": "a1", "thread_id": "t1"}}
    captured: dict = {}

    def fake_request(method: str, path: str, body: dict) -> dict:
        captured["body"] = body
        return {
            "sources": [
                {"id": "s1", "content": "Alice said hello.", "event_date": "2024-01-01"},
            ]
        }

    provider._request = fake_request  # type: ignore[method-assign]
    docs, raw = provider.retrieve("what happened?", k=5, user_id="default")
    assert captured["body"]["mode"] == "sources"
    assert "include_sources" not in captured["body"]
    assert raw == {"sources": [{"text": "Alice said hello.", "event_date": "2024-01-01"}]}
    assert len(docs) == 1


def test_retrieve_facts_mode_shapes_answer_context(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RECALLD_ANSWER_CONTEXT", "facts")
    provider = _StubRecalld()
    provider._agents = {"default": {"agent_id": "a1", "thread_id": "t1"}}

    def fake_request(method: str, path: str, body: dict) -> dict:
        assert body["mode"] == "facts"
        return {
            "facts": [
                {
                    "id": "f1",
                    "text": "Bob prefers mornings.",
                    "kind": "PREFERENCE",
                    "event_date": "2024-02-01",
                }
            ]
        }

    provider._request = fake_request  # type: ignore[method-assign]
    _, raw = provider.retrieve("preference?", k=3, user_id="default")
    assert raw == {
        "facts": [
            {
                "text": "Bob prefers mornings.",
                "kind": "PREFERENCE",
                "event_date": "2024-02-01",
            }
        ]
    }
