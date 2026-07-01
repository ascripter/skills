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
    component — all its tasks) flips the validator to exit 1 AND flips grade.py
    must-assertions to fail;
  * a work-unit-coverage corruption (drop ONE work_unit task while its component
    stays covered by its other work_unit tasks) flips the validator to exit 1 on
    the atomic work-unit-coverage gate ALONE — proving that gate bites
    independently of component coverage;
  * a corrupted stitch gold (a system task's cross-file dep pointed at a
    non-existent backend-api/TSK-999) flips the validator to exit 1 AND flips
    grade_eval_4's union-resolve + validator checks — proving the cross-file
    checks have teeth;
  * the web-frontend gold (TASKS__web-frontend.json) validates [OK] complete —
    exercising the surface-coverage gate (slug→SCR via UX.yaml) and the
    token_based_ui design gate that the backend-only golds never touch — and two
    corruptions flip it red: dropping the kind:design task trips design coverage,
    and dropping a view task trips surface + component + test coverage.

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


def _stage_fe(tag: str, tasks_obj: dict | None) -> Path:
    """Stage the web-frontend scenario: web-app upstreams + the container ARCH
    (which owns the four UX surfaces) + the frontend UX/DESIGN/ARCH__/TEST__
    fixtures + a TASKS__web-frontend.json (the gold, or a mutated copy)."""
    docs = SCRATCH / tag / "test-project" / "docs"
    _copy_tree(FIX / "web-app" / "docs", docs)
    shutil.copy2(FIX / "web-app-container" / "docs" / "ARCH.yaml", docs / "ARCH.yaml")
    _copy_tree(FIX / "web-frontend" / "docs", docs)
    if tasks_obj is None:
        shutil.copy2(GOLD / "TASKS__web-frontend.json", docs / "TASKS__web-frontend.json")
    else:
        (docs / "TASKS__web-frontend.json").write_text(json.dumps(tasks_obj, indent=2), encoding="utf-8")
    return SCRATCH / tag / "test-project"


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
    # 1) illegal cross-scope requirement on a surviving task, 2) drop EVERY
    #    digest-settings-controller task — uncovering the component, its
    #    work_units (getDigestSettings/updateDigestSettings) and its test (TST-004).
    #    Both must be caught. (id-agnostic so it survives any re-slicing of the gold.)
    for t in corrupt["tasks"]:
        if t.get("component_ref") == "tasks-controller":
            t.setdefault("implements", []).append("FR-005")
            break
    corrupt["tasks"] = [t for t in corrupt["tasks"]
                        if t.get("component_ref") != "digest-settings-controller"]
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

    print("== work-unit-coverage corruption (atomic gate: drop one work_unit task, component stays covered) ==")
    # Drop exactly one work_unit task (target_symbol == "listTasks"). tasks-controller
    # stays covered by its other work_unit tasks, so ONLY the work-unit-coverage gate
    # should fire — proving the atomic gate bites independently of component coverage.
    op_corrupt = json.loads((GOLD / "TASKS__backend-api.json").read_text(encoding="utf-8"))
    op_corrupt["tasks"] = [t for t in op_corrupt["tasks"]
                           if t.get("target_symbol") != "listTasks"]
    odocs = SCRATCH / "op-corrupt" / "test-project" / "docs"
    _copy_tree(FIX / "web-app" / "docs", odocs)
    _copy_tree(FIX / "web-app-container" / "docs", odocs)
    (odocs / "TASKS__backend-api.json").write_text(json.dumps(op_corrupt, indent=2), encoding="utf-8")
    rc_o, out_o = _validate(SCRATCH / "op-corrupt" / "test-project")
    op_red = rc_o == 1 and "work-unit coverage" in out_o and "listTasks" in out_o
    op_comp_silent = "component coverage" not in out_o   # component stays covered
    print(f"  drop one work_unit task: exit={rc_o}  {'RED (correct)' if op_red else 'UNEXPECTED — work-unit gate silent'}")
    print(f"  component stays covered (no component-coverage error): {'yes' if op_comp_silent else 'NO — unexpected'}")
    ok = ok and op_red and op_comp_silent

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

    print("== frontend gold (surface + design coverage gates) ==")
    fe_gold = json.loads((GOLD / "TASKS__web-frontend.json").read_text(encoding="utf-8"))
    rc_f, out_f = _validate(_stage_fe("fe-gold", None))
    fe_v = rc_f == 0 and "complete" in out_f.lower()
    print(f"  frontend gold: exit={rc_f}  {'OK' if fe_v else 'UNEXPECTED'}  | {out_f.splitlines()[0] if out_f else ''}")
    ok = ok and fe_v

    print("== frontend corruption (expect the new gates RED) ==")
    # drop the kind:design task (and its dangling depends_on) → design-coverage gate.
    nod = json.loads(json.dumps(fe_gold))
    nod["tasks"] = [t for t in nod["tasks"] if t["tsk_id"] != "TSK-002"]
    for t in nod["tasks"]:
        t["depends_on"] = [d for d in t.get("depends_on", []) if d != "TSK-002"]
    rc_nd, out_nd = _validate(_stage_fe("fe-nodesign", nod))
    design_red = rc_nd == 1 and "design coverage" in out_nd
    print(f"  drop design task: exit={rc_nd}  {'RED (correct)' if design_red else 'UNEXPECTED — design gate silent'}")
    ok = ok and design_red
    # drop the task-list view impl + its test → surface + component + test gates.
    nos = json.loads(json.dumps(fe_gold))
    nos["tasks"] = [t for t in nos["tasks"] if t["tsk_id"] not in ("TSK-003", "TSK-008")]
    rc_ns, out_ns = _validate(_stage_fe("fe-nosurface", nos))
    surface_red = rc_ns == 1 and "surface coverage" in out_ns and "SCR-001" in out_ns
    print(f"  drop task-list view+test: exit={rc_ns}  {'RED (correct)' if surface_red else 'UNEXPECTED — surface gate silent'}")
    for line in out_ns.splitlines():
        if "coverage:" in line:
            print(f"      caught: {line.strip()}")
    ok = ok and surface_red

    print()
    if ok:
        print("SELFTEST PASS — grader and validator agree on gold (green) and corruption (red).")
        return 0
    print("SELFTEST FAIL — see disagreements above.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
