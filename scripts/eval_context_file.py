#!/usr/bin/env python3
"""
Evaluate one benchmark question using arbitrary plaintext context.

Loads gold Q/A from the dataset, feeds a context file to the AMB answerer,
then judges the answer: same path as a full run, without ingestion or retrieval.

Usage (from repo root, with amb/.env configured):

    uv run python scripts/eval_context_file.py \\
        --dataset locomo \\
        --split locomo10 \\
        --mode rag \\
        --unit conv-30 \\
        --query-id conv-30_q0 \\
        path/to/context.txt
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
AMB_DIR = REPO_ROOT / "amb"
AMB_SRC = AMB_DIR / "src"
_AMB_ENV_MARKER = "RECALLD_EVAL_IN_AMB"


def fail(msg: str, code: int = 1) -> None:
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(code)


def reexec_in_amb_if_needed() -> None:
    if os.environ.get(_AMB_ENV_MARKER):
        return
    if not (AMB_DIR / "pyproject.toml").exists():
        fail("AMB not set up. Run: uv run python scripts/setup.py")
    try:
        import rich  # noqa: F401
    except ImportError:
        env = os.environ.copy()
        env[_AMB_ENV_MARKER] = "1"
        cmd = ["uv", "run", "python", str(Path(__file__).resolve()), *sys.argv[1:]]
        raise SystemExit(subprocess.call(cmd, cwd=AMB_DIR, env=env))


def load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if key and key not in os.environ:
            os.environ[key] = value.strip().strip('"').strip("'")


def bootstrap() -> None:
    if str(AMB_SRC) not in sys.path:
        sys.path.insert(0, str(AMB_SRC))
    load_dotenv(AMB_DIR / ".env")
    key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if key:
        os.environ.setdefault("GOOGLE_API_KEY", key)


def resolve_context_path(raw: str) -> Path:
    path = Path(raw)
    if not path.is_absolute():
        path = REPO_ROOT / path
    if not path.is_file():
        fail(f"Context file not found: {path}")
    return path


def score_mcq(answer: str, gold_answers: list[str]) -> tuple[bool, str]:
    def norm(s: str) -> str:
        return s.strip().lower().strip("(). ")[:1]

    answer_letter = norm(answer)
    for gold in gold_answers:
        if norm(gold) == answer_letter:
            return True, "letter match"
    return False, f"expected one of {gold_answers!r}, got {answer!r}"


def find_query(dataset, split: str, query_id: str, unit: str | None):
    queries = dataset.load_queries(split)
    if unit:
        queries = [q for q in queries if str(q.user_id) == str(unit)]
    matches = [q for q in queries if q.id == query_id]
    if not matches:
        hint = f" (unit={unit})" if unit else ""
        fail(f"Query not found: {query_id}{hint}")
    if len(matches) > 1:
        fail(f"Multiple queries matched {query_id!r}")
    return matches[0]


def judge_prompt_fn_for_query(dataset, query) -> object:
    if hasattr(dataset, "get_judge_prompt_fn"):
        return dataset.get_judge_prompt_fn(
            query.meta.get("question_type") or query.meta.get("category"),
            meta=query.meta,
        )
    return dataset.build_judge_prompt


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Answer and judge one benchmark question from a plaintext context file",
    )
    parser.add_argument("context_file", help="Plaintext context to feed the answerer")
    parser.add_argument("--dataset", default="locomo", help="Dataset name (default: locomo)")
    parser.add_argument("--split", default="locomo10", help="Dataset split (default: locomo10)")
    parser.add_argument("--mode", default="rag", help="Response mode (default: rag)")
    parser.add_argument("--query-id", required=True, help="Benchmark query id (e.g. conv-30_q0)")
    parser.add_argument(
        "--unit",
        help="Conversation / isolation unit (recommended; e.g. conv-30)",
    )
    args = parser.parse_args()

    reexec_in_amb_if_needed()
    bootstrap()

    from memory_bench.dataset import get_dataset
    from memory_bench.judge import GeminiJudge
    from memory_bench.llm import get_answer_llm
    from memory_bench.modes import get_mode
    from memory_bench.models import QueryResult

    if args.mode != "rag":
        fail(f"Only --mode rag is supported (got {args.mode!r})")

    dataset = get_dataset(args.dataset)
    if args.split not in dataset.splits:
        fail(f"Unknown split {args.split!r}. Available: {', '.join(dataset.splits)}")

    query = find_query(dataset, args.split, args.query_id, args.unit)
    context_path = resolve_context_path(args.context_file)
    context = context_path.read_text(encoding="utf-8")

    task_type = dataset.task_type

    def prompt_fn(q: str, ctx: str, meta=None) -> str:
        return dataset.build_rag_prompt(q, ctx, task_type, args.split, None, meta)

    meta = {**query.meta, "_prompt_fn": prompt_fn}
    mode = get_mode(args.mode, llm=get_answer_llm())
    answer_result = mode.answer_from_context(query.query, context, task_type=task_type, meta=meta)

    answer_llm = getattr(mode, "llm_id", None)
    dataset_judge_llm = dataset.default_judge_llm() if hasattr(dataset, "default_judge_llm") else None
    judge = GeminiJudge(llm=dataset_judge_llm)
    judge_llm = getattr(judge._llm, "model_id", None)

    if not answer_result.context.strip():
        correct, judge_reason = False, "empty context, no memories retrieved"
    elif task_type == "mcq":
        correct, judge_reason = score_mcq(answer_result.answer, query.gold_answers)
    elif hasattr(dataset, "score_result"):
        tmp_result = QueryResult(
            query_id=query.id,
            query=query.query,
            answer=answer_result.answer,
            reasoning=answer_result.reasoning,
            context=answer_result.context,
            context_tokens=0,
            retrieve_time_ms=answer_result.retrieve_time_ms,
            gold_answers=query.gold_answers,
            correct=False,
            judge_reason="",
            meta=query.meta,
        )
        score = float(dataset.score_result(tmp_result, judge._llm))
        correct = score >= 0.5
        judge_reason = f"score={score:.3f}"
    else:
        judge_result = judge.score(
            query.query,
            answer_result.answer,
            query.gold_answers,
            judge_prompt_fn_for_query(dataset, query),
        )
        correct, judge_reason = judge_result.correct, judge_result.reason

    print(f"query_id: {query.id}")
    print(f"question: {query.query}")
    print(f"gold: {query.gold_answers[0] if query.gold_answers else ''}")
    if len(query.gold_answers) > 1:
        print(f"gold_all: {query.gold_answers}")
    print(f"context_file: {context_path}")
    print(f"answer: {answer_result.answer}")
    print(f"reasoning: {answer_result.reasoning}")
    print(f"correct: {correct}")
    print(f"judge_reason: {judge_reason}")
    if answer_llm:
        print(f"answer_llm: {answer_llm}")
    if judge_llm:
        print(f"judge_llm: {judge_llm}")

    sys.exit(0 if correct else 2)


if __name__ == "__main__":
    main()
