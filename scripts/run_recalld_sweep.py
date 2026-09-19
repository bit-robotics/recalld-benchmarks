#!/usr/bin/env python3
"""
Run a Recalld retrieval ablation sweep: ingest once, score every k/endpoint combo.

The first matrix entry ingests conversation documents into Recalld and preserves
agents (RECALLD_KEEP_BENCHMARK_AGENTS). Subsequent entries reuse the same agents
via --skip-ingestion and a shared agent map (RECALLD_AGENT_MAP_PATH).

Usage (from repo root):

    uv run python scripts/run_recalld_sweep.py --unit conv-30 --k 10 25 50 100
    uv run python scripts/run_recalld_sweep.py --unit conv-30 --k 10 25 50 100 --resume
    uv run python scripts/run_recalld_sweep.py --sweep-id <id> --cleanup --yes
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
AMB_DIR = REPO_ROOT / "amb"
SWEEPS_DIR = REPO_ROOT / "experiments" / "sweeps"

DEFAULT_ENDPOINTS = ("search", "recall")
DEFAULT_K = (10, 25, 50, 100)
DEFAULT_DATASET = "locomo"
DEFAULT_SPLIT = "locomo10"
DEFAULT_MODE = "rag"

ENDPOINT_MEMORY = {
    "search": "recalld",
    "recall": "recalld-recall",
}


def fail(msg: str, code: int = 1) -> None:
    print(f"\nERROR: {msg}", file=sys.stderr)
    sys.exit(code)


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def default_sweep_id(unit: str) -> str:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    safe_unit = unit.replace("/", "-")
    return f"{safe_unit}-{stamp}"


def sweep_dir(sweep_id: str) -> Path:
    return SWEEPS_DIR / sweep_id


def state_path(sweep_id: str) -> Path:
    return sweep_dir(sweep_id) / "state.json"


def agent_map_path(sweep_id: str) -> Path:
    return sweep_dir(sweep_id) / "recalld-agents.json"


def output_path(dataset: str, run_name: str, mode: str, split: str) -> Path:
    return AMB_DIR / "outputs" / dataset / run_name / mode / f"{split}.json"


def build_run_name(endpoint: str, k: int, sweep_id: str) -> str:
    return f"recalld-{endpoint}-k{k}-{sweep_id}"


def build_matrix(endpoints: list[str], k_values: list[int]) -> list[dict[str, Any]]:
    matrix: list[dict[str, Any]] = []
    for endpoint in endpoints:
        for k in k_values:
            matrix.append({"endpoint": endpoint, "k": k, "memory": ENDPOINT_MEMORY[endpoint]})
    return matrix


def load_dotenv(path: Path) -> dict[str, str]:
    env: dict[str, str] = {}
    if not path.exists():
        return env
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        env[key.strip()] = value.strip().strip('"').strip("'")
    return env


def load_state(sweep_id: str) -> dict[str, Any]:
    path = state_path(sweep_id)
    if not path.exists():
        fail(f"No sweep state at {path}. Run the sweep first or check --sweep-id.")
    return json.loads(path.read_text(encoding="utf-8"))


def save_state(state: dict[str, Any]) -> None:
    path = state_path(state["sweep_id"])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2), encoding="utf-8")


def experiment_key(endpoint: str, k: int) -> str:
    return f"{endpoint}-k{k}"


def init_state(
    sweep_id: str,
    *,
    dataset: str,
    split: str,
    mode: str,
    unit: str,
    query_limit: int | None,
    endpoints: list[str],
    k_values: list[int],
) -> dict[str, Any]:
    map_path = agent_map_path(sweep_id)
    experiments: list[dict[str, Any]] = []
    for entry in build_matrix(endpoints, k_values):
        endpoint = entry["endpoint"]
        k = entry["k"]
        run_name = build_run_name(endpoint, k, sweep_id)
        experiments.append(
            {
                "key": experiment_key(endpoint, k),
                "endpoint": endpoint,
                "k": k,
                "memory": entry["memory"],
                "run_name": run_name,
                "status": "pending",
                "output_path": str(output_path(dataset, run_name, mode, split)),
                "command": None,
                "answer_llm": None,
                "judge_llm": None,
                "accuracy": None,
                "avg_context_tokens": None,
                "completed_at": None,
                "error": None,
            }
        )

    return {
        "sweep_id": sweep_id,
        "created_at": utc_now(),
        "updated_at": utc_now(),
        "dataset": dataset,
        "split": split,
        "mode": mode,
        "unit": unit,
        "query_limit": query_limit,
        "endpoints": endpoints,
        "k_values": k_values,
        "agent_map_path": str(map_path),
        "ingestion_complete": False,
        "experiments": experiments,
    }


def merge_state(existing: dict[str, Any], fresh: dict[str, Any]) -> dict[str, Any]:
    """Keep completed experiment metadata when resuming with the same matrix."""
    by_key = {exp["key"]: exp for exp in existing.get("experiments", [])}
    merged_experiments: list[dict[str, Any]] = []
    for exp in fresh["experiments"]:
        prev = by_key.get(exp["key"])
        if prev and prev.get("status") == "complete":
            merged_experiments.append(prev)
        else:
            merged_experiments.append(exp)
    existing.update(
        {
            "updated_at": utc_now(),
            "dataset": fresh["dataset"],
            "split": fresh["split"],
            "mode": fresh["mode"],
            "unit": fresh["unit"],
            "query_limit": fresh["query_limit"],
            "endpoints": fresh["endpoints"],
            "k_values": fresh["k_values"],
            "agent_map_path": fresh["agent_map_path"],
            "experiments": merged_experiments,
        }
    )
    return existing


def build_amb_command(
    *,
    dataset: str,
    split: str,
    memory: str,
    mode: str,
    unit: str,
    query_limit: int | None,
    run_name: str,
    skip_ingestion: bool,
) -> list[str]:
    uv = shutil.which("uv")
    if not uv:
        fail("uv not found. Install from https://docs.astral.sh/uv/")

    cmd = [
        uv,
        "run",
        "omb",
        "run",
        "--dataset",
        dataset,
        "--split",
        split,
        "--memory",
        memory,
        "--mode",
        mode,
        "--unit",
        unit,
        "--name",
        run_name,
    ]
    if query_limit is not None:
        cmd.extend(["--query-limit", str(query_limit)])
    if skip_ingestion:
        cmd.append("--skip-ingestion")
    return cmd


def run_amb(cmd: list[str], extra_env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.update(load_dotenv(AMB_DIR / ".env"))
    env.update(extra_env)
    print("\n$ " + " ".join(cmd))
    return subprocess.run(cmd, cwd=AMB_DIR, env=env, text=True)


def summarize_output(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return {
        "accuracy": data.get("accuracy"),
        "answer_llm": data.get("answer_llm"),
        "judge_llm": data.get("judge_llm"),
        "avg_context_tokens": data.get("avg_context_tokens"),
    }


def delete_recalld_agents(agent_map: dict[str, dict[str, str]], env: dict[str, str]) -> None:
    api_key = env.get("RECALLD_API_KEY", "")
    base_url = env.get("RECALLD_BASE_URL", "https://eu.recalld.ai").rstrip("/")
    if not api_key:
        fail("RECALLD_API_KEY is not set in amb/.env")

    for user_id, container in agent_map.items():
        agent_id = container.get("agent_id")
        if not agent_id:
            continue
        url = f"{base_url}/v1/agents/{agent_id}"
        request = urllib.request.Request(url, method="DELETE", headers={"Authorization": f"Bearer {api_key}"})
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                if response.status not in (200, 204):
                    body = response.read().decode("utf-8", errors="replace")
                    fail(f"Failed to delete agent {agent_id}: {response.status} {body}")
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                print(f"  agent {agent_id} ({user_id}): already deleted")
                continue
            body = exc.read().decode("utf-8", errors="replace")
            fail(f"Failed to delete agent {agent_id}: {exc.code} {body}")
        print(f"  deleted agent {agent_id} ({user_id})")


def cmd_cleanup(args: argparse.Namespace) -> int:
    if not args.sweep_id:
        fail("--cleanup requires --sweep-id")

    state = load_state(args.sweep_id)
    map_file = Path(state["agent_map_path"])
    if not map_file.exists():
        print(f"No agent map at {map_file}; nothing to delete.")
    else:
        agent_map = json.loads(map_file.read_text(encoding="utf-8"))
        if not agent_map:
            print("Agent map is empty.")
        else:
            print(f"About to delete {len(agent_map)} Recalld agent(s) from sweep {args.sweep_id}:")
            for user_id, container in agent_map.items():
                print(f"  - {container.get('agent_id')} (user_id={user_id})")
            if not args.yes:
                answer = input("Proceed? [y/N] ").strip().lower()
                if answer not in {"y", "yes"}:
                    print("Aborted.")
                    return 0
            env = load_dotenv(AMB_DIR / ".env")
            delete_recalld_agents(agent_map, env)
            map_file.unlink(missing_ok=True)

    sweep_path = sweep_dir(args.sweep_id)
    if sweep_path.exists():
        shutil.rmtree(sweep_path)
        print(f"Removed sweep state directory {sweep_path}")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    if not AMB_DIR.exists():
        fail("amb/ not found. Run: uv run python scripts/setup.py")

    unit = args.unit
    if not unit:
        fail("--unit is required (e.g. conv-30)")

    sweep_id = args.sweep_id or default_sweep_id(unit)
    endpoints = args.endpoints or list(DEFAULT_ENDPOINTS)
    k_values = args.k or list(DEFAULT_K)

    for endpoint in endpoints:
        if endpoint not in ENDPOINT_MEMORY:
            fail(f"Unknown endpoint {endpoint!r}. Choose from: {', '.join(ENDPOINT_MEMORY)}")

    fresh = init_state(
        sweep_id,
        dataset=args.dataset,
        split=args.split,
        mode=args.mode,
        unit=unit,
        query_limit=args.query_limit,
        endpoints=endpoints,
        k_values=k_values,
    )

    path = state_path(sweep_id)
    if path.exists():
        if not args.resume:
            fail(
                f"Sweep {sweep_id} already exists at {path}. "
                "Pass --resume to continue or choose a new --sweep-id."
            )
        state = merge_state(load_state(sweep_id), fresh)
    else:
        state = fresh
        save_state(state)

    map_file = Path(state["agent_map_path"])
    map_file.parent.mkdir(parents=True, exist_ok=True)

    print(f"Sweep ID:     {sweep_id}")
    print(f"State file:   {path}")
    print(f"Agent map:    {map_file}")
    print(f"Unit:         {unit}")
    print(f"Matrix:       {len(state['experiments'])} experiments")
    print(f"Ingestion:    {'done' if state.get('ingestion_complete') else 'pending'}")

    ingestion_done = bool(state.get("ingestion_complete"))
    if not ingestion_done and map_file.exists():
        map_data = json.loads(map_file.read_text(encoding="utf-8") or "{}")
        any_complete = any(
            e.get("status") == "complete" and Path(e["output_path"]).exists()
            for e in state["experiments"]
        )
        if map_data and any_complete:
            ingestion_done = True
            state["ingestion_complete"] = True
            save_state(state)

    for exp in state["experiments"]:
        if exp.get("status") == "complete":
            out = Path(exp["output_path"])
            if out.exists():
                print(f"\n[skip] {exp['key']} already complete: {out}")
                continue
            print(f"\n[redo] {exp['key']} marked complete but output missing; re-running")

        skip_ingestion = ingestion_done

        cmd = build_amb_command(
            dataset=state["dataset"],
            split=state["split"],
            memory=exp["memory"],
            mode=state["mode"],
            unit=state["unit"],
            query_limit=state["query_limit"],
            run_name=exp["run_name"],
            skip_ingestion=skip_ingestion,
        )
        extra_env = {
            "RECALLD_KEEP_BENCHMARK_AGENTS": "true",
            "RECALLD_AGENT_MAP_PATH": str(map_file.resolve()),
            "RECALLD_TOP_K": str(exp["k"]),
        }

        exp["status"] = "running"
        exp["command"] = " ".join(cmd)
        state["updated_at"] = utc_now()
        save_state(state)

        print(f"\n=== {exp['key']} ({exp['memory']}, k={exp['k']}, skip_ingestion={skip_ingestion}) ===")
        result = run_amb(cmd, extra_env)

        out = Path(exp["output_path"])
        if result.returncode != 0 or not out.exists():
            exp["status"] = "failed"
            exp["error"] = (
                f"omb exited {result.returncode}"
                if result.returncode != 0
                else f"expected output missing: {out}"
            )
            exp["completed_at"] = utc_now()
            state["updated_at"] = utc_now()
            save_state(state)
            fail(
                f"Experiment {exp['key']} failed. "
                "Fix the issue and re-run with --resume. "
                "Skip-ingestion experiments were not started."
                if not ingestion_done
                else f"Experiment {exp['key']} failed. Re-run with --resume to retry."
            )

        summary = summarize_output(out)
        exp.update(summary)
        exp["status"] = "complete"
        exp["error"] = None
        exp["completed_at"] = utc_now()

        if not ingestion_done:
            ingestion_done = True
            state["ingestion_complete"] = True
            if not map_file.exists():
                fail(f"Ingestion finished but agent map not found at {map_file}")

        state["updated_at"] = utc_now()
        save_state(state)
        acc = summary.get("accuracy")
        acc_label = f"{acc:.1%}" if isinstance(acc, (int, float)) else "n/a"
        print(f"Done: accuracy={acc_label} avg_context_tokens={summary.get('avg_context_tokens')}")

    print(f"\nSweep {sweep_id} complete.")
    print(f"Verify retrievals, e.g.:")
    for exp in state["experiments"][:2]:
        print(
            f"  uv run python scripts/verify_retrievals.py --name {exp['run_name']} "
            f"--mode {state['mode']}"
        )
    print(f"\nCleanup when finished:")
    print(f"  uv run python scripts/run_recalld_sweep.py --sweep-id {sweep_id} --cleanup")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Recalld retrieval ablation sweep runner")
    parser.add_argument("--sweep-id", help="Sweep identifier (default: <unit>-<timestamp>)")
    parser.add_argument("--unit", help="LoCoMo conversation unit, e.g. conv-30")
    parser.add_argument("--query-limit", type=int, help="Limit questions per run")
    parser.add_argument("--dataset", default=DEFAULT_DATASET)
    parser.add_argument("--split", default=DEFAULT_SPLIT)
    parser.add_argument("--mode", default=DEFAULT_MODE, choices=["rag"])
    parser.add_argument(
        "--endpoints",
        nargs="+",
        choices=list(ENDPOINT_MEMORY),
        help="Recalld endpoints to sweep (default: search recall)",
    )
    parser.add_argument("--k", nargs="+", type=int, help="Top-k values (default: 10 25 50 100)")
    parser.add_argument("--resume", action="store_true", help="Resume an existing sweep")
    parser.add_argument("--cleanup", action="store_true", help="Delete preserved agents for a sweep")
    parser.add_argument("--yes", action="store_true", help="Skip confirmation prompts (cleanup)")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if args.cleanup:
        return cmd_cleanup(args)
    return cmd_run(args)


if __name__ == "__main__":
    sys.exit(main())
