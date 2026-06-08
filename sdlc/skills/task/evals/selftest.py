"""Self-test the sdlc-task eval suite without spending subagent runs.

It stages the _gold reference outputs into isolated test-project dirs (the same
shape stage_iteration.py produces), then confirms the validator AND grade.py
agree:

  * the system gold (docs/TASKS.json) validates [OK] complete and grade_eval_1
    scores every assertion green;
  * the container gold (docs/TASKS__backend-api.json) validates [OK] complete and
    grade_eval_2 / grade_eval_3 score green;
  * the stitch gold (the stitched system TASKS.json + the pre-built container
    TASKS__backend-api.json coexisting) validates [OK] complete across BOTH files
    and grade_eval_4 scores green — the only scenario that walks the cross-file
    union-graph resolution;
  * a corrupted container gold (an illegal `implements: [FR-005]` plus a dropped
    component task) flips the validator to exit 1 AND flips grade.py must-assertions
    to fail;
  * a corrupted stitch gold (a system task's cross-file dep pointed at a
    non-existent backend-api/TSK-999) flips the validator to exit 1 AND flips
    grade_eval_4's union-resolve + validator checks — proving the cross-file
    checks have teeth.

Usage:
    python sdlc/skills/task/evals/selftest.py

Exit 0 = grader and validator agree on gold (green) and on corruption (red).
Exit 1 = a disagreement (a gap in either the validator or grade.py).
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SKILL_ROOT = HERE.parent
REPO_ROOT = SKILL_ROOT.parents[2]
FIX = HERE / "fixtures"
GOLD = HERE / "_gold"
VALIDATOR = SKILL_ROOT / "validate_schema.py"
SCRATCH = REPO_ROOT / "sdlc-task-workspace" / "_selftest"

sys.path.insert(0, str(HERE))
import grade  # noqa: E402  (the suite's own grader)


def _copy_tree(src: Path, dst: Path) -> None:
    dst.mkdir(parents=True, exist_ok=True)
    for f in src.iterdir():
        if f.is_file():
            shutil.copy2(f, dst / f.name)


def _stage() -> tuple[Path, Path, Path]:
    if SCRATCH.exists():
        shutil.rmtree(SCRATCH)
    sysd = SCRATCH / "system" / "test-project" / "docs"
    cond = SCRATCH / "container" / "test-project" / "docs"
    stid = SCRATCH / "stitch" / "test-project" / "docs"
    # system: web-app upstreams + gold TASKS.json
    _copy_tree(FIX / "web-app" / "docs", sysd)
    shutil.copy2(GOLD / "TASKS.json", sysd / "TASKS.json")
    # container: web-app upstreams, ARCH overridden by the container ARCH + deep-dive
    # + container test strategy, + gold TASKS__backend-api.json
    _copy_tree(FIX / "web-app" / "docs", cond)
    _copy_tree(FIX / "web-app-container" / "docs", cond)  # overwrites ARCH.yaml, adds the container files
    shutil.copy2(GOLD / "TASKS__backend-api.json", cond / "TASKS__backend-api.json")
    # stitch: BOTH files coexist — the system stitched gold + the pre-built container.
    # This is the only scenario that exercises the cross-file union-graph resolution.
    _copy_tree(FIX / "web-app" / "docs", stid)
    _copy_tree(FIX / "web-app-container" / "docs", stid)
    shutil.copy2(GOLD / "TASKS.stitched.json", stid / "TASKS.json")
    shutil.copy2(FIX / "web-app-stitch" / "docs" / "TASKS__backend-api.json", stid / "TASKS__backend-api.json")
    return (
        SCRATCH / "system" / "test-project",
        SCRATCH / "container" / "test-project",
        SCRATCH / "stitch" / "test-project",
    )


def _validate(tp: Path) -> tuple[int, str]:
    r = subprocess.run(
        [sys.executable, str(VALIDATOR), "--path", "docs/TASKS.json"],
        cwd=tp, capture_output=True, text=True,
    )
    return r.returncode, (r.stdout + r.stderr).strip()


def _summarize(name: str, results: list[dict]) -> bool:
    failed = [r for r in results if not r["passed"]]
    mark = "GREEN" if not failed else f"RED ({len(failed)} failed)"
    print(f"  {name}: {sum(r['passed'] for r in results)}/{len(results)}  [{mark}]")
    for r in failed:
        print(f"      FAIL: {r['text']}\n            {r['evidence']}")
    return not failed


def main() -> int:
    sys_tp, con_tp, stitch_tp = _stage()
    ok = True

    print("== validator on gold ==")
    rc_s, out_s = _validate(sys_tp)
    rc_c, out_c = _validate(con_tp)
    rc_t, out_t = _validate(stitch_tp)
    sys_v = rc_s == 0 and "complete" in out_s.lower()
    con_v = rc_c == 0 and "complete" in out_c.lower()
    stitch_v = rc_t == 0 and "complete" in out_t.lower()
    print(f"  system  gold: exit={rc_s}  {'OK' if sys_v else 'UNEXPECTED'}  | {out_s.splitlines()[0] if out_s else ''}")
    print(f"  container gold: exit={rc_c}  {'OK' if con_v else 'UNEXPECTED'}  | {out_c.splitlines()[0] if out_c else ''}")
    print(f"  stitch  gold: exit={rc_t}  {'OK' if stitch_v else 'UNEXPECTED'}  | {out_t.splitlines()[0] if out_t else ''}")
    ok = ok and sys_v and con_v and stitch_v

    print("== grade.py on gold (expect all GREEN) ==")
    ok = _summarize("eval 1 (system)", grade.grade_eval_1(sys_tp)) and ok
    ok = _summarize("eval 2 (container)", grade.grade_eval_2(con_tp)) and ok
    ok = _summarize("eval 3 (--next)", grade.grade_eval_3(con_tp)) and ok
    ok = _summarize("eval 4 (stitch)", grade.grade_eval_4(stitch_tp)) and ok

    print("== corruption test (expect validator RED + grade.py must-fail) ==")
    corrupt = json.loads((GOLD / "TASKS__backend-api.json").read_text(encoding="utf-8"))
    # 1) illegal cross-scope requirement, 2) drop the comments-controller impl task
    #    (so its component is uncovered) — both must be caught.
    for t in corrupt["tasks"]:
        if t["tsk_id"] == "TSK-003":
            t.setdefault("implements", []).append("FR-005")
    corrupt["tasks"] = [t for t in corrupt["tasks"] if t["tsk_id"] != "TSK-004"]
    cdocs = SCRATCH / "corrupt" / "test-project" / "docs"
    _copy_tree(FIX / "web-app" / "docs", cdocs)
    _copy_tree(FIX / "web-app-container" / "docs", cdocs)
    (cdocs / "TASKS__backend-api.json").write_text(json.dumps(corrupt, indent=2), encoding="utf-8")
    rc_x, out_x = _validate(SCRATCH / "corrupt" / "test-project")
    res_x = grade.grade_eval_2(SCRATCH / "corrupt" / "test-project")
    must_fail = [r for r in res_x if not r["passed"]]
    val_red = rc_x == 1
    grade_red = len(must_fail) >= 1
    print(f"  validator: exit={rc_x}  {'RED (correct)' if val_red else 'UNEXPECTED — should be 1'}")
    print(f"  grade.py: {len(must_fail)} assertion(s) failed  {'(correct)' if grade_red else 'UNEXPECTED — should fail'}")
    for r in must_fail:
        print(f"      caught: {r['text']}")
    ok = ok and val_red and grade_red

    print("== stitch corruption test (cross-file dep to a non-existent container task) ==")
    # Point a system task's cross-file dep at backend-api/TSK-999 (no such task).
    # The union-graph walk must report it unresolved → validator exit 1 AND
    # grade_eval_4 must flip the A5 (union resolve/acyclic) and A9 (validator) checks.
    bad_sys = json.loads((GOLD / "TASKS.stitched.json").read_text(encoding="utf-8"))
    for t in bad_sys["tasks"]:
        if t["tsk_id"] == "TSK-002":
            t["depends_on"] = ["TSK-001", "backend-api/TSK-999"]
    sdocs = SCRATCH / "stitch-corrupt" / "test-project" / "docs"
    _copy_tree(FIX / "web-app" / "docs", sdocs)
    _copy_tree(FIX / "web-app-container" / "docs", sdocs)
    (sdocs / "TASKS.json").write_text(json.dumps(bad_sys, indent=2), encoding="utf-8")
    shutil.copy2(FIX / "web-app-stitch" / "docs" / "TASKS__backend-api.json", sdocs / "TASKS__backend-api.json")
    rc_sx, out_sx = _validate(SCRATCH / "stitch-corrupt" / "test-project")
    res_sx = grade.grade_eval_4(SCRATCH / "stitch-corrupt" / "test-project")
    sx_must_fail = [r for r in res_sx if not r["passed"]]
    sx_val_red = rc_sx == 1
    sx_grade_red = len(sx_must_fail) >= 1
    print(f"  validator: exit={rc_sx}  {'RED (correct)' if sx_val_red else 'UNEXPECTED — should be 1'}")
    print(f"  grade.py: {len(sx_must_fail)} assertion(s) failed  {'(correct)' if sx_grade_red else 'UNEXPECTED — should fail'}")
    for r in sx_must_fail:
        print(f"      caught: {r['text']}")
    ok = ok and sx_val_red and sx_grade_red

    print()
    if ok:
        print("SELFTEST PASS — grader and validator agree on gold (green) and corruption (red).")
        return 0
    print("SELFTEST FAIL — see disagreements above.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
