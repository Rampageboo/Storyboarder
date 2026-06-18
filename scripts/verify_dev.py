#!/usr/bin/env python3
"""Local development verification gate.

Run all checks or a targeted subset before merging a branch.

Usage:
    python scripts/verify_dev.py                  # full gate
    python scripts/verify_dev.py --backend        # py_compile + migration + pytest
    python scripts/verify_dev.py --frontend       # lint + build
    python scripts/verify_dev.py --fast           # py_compile + migration + smoke + lint
    python scripts/verify_dev.py --continue-on-fail  # don't stop on first failure
"""
from __future__ import annotations

import argparse
import platform
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Use npm.cmd on Windows so shell=False works correctly.
NPM = "npm.cmd" if platform.system() == "Windows" else "npm"

BACKEND_MODULES = [
    "storyboard_tool/project_manager.py",
    "storyboard_tool/backend_service.py",
    "storyboard_tool/reference_segments.py",
    "storyboard_tool/external_tools.py",
    "storyboard_tool/export_service.py",
    "storyboard_tool/project_transaction.py",
    "storyboard_tool/app_state.py",
    "storyboard_tool/shot_service.py",
    "storyboard_tool/api.py",
    "storyboard_tool/schemas.py",
    "storyboard_tool/errors.py",
    "storyboard_tool/models.py",
]


def _label(text: str) -> None:
    width = 64
    print(f"\n{'-' * width}")
    print(f"  {text}")
    print(f"{'-' * width}")


def _run(label: str, cmd: list[str], *, cwd: Path | None = None) -> bool:
    """Print label + command, run it, return True on success."""
    _label(label)
    display = " ".join(str(c) for c in cmd)
    print(f"$ {display}\n")
    result = subprocess.run(cmd, cwd=cwd or ROOT)
    ok = result.returncode == 0
    if not ok:
        print(f"\nFAILED (exit {result.returncode}): {label}")
    return ok


def check_py_compile() -> bool:
    modules = [str(ROOT / m) for m in BACKEND_MODULES]
    return _run(
        "Python syntax check (py_compile)",
        [sys.executable, "-m", "py_compile", *modules],
    )


def check_validate_migration() -> bool:
    return _run(
        "Migration validator (validate_migration.py)",
        [sys.executable, str(ROOT / "scripts" / "validate_migration.py")],
    )


def check_pytest_full() -> bool:
    return _run(
        "Full test suite (pytest tests/)",
        [sys.executable, "-m", "pytest", "tests/", "-q"],
    )


def check_pytest_smoke() -> bool:
    return _run(
        "Smoke tests (pytest tests/test_smoke.py)",
        [sys.executable, "-m", "pytest", "tests/test_smoke.py", "-q"],
    )


def check_frontend_lint() -> bool:
    return _run(
        "Frontend lint (eslint)",
        [NPM, "run", "lint"],
        cwd=ROOT / "frontend",
    )


def check_frontend_build() -> bool:
    return _run(
        "Frontend build (vite)",
        [NPM, "run", "build"],
        cwd=ROOT / "frontend",
    )


# ---------------------------------------------------------------------------
# Mode definitions — each returns an ordered list of (check_fn, name) pairs.
# ---------------------------------------------------------------------------

def _steps_backend() -> list[tuple]:
    return [
        (check_py_compile, "py_compile"),
        (check_validate_migration, "validate_migration"),
        (check_pytest_full, "pytest full"),
    ]


def _steps_frontend() -> list[tuple]:
    return [
        (check_frontend_lint, "frontend lint"),
        (check_frontend_build, "frontend build"),
    ]


def _steps_fast() -> list[tuple]:
    return [
        (check_py_compile, "py_compile"),
        (check_validate_migration, "validate_migration"),
        (check_pytest_smoke, "pytest smoke"),
        (check_frontend_lint, "frontend lint"),
    ]


def _steps_full() -> list[tuple]:
    return [
        (check_py_compile, "py_compile"),
        (check_validate_migration, "validate_migration"),
        (check_pytest_full, "pytest full"),
        (check_frontend_lint, "frontend lint"),
        (check_frontend_build, "frontend build"),
    ]


def _run_steps(steps: list[tuple], *, stop_on_fail: bool) -> int:
    passed: list[str] = []
    failed: list[str] = []
    for fn, name in steps:
        ok = fn()
        (passed if ok else failed).append(name)
        if not ok and stop_on_fail:
            break

    width = 64
    print(f"\n{'=' * width}")
    print("  VERIFICATION SUMMARY")
    print(f"{'=' * width}")
    for name in passed:
        print(f"  PASS  {name}")
    for name in failed:
        print(f"  FAIL  {name}")
    # Any steps skipped due to stop_on_fail
    ran = len(passed) + len(failed)
    skipped = len(steps) - ran
    if skipped:
        remaining = [n for _, n in steps[ran:]]
        for name in remaining:
            print(f"  SKIP  {name}  (not reached)")
    print(f"{'=' * width}")
    if failed:
        print(f"  RESULT: FAILED  ({len(failed)} step(s) failed)\n")
        return 1
    print(f"  RESULT: PASSED  ({len(passed)} step(s))\n")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Storyboarder local development verification gate.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__.strip(),
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--backend", action="store_true", help="py_compile + migration + pytest")
    mode.add_argument("--frontend", action="store_true", help="lint + build")
    mode.add_argument("--fast", action="store_true", help="py_compile + migration + smoke + lint")
    parser.add_argument(
        "--continue-on-fail",
        action="store_true",
        help="run all steps even if one fails (default: stop on first failure)",
    )
    args = parser.parse_args()

    if args.backend:
        steps = _steps_backend()
        label = "BACKEND"
    elif args.frontend:
        steps = _steps_frontend()
        label = "FRONTEND"
    elif args.fast:
        steps = _steps_fast()
        label = "FAST"
    else:
        steps = _steps_full()
        label = "FULL"

    print(f"\nStoryboarder verify_dev  mode: {label}")
    print(f"Python: {sys.executable}")
    print(f"Root:   {ROOT}")

    return _run_steps(steps, stop_on_fail=not args.continue_on_fail)


if __name__ == "__main__":
    raise SystemExit(main())
