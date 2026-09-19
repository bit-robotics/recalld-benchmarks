"""Parse AMB LoCoMo documents into provider-ready messages."""

from __future__ import annotations

import json
import re
from typing import Any

_CONTEXT_RE = re.compile(r"Conversation between (.+?) and (.+?) \(")


def parse_speakers(context: str | None) -> tuple[str, str]:
    """Return (speaker_a, speaker_b) from a LoCoMo document context string."""
    if not context:
        return "A", "B"
    match = _CONTEXT_RE.search(context)
    if not match:
        return "A", "B"
    return match.group(1).strip(), match.group(2).strip()


def parse_turns(content: str) -> list[dict[str, Any]]:
    """Parse LoCoMo session content (JSON array of turns) into a list of dicts."""
    turns = json.loads(content)
    if not isinstance(turns, list):
        raise ValueError("LoCoMo document content must be a JSON array of turns")
    return [t for t in turns if isinstance(t, dict)]


def doc_to_mem0_messages(
    content: str,
    context: str | None,
    timestamp: str | None,
) -> list[dict[str, str]]:
    """Map LoCoMo turns to Mem0 message dicts (role + content)."""
    speaker_a, speaker_b = parse_speakers(context)
    messages: list[dict[str, str]] = []
    for turn in parse_turns(content):
        speaker = turn.get("speaker", "")
        text = turn.get("text", "")
        if not text:
            continue
        role = "user" if speaker == speaker_a else "assistant"
        messages.append({"role": role, "content": text})
    return messages


def doc_to_recalld_inputs(
    content: str,
    context: str | None,
    timestamp: str | None,
) -> list[dict[str, Any]]:
    """Map LoCoMo turns to Recalld memory input dicts."""
    speaker_a, speaker_b = parse_speakers(context)
    inputs: list[dict[str, Any]] = []
    for turn in parse_turns(content):
        speaker = turn.get("speaker", "")
        text = turn.get("text", "")
        caption = turn.get("blip_caption", "")
        if caption:
            text = f"{text} [shares a photo: {caption}]" if text else f"[shares a photo: {caption}]"
        if not text:
            continue
        kind = "USER" if speaker == speaker_a else "AGENT"
        item: dict[str, Any] = {
            "kind": kind,
            "content": text,
            "content_type": "text/plain",
            "author": speaker,
        }
        if timestamp:
            item["event_date"] = timestamp
        inputs.append(item)
    return inputs
