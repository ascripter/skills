"""Grade subagent outputs for the sdlc-test eval suite.

Usage:
    python sdlc/skills/test/evals/grade.py --iteration 1

For each eval directory under sdlc-test-workspace/iteration-N/, this inspects
test-project/docs/TEST-STRATEGY.yaml (+ any TEST-STRATEGY__*.yaml) against the
assertions for that eval, runs the sdlc-test validator for the exit-code check,
and writes per-eval grading.json + a top-level benchmark.md summary.

The structural checks mirror the validator's own trace-or-defer semantics
(coverage via `covers` / `targets_*`, deferral via a WRN-NNN that names the id)
so the grader and the validator agree on what "covered" means.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Callable, List, Set

import yaml

REPO_ROOT = Path(__file__).resolve().parents[4]
SKILL_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = REPO_ROOT / "sdlc-test-workspace"
VALIDATOR = SKILL_ROOT / "validate_schema.py"

TST_RE = re.compile(r"^TST-\d{3,}$")
WRN_RE = re.compile(r"^WRN-\d{3,}:\s+.+")
REQ_TOKEN_RE = re.compile(r"\b(?:FR|NFR|ACR|WKF)-\d+\b", re.IGNORECASE)
CHANGELOG_RE = re.compile(r"^\d+(?:\.\d+)*\s*\(\d{4}-\d{2}-\d{2}\):\s+.+")


def _assert(text: str, ok: bool, evidence: str) -> dict:
    return {"text": text, "passed": bool(ok), "evidence": evidence}


def _load_yaml(path: Path):
    if not path.exists():
        return None
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        return {"__parse_error__": str(e)}


def _validator_exit(tp: Path) -> tuple[int, str]:
    """Run the sdlc-test validator anchored at docs/TEST-STRATEGY.yaml.

    The validator validates the system file plus every sibling
    TEST-STRATEGY__*.yaml in the same dir, so a single anchor covers all modes.
    """
    anchor = tp / "docs" / "TEST-STRATEGY.yaml"
    if not (anchor.exists() or list((tp / "docs").glob("TEST-STRATEGY__*.yaml"))):
        return 99, "no TEST-STRATEGY*.yaml produced"
    r = subprocess.run(
        [sys.executable, str(VALIDATOR), "--path", "docs/TEST-STRATEGY.yaml"],
        cwd=tp,
        capture_output=True,
        text=True,
    )
    return r.returncode, (r.stdout + r.stderr).strip()


def _all_match(values, regex: re.Pattern) -> bool:
    return all(isinstance(v, str) and regex.match(v) for v in values)


def _tests(doc: dict) -> List[dict]:
    return [t for t in (doc.get("tests") or []) if isinstance(t, dict)]


def _req_tokens(strings) -> Set[str]:
    out: Set[str] = set()
    for s in strings or []:
        if isinstance(s, str):
            for m in REQ_TOKEN_RE.findall(s):
                out.add(m.upper())
    return out


def _deferred_literals(warnings, ids: Set[str]) -> Set[str]:
    deferred: Set[str] = set()
    for i in ids:
        pat = re.compile(r"\b" + re.escape(i) + r"\b")
        if any(isinstance(w, str) and pat.search(w) for w in (warnings or [])):
            deferred.add(i)
    return deferred


def _changelog_ok(doc: dict) -> bool:
    changelog = (doc.get("metadata") or {}).get("changelog") or []
    return isinstance(changelog, list) and len(changelog) >= 1 and any(
        isinstance(e, str) and CHANGELOG_RE.match(e) for e in changelog
    )


# ---------------------------------------------------------------------------
# Upstream loaders (read from the staged test-project, so the grader tracks
# whatever the fixtures actually declare).
# ---------------------------------------------------------------------------


def _arch_container_ids(tp: Path) -> Set[str]:
    arch = _load_yaml(tp / "docs" / "ARCH.yaml")
    if not isinstance(arch, dict):
        return set()
    return {
        c.get("container_id")
        for c in (arch.get("containers") or [])
        if isinstance(c, dict) and c.get("container_id")
    }


def _arch_backend_facts(tp: Path) -> dict:
    """component_ids, components_with_acceptance, failure_mode_ids,
    security_concern_ids declared in ARCH__backend-api.yaml."""
    facts = {
        "component_ids": set(),
        "components_with_acceptance": set(),
        "failure_mode_ids": set(),
        "security_concern_ids": set(),
    }
    raw = _load_yaml(tp / "docs" / "ARCH__backend-api.yaml")
    if not isinstance(raw, dict):
        return facts
    for fm in raw.get("failure_modes") or []:
        if isinstance(fm, dict) and isinstance(fm.get("id"), str):
            facts["failure_mode_ids"].add(fm["id"])
    for sc in raw.get("security_concerns") or []:
        if isinstance(sc, dict) and isinstance(sc.get("id"), str):
            facts["security_concern_ids"].add(sc["id"])
    for comp in raw.get("components") or []:
        if not isinstance(comp, dict):
            continue
        cid = comp.get("component_id")
        if cid:
            facts["component_ids"].add(cid)
            if comp.get("acceptance_criteria"):
                facts["components_with_acceptance"].add(cid)
        for fm in comp.get("failure_modes") or []:
            if isinstance(fm, dict) and isinstance(fm.get("id"), str):
                facts["failure_mode_ids"].add(fm["id"])
    return facts


# ---------------------------------------------------------------------------
# Shared container coverage assertions (used by evals 2 and 3).
# ---------------------------------------------------------------------------


def _container_coverage_asserts(tp: Path, container: dict) -> List[dict]:
    facts = _arch_backend_facts(tp)
    tests = _tests(container)
    warnings = container.get("test_strategy_warnings") or []

    covers_tokens: Set[str] = set()
    component_refs: Set[str] = set()
    unit_without_ref = 0
    targeted_fmodes: Set[str] = set()
    targeted_concerns: Set[str] = set()
    for t in tests:
        covers_tokens |= _req_tokens(t.get("covers") or [])
        if t.get("component_ref"):
            component_refs.add(t["component_ref"])
        if t.get("tier") == "unit" and not t.get("component_ref"):
            unit_without_ref += 1
        if t.get("targets_failure_mode"):
            targeted_fmodes.add(t["targets_failure_mode"])
        if t.get("targets_security_concern"):
            targeted_concerns.add(t["targets_security_concern"])

    deferred_reqs = _req_tokens(warnings)
    deferred_components = _deferred_literals(warnings, facts["components_with_acceptance"])
    deferred_fmodes = _deferred_literals(warnings, facts["failure_mode_ids"])
    deferred_concerns = _deferred_literals(warnings, facts["security_concern_ids"])

    required_frs = {"FR-001", "FR-002", "FR-003", "FR-004"}
    fr_covered = all((f in covers_tokens or f in deferred_reqs) for f in required_frs)
    no_fr005 = "FR-005" not in covers_tokens

    accept = facts["components_with_acceptance"]
    accept_covered = all((c in component_refs or c in deferred_components) for c in accept)

    refs_resolve = component_refs.issubset(facts["component_ids"]) if facts["component_ids"] else True

    fmodes_covered = all(
        (fid in targeted_fmodes or fid in deferred_fmodes) for fid in facts["failure_mode_ids"]
    )
    concerns_covered = all(
        (sid in targeted_concerns or sid in deferred_concerns)
        for sid in facts["security_concern_ids"]
    )

    tst_ids = [t.get("tst_id") for t in tests]
    tst_ok = all(isinstance(x, str) and TST_RE.match(x) for x in tst_ids) and (
        len(tst_ids) == len(set(tst_ids))
    )

    return [
        _assert(
            "FR-001..FR-004 each covered by a test or deferred (WRN-NNN)",
            fr_covered,
            f"covers={sorted(t for t in covers_tokens if t.startswith('FR'))}; deferred={sorted(deferred_reqs)}",
        ),
        _assert("No test covers FR-005 (owned by digest-worker, not backend-api)", no_fr005,
                f"covers_FR={sorted(t for t in covers_tokens if t.startswith('FR'))}"),
        _assert(
            "Every acceptance-bearing component targeted by component_ref or deferred",
            accept_covered,
            f"acceptance_components={sorted(accept)}; component_refs={sorted(component_refs)}; deferred={sorted(deferred_components)}",
        ),
        _assert("No unit-tier test missing component_ref", unit_without_ref == 0,
                f"unit_without_ref={unit_without_ref}"),
        _assert("Every component_ref resolves to an ARCH__backend-api component",
                refs_resolve, f"refs={sorted(component_refs)}; known={sorted(facts['component_ids'])}"),
        _assert(
            "failure_modes ids each exercised (targets_failure_mode) or deferred",
            fmodes_covered,
            f"failure_modes={sorted(facts['failure_mode_ids'])}; targeted={sorted(targeted_fmodes)}; deferred={sorted(deferred_fmodes)}",
        ),
        _assert(
            "security_concerns ids each exercised (targets_security_concern) or deferred",
            concerns_covered,
            f"concerns={sorted(facts['security_concern_ids'])}; targeted={sorted(targeted_concerns)}; deferred={sorted(deferred_concerns)}",
        ),
        _assert("All tst_id match TST-NNN and are unique", tst_ok, f"tst_ids={tst_ids}"),
        _assert("All test_strategy_warnings start with WRN-NNN",
                _all_match(warnings, WRN_RE), f"warnings={warnings[:3]}"),
    ]


# ---------------------------------------------------------------------------
# Per-eval graders
# ---------------------------------------------------------------------------


def grade_eval_1(tp: Path) -> List[dict]:
    """system-workflow-coverage — system file + cross-container WKF gate."""
    sysm = _load_yaml(tp / "docs" / "TEST-STRATEGY.yaml")
    rc, vout = _validator_exit(tp)
    if not isinstance(sysm, dict) or "__parse_error__" in sysm:
        return [_assert("docs/TEST-STRATEGY.yaml exists and parses", False,
                        str(sysm) if sysm else "missing")]

    meta = sysm.get("metadata") or {}
    approach = sysm.get("test_approach") or {}
    cov = sysm.get("coverage_threshold") or {}
    tests = _tests(sysm)
    warnings = sysm.get("test_strategy_warnings") or []
    arch_ids = _arch_container_ids(tp)

    covers_wkf: Set[str] = set()
    involves: Set[str] = set()
    covers_format_ok = True
    for t in tests:
        for ref in t.get("covers") or []:
            up = str(ref).upper()
            if not REQ_TOKEN_RE.fullmatch(up):
                covers_format_ok = False
            if up.startswith("WKF-"):
                covers_wkf.add(up)
        involves.update(t.get("involves_containers") or [])
    deferred = _req_tokens(warnings)
    cross_wkf = {"WKF-001", "WKF-002", "WKF-003"}
    wkf_covered = all((w in covers_wkf or w in deferred) for w in cross_wkf)
    involves_resolve = involves.issubset(arch_ids) if arch_ids else True

    tst_ids = [t.get("tst_id") for t in tests]
    tst_ok = all(isinstance(x, str) and TST_RE.match(x) for x in tst_ids) and (
        len(tst_ids) == len(set(tst_ids))
    )

    return [
        _assert("docs/TEST-STRATEGY.yaml exists and parses", True, str(tp / "docs" / "TEST-STRATEGY.yaml")),
        _assert("Validator exits 0", rc == 0, f"exit={rc}; {vout[:200]}"),
        _assert("metadata.status == 'complete'", meta.get("status") == "complete", f"status={meta.get('status')!r}"),
        _assert("test_approach.pyramid_targets is set", bool(approach.get("pyramid_targets")),
                f"pyramid_targets={approach.get('pyramid_targets')!r}"),
        _assert("coverage_threshold.line_pct is set", cov.get("line_pct") is not None,
                f"line_pct={cov.get('line_pct')!r}"),
        _assert("mock_policy and fixture_strategy are set",
                bool(sysm.get("mock_policy")) and bool(sysm.get("fixture_strategy")),
                f"mock={bool(sysm.get('mock_policy'))}; fixture={bool(sysm.get('fixture_strategy'))}"),
        _assert("tests[] is non-empty", len(tests) >= 1, f"n_tests={len(tests)}"),
        _assert("WKF-001/002/003 each covered by a system test or deferred (WRN-NNN)",
                wkf_covered, f"covered_wkf={sorted(covers_wkf)}; deferred={sorted(deferred)}"),
        _assert("All covers entries are FR/NFR/ACR/WKF ids", covers_format_ok,
                f"covers_sample={[t.get('covers') for t in tests][:4]}"),
        _assert("All involves_containers resolve to ARCH container_ids", involves_resolve,
                f"involves={sorted(involves)}; arch_ids={sorted(arch_ids)}"),
        _assert("All test_strategy_warnings start with WRN-NNN", _all_match(warnings, WRN_RE),
                f"warnings={warnings[:3]}"),
        _assert("All tst_id match TST-NNN and are unique", tst_ok, f"tst_ids={tst_ids}"),
        _assert("metadata.changelog has >= 1 well-formed entry", _changelog_ok(sysm),
                f"changelog={(meta.get('changelog') or [])[:2]}"),
    ]


def grade_eval_2(tp: Path) -> List[dict]:
    """container-coverage-gate — backend-api container file + trace-or-defer gate."""
    container = _load_yaml(tp / "docs" / "TEST-STRATEGY__backend-api.yaml")
    sysm = _load_yaml(tp / "docs" / "TEST-STRATEGY.yaml")
    rc, vout = _validator_exit(tp)
    if not isinstance(container, dict) or "__parse_error__" in container:
        return [_assert("docs/TEST-STRATEGY__backend-api.yaml exists and parses", False,
                        str(container) if container else "missing")]

    meta = container.get("metadata") or {}
    registered = False
    if isinstance(sysm, dict):
        registered = any(
            isinstance(r, dict) and r.get("container_id") == "backend-api"
            for r in (sysm.get("container_strategies") or [])
        )

    out = [
        _assert("docs/TEST-STRATEGY__backend-api.yaml exists and parses", True,
                str(tp / "docs" / "TEST-STRATEGY__backend-api.yaml")),
        _assert("Validator exits 0", rc == 0, f"exit={rc}; {vout[:200]}"),
        _assert("container_id == 'backend-api'", container.get("container_id") == "backend-api",
                f"container_id={container.get('container_id')!r}"),
        _assert("metadata.status == 'complete'", meta.get("status") == "complete",
                f"status={meta.get('status')!r}"),
        _assert("tests[] is non-empty", len(_tests(container)) >= 1, f"n_tests={len(_tests(container))}"),
    ]
    out.extend(_container_coverage_asserts(tp, container))
    out.append(_assert("backend-api registered in TEST-STRATEGY.yaml.container_strategies[]",
                       registered, f"registered={registered}"))
    out.append(_assert("metadata.changelog has >= 1 well-formed entry", _changelog_ok(container),
                       f"changelog={(meta.get('changelog') or [])[:2]}"))
    return out


def grade_eval_3(tp: Path) -> List[dict]:
    """next-advances-to-container — resolver lands on backend-api, system intact."""
    container = _load_yaml(tp / "docs" / "TEST-STRATEGY__backend-api.yaml")
    sysm = _load_yaml(tp / "docs" / "TEST-STRATEGY.yaml")
    rc, vout = _validator_exit(tp)

    produced_container_files = sorted(p.name for p in (tp / "docs").glob("TEST-STRATEGY__*.yaml"))
    only_backend = produced_container_files == ["TEST-STRATEGY__backend-api.yaml"]

    # System file must be left intact: its 5 original tests still present, complete.
    sys_tst_ids = set()
    sys_status = None
    registered = False
    if isinstance(sysm, dict):
        sys_tst_ids = {t.get("tst_id") for t in _tests(sysm)}
        sys_status = (sysm.get("metadata") or {}).get("status")
        registered = any(
            isinstance(r, dict) and r.get("container_id") == "backend-api"
            for r in (sysm.get("container_strategies") or [])
        )
    sys_intact = {"TST-001", "TST-002", "TST-003", "TST-004", "TST-005"}.issubset(sys_tst_ids)

    if not isinstance(container, dict) or "__parse_error__" in container:
        return [
            _assert("--next produced docs/TEST-STRATEGY__backend-api.yaml", False,
                    f"container_files={produced_container_files}"),
            _assert("Validator exits 0", rc == 0, f"exit={rc}; {vout[:200]}"),
        ]

    out = [
        _assert("--next advanced to backend-api (produced its container file)", True,
                f"container_files={produced_container_files}"),
        _assert("Validator exits 0", rc == 0, f"exit={rc}; {vout[:200]}"),
        _assert("No OTHER container file was created (only backend-api)", only_backend,
                f"container_files={produced_container_files}"),
        _assert("--next did NOT re-run system mode (5 original tests intact)", sys_intact,
                f"system_tst_ids={sorted(x for x in sys_tst_ids if x)}"),
        _assert("System metadata.status stayed 'complete'", sys_status == "complete",
                f"status={sys_status!r}"),
        _assert("backend-api registered in TEST-STRATEGY.yaml.container_strategies[]",
                registered, f"registered={registered}"),
        _assert("container_id == 'backend-api'", container.get("container_id") == "backend-api",
                f"container_id={container.get('container_id')!r}"),
        _assert("Container metadata.status == 'complete'",
                (container.get("metadata") or {}).get("status") == "complete",
                f"status={(container.get('metadata') or {}).get('status')!r}"),
    ]
    out.extend(_container_coverage_asserts(tp, container))
    return out


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
        print(f"  eval {eid:>2}: {meta['eval_name']:<36} [{bar}] {passed}/{total}")

    lines = ["# sdlc-test eval results - iteration " + str(args.iteration), ""]
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
