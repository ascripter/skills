"""Eval fixture assertions for the mixed block-/flow-style work_units regression.

Reproduces (in miniature) the AICF `aicf-cli` incident: a `/sdlc:task` run was
wrongly REFUSED because its readiness reasoning counted work_units with a line
grep ("- name:") that matched only block-style entries and missed the flow-style
("- {name: ...}") ones — reporting most components as unit-free against a
fully-backfilled ARCH. Both skills were hardened; this test proves it:

  (task)  count_work_units.py derives counts from a real YAML parse, so on the
          fully-backfilled mixed-style container it finds ALL units (block AND
          flow), reports zero non-trivial gaps, and exits 0 → the run proceeds.
          A pure grep for "- name:" would undercount and wrongly signal a gap.

  (arch)  the arch validator's blocking rules fire on the *incomplete* mixed-style
          container: cross-check #21 (a non-trivial component with no work_units
          and no waiver) and cross-check #22 (a component that claims an FR no
          work_unit realizes). The valid mixed-style container passes [OK] — the
          waiver + plumbing archetypes are correctly exempt.

Fixtures live under sdlc/skills/arch/_smoke/:
  19_work_units_mixed_style/   — VALID, fully backfilled (mixed styles).
  20_work_units_incomplete/    — INCOMPLETE (#21 + #22 fire).

Usage:
    python sdlc/skills/task/_smoke/work_units_style_selftest.py

Exit 0 = every assertion held; exit 1 = a regression.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

try:  # captured validator output may carry non-ASCII on some consoles (cp1252)
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
except Exception:
    pass

HERE = Path(__file__).resolve().parent
TASK_SKILL = HERE.parent
REPO_ROOT = TASK_SKILL.parents[2]
ARCH_SMOKE = REPO_ROOT / "sdlc" / "skills" / "arch" / "_smoke"
COUNTER = TASK_SKILL / "count_work_units.py"
ARCH_VALIDATOR = REPO_ROOT / "sdlc" / "skills" / "arch" / "validate_schema.py"

VALID = ARCH_SMOKE / "19_work_units_mixed_style"
INCOMPLETE = ARCH_SMOKE / "20_work_units_incomplete"


def _run(args: list[str]) -> tuple[int, str]:
    r = subprocess.run(
        [sys.executable, *args], capture_output=True, text=True, cwd=REPO_ROOT
    )
    return r.returncode, (r.stdout + r.stderr)


def _grep_block_count(arch_file: Path) -> int:
    """The naive miscount: block-style '- name:' lines only (misses flow style)."""
    return len(re.findall(r"^\s*-\s+name:", arch_file.read_text(encoding="utf-8"), re.M))


def main() -> int:
    checks: list[tuple[str, bool, str]] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        checks.append((name, ok, detail))

    # ---- (task) count_work_units.py on the VALID mixed-style container ----
    rc, out = _run([str(COUNTER), str(VALID / "ARCH__api.yaml")])
    m = re.search(r"TOTAL:.*?(\d+) work_unit\(s\); (\d+) non-trivial zero-unit", out)
    total_units = int(m.group(1)) if m else -1
    gaps = int(m.group(2)) if m else -1
    check("valid: parse-based count finds all 4 units (2 block + 2 flow)", total_units == 4,
          f"got {total_units}; output:\n{out}")
    check("valid: flow-style updateTask/deleteTask are counted",
          "units=4" in out, out)
    check("valid: zero non-trivial gaps -> run proceeds (exit 0)", rc == 0 and gaps == 0,
          f"rc={rc} gaps={gaps}")

    # A naive grep would undercount — this is the bug the parse fixes.
    grep_n = _grep_block_count(VALID / "ARCH__api.yaml")
    check("valid: a line-grep for '- name:' WOULD undercount (proves parse matters)",
          grep_n < total_units, f"grep saw {grep_n}, parse saw {total_units}")

    # ---- (task) count_work_units.py on the INCOMPLETE container ----
    rc, out = _run([str(COUNTER), str(INCOMPLETE / "ARCH__api.yaml")])
    check("incomplete: helper flags tasks-service as a non-trivial gap (exit 1)",
          rc == 1 and "tasks-service" in out and "fix upstream" in out, f"rc={rc}\n{out}")

    # ---- (arch) validator on the VALID container → [OK] ----
    rc, out = _run([str(ARCH_VALIDATOR), "--path", str(VALID / "ARCH.yaml")])
    check("arch: valid mixed-style container passes [OK] complete (exit 0)",
          rc == 0 and "[OK]" in out, f"rc={rc}\n{out[:400]}")
    check("arch: audit-logger waiver is honoured (advisory, not blocking)",
          "waived" in out, out[:400])

    # ---- (arch) validator on the INCOMPLETE container → [FAIL] with #21 + #22 ----
    rc, out = _run([str(ARCH_VALIDATOR), "--path", str(INCOMPLETE / "ARCH.yaml")])
    check("arch: incomplete container FAILs (exit 1)", rc == 1 and "[FAIL]" in out,
          f"rc={rc}\n{out[:400]}")
    check("arch: #21 fires — tasks-service non-trivial with no work_units",
          "cross-check 21" in out and "tasks-service" in out, out)
    check("arch: #22 fires — tasks-controller claims FR-003 no work_unit realizes",
          "cross-check 22" in out and "FR-003" in out, out)

    ok = all(c[1] for c in checks)
    print("== work_units mixed-style eval ==")
    for name, passed, detail in checks:
        mark = "PASS" if passed else "FAIL"
        print(f"  [{mark}] {name}")
        if not passed:
            print(f"         {detail}")
    print()
    print("SELFTEST PASS" if ok else "SELFTEST FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
