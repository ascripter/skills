"""Grade subagent outputs for the sdlc-data eval suite.

Usage:
    python sdlc/skills/data/evals/grade.py --iteration 1

For each eval directory under sdlc-data-workspace/iteration-N/, this inspects
test-project/docs/DATA-MODEL.yaml against the assertions declared in the
eval's expected_output and writes per-eval grading.json + a top-level
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
WORKSPACE = REPO_ROOT / "sdlc-data-workspace"
VALIDATOR = SKILL_ROOT / "validate_schema.py"

FR_RE = re.compile(r"^FR-\d{3,}$")
SCR_RE = re.compile(r"^SCR-\d{3,}$")
WKF_RE = re.compile(r"^WKF-\d{3,}$")
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
        return 99, "DATA-MODEL.yaml missing"
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
    """workflow-implied-entity: sweep canary on WKF-003 implying BranchSession."""
    dm = _load_yaml(tp / "docs" / "DATA-MODEL.yaml")
    rc, vout = _validator_exit(tp / "docs" / "DATA-MODEL.yaml", tp)

    if not isinstance(dm, dict):
        return [_assert("docs/DATA-MODEL.yaml exists and is valid YAML", False, str(tp / "docs" / "DATA-MODEL.yaml"))]

    entities = dm.get("entities") or {}
    entity_names = list(entities.keys())

    status = (dm.get("metadata") or {}).get("status")
    changelog = (dm.get("metadata") or {}).get("changelog") or []
    warnings = dm.get("data_warnings") or []

    fr_traces_ok = True
    scr_traces_ok = True
    wkf_traces_ok = True
    all_fr: set[str] = set()
    all_scr: set[str] = set()
    all_wkf: set[str] = set()
    for ent in entities.values():
        if not isinstance(ent, dict):
            continue
        for f in ent.get("traces_prd_features") or []:
            all_fr.add(f)
            if not (isinstance(f, str) and FR_RE.match(f)):
                fr_traces_ok = False
        for s in ent.get("traces_ux_surfaces") or []:
            all_scr.add(s)
            if not (isinstance(s, str) and SCR_RE.match(s)):
                scr_traces_ok = False
        for w in ent.get("traces_prd_workflows") or []:
            all_wkf.add(w)
            if not (isinstance(w, str) and WKF_RE.match(w)):
                wkf_traces_ok = False

    # Sweep canary: at least one entity should trace WKF-003.
    sweep_caught = "WKF-003" in all_wkf
    # Sweep candidate naming hint: any entity name containing "branch" or "session".
    sweep_name_hint = any(
        re.search(r"branch|session", name, re.IGNORECASE) for name in entity_names
    )

    changelog_ok = isinstance(changelog, list) and len(changelog) >= 1 and any(
        isinstance(e, str) and CHANGELOG_RE.match(e) for e in changelog
    )
    warnings_ok = _all_match(warnings, WRN_RE)

    return [
        _assert("docs/DATA-MODEL.yaml exists and parses", True, str(tp / "docs" / "DATA-MODEL.yaml")),
        _assert("Validator exits 0", rc == 0, f"exit={rc}; {vout[:200]}"),
        _assert("Status == 'complete'", status == "complete", f"status={status!r}"),
        _assert(
            "entities has >= 2 entries (Project + sweep-derived)",
            len(entities) >= 2,
            f"n_entities={len(entities)}, names={entity_names}",
        ),
        _assert(
            "Sweep entity references WKF-003",
            sweep_caught,
            f"all_wkf_traces={sorted(all_wkf)}",
        ),
        _assert(
            "A BranchSession-style entity is present (name contains 'branch' or 'session')",
            sweep_name_hint,
            f"entity_names={entity_names}",
        ),
        _assert(
            "Every entity's traces_prd_features matches FR-NNN",
            fr_traces_ok,
            f"sample={sorted(all_fr)[:5]}",
        ),
        _assert(
            "Every entity's traces_ux_surfaces matches SCR-NNN",
            scr_traces_ok,
            f"sample={sorted(all_scr)[:5]}",
        ),
        _assert(
            "Every entity's traces_prd_workflows (if present) matches WKF-NNN",
            wkf_traces_ok,
            f"sample={sorted(all_wkf)[:5]}",
        ),
        _assert(
            "metadata.changelog has >= 1 entry of form '<ver> (YYYY-MM-DD): ...'",
            changelog_ok,
            f"changelog={changelog[:2] if isinstance(changelog, list) else changelog}",
        ),
        _assert(
            "All data_warnings entries (if any) start with WRN-NNN",
            warnings_ok,
            f"warnings={warnings[:3]}",
        ),
    ]


def grade_eval_2(tp: Path) -> List[dict]:
    """existing-data-update-flow: merge path on stale DATA-MODEL."""
    dm = _load_yaml(tp / "docs" / "DATA-MODEL.yaml")
    rc, vout = _validator_exit(tp / "docs" / "DATA-MODEL.yaml", tp)

    if not isinstance(dm, dict):
        return [_assert("docs/DATA-MODEL.yaml exists and parses", False, str(tp / "docs" / "DATA-MODEL.yaml"))]

    entities = dm.get("entities") or {}
    metadata = dm.get("metadata") or {}
    status = metadata.get("status")
    changelog = metadata.get("changelog") or []
    version = str(metadata.get("data_model_version") or "")
    warnings = dm.get("data_warnings") or []

    comment_ent = entities.get("Comment") if isinstance(entities.get("Comment"), dict) else None
    comment_fr_ok = bool(comment_ent) and "FR-003" in (comment_ent.get("traces_prd_features") or [])
    comment_scr_ok = bool(comment_ent) and "SCR-003" in (comment_ent.get("traces_ux_surfaces") or [])

    # Task entity preservation — original fixture had traces_prd_features ["FR-001","FR-002"].
    task_ent = entities.get("Task") if isinstance(entities.get("Task"), dict) else None
    task_traces = set((task_ent or {}).get("traces_prd_features") or [])
    task_preserved = task_ent is not None and {"FR-001", "FR-002"}.issubset(task_traces)

    changelog_ok = isinstance(changelog, list) and len(changelog) >= 1 and any(
        isinstance(e, str) and CHANGELOG_RE.match(e) for e in changelog
    )
    warnings_ok = _all_match(warnings, WRN_RE)
    version_ok = bool(re.match(r"^1\.[1-9]\d*", version)) or bool(re.match(r"^[2-9]\.", version))

    return [
        _assert("docs/DATA-MODEL.yaml exists and parses", True, str(tp / "docs" / "DATA-MODEL.yaml")),
        _assert("Validator exits 0", rc == 0, f"exit={rc}; {vout[:200]}"),
        _assert("Status == 'complete'", status == "complete", f"status={status!r}"),
        _assert(
            "Comment entity present",
            comment_ent is not None,
            f"entity_names={list(entities.keys())}",
        ),
        _assert(
            "Comment.traces_prd_features contains FR-003",
            comment_fr_ok,
            f"comment_features={(comment_ent or {}).get('traces_prd_features')}",
        ),
        _assert(
            "Comment.traces_ux_surfaces contains SCR-003",
            comment_scr_ok,
            f"comment_surfaces={(comment_ent or {}).get('traces_ux_surfaces')}",
        ),
        _assert(
            "Task entity preserved with FR-001 + FR-002 traces",
            task_preserved,
            f"task_traces={sorted(task_traces)}",
        ),
        _assert(
            "metadata.changelog populated (>= 1 entry, formatted)",
            changelog_ok,
            f"changelog_len={len(changelog) if isinstance(changelog, list) else 'n/a'}; first={changelog[:1]}",
        ),
        _assert(
            "data_model_version >= 1.1",
            version_ok,
            f"version={version!r}",
        ),
        _assert(
            "All data_warnings entries (if any) start with WRN-NNN",
            warnings_ok,
            f"warnings={warnings[:3]}",
        ),
    ]


def _fr_coverage(entities: dict, required: set[str]) -> tuple[bool, set[str]]:
    traced: set[str] = set()
    for ent in entities.values():
        if isinstance(ent, dict):
            for f in ent.get("traces_prd_features") or []:
                traced.add(f)
    return required.issubset(traced), traced


def grade_eval_3(tp: Path) -> List[dict]:
    """file-native-paradigm: agent recommends file_native and produces a clean
    file-native model (identity_conventions + pydantic_type fields, no fabricated
    relational blocks)."""
    dm = _load_yaml(tp / "docs" / "DATA-MODEL.yaml")
    rc, vout = _validator_exit(tp / "docs" / "DATA-MODEL.yaml", tp)

    if not isinstance(dm, dict):
        return [_assert("docs/DATA-MODEL.yaml exists and parses", False, str(tp / "docs" / "DATA-MODEL.yaml"))]

    persistence = dm.get("persistence") or {}
    paradigm = persistence.get("paradigm")
    primary = persistence.get("primary_store")
    metadata = dm.get("metadata") or {}
    status = metadata.get("status")
    changelog = metadata.get("changelog") or []
    entities = dm.get("entities") or {}
    ic = dm.get("identity_conventions") or {}
    ic_rules = ic.get("rules") if isinstance(ic, dict) else None

    # No fabricated relational structure.
    id_strategy = dm.get("id_strategy") or {}
    id_scheme = id_strategy.get("scheme") if isinstance(id_strategy, dict) else None
    rels = dm.get("relationships")
    rel_clean = not rels  # absent or empty list
    iq = dm.get("indexes_and_queries") or {}
    iq_clean = not (iq.get("expected_indexes") if isinstance(iq, dict) else None)

    # At least one entity field uses pydantic_type.
    pydantic_type_used = False
    for ent in entities.values():
        if isinstance(ent, dict):
            for fld in (ent.get("fields") or {}).values():
                if isinstance(fld, dict) and fld.get("pydantic_type"):
                    pydantic_type_used = True

    fr_ok, traced = _fr_coverage(entities, {"FR-001", "FR-002", "FR-003"})
    changelog_ok = isinstance(changelog, list) and len(changelog) >= 1

    return [
        _assert("docs/DATA-MODEL.yaml exists and parses", True, str(tp / "docs" / "DATA-MODEL.yaml")),
        _assert("Validator exits 0", rc == 0, f"exit={rc}; {vout[:200]}"),
        _assert("Status == 'complete'", status == "complete", f"status={status!r}"),
        _assert("persistence.paradigm == 'file_native'", paradigm == "file_native", f"paradigm={paradigm!r}"),
        _assert("persistence.primary_store == 'filesystem'", primary == "filesystem", f"primary_store={primary!r}"),
        _assert(
            "identity_conventions.rules is non-empty",
            isinstance(ic_rules, list) and len(ic_rules) >= 1,
            f"rules={ic_rules!r}",
        ),
        _assert(
            "No fabricated id_strategy.scheme (file_native has no surrogate PK)",
            id_scheme is None,
            f"id_strategy.scheme={id_scheme!r}",
        ),
        _assert(
            "No fabricated relationships block",
            rel_clean,
            f"relationships={rels!r}",
        ),
        _assert(
            "No fabricated expected_indexes",
            iq_clean,
            f"indexes_and_queries={iq!r}",
        ),
        _assert(
            "At least one entity field uses pydantic_type",
            pydantic_type_used,
            f"entities={list(entities.keys())}",
        ),
        _assert("entities has >= 2 entries (Outline + Section)", len(entities) >= 2, f"names={list(entities.keys())}"),
        _assert("All PRD must-have FRs (FR-001..003) covered", fr_ok, f"traced={sorted(traced)}"),
        _assert("metadata.changelog has >= 1 entry", changelog_ok, f"changelog={changelog[:2]}"),
    ]


def grade_eval_4(tp: Path) -> List[dict]:
    """paradigm-recommendation-relational: agent honors the explicit sqlite
    storage preference and produces a populated relational model."""
    dm = _load_yaml(tp / "docs" / "DATA-MODEL.yaml")
    rc, vout = _validator_exit(tp / "docs" / "DATA-MODEL.yaml", tp)

    if not isinstance(dm, dict):
        return [_assert("docs/DATA-MODEL.yaml exists and parses", False, str(tp / "docs" / "DATA-MODEL.yaml"))]

    persistence = dm.get("persistence") or {}
    paradigm = persistence.get("paradigm")
    primary = persistence.get("primary_store")
    metadata = dm.get("metadata") or {}
    status = metadata.get("status")
    entities = dm.get("entities") or {}

    id_strategy = dm.get("id_strategy") or {}
    id_scheme = id_strategy.get("scheme") if isinstance(id_strategy, dict) else None
    rels = dm.get("relationships")
    iq = dm.get("indexes_and_queries") or {}
    access_patterns = iq.get("access_patterns") if isinstance(iq, dict) else None
    ic = dm.get("integrity_and_constraints") or {}
    default_on_delete = ic.get("default_on_delete") if isinstance(ic, dict) else None

    fr_ok, traced = _fr_coverage(entities, {"FR-001", "FR-002", "FR-003"})

    return [
        _assert("docs/DATA-MODEL.yaml exists and parses", True, str(tp / "docs" / "DATA-MODEL.yaml")),
        _assert("Validator exits 0", rc == 0, f"exit={rc}; {vout[:200]}"),
        _assert("Status == 'complete'", status == "complete", f"status={status!r}"),
        _assert(
            "persistence.paradigm == 'relational' (defaults/honored, may be omitted)",
            paradigm in ("relational", None),
            f"paradigm={paradigm!r}",
        ),
        _assert(
            "persistence.primary_store == 'sqlite' (honors PRD preference)",
            primary == "sqlite",
            f"primary_store={primary!r}",
        ),
        _assert("id_strategy.scheme is set", id_scheme is not None, f"scheme={id_scheme!r}"),
        _assert("relationships block present", rels is not None, f"relationships={rels!r}"),
        _assert(
            "indexes_and_queries.access_patterns present",
            access_patterns is not None,
            f"access_patterns={access_patterns!r}",
        ),
        _assert(
            "integrity_and_constraints.default_on_delete set",
            default_on_delete is not None,
            f"default_on_delete={default_on_delete!r}",
        ),
        _assert("entities has >= 2 entries (Project + sweep)", len(entities) >= 2, f"names={list(entities.keys())}"),
        _assert("All PRD must-have FRs (FR-001..003) covered", fr_ok, f"traced={sorted(traced)}"),
    ]


GRADERS: dict[int, Callable[[Path], List[dict]]] = {
    1: grade_eval_1,
    2: grade_eval_2,
    3: grade_eval_3,
    4: grade_eval_4,
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

    lines = ["# sdlc-data eval results - iteration " + str(args.iteration), ""]
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
