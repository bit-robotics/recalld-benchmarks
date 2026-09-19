#!/usr/bin/env python3
"""
Checks that a benchmark run actually retrieved memories.

A run can fail silently: if retrieval returns nothing, the answer model guesses
and the score looks real but is meaningless. This script makes that impossible
to miss.

Usage (from the repo root, after a run):

    uv run python scripts/verify_retrievals.py recalld
    uv run python scripts/verify_retrievals.py recalld-recall --mode rag
    uv run python scripts/verify_retrievals.py --name recalld-search-k25-<sweep-id> --mode rag
    uv run python scripts/verify_retrievals.py --path amb/outputs/locomo/<run-name>/rag/locomo10.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from report_validation import has_context, load_report

REPO_ROOT = Path(__file__).resolve().parent.parent
OUTPUTS_DIR = REPO_ROOT / "amb" / "outputs" / "locomo"


def fail(msg: str) -> None:
    print(f"\nFAIL: {msg}", file=sys.stderr)
    sys.exit(1)


def resolve_output_path(
    *,
    provider: str | None,
    mode: str,
    split: str,
    name: str | None,
    path: str | None,
    dataset: str,
) -> Path:
    if path:
        candidate = Path(path)
        if not candidate.is_absolute():
            candidate = REPO_ROOT / candidate
        return candidate

    run_name = name or provider
    if not run_name:
        fail("Provide a provider, --name, or --path")

    return REPO_ROOT / "amb" / "outputs" / dataset / run_name / mode / f"{split}.json"


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify AMB retrieval contexts are non-empty")
    parser.add_argument("provider", nargs="?", help="Default AMB provider name (e.g. recalld)")
    parser.add_argument("--mode", default="rag", help="AMB response mode (default: rag)")
    parser.add_argument("--split", default="locomo10", help="Dataset split (default: locomo10)")
    parser.add_argument("--dataset", default="locomo", help="Dataset name (default: locomo)")
    parser.add_argument(
        "--name",
        help="AMB run name from --name (e.g. recalld-search-k25-<sweep-id>)",
    )
    parser.add_argument("--path", help="Direct path to an AMB output JSON file")
    args = parser.parse_args()

    path = resolve_output_path(
        provider=args.provider,
        mode=args.mode,
        split=args.split,
        name=args.name,
        path=args.path,
        dataset=args.dataset,
    )
    if not path.exists():
        fail(f"No output file at {path}. Run a benchmark first.")

    data = load_report(path)
    results = data.get("results", [])
    if not results:
        fail(f"Output file has no results: {path}")

    empty: list[str] = []
    rows: list[tuple[str, int]] = []

    for r in results:
        qid = r.get("query_id", "?")
        count = 1 if has_context(r.get("context")) else 0
        rows.append((qid, count))
        if count == 0:
            empty.append(qid)

    label = args.name or args.provider or path.stem
    print(f"\nRun:       {label}")
    print(f"Mode:      {args.mode}")
    print(f"Output:    {path}")
    print(f"Questions: {len(rows)}\n")
    print("Retrieval per question:")
    for qid, count in rows:
        marker = "  <-- EMPTY CONTEXT" if count == 0 else ""
        print(f"  {qid}: {'retrieved' if count else 'empty'}{marker}")

    print("\n--- 3 sample contexts (for human review) ---")
    for r in results[:3]:
        qid = r.get("query_id", "?")
        print(f"\n### {qid}")
        print(f"Question: {r.get('query', '')}")
        ctx = r.get("context") or "(empty)"
        if not isinstance(ctx, str):
            ctx = json.dumps(ctx)
        preview = ctx[:500] + ("..." if len(ctx) > 500 else "")
        print(f"Context ({len(ctx)} chars):\n{preview}")

    if empty:
        fail(
            f"{len(empty)} of {len(rows)} questions got EMPTY context: "
            f"{', '.join(empty)}\n"
            f"Do NOT trust scores from this run. Fix retrieval first."
        )

    print(f"\nOK: every question retrieved at least some context.")


if __name__ == "__main__":
    main()
