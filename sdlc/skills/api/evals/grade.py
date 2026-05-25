"""Grade subagent outputs for the sdlc-api eval suite.

Usage:
    python sdlc/skills/api/evals/grade.py --iteration 1

For each eval directory under sdlc-api-workspace/iteration-N/, this inspects
test-project/docs/API.yaml (+ per-resource docs/API__*.yaml) against the
assertions declared in the eval's expected_output. Writes per-eval grading.json
+ a top-level benchmark.md summary.
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
WORKSPACE = REPO_ROOT / "sdlc-api-workspace"
VALIDATOR = SKILL_ROOT / "validate_schema.py"

FR_RE = re.compile(r"^FR-\d{3,}$")
SCR_RE = re.compile(r"^SCR-\d{3,}$")
WKF_RE = re.compile(r"^WKF-\d{3,}$")
OPR_RE = re.compile(r"^OPR-\d{3,}$")
WRN_RE = re.compile(r"^WRN-\d{3,}:\s+.+")
CHANGELOG_RE = re.compile(r"^\d+(?:\.\d+)*\s*\(\d{4}-\d{2}-\d{2}\):\s+.+")


def _assert(text: str, ok: bool, evidence: str) -> dict:
    return {"text": text, "passed": bool(ok), "evidence": evidence}


def _load_yaml(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        return {"__parse_error__": str(e)}


def _validator_exit(yaml_path: Path, cwd: Path) -> tuple[int, str]:
    if not yaml_path.exists():
        return 99, "API.yaml missing"
    r = subprocess.run(
        [sys.executable, str(VALIDATOR), "--path", str(yaml_path.relative_to(cwd))],
        cwd=cwd,
        capture_output=True,
        text=True,
    )
    return r.returncode, (r.stdout + r.stderr).strip()


def _all_match(values, regex: re.Pattern) -> bool:
    return all(isinstance(v, str) and regex.match(v) for v in values)


def grade_eval_1(tp: Path) -> List[dict]:
    """rest-with-coverage-sweep — FR-004 sweep canary, AuditLog internal-only, SCR-004 coverage."""
    api = _load_yaml(tp / "docs" / "API.yaml")
    rc, vout = _validator_exit(tp / "docs" / "API.yaml", tp)

    if not isinstance(api, dict):
        return [_assert("docs/API.yaml exists and parses", False, str(tp / "docs" / "API.yaml"))]

    api_kind = api.get("api_kind")
    metadata = api.get("metadata") or {}
    status = metadata.get("status")
    changelog = metadata.get("changelog") or []
    warnings = api.get("api_warnings") or []
    inventory = api.get("resource_inventory") or []
    non_api = api.get("non_api_features") or []

    # Aggregate traces & entity refs across resource_inventory + per-resource yamls.
    inv_resources = [r for r in inventory if isinstance(r, dict)]
    resource_names = [r.get("resource") or r.get("name") for r in inv_resources]

    # Walk all resource_inventory items.
    inv_fr_traces: set[str] = set()
    inv_scr_traces: set[str] = set()
    inv_wkf_traces: set[str] = set()
    primary_entities: list[str] = []
    audit_log_as_public = False
    for r in inv_resources:
        primary = r.get("primary_entity")
        if primary:
            primary_entities.append(primary)
            if primary == "AuditLog":
                audit_log_as_public = True
        for f in r.get("traces_prd_features") or []:
            inv_fr_traces.add(f)
        for s in r.get("traces_ux_surfaces") or []:
            inv_scr_traces.add(s)
        for w in r.get("traces_prd_workflows") or []:
            inv_wkf_traces.add(w)

    # Non-API features: extract any FR-NNN tokens from the items.
    non_api_fr: set[str] = set()
    if isinstance(non_api, list):
        for item in non_api:
            if isinstance(item, str):
                non_api_fr.update(FR_RE.findall(item))
                non_api_fr.update(re.findall(r"FR-\d{3,}", item))
            elif isinstance(item, dict):
                for f in item.get("features") or []:
                    if isinstance(f, str) and FR_RE.match(f):
                        non_api_fr.add(f)
                ref = item.get("feature") or item.get("id")
                if isinstance(ref, str) and FR_RE.match(ref):
                    non_api_fr.add(ref)

    fr_universe = {"FR-001", "FR-002", "FR-003", "FR-004"}
    fr_covered = fr_universe.issubset(inv_fr_traces | non_api_fr)
    fr_004_handled = ("FR-004" in inv_fr_traces) or ("FR-004" in non_api_fr)

    # SCR coverage — check that SCR-001..003 are traced; SCR-004 either traced OR deferred via WRN.
    scr_data_bearing = {"SCR-001", "SCR-002", "SCR-003"}
    scr_data_covered = scr_data_bearing.issubset(inv_scr_traces)
    scr_004_routed = "SCR-004" in inv_scr_traces
    scr_004_in_warning = any(
        isinstance(w, str) and "SCR-004" in w for w in warnings
    )
    scr_004_handled = scr_004_routed or scr_004_in_warning

    # AuditLog handling: should NOT be a public resource. Should be mentioned in api_warnings.
    audit_log_in_warning = any(
        isinstance(w, str) and "AuditLog" in w for w in warnings
    )

    # Per-resource yaml scan: every endpoint must have id: OPR-NNN.
    per_resource_yamls = sorted((tp / "docs").glob("API__*.yaml"))
    all_endpoints_have_opr = True
    opr_ids_seen: set[str] = set()
    n_endpoints = 0
    for prp in per_resource_yamls:
        prd = _load_yaml(prp)
        if not isinstance(prd, dict):
            all_endpoints_have_opr = False
            continue
        for ep in (prd.get("endpoints") or []):
            n_endpoints += 1
            if not isinstance(ep, dict):
                all_endpoints_have_opr = False
                continue
            ep_id = ep.get("id")
            if not (isinstance(ep_id, str) and OPR_RE.match(ep_id)):
                all_endpoints_have_opr = False
            else:
                opr_ids_seen.add(ep_id)
    opr_unique = len(opr_ids_seen) == n_endpoints  # no duplicates

    # Trace format checks
    fr_ok = _all_match(inv_fr_traces, FR_RE)
    scr_ok = _all_match(inv_scr_traces, SCR_RE)
    wkf_ok = _all_match(inv_wkf_traces, WKF_RE) if inv_wkf_traces else True

    warnings_ok = _all_match(warnings, WRN_RE)
    changelog_ok = isinstance(changelog, list) and len(changelog) >= 1 and any(
        isinstance(e, str) and CHANGELOG_RE.match(e) for e in changelog
    )

    return [
        _assert("docs/API.yaml exists and parses", True, str(tp / "docs" / "API.yaml")),
        _assert("Validator exits 0", rc == 0, f"exit={rc}; {vout[:200]}"),
        _assert("Status == 'complete'", status == "complete", f"status={status!r}"),
        _assert("api_kind == 'rest'", api_kind == "rest", f"api_kind={api_kind!r}"),
        _assert(
            "resource_inventory covers Task and Comment",
            "Task" in primary_entities and "Comment" in primary_entities,
            f"primary_entities={primary_entities}; resource_names={resource_names}",
        ),
        _assert(
            "FR-001..FR-004 each traced by a resource OR in non_api_features",
            fr_covered,
            f"inv_traced={sorted(inv_fr_traces)}; non_api={sorted(non_api_fr)}",
        ),
        _assert(
            "FR-004 (digest) handled (resource or non_api_features)",
            fr_004_handled,
            f"in_inv={'FR-004' in inv_fr_traces}; in_non_api={'FR-004' in non_api_fr}",
        ),
        _assert(
            "SCR-001..SCR-003 each traced by >=1 resource",
            scr_data_covered,
            f"scr_traces={sorted(inv_scr_traces)}",
        ),
        _assert(
            "SCR-004 routed to a resource OR deferred via api_warnings",
            scr_004_handled,
            f"in_traces={scr_004_routed}; in_warning={scr_004_in_warning}",
        ),
        _assert(
            "AuditLog NOT exposed as a public resource",
            not audit_log_as_public,
            f"primary_entities={primary_entities}",
        ),
        _assert(
            "AuditLog flagged via api_warnings (internal-only)",
            audit_log_in_warning,
            f"warnings_mentioning_AuditLog={[w for w in warnings if 'AuditLog' in str(w)]}",
        ),
        _assert(
            "Every endpoint in per-resource yamls has stable id: OPR-NNN",
            all_endpoints_have_opr and n_endpoints > 0,
            f"n_endpoints={n_endpoints}; all_have_opr={all_endpoints_have_opr}",
        ),
        _assert(
            "OPR-NNN ids are unique across all endpoints",
            opr_unique,
            f"unique_opr={len(opr_ids_seen)} of {n_endpoints}",
        ),
        _assert("All traces_prd_features match FR-NNN", fr_ok, f"sample={sorted(inv_fr_traces)[:5]}"),
        _assert("All traces_ux_surfaces match SCR-NNN", scr_ok, f"sample={sorted(inv_scr_traces)[:5]}"),
        _assert("All traces_prd_workflows match WKF-NNN", wkf_ok, f"sample={sorted(inv_wkf_traces)[:5]}"),
        _assert(
            "All api_warnings entries start with WRN-NNN",
            warnings_ok,
            f"warnings={warnings[:3]}",
        ),
        _assert(
            "metadata.changelog has >= 1 entry of form '<ver> (YYYY-MM-DD): ...'",
            changelog_ok,
            f"changelog={changelog[:2] if isinstance(changelog, list) else changelog}",
        ),
    ]


def grade_eval_2(tp: Path) -> List[dict]:
    """api-kind-none — early-skip path on CLI tool."""
    api = _load_yaml(tp / "docs" / "API.yaml")
    rc, vout = _validator_exit(tp / "docs" / "API.yaml", tp)

    if not isinstance(api, dict):
        return [_assert("docs/API.yaml exists and parses", False, str(tp / "docs" / "API.yaml"))]

    api_kind = api.get("api_kind")
    metadata = api.get("metadata") or {}
    status = metadata.get("status")
    changelog = metadata.get("changelog") or []
    warnings = api.get("api_warnings") or []
    inventory = api.get("resource_inventory")
    rationale = (
        api.get("api_kind_rationale")
        or api.get("rationale")
        or api.get("api_kind_reason")
    )

    inventory_empty = inventory is None or (isinstance(inventory, list) and len(inventory) == 0)

    per_resource_yamls = list((tp / "docs").glob("API__*.yaml"))
    no_per_resource = len(per_resource_yamls) == 0

    changelog_ok = isinstance(changelog, list) and len(changelog) >= 1 and any(
        isinstance(e, str) and CHANGELOG_RE.match(e) for e in changelog
    )
    warnings_ok = _all_match(warnings, WRN_RE)

    return [
        _assert("docs/API.yaml exists and parses", True, str(tp / "docs" / "API.yaml")),
        _assert("Validator exits 0", rc == 0, f"exit={rc}; {vout[:200]}"),
        _assert("Status == 'complete'", status == "complete", f"status={status!r}"),
        _assert("api_kind == 'none'", api_kind == "none", f"api_kind={api_kind!r}"),
        _assert(
            "A rationale string is present",
            isinstance(rationale, str) and len(rationale.strip()) > 0,
            f"rationale={rationale!r}",
        ),
        _assert(
            "resource_inventory is empty or null",
            inventory_empty,
            f"inventory_len={len(inventory) if isinstance(inventory, list) else inventory}",
        ),
        _assert(
            "No docs/API__<resource>.yaml files exist",
            no_per_resource,
            f"per_resource_yamls={[p.name for p in per_resource_yamls]}",
        ),
        _assert(
            "metadata.changelog initialized (>= 1 entry, formatted)",
            changelog_ok,
            f"changelog={changelog[:2] if isinstance(changelog, list) else changelog}",
        ),
        _assert(
            "api_warnings empty OR each entry starts with WRN-NNN",
            warnings_ok,
            f"warnings={warnings[:3]}",
        ),
    ]


GRADERS: dict[int, Callable[[Path], List[dict]]] = {
    1: grade_eval_1,
    2: grade_eval_2,
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--iteration", type=int, default=1)
    args = parser.parse_args()

    iteration_dir = WORKSPACE / f"iteration-{args.iteration}"
    if not iteration_dir.exists():
        print(f"ERROR: {iteration_dir} does not exist - run stage_iteration.py first.")
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

    lines = ["# sdlc-api eval results - iteration " + str(args.iteration), ""]
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
        lines.append(f"\n### Eval {r['eval_id']} - {r['eval_name']}  ({r['passed']}/{r['total']})\n")
        for exp in r["expectations"]:
            mark = "[OK]  " if exp["passed"] else "[FAIL]"
            lines.append(f"- {mark} {exp['text']}  \n  *evidence:* `{exp['evidence']}`")
    out = iteration_dir / "benchmark.md"
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nWrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
