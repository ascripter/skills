"""Grade subagent outputs for the sdlc-ux eval suite.

Usage:
    python sdlc/skills/ux/evals/grade.py --iteration 1

For each eval directory under sdlc-ux-workspace/iteration-N/, this inspects
test-project/ to check assertion-style claims about the produced UX.yaml +
UX__*.yaml siblings. Writes per-eval grading.json and a top-level
benchmark.md summary.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Callable, List

import yaml

REPO_ROOT = Path(__file__).resolve().parents[4]
SKILL_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = REPO_ROOT / "sdlc-ux-workspace"
VALIDATOR = SKILL_ROOT / "validate_schema.py"

SCR_RE = re.compile(r"^SCR-\d{3,}$")
WRN_RE = re.compile(r"^WRN-\d{3,}:\s+.+")


def _assert(text: str, ok: bool, evidence: str) -> dict:
    return {"text": text, "passed": bool(ok), "evidence": evidence}


def _load_yaml(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        return {"__parse_error__": str(e)}


def _validator_exit(ux_path: Path, cwd: Path) -> tuple[int, str]:
    """Run validator with cwd set so it reads the fixture-local docs/PRD.yaml."""
    if not ux_path.exists():
        return 99, "UX.yaml missing"
    r = subprocess.run(
        [sys.executable, str(VALIDATOR), "--path", str(ux_path.relative_to(cwd))],
        cwd=cwd,
        capture_output=True,
        text=True,
    )
    return r.returncode, (r.stdout + r.stderr).strip()


def grade_eval_1(tp: Path) -> List[dict]:
    """cli-with-entity-implied-surface"""
    ux = _load_yaml(tp / "docs" / "UX.yaml")
    rc, vout = _validator_exit(tp / "docs" / "UX.yaml", tp)

    surfaces = ux.get("surface_inventory") if isinstance(ux, dict) else None
    inv: list = surfaces or []
    n_surfaces = len(inv)
    all_ids_ok = all(isinstance(s, dict) and SCR_RE.match(s.get("id", "") or "") for s in inv)
    wkfs_covered = set()
    for s in inv:
        for w in (s.get("traces_workflows") or []):
            wkfs_covered.add(w)
    all_wkfs_covered = {"WKF-001", "WKF-002", "WKF-003"}.issubset(wkfs_covered)

    # Sweep canary: any surface should reference ENT-002 (the NoteRegistry whose
    # description named the `myapp list` verb) OR have a surface_id containing
    # "list".
    refs_ent002 = any("ENT-002" in (s.get("references_entities") or []) for s in inv)
    list_surface = any("list" in (s.get("surface_id", "") or "").lower() for s in inv)
    sweep_caught = refs_ent002 or list_surface

    warnings = ux.get("ux_warnings") if isinstance(ux, dict) else None
    warnings = warnings or []
    warnings_all_prefixed = all(isinstance(w, str) and WRN_RE.match(w) for w in warnings)

    status = (ux.get("metadata") or {}).get("status") if isinstance(ux, dict) else None

    return [
        _assert("docs/UX.yaml exists", isinstance(ux, dict), str(tp / "docs" / "UX.yaml")),
        _assert("Validator exits 0", rc == 0, f"exit={rc}; {vout[:200]}"),
        _assert(
            "Status == 'complete'", status == "complete", f"status={status!r}",
        ),
        _assert(
            "surface_inventory has >= 4 surfaces (3 WKF + >= 1 sweep)",
            n_surfaces >= 4,
            f"n_surfaces={n_surfaces}",
        ),
        _assert(
            "Every surface_inventory[i].id matches SCR-NNN",
            all_ids_ok,
            f"ids={[s.get('id') for s in inv]}",
        ),
        _assert(
            "WKF-001/002/003 all referenced in traces_workflows",
            all_wkfs_covered,
            f"covered={sorted(wkfs_covered)}",
        ),
        _assert(
            "Sweep caught the ENT-002-implied surface (list / NoteRegistry)",
            sweep_caught,
            f"list_surface_seen={list_surface}; refs_ent002={refs_ent002}",
        ),
        _assert(
            "All ux_warnings entries (if any) start with WRN-NNN",
            warnings_all_prefixed,
            f"warnings={warnings[:3]}...",
        ),
    ]


GRADERS: dict[int, Callable[[Path], List[dict]]] = {
    1: grade_eval_1,
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--iteration", type=int, default=1)
    args = parser.parse_args()

    iteration_dir = WORKSPACE / f"iteration-{args.iteration}"
    if not iteration_dir.exists():
        print(f"ERROR: {iteration_dir} does not exist — run stage_iteration.py first.")
        return 2

    rows: list[dict] = []
    for eval_dir in sorted(iteration_dir.iterdir()):
        if not eval_dir.is_dir() or not eval_dir.name.startswith("eval-"):
            continue
        meta_path = eval_dir / "eval_metadata.json"
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        eid = meta["eval_id"]
        grader = GRADERS.get(eid)
        if grader is None:
            print(f"WARN: no grader for eval {eid}, skipping")
            continue
        tp = eval_dir / "test-project"
        results = grader(tp)
        passed = sum(1 for r in results if r["passed"])
        total = len(results)
        grading = {
            "eval_id": eid,
            "eval_name": meta["eval_name"],
            "passed": passed,
            "total": total,
            "pass_rate": passed / total if total else 0.0,
            "expectations": results,
        }
        (eval_dir / "grading.json").write_text(json.dumps(grading, indent=2), encoding="utf-8")
        rows.append(grading)
        bar = "#" * passed + "-" * (total - passed)
        print(f"  eval {eid:>2}: {meta['eval_name']:<40} [{bar}] {passed}/{total}")

    lines = ["# sdlc-ux eval results — iteration " + str(args.iteration), ""]
    total_p = sum(r["passed"] for r in rows)
    total_t = sum(r["total"] for r in rows)
    lines.append(
        f"**Overall pass rate:** {total_p}/{total_t} ({(total_p/total_t*100 if total_t else 0):.0f}%)"
    )
    lines.append("")
    lines.append("| Eval | Name | Passed | Total |")
    lines.append("|---:|---|---:|---:|")
    for r in rows:
        lines.append(f"| {r['eval_id']} | {r['eval_name']} | {r['passed']} | {r['total']} |")
    lines.append("")
    lines.append("## Per-eval detail")
    for r in rows:
        lines.append(f"\n### Eval {r['eval_id']} — {r['eval_name']}  ({r['passed']}/{r['total']})\n")
        for exp in r["expectations"]:
            mark = "[OK]  " if exp["passed"] else "[FAIL]"
            lines.append(f"- {mark} {exp['text']}  \n  *evidence:* `{exp['evidence']}`")
    out = iteration_dir / "benchmark.md"
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nWrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
