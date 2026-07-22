"""Golden check for docs_index.py's cross-reference graph (SK-01/SK-29).

Proves the id-integrity features ported from the AICF navigation fork into the
stock generator: the `referenced_by` blast-radius map, the `dangling` block, and
the `--check` gate — while confirming the pre-existing location-map behaviour
(sections/symbols/shards) still works.

Builds two tiny docs/ trees in a tempdir:
  clean/    PRD defines FR-001/FR-002; UX surface SCR-001 implements FR-001.
            -> FR-001 is referenced_by SCR-001; dangling == []; --check exits 0.
  dangling/ same, but SCR-002 implements FR-999 (never defined).
            -> FR-999 is dangling; --check exits 1.

Usage:
    python sdlc/skills/setup/_smoke/index_selftest.py

Exit 0 = every assertion held (SELFTEST PASS); exit 1 = a regression.
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
except Exception:
    pass

HERE = Path(__file__).resolve().parent
DOCS_INDEX = HERE.parent / "docs_index.py"

_PRD = """\
metadata:
  prd_version: "1.0"
  status: complete
functional_requirements:
  features:
    - "FR-001: A client can create an item."
    - "FR-002: A client can list items."
use_cases:
  core_workflows:
    - "WKF-001: Create then list."
"""

_UX_CLEAN = """\
metadata:
  ux_version: "1.0"
  status: complete
surfaces:
  - id: SCR-001
    name: Create item
    implements_requirements: [FR-001]
  - id: SCR-002
    name: List items
    implements_requirements: [FR-002]
"""

# SCR-002 traces a requirement that no PRD feature defines -> dangling.
_UX_DANGLING = _UX_CLEAN.replace("implements_requirements: [FR-002]",
                                 "implements_requirements: [FR-999]")


def _write_tree(root: Path, ux: str) -> Path:
    docs = root / "docs"
    docs.mkdir(parents=True, exist_ok=True)
    (docs / "PRD.yaml").write_text(_PRD, encoding="utf-8")
    (docs / "UX.yaml").write_text(ux, encoding="utf-8")
    return docs


def _run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(DOCS_INDEX), *args],
        capture_output=True, text=True,
    )


def main() -> int:
    checks: list[tuple[str, bool]] = []
    with tempfile.TemporaryDirectory() as tmp:
        clean = _write_tree(Path(tmp) / "clean", _UX_CLEAN)
        dang = _write_tree(Path(tmp) / "dangling", _UX_DANGLING)

        # 1) generate the clean index and inspect it
        gen = _run("--docs-dir", str(clean))
        checks.append((f"generate clean index exits 0 (got {gen.returncode})", gen.returncode == 0))
        idx = (clean / "INDEX.yaml").read_text(encoding="utf-8") if (clean / "INDEX.yaml").exists() else ""
        checks.append(("INDEX.yaml has a referenced_by block", "referenced_by:" in idx))
        checks.append(("FR-001 is a symbol (feature indexed)", "FR-001:" in idx))
        checks.append(("SCR-001 surface symbol indexed", "SCR-001" in idx))
        checks.append(("clean corpus reports dangling: []", "dangling: []" in idx))
        checks.append(("FR-001 blast-radius names SCR-001",
                       "referenced_by:" in idx and "SCR-001" in idx.split("referenced_by:", 1)[1]))

        # 2) --check gates: 0 on clean, non-zero on dangling
        chk_clean = _run("--docs-dir", str(clean), "--check")
        checks.append((f"--check exits 0 on clean corpus (got {chk_clean.returncode})", chk_clean.returncode == 0))
        chk_dang = _run("--docs-dir", str(dang), "--check")
        checks.append((f"--check exits non-zero on dangling ref (got {chk_dang.returncode})", chk_dang.returncode != 0))
        checks.append(("--check names the dangling id FR-999", "FR-999" in chk_dang.stdout))

        # 3) --refs answers on a defined id
        refs = _run("--docs-dir", str(clean), "--refs", "FR-001")
        checks.append((f"--refs FR-001 exits 0 (got {refs.returncode})", refs.returncode == 0))
        checks.append(("--refs FR-001 lists SCR-001 in referenced_by", "SCR-001" in refs.stdout))

        # 4) --find filters by kind
        find = _run("--docs-dir", str(clean), "--find", "kind=surface")
        checks.append((f"--find kind=surface exits 0 (got {find.returncode})", find.returncode == 0))
        checks.append(("--find kind=surface returns SCR-001", "SCR-001" in find.stdout))

    failed = [name for name, ok in checks if not ok]
    for name, ok in checks:
        print(f"  {'[OK]  ' if ok else '[FAIL]'} {name}")
    if failed:
        print(f"SELFTEST FAIL - {len(failed)} of {len(checks)} assertion(s) failed")
        return 1
    print(f"SELFTEST PASS - {len(checks)} assertion(s) held")
    return 0


if __name__ == "__main__":
    sys.exit(main())
