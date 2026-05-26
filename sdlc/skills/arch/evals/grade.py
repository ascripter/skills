"""Grade subagent outputs for the sdlc-arch eval suite.

Usage:
    python sdlc/skills/arch/evals/grade.py --iteration 1

For each eval directory under sdlc-arch-workspace/iteration-N/, this inspects
test-project/docs/ARCH.yaml (+ any per-container docs/ARCH__*.yaml) against
the assertions for that eval. Writes per-eval grading.json + a top-level
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
WORKSPACE = REPO_ROOT / "sdlc-arch-workspace"
VALIDATOR = SKILL_ROOT / "validate_schema.py"

FR_RE = re.compile(r"^FR-\d{3,}$")
WKF_RE = re.compile(r"^WKF-\d{3,}$")
WRN_RE = re.compile(r"^WRN-\d{3,}:\s+.+")
CHANGELOG_RE = re.compile(r"^\d+(?:\.\d+)*\s*\(\d{4}-\d{2}-\d{2}\):\s+.+")

# Operational-container archetypes that can legitimately own the FR-005 send job.
OPERATIONAL_ARCHETYPES = {"scheduler", "worker", "stream-processor", "etl-pipeline"}


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
        return 99, "ARCH.yaml missing"
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
    """web-app-with-digest-job — operational-container sweep + conventions."""
    arch = _load_yaml(tp / "docs" / "ARCH.yaml")
    rc, vout = _validator_exit(tp / "docs" / "ARCH.yaml", tp)

    if not isinstance(arch, dict):
        return [_assert("docs/ARCH.yaml exists and parses", False, str(tp / "docs" / "ARCH.yaml"))]

    metadata = arch.get("metadata") or {}
    status = metadata.get("status")
    changelog = metadata.get("changelog") or []
    pattern = (arch.get("architecture_pattern") or {}).get("pattern")
    identity = arch.get("identity_and_auth") or {}
    token_strategy = identity.get("token_strategy")
    containers = [c for c in (arch.get("containers") or []) if isinstance(c, dict)]
    warnings = arch.get("arch_warnings") or []
    non_container = arch.get("non_container_features") or []

    # Aggregate per-container fields.
    archetypes = [c.get("archetype") for c in containers]
    owns_api: set[str] = set()
    owns_ux: set[str] = set()
    persistence: set[str] = set()
    implements: set[str] = set()
    wkf_traces: set[str] = set()
    for c in containers:
        owns_api.update(c.get("owns_api_resources") or [])
        owns_ux.update(c.get("owns_ux_surfaces") or [])
        persistence.update(c.get("persistence") or [])
        implements.update(c.get("implements_requirements") or [])
        wkf_traces.update(c.get("traces_prd_workflows") or [])

    # FR-005 owned by an operational container?
    fr005_in_operational = any(
        c.get("archetype") in OPERATIONAL_ARCHETYPES
        and "FR-005" in (c.get("implements_requirements") or [])
        for c in containers
    )
    fr005_handled = fr005_in_operational or ("FR-005" in {
        x.strip().upper() for x in non_container if isinstance(x, str)
    })

    # Feature coverage: FR-001..FR-005 each implemented OR opted out.
    implemented_norm = {f.strip().upper() for f in implements if isinstance(f, str)}
    nonc_norm = {f.strip().upper() for f in non_container if isinstance(f, str)}
    fr_universe = {f"FR-00{i}" for i in range(1, 6)}
    fr_covered = fr_universe.issubset(implemented_norm | nonc_norm)

    has_identity_container = any(
        c.get("archetype") == "identity-provider"
        or "identity" in str(c.get("container_id", "")).lower()
        for c in containers
    )
    has_operational_container = any(a in OPERATIONAL_ARCHETYPES for a in archetypes)

    # Coverage of the concrete upstream ids.
    api_owned = {"tasks", "comments", "digest-settings"}.issubset(owns_api)
    ux_owned = {"task-list", "task-detail", "comments-panel", "digest-settings"}.issubset(owns_ux)
    postgres_bound = "postgres" in persistence

    fr_format_ok = _all_match(implements, FR_RE) and _all_match(non_container, FR_RE)
    wkf_format_ok = _all_match(wkf_traces, WKF_RE) if wkf_traces else True
    warnings_ok = _all_match(warnings, WRN_RE)
    changelog_ok = isinstance(changelog, list) and len(changelog) >= 1 and any(
        isinstance(e, str) and CHANGELOG_RE.match(e) for e in changelog
    )

    return [
        _assert("docs/ARCH.yaml exists and parses", True, str(tp / "docs" / "ARCH.yaml")),
        _assert("Validator exits 0", rc == 0, f"exit={rc}; {vout[:200]}"),
        _assert("Status == 'complete'", status == "complete", f"status={status!r}"),
        _assert("architecture_pattern.pattern is set", bool(pattern), f"pattern={pattern!r}"),
        _assert(
            "identity_and_auth.token_strategy == 'jwt' (PRD conventions)",
            token_strategy == "jwt",
            f"token_strategy={token_strategy!r}",
        ),
        _assert(
            "An identity-provider container exists (auth_model: jwt)",
            has_identity_container,
            f"archetypes={archetypes}",
        ),
        _assert(
            "An operational container (scheduler/worker/...) exists",
            has_operational_container,
            f"archetypes={archetypes}",
        ),
        _assert(
            "FR-005 (digest send) owned by an operational container OR non_container_features",
            fr005_handled,
            f"in_operational={fr005_in_operational}; non_container={sorted(nonc_norm)}",
        ),
        _assert(
            "Every PRD must-have FR-001..FR-005 implemented OR opted out",
            fr_covered,
            f"implemented={sorted(implemented_norm)}; non_container={sorted(nonc_norm)}",
        ),
        _assert(
            "Backend container owns tasks, comments, digest-settings",
            api_owned,
            f"owns_api={sorted(owns_api)}",
        ),
        _assert(
            "Frontend container owns the four UX surfaces (by surface_id)",
            ux_owned,
            f"owns_ux={sorted(owns_ux)}",
        ),
        _assert("A postgres store is bound to some container", postgres_bound, f"persistence={sorted(persistence)}"),
        _assert("All implements_requirements / non_container_features match FR-NNN", fr_format_ok, f"impl={sorted(implements)[:6]}"),
        _assert("All traces_prd_workflows match WKF-NNN", wkf_format_ok, f"wkf={sorted(wkf_traces)}"),
        _assert("All arch_warnings entries start with WRN-NNN", warnings_ok, f"warnings={warnings[:3]}"),
        _assert(
            "metadata.changelog has >= 1 entry of form '<ver> (YYYY-MM-DD): ...'",
            changelog_ok,
            f"changelog={changelog[:2] if isinstance(changelog, list) else changelog}",
        ),
    ]


def grade_eval_2(tp: Path) -> List[dict]:
    """container-mode-component-traces — component PRD/API traces + parent-subset."""
    arch = _load_yaml(tp / "docs" / "ARCH.yaml")
    container = _load_yaml(tp / "docs" / "ARCH__backend-api.yaml")
    rc, vout = _validator_exit(tp / "docs" / "ARCH.yaml", tp)

    if not isinstance(container, dict):
        return [_assert(
            "docs/ARCH__backend-api.yaml exists and parses",
            False,
            str(tp / "docs" / "ARCH__backend-api.yaml"),
        )]

    metadata = container.get("metadata") or {}
    status = metadata.get("status")
    changelog = metadata.get("changelog") or []
    warnings = container.get("arch_warnings") or []
    components = [c for c in (container.get("components") or []) if isinstance(c, dict)]

    parent_frs = {"FR-001", "FR-002", "FR-003", "FR-004"}
    parent_resources = {"tasks", "comments", "digest-settings"}

    comp_impl: set[str] = set()
    comp_resources: set[str] = set()
    comp_wkf: set[str] = set()
    for c in components:
        comp_impl.update(c.get("implements_requirements") or [])
        comp_resources.update(c.get("traces_api_resources") or [])
        comp_wkf.update(c.get("traces_prd_workflows") or [])

    impl_norm = {x.strip().upper() for x in comp_impl if isinstance(x, str)}
    impl_subset = impl_norm.issubset(parent_frs)
    no_fr005 = "FR-005" not in impl_norm
    resources_subset = {r for r in comp_resources if isinstance(r, str)}.issubset(parent_resources)

    fr_format_ok = _all_match(comp_impl, FR_RE)
    wkf_format_ok = _all_match(comp_wkf, WKF_RE) if comp_wkf else True
    warnings_ok = _all_match(warnings, WRN_RE)
    changelog_ok = isinstance(changelog, list) and len(changelog) >= 1 and any(
        isinstance(e, str) and CHANGELOG_RE.match(e) for e in changelog
    )

    # ARCH.yaml backend-api.file_path now points at the new file.
    file_path_ok = False
    if isinstance(arch, dict):
        for c in (arch.get("containers") or []):
            if isinstance(c, dict) and c.get("container_id") == "backend-api":
                fp = str(c.get("file_path") or "")
                file_path_ok = fp.replace("\\", "/").endswith("docs/ARCH__backend-api.yaml")

    return [
        _assert("docs/ARCH__backend-api.yaml exists and parses", True, str(tp / "docs" / "ARCH__backend-api.yaml")),
        _assert("Validator exits 0", rc == 0, f"exit={rc}; {vout[:200]}"),
        _assert("Container status == 'complete'", status == "complete", f"status={status!r}"),
        _assert("Component inventory is non-empty", len(components) >= 1, f"n_components={len(components)}"),
        _assert(
            "Every component implements_requirements ⊆ parent {FR-001..FR-004}",
            impl_subset,
            f"component_impl={sorted(impl_norm)}",
        ),
        _assert(
            "No component implements FR-005 (belongs to digest-worker)",
            no_fr005,
            f"component_impl={sorted(impl_norm)}",
        ),
        _assert(
            "Every component traces_api_resources ⊆ {tasks, comments, digest-settings}",
            resources_subset,
            f"component_resources={sorted(comp_resources)}",
        ),
        _assert("All component implements_requirements match FR-NNN", fr_format_ok, f"impl={sorted(comp_impl)[:6]}"),
        _assert("All component traces_prd_workflows match WKF-NNN", wkf_format_ok, f"wkf={sorted(comp_wkf)}"),
        _assert("All arch_warnings entries start with WRN-NNN", warnings_ok, f"warnings={warnings[:3]}"),
        _assert(
            "metadata.changelog has >= 1 entry of form '<ver> (YYYY-MM-DD): ...'",
            changelog_ok,
            f"changelog={changelog[:2] if isinstance(changelog, list) else changelog}",
        ),
        _assert(
            "ARCH.yaml.containers[backend-api].file_path points at the new file",
            file_path_ok,
            f"file_path_ok={file_path_ok}",
        ),
    ]


def grade_eval_3(tp: Path) -> List[dict]:
    """edge-rederivation — -d repopulates the typed edge graph, inventory untouched."""
    arch = _load_yaml(tp / "docs" / "ARCH.yaml")
    rc, vout = _validator_exit(tp / "docs" / "ARCH.yaml", tp)

    if not isinstance(arch, dict):
        return [_assert("docs/ARCH.yaml exists and parses", False, str(tp / "docs" / "ARCH.yaml"))]

    metadata = arch.get("metadata") or {}
    status = metadata.get("status")
    containers = [c for c in (arch.get("containers") or []) if isinstance(c, dict)]
    container_ids = {c.get("container_id") for c in containers}
    edges = [e for e in (arch.get("edges") or []) if isinstance(e, dict)]

    expected_ids = {
        "web-frontend", "backend-api", "digest-worker",
        "primary-postgres", "identity-provider",
    }
    inventory_unchanged = container_ids == expected_ids

    def _has(frm: str, to: str, types: set[str], via_res: str | None = None) -> bool:
        for e in edges:
            if e.get("from") != frm or e.get("to") != to:
                continue
            if e.get("type") not in types:
                continue
            if via_res is not None and e.get("via_resource_id") != via_res:
                continue
            return True
        return False

    fe_calls = all(
        _has("web-frontend", "backend-api", {"calls"}, r)
        for r in ("tasks", "comments", "digest-settings")
    )
    be_pg = _has("backend-api", "primary-postgres", {"reads", "writes"})
    be_idp = _has("backend-api", "identity-provider", {"calls"})
    worker_pg = _has("digest-worker", "primary-postgres", {"reads", "writes"})

    return [
        _assert("docs/ARCH.yaml exists and parses", True, str(tp / "docs" / "ARCH.yaml")),
        _assert("Validator exits 0", rc == 0, f"exit={rc}; {vout[:200]}"),
        _assert("metadata.status remained 'complete'", status == "complete", f"status={status!r}"),
        _assert(
            "Container inventory unchanged (same 5 container_ids)",
            inventory_unchanged,
            f"container_ids={sorted(x for x in container_ids if x)}",
        ),
        _assert("Edge list is non-empty after re-derivation", len(edges) >= 1, f"n_edges={len(edges)}"),
        _assert(
            "web-frontend -> backend-api calls for tasks, comments, digest-settings",
            fe_calls,
            f"edges={[(e.get('from'), e.get('to'), e.get('type'), e.get('via_resource_id')) for e in edges]}",
        ),
        _assert("backend-api -> primary-postgres reads/writes edge present", be_pg, f"be_pg={be_pg}"),
        _assert("backend-api -> identity-provider calls edge present", be_idp, f"be_idp={be_idp}"),
        _assert("digest-worker -> primary-postgres reads/writes edge present", worker_pg, f"worker_pg={worker_pg}"),
    ]


GRADERS: dict[int, Callable[[Path], List[dict]]] = {
    1: grade_eval_1,
    2: grade_eval_2,
    3: grade_eval_3,
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

    lines = ["# sdlc-arch eval results - iteration " + str(args.iteration), ""]
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
