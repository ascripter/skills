"""Smoke-test the sdlc-design validator against every fixture in this folder.

Each subdirectory holds a DESIGN.yaml (+ optional DESIGN__*.yaml siblings). The
expected validator exit code is encoded in EXPECTED below, keyed by directory
name. Run from anywhere:

    python sdlc/skills/design/_smoke/run_all.py
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
VALIDATOR = HERE.parent / "validate_schema.py"

# Expected exit code per fixture directory.
#   0 = valid (complete or draft); 1 = schema/composition/coverage failure.
EXPECTED = {
    "01_valid_token_web": 0,
    "02_valid_dual_axis_game": 0,
    "03_valid_headless_cli": 0,
    "04_complete_missing_tokens_file": 1,
    "05_uncovered_generated_asset": 1,
    "06_bad_id_prefix": 1,
    "07_headless_not_exclusive": 1,
    "08_deferred_asset_ok": 0,
}


def main() -> int:
    failures = 0
    ran = 0
    for name in sorted(EXPECTED):
        case_dir = HERE / name
        design = case_dir / "DESIGN.yaml"
        if not design.exists():
            print(f"[SKIP] {name}: no DESIGN.yaml yet")
            continue
        ran += 1
        proc = subprocess.run(
            [sys.executable, str(VALIDATOR), "--path", str(design)],
            capture_output=True,
            text=True,
        )
        expected = EXPECTED[name]
        ok = proc.returncode == expected
        flag = "PASS" if ok else "FAIL"
        print(f"[{flag}] {name}: exit {proc.returncode} (expected {expected})")
        if not ok:
            failures += 1
            print("------ stdout ------")
            print(proc.stdout)
            print("------ stderr ------")
            print(proc.stderr)
    print(f"\n{ran} fixture(s) run, {failures} unexpected result(s).")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
