#!/usr/bin/env python3
"""
Aggregate committed benchmark reports into the headline numbers.

Reads every report in a results/ run directory (``*.json`` or ``*.json.gz``) and
recomputes accuracy and mean context tokens from the per-question rows, so the
published figures can be checked without re-running the benchmark.

Usage (from the repo root):

    uv run python scripts/summarize_results.py
    uv run python scripts/summarize_results.py results/2026-08-06_locomo_recalld-recall-sources
    uv run python scripts/summarize_results.py --json
"""

from __future__ import annotations

import argparse
import gzip
import json
import sys
from pathlib import Path
from typing import Any

from report_validation import has_context

REPO_ROOT = Path(__file__).resolve().parent.parent
RESULTS_DIR = REPO_ROOT / "results"


def load_report(path: Path) -> dict[str, Any]:
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8") as handle:
        return json.load(handle)


def find_reports(run_dir: Path) -> list[Path]:
    return sorted(
        p for p in run_dir.iterdir() if p.suffix == ".gz" or p.suffix == ".json"
    )


def summarize(run_dir: Path) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    total = correct = 0
    context_tokens: list[int] = []
    models: set[str] = set()
    judges: set[str] = set()
    empty: list[str] = []

    for path in find_reports(run_dir):
        report = load_report(path)
        results = report.get("results", [])
        if not results:
            raise SystemExit(f"ERROR: {path} has no results")

        n = len(results)
        c = sum(1 for r in results if r.get("correct"))
        tokens = [r["context_tokens"] for r in results if r.get("context_tokens") is not None]
        empty.extend(r.get("query_id", "?") for r in results if not has_context(r.get("context")))

        total += n
        correct += c
        context_tokens.extend(tokens)
        models.add(str(report.get("answer_llm")))
        judges.add(str(report.get("judge_llm")))
        rows.append(
            {
                "report": path.name,
                "unit": path.stem.replace(".json", ""),
                "questions": n,
                "correct": c,
                "accuracy": c / n,
                "avg_context_tokens": round(sum(tokens) / len(tokens), 1) if tokens else None,
            }
        )

    if not rows:
        raise SystemExit(f"ERROR: no reports found in {run_dir}")

    return {
        "run": run_dir.name,
        "reports": len(rows),
        "questions": total,
        "correct": correct,
        "accuracy": correct / total,
        "avg_context_tokens": round(sum(context_tokens) / len(context_tokens), 1),
        "answer_llm": sorted(models),
        "judge_llm": sorted(judges),
        "empty_retrievals": empty,
        "per_report": rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Summarize committed benchmark reports")
    parser.add_argument(
        "run_dir",
        nargs="?",
        help="Results run directory (default: every run directory under results/)",
    )
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of a table")
    args = parser.parse_args()

    if args.run_dir:
        run_dirs = [Path(args.run_dir)]
    else:
        run_dirs = sorted(p for p in RESULTS_DIR.iterdir() if p.is_dir())
    if not run_dirs:
        print(f"No run directories under {RESULTS_DIR}", file=sys.stderr)
        return 1

    summaries = [summarize(d) for d in run_dirs]

    if args.json:
        print(json.dumps(summaries, indent=2))
        return 0

    for s in summaries:
        print(f"\n{s['run']}")
        print(f"  answer  {', '.join(s['answer_llm'])}")
        print(f"  judge   {', '.join(s['judge_llm'])}\n")
        print(f"  {'unit':10} {'questions':>9} {'correct':>8} {'accuracy':>9} {'ctx tokens':>11}")
        for r in s["per_report"]:
            print(
                f"  {r['unit']:10} {r['questions']:>9} {r['correct']:>8} "
                f"{r['accuracy'] * 100:>8.1f}% {r['avg_context_tokens']:>11}"
            )
        print(
            f"  {'TOTAL':10} {s['questions']:>9} {s['correct']:>8} "
            f"{s['accuracy'] * 100:>8.1f}% {s['avg_context_tokens']:>11}"
        )
        if s["empty_retrievals"]:
            print(
                f"  WARNING: {len(s['empty_retrievals'])} question(s) retrieved nothing "
                f"and are still counted above: {', '.join(s['empty_retrievals'])}"
            )
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
