"""Golden check for the worker-packet builder (topo_order.py --emit).

Reproduces (in miniature) the SK-25/K2 corpus incident: every test-task worker
packet shipped an EMPTY requirement_context because emit_packets harvested only
`implements` + `implements_workflows` while a test task's requirement ids live
in `test_spec.covers` — so all 224 corpus test workers built without their
FR/ACR grounding. The fix harvests covers and resolves ACR-NNN lines from
PRD's success_metrics.acceptance_criteria; this script proves both against the
demo-docs fixture (the only staged PRD with ACR instances — the AICF meta
corpus has none, so the live regression there is FR-only):

  (impl)  demo-api/TSK-003 (`implements: [FR-001]`) resolves FR-001.
  (test)  demo-api/TSK-005 (`test_spec.covers: [FR-001, ACR-001]`) resolves
          BOTH ids — the packet, not PRD, carries the test worker's grounding.
  (clean) neither packet carries requirement_context_unresolved.

Usage:
    python sdlc/skills/code/_smoke/emit_selftest.py

Exit 0 = every assertion held (SELFTEST PASS); exit 1 = a regression.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

try:  # PRD statements may carry non-ASCII on some consoles (cp1252)
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
except Exception:
    pass

HERE = Path(__file__).resolve().parent
CODE_SKILL = HERE.parent
REPO_ROOT = CODE_SKILL.parents[2]
TOPO = CODE_SKILL / "topo_order.py"
DEMO_DOCS = HERE / "demo-docs"

QIDS = ["demo-api/TSK-003", "demo-api/TSK-005"]


def main() -> int:
    r = subprocess.run(
        [sys.executable, str(TOPO), "--docs", str(DEMO_DOCS), "--emit", *QIDS],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )
    checks: list[tuple[str, bool]] = []
    checks.append((f"--emit exits 0 (got {r.returncode})", r.returncode == 0))

    packets = {}
    try:
        packets = {p["qualified_id"]: p for p in json.loads(r.stdout)}
        checks.append(("both packets emitted", set(packets) == set(QIDS)))
    except (json.JSONDecodeError, KeyError, TypeError) as e:
        checks.append((f"stdout parses as packet JSON ({e})", False))

    impl = packets.get("demo-api/TSK-003") or {}
    test = packets.get("demo-api/TSK-005") or {}
    impl_rc = impl.get("requirement_context") or {}
    test_rc = test.get("requirement_context") or {}

    checks.append(("impl packet resolves FR-001 (implements)", "FR-001" in impl_rc))
    checks.append(("test packet resolves FR-001 (test_spec.covers)", "FR-001" in test_rc))
    checks.append(("test packet resolves ACR-001 (test_spec.covers)", "ACR-001" in test_rc))
    checks.append(
        (
            "resolved statements are non-empty PRD text",
            all(isinstance(v, str) and v.strip() for v in list(impl_rc.values()) + list(test_rc.values())),
        )
    )
    checks.append(
        (
            "no requirement_context_unresolved on either packet",
            "requirement_context_unresolved" not in impl
            and "requirement_context_unresolved" not in test,
        )
    )

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
