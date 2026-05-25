"""Run validate_schema.py against every smoke fixture and verify outcomes.

Usage (from the repo root or anywhere):

    python sdlc/skills/ux/_smoke/run_all.py

Exit code 0 means every fixture produced its expected validator exit code.
Exit code 1 means at least one fixture diverged from expectation.

Fixtures are discovered under this directory; each declared in EXPECTATIONS
below maps to its expected validator exit code (0 for [OK]/[DRAFT], 1 for
[FAIL]). For fixtures that ship a docs/PRD.yaml inside themselves (e.g.
05_coverage_failure), the runner cds into the fixture dir so the coverage
check sees the fixture-local PRD instead of the project-root one.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
VALIDATOR = HERE.parent / "validate_schema.py"

# (fixture-dir-name, ux_yaml_relative_path-from-fixture, expected_exit)
# expected_exit is the exit code the validator should produce.
EXPECTATIONS = [
    ("01_valid_draft_single",      "UX.yaml",          0),
    ("02_bad_enum",                "UX.yaml",          1),
    ("03_complete_missing_required", "UX.yaml",        1),
    ("04_valid_cli_complete",      "UX.yaml",          0),
    ("05_coverage_failure",        "docs/UX.yaml",     1),
    ("06_bad_id_prefix",           "UX.yaml",          1),
    ("07_wrong_family_in_refs",    "UX.yaml",          1),
    ("08_valid_monorepo",          "UX.yaml",          0),
    ("09_monorepo_mode_mismatch",  "UX.yaml",          1),
    ("10_valid_nonflow_traces",    "UX.yaml",          0),
    ("11_warnings_bad_prefix",     "UX.yaml",          1),
]


def _run(fixture_dir: Path, ux_rel: str) -> int:
    """Run the validator inside fixture_dir. cwd-scoped so any fixture-local
    docs/PRD.yaml is picked up by the coverage check.
    """
    result = subprocess.run(
        [sys.executable, str(VALIDATOR), "--path", ux_rel],
        cwd=fixture_dir,
        capture_output=True,
        text=True,
    )
    return result.returncode


def main() -> int:
    results: list[tuple[str, int, int, bool]] = []
    width = max(len(name) for name, _, _ in EXPECTATIONS)
    for name, ux_rel, expected in EXPECTATIONS:
        fixture = HERE / name
        if not fixture.exists():
            print(f"  {name:<{width}}  SKIP  (directory not found)")
            results.append((name, -1, expected, False))
            continue
        actual = _run(fixture, ux_rel)
        ok = actual == expected
        marker = "PASS" if ok else "FAIL"
        print(f"  {name:<{width}}  {marker}  (expected exit {expected}, got {actual})")
        results.append((name, actual, expected, ok))

    n_pass = sum(1 for _, _, _, ok in results if ok)
    n_total = len(results)
    print()
    print(f"{n_pass}/{n_total} fixtures matched expected outcome.")
    return 0 if n_pass == n_total else 1


if __name__ == "__main__":
    raise SystemExit(main())
