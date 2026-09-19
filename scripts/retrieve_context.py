#!/usr/bin/env python3
"""
Retrieve context for one benchmark question via an AMB memory provider.

Loads settings from amb/.env (with override), calls the memory tool for a single
query, and writes the retrieved context JSON to --output. No ingest, answer, or judge.

CLI mirrors `omb run` for the shared flags (--dataset, --split, --memory, --unit,
--query-id, --name). Env vars that affect Recalld retrieval are applied as-is:
RECALLD_TOP_K, RECALLD_ANSWER_CONTEXT,
RECALLD_AGENT_MAP_PATH, RECALLD_BASE_URL, RECALLD_API_KEY, etc.

Usage (from repo root, with amb/.env configured):

    # same providers as omb: recalld | recalld-recall
    uv run python scripts/retrieve_context.py \\
        --dataset locomo \\
        --split locomo10 \\
        --memory recalld-recall \\
        --unit conv-30 \\
        --query-id conv-30_q3 \\
        --name recalld-recall-v16 \\
        -o context.txt
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
AMB_DIR = REPO_ROOT / "amb"
AMB_SRC = AMB_DIR / "src"
_AMB_ENV_MARKER = "RECALLD_RETRIEVE_IN_AMB"
_DEFAULT_K = 10

# Same provider names as `omb run --memory …`
RECALLD_MEMORY_PROVIDERS = ("recalld", "recalld-recall")


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


def load_dotenv(path: Path, *, override: bool = True) -> None:
    """Load amb/.env into os.environ.

    override=True so edits to RECALLD_TOP_K / RECALLD_ANSWER_CONTEXT / etc.
    always take effect (matches how AMB's omb CLI loads dotenv).
    """
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if not key:
            continue
        if override or key not in os.environ:
            os.environ[key] = value.strip().strip('"').strip("'")


def bootstrap() -> None:
    if str(AMB_SRC) not in sys.path:
        sys.path.insert(0, str(AMB_SRC))
    load_dotenv(AMB_DIR / ".env", override=True)


def resolve_output_path(raw: str) -> Path:
    path = Path(raw)
    if not path.is_absolute():
        path = REPO_ROOT / path
    return path


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


def effective_top_k(requested_k: int = _DEFAULT_K) -> int:
    override = os.environ.get("RECALLD_TOP_K", "").strip()
    if override:
        try:
            return int(override)
        except ValueError:
            pass
    return requested_k


def context_item_count(raw: dict | None) -> int:
    if not raw:
        return 0
    if "facts" in raw:
        return len(raw.get("facts") or [])
    if "sources" in raw:
        return len(raw.get("sources") or [])
    return 0


def store_dir_for(dataset: str, run_name: str, split: str) -> Path:
    """Match AMB EvalRunner store layout: outputs/<dataset>/<run_name>/_store/<split>/all."""
    return AMB_DIR / "outputs" / dataset / run_name / "_store" / split / "all"


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Retrieve context for one benchmark question via a memory provider. "
            "Flags mirror `omb run`; Recalld behaviour is driven by amb/.env."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Recalld --memory values (same as omb):\n"
            "  recalld         POST /memory/search\n"
            "  recalld-recall  POST /memory/recall\n"
            "\n"
            "Env (amb/.env) applied on every run:\n"
            "  RECALLD_TOP_K, RECALLD_ANSWER_CONTEXT,\n"
            "  RECALLD_AGENT_MAP_PATH, RECALLD_BASE_URL, RECALLD_API_KEY, …"
        ),
    )
    parser.add_argument("--dataset", default="locomo", help="Dataset name (default: locomo)")
    parser.add_argument("--split", default="locomo10", help="Dataset split (default: locomo10)")
    parser.add_argument(
        "--memory",
        default="recalld-recall",
        metavar="NAME",
        help=(
            "Memory provider (default: recalld-recall). "
            "Recalld: recalld | recalld-recall"
        ),
    )
    parser.add_argument(
        "--mode",
        default="rag",
        help="Response mode (accepted for omb parity; only retrieval is performed)",
    )
    parser.add_argument(
        "-n",
        "--name",
        help=(
            "Run name for the agent store path "
            "(default: same as --memory). Match the --name used by omb run."
        ),
    )
    parser.add_argument("--query-id", required=True, help="Benchmark query id (e.g. conv-30_q0)")
    parser.add_argument(
        "--unit",
        required=True,
        help="Conversation / isolation unit (e.g. conv-30)",
    )
    parser.add_argument(
        "-o",
        "--output",
        required=True,
        help="Path to write retrieved context JSON",
    )
    args = parser.parse_args()

    reexec_in_amb_if_needed()
    bootstrap()

    from memory_bench.dataset import get_dataset
    from memory_bench.memory import get_memory_provider

    dataset = get_dataset(args.dataset)
    if args.split not in dataset.splits:
        fail(f"Unknown split {args.split!r}. Available: {', '.join(dataset.splits)}")

    run_name = args.name or args.memory
    query = find_query(dataset, args.split, args.query_id, args.unit)
    output_path = resolve_output_path(args.output)

    try:
        memory = get_memory_provider(args.memory)
    except ValueError as exc:
        fail(str(exc))

    memory.initialize()
    store_dir = store_dir_for(args.dataset, run_name, args.split)
    memory.prepare(
        store_dir,
        unit_ids={args.unit},
        reset=False,
    )

    query_timestamp = query.meta.get("query_timestamp")
    retrieval_query = query.meta.get("retrieval_query") or query.query
    _docs, raw_response = memory.retrieve(
        retrieval_query,
        user_id=args.unit,
        query_timestamp=query_timestamp,
    )

    if not raw_response or context_item_count(raw_response) == 0:
        agent_map = os.environ.get("RECALLD_AGENT_MAP_PATH", "").strip() or str(
            store_dir / "recalld-agents.json"
        )
        fail(
            f"No context retrieved for unit={args.unit!r} "
            f"(agent map: {agent_map})"
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(raw_response, indent=2), encoding="utf-8")

    top_k = effective_top_k()
    item_count = context_item_count(raw_response)
    if "sources" in (raw_response or {}):
        context_key = "sources"
    elif "facts" in (raw_response or {}):
        context_key = "facts"
    else:
        context_key = "items"

    answer_context = os.environ.get("RECALLD_ANSWER_CONTEXT", "facts").strip() or "facts"
    agent_map = os.environ.get("RECALLD_AGENT_MAP_PATH", "").strip() or str(
        store_dir / "recalld-agents.json"
    )

    print(f"query_id: {query.id}")
    print(f"question: {query.query}")
    print(f"memory: {args.memory}")
    print(f"name: {run_name}")
    print(f"top_k: {top_k}")
    print(f"answer_context: {answer_context}")
    print(f"api_mode: {answer_context}")
    print(f"agent_map: {agent_map}")
    print(f"{context_key}_count: {item_count}")
    print(f"output: {output_path}")


if __name__ == "__main__":
    main()
