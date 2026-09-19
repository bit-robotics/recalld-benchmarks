#!/usr/bin/env python3
"""
Per-question flip table between two AMB output JSON files.

Usage (from repo root):

    uv run python scripts/compare_runs.py \\
        --baseline amb/outputs/locomo/recalld/rag/locomo10.json \\
        --candidate amb/outputs/locomo/recalld-recall/rag/locomo10.json

Paths may be absolute or relative to the repo root.

Exit code 0 when no regressions (no question correct in baseline but wrong in candidate).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def load_results(path: Path) -> dict[str, dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return {row["query_id"]: row for row in data.get("results", [])}


def resolve_path(raw: str) -> Path:
    path = Path(raw)
    if not path.is_absolute():
        path = REPO_ROOT / path
    return path


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare two AMB runs question-by-question")
    parser.add_argument("--baseline", required=True, help="Baseline output JSON")
    parser.add_argument("--candidate", required=True, help="Candidate output JSON to compare")
    args = parser.parse_args()

    baseline_path = resolve_path(args.baseline)
    candidate_path = resolve_path(args.candidate)
    if not baseline_path.exists():
        print(f"ERROR: baseline not found: {baseline_path}", file=sys.stderr)
        sys.exit(2)
    if not candidate_path.exists():
        print(f"ERROR: candidate not found: {candidate_path}", file=sys.stderr)
        sys.exit(2)

    base = load_results(baseline_path)
    cand = load_results(candidate_path)
    all_ids = sorted(set(base) | set(cand))

    regressions: list[str] = []
    improvements: list[str] = []
    both_wrong: list[str] = []
    both_right = 0

    for qid in all_ids:
        b = base.get(qid, {})
        c = cand.get(qid, {})
        b_ok = bool(b.get("correct"))
        c_ok = bool(c.get("correct"))
        if b_ok and c_ok:
            both_right += 1
        elif b_ok and not c_ok:
            regressions.append(qid)
        elif not b_ok and c_ok:
            improvements.append(qid)
        else:
            both_wrong.append(qid)

    b_data = json.loads(baseline_path.read_text(encoding="utf-8"))
    c_data = json.loads(candidate_path.read_text(encoding="utf-8"))

    print(f"Baseline:  {baseline_path.name} @ {baseline_path.parent.parent.name}")
    print(f"  accuracy: {b_data.get('accuracy', 0):.4f}  correct: {b_data.get('correct')}/{b_data.get('total_queries')}")
    print(f"Candidate: {candidate_path.name} @ {candidate_path.parent.parent.name}")
    print(f"  accuracy: {c_data.get('accuracy', 0):.4f}  correct: {c_data.get('correct')}/{c_data.get('total_queries')}")
    print()

    def print_rows(title: str, qids: list[str]) -> None:
        if not qids:
            return
        print(title)
        for qid in qids:
            row = cand.get(qid) or base.get(qid) or {}
            gold = (row.get("gold_answers") or [""])[0]
            print(f"  - {qid}: {row.get('query', '')[:72]}")
            print(f"    gold: {gold[:80]}")
        print()

    print_rows("REGRESSIONS (correct in baseline, wrong in candidate):", regressions)
    print_rows("IMPROVEMENTS (wrong in baseline, correct in candidate):", improvements)
    print_rows("STILL WRONG (wrong in both):", both_wrong)

    print(f"Both correct: {both_right}")
    print(f"Net delta: {len(improvements) - len(regressions):+d}")

    if regressions:
        print("\nFAIL: regressions detected.", file=sys.stderr)
        sys.exit(1)
    print("\nOK: no regressions vs baseline.")


if __name__ == "__main__":
    main()
