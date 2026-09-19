#!/usr/bin/env python3
"""
Set up the AMB benchmark harness. Run from the repo root:

    uv run python scripts/setup.py

Steps:
  1. Clone agent-memory-benchmark into ./amb (if missing)
  2. Checkout the pinned commit
  3. Copy provider adapters and tests from ./overlay into the clone
  4. Apply every patch in ./patches, in filename order
  5. uv sync inside amb/
  6. Copy .env.example to amb/.env if missing

Safe to re-run: every step checks whether it is already done.
"""

from __future__ import annotations

import hashlib
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
AMB_DIR = REPO_ROOT / "amb"
AMB_REPO = "https://github.com/vectorize-io/agent-memory-benchmark"
PINNED_COMMIT = "aa9273ab9e34bbeaff3c6ef2f694142a552d5b22"
PATCHES_DIR = REPO_ROOT / "patches"
OVERLAY_DIR = REPO_ROOT / "overlay"
# Records which patch stack the clone in ./amb currently carries.
STAMP_FILE = ".patches-applied"


def stack_digest(patches: list[Path]) -> str:
    """Digest of the patch stack: filenames and contents, in application order."""
    digest = hashlib.sha256()
    for patch in patches:
        digest.update(patch.name.encode())
        digest.update(patch.read_bytes())
    return digest.hexdigest()


def apply_stack(amb_dir: Path, patches: list[Path]) -> bool:
    """Apply every patch in order.

    The stack is sequential: a later patch can edit a region an earlier one
    touched, so a patch cannot be reverse-checked individually to see whether it
    is already applied. Record the whole stack instead.
    """
    stamp = amb_dir / STAMP_FILE
    digest = stack_digest(patches)
    if stamp.exists():
        if stamp.read_text(encoding="utf-8").strip() == digest:
            step(f"Patch stack already applied ({len(patches)} patches), skipping")
            return True
        print(
            f"\n{amb_dir} carries a different patch stack than ./patches.\n"
            f"Delete {amb_dir} and run this script again.",
            file=sys.stderr,
        )
        return False

    for patch_file in patches:
        step(f"Applying {patch_file.name}")
        result = run(["git", "-C", str(amb_dir), "apply", str(patch_file)], check=False)
        if result.returncode != 0:
            print(
                f"\n{patch_file.name} failed to apply. "
                f"Delete {amb_dir} and run this script again.\n"
                f"{result.stderr}",
                file=sys.stderr,
            )
            return False

    stamp.write_text(digest + "\n", encoding="utf-8")
    return True


def step(msg: str) -> None:
    print(f"\n==> {msg}")


def run(cmd: list[str], cwd: Path | None = None, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=cwd, check=check, text=True, capture_output=True)


def git_head(repo: Path) -> str:
    return run(["git", "-C", str(repo), "rev-parse", "HEAD"]).stdout.strip()


def main() -> int:
    # 1. Clone
    if not AMB_DIR.exists():
        step(f"Cloning AMB into {AMB_DIR}")
        run(["git", "clone", AMB_REPO, str(AMB_DIR)])
    else:
        step(f"{AMB_DIR} already exists, skipping clone")

    # 2. Pin commit
    head = git_head(AMB_DIR)
    if head == PINNED_COMMIT:
        step(f"Already on pinned commit {PINNED_COMMIT[:8]}")
    else:
        step(f"Checking out pinned commit {PINNED_COMMIT[:8]}")
        result = run(["git", "-C", str(AMB_DIR), "checkout", PINNED_COMMIT], check=False)
        if result.returncode != 0:
            print(
                f"\nCould not check out pinned commit.\n"
                f"Delete {AMB_DIR} and run this script again.\n"
                f"{result.stderr}",
                file=sys.stderr,
            )
            return 1

    # 3. Copy overlay (adapters into amb/src, tests into amb/tests)
    step("Copying provider adapters and tests from ./overlay")
    if not OVERLAY_DIR.is_dir():
        print(f"Overlay not found at {OVERLAY_DIR}", file=sys.stderr)
        return 1
    for sub in ("src", "tests"):
        overlay_sub = OVERLAY_DIR / sub
        if not overlay_sub.is_dir():
            print(f"Overlay not found at {overlay_sub}", file=sys.stderr)
            return 1
        for src_path in overlay_sub.rglob("*"):
            if src_path.is_dir() or "__pycache__" in src_path.parts:
                continue
            dest = AMB_DIR / sub / src_path.relative_to(overlay_sub)
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src_path, dest)

    # 4. Apply patches in filename order. The stack is sequential, and patches
    #    02 and 01 both touch src/memory_bench/memory/__init__.py.
    patches = sorted(PATCHES_DIR.glob("*.patch"))
    if not patches:
        print(f"No patches found in {PATCHES_DIR}", file=sys.stderr)
        return 1
    if not apply_stack(AMB_DIR, patches):
        return 1

    # 5. Install dependencies
    step("Installing dependencies (uv sync)")
    uv = shutil.which("uv")
    if not uv:
        print("\nuv not found. Install from https://docs.astral.sh/uv/", file=sys.stderr)
        return 1
    result = run([uv, "sync"], cwd=AMB_DIR, check=False)
    if result.returncode != 0:
        print(f"\nuv sync failed:\n{result.stdout}\n{result.stderr}", file=sys.stderr)
        return 1

    # 6. Environment file
    env_example = REPO_ROOT / ".env.example"
    env_dest = AMB_DIR / ".env"
    if not env_dest.exists() and env_example.exists():
        step("Creating amb/.env from .env.example")
        shutil.copy2(env_example, env_dest)
    else:
        step("amb/.env already exists, keeping it")

    print(
        """
Done. Next steps:

  1. Fill in your keys:        amb/.env
  2. Check the adapters pass:  cd amb && uv run --with pytest pytest tests -q
  3. Run the validation gate:  see README, "Validation gate"
"""
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
