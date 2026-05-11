"""Grade subagent outputs for the sdlc-prd eval suite.

Usage:
    python evals/grade.py --iteration 1

For each eval directory under sdlc-prd-workspace/iteration-N/, this
inspects test-project/ to check assertion-style claims about the produced
PRD.yaml, .claude/skills-state/sdlc-prd.state.yaml, and CLAUDE.md.

Writes per-eval grading.json and a top-level benchmark.md summary.
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
WORKSPACE = REPO_ROOT / "sdlc-prd-workspace"
VALIDATOR = SKILL_ROOT / "validate_prd.py"


# -----------------------------------------------------------------------------
# Assertion plumbing
# -----------------------------------------------------------------------------


def _assert(text: str, ok: bool, evidence: str) -> dict:
    return {"text": text, "passed": bool(ok), "evidence": evidence}


def _load_yaml(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        return {"__parse_error__": str(e)}


def _validator_exit(prd_path: Path) -> tuple[int, str]:
    if not prd_path.exists():
        return 99, "PRD.yaml missing"
    r = subprocess.run(
        [sys.executable, str(VALIDATOR), "--path", str(prd_path)],
        capture_output=True,
        text=True,
    )
    return r.returncode, (r.stdout + r.stderr).strip()


def _has_pointer_block(text: str) -> int:
    """Return the count of Product Requirements pointer blocks in text."""
    if text is None:
        return 0
    # Match the heading and the literal `PRD.yaml` and `sdlc-prd` nearby.
    pattern = r"^##\s+Product Requirements\b[\s\S]{0,500}?`PRD\.yaml`[\s\S]{0,500}?sdlc-prd"
    return len(re.findall(pattern, text, re.MULTILINE))


def _get(obj, *path):
    cur = obj
    for p in path:
        if not isinstance(cur, dict) or p not in cur:
            return None
        cur = cur[p]
    return cur


# -----------------------------------------------------------------------------
# Per-eval graders. Each takes the test-project Path, returns list[dict].
# -----------------------------------------------------------------------------


def grade_eval_1(tp: Path) -> List[dict]:
    """empty-project-cold-interview"""
    prd = _load_yaml(tp / "docs" / "PRD.yaml")
    state = _load_yaml(tp / ".claude" / "skills-state" / "sdlc-prd.state.yaml")
    claude_md_path = tp / "CLAUDE.md"
    claude_md = claude_md_path.read_text(encoding="utf-8") if claude_md_path.exists() else None
    rc, vout = _validator_exit(tp / "docs" / "PRD.yaml")
    return [
        _assert("PRD.yaml exists", prd is not None, str(tp / "docs" / "PRD.yaml")),
        _assert("Validator exits 0", rc == 0, f"exit={rc}; {vout[:120]}"),
        _assert(
            "product_identity.name is non-null",
            _get(prd, "product_identity", "name"),
            str(_get(prd, "product_identity", "name")),
        ),
        _assert(
            "required: problem_statement non-null",
            _get(prd, "problem_opportunity", "problem_statement"),
            str(_get(prd, "problem_opportunity", "problem_statement")),
        ),
        _assert(
            "required: primary_language non-null",
            _get(prd, "technical_constraints", "primary_language"),
            str(_get(prd, "technical_constraints", "primary_language")),
        ),
        _assert("CLAUDE.md exists", claude_md is not None, str(claude_md_path)),
        _assert(
            "CLAUDE.md has exactly one pointer block",
            _has_pointer_block(claude_md or "") == 1,
            f"count={_has_pointer_block(claude_md or '')}",
        ),
        _assert(
            "State file exists with status=complete",
            _get(state, "status") == "complete",
            f"status={_get(state, 'status')}",
        ),
    ]


def grade_eval_2(tp: Path) -> List[dict]:
    """partial-context-prefill"""
    prd = _load_yaml(tp / "docs" / "PRD.yaml")
    rc, vout = _validator_exit(tp / "docs" / "PRD.yaml")
    name = _get(prd, "product_identity", "name")
    lang = _get(prd, "technical_constraints", "primary_language")
    # Confidence on a pre-fillable field — should be confirmed or inferred (not None)
    name_conf = _get(prd, "product_identity", "name_confidence")
    lang_conf = _get(prd, "technical_constraints", "primary_language_confidence")
    return [
        _assert("PRD.yaml exists", prd is not None, str(tp / "docs" / "PRD.yaml")),
        _assert("Validator exits 0", rc == 0, f"exit={rc}; {vout[:120]}"),
        _assert(
            "name pre-filled from package.json (acme-tasks)", name == "acme-tasks", f"name={name}"
        ),
        _assert(
            "primary_language is js or ts (from package.json scan)",
            lang in {"javascript", "typescript"},
            f"primary_language={lang}",
        ),
        _assert(
            "name_confidence is set (confirmed/inferred)",
            name_conf in {"confirmed", "inferred"},
            f"name_confidence={name_conf}",
        ),
        _assert(
            "primary_language_confidence is set",
            lang_conf in {"confirmed", "inferred"},
            f"primary_language_confidence={lang_conf}",
        ),
    ]


def grade_eval_3(tp: Path) -> List[dict]:
    """resume-from-state"""
    prd = _load_yaml(tp / "docs" / "PRD.yaml")
    state = _load_yaml(tp / ".claude" / "skills-state" / "sdlc-prd.state.yaml")
    rc, vout = _validator_exit(tp / "docs" / "PRD.yaml")
    return [
        _assert("PRD.yaml exists", prd is not None, str(tp / "docs" / "PRD.yaml")),
        _assert("Validator exits 0", rc == 0, f"exit={rc}; {vout[:120]}"),
        _assert(
            "Resumed name is preserved (Resumable)",
            _get(prd, "product_identity", "name") == "Resumable",
            f"name={_get(prd, 'product_identity', 'name')}",
        ),
        _assert(
            "Resumed problem_statement preserved",
            _get(prd, "problem_opportunity", "problem_statement")
            == "We need to verify state persistence across sessions.",
            f"problem_statement={_get(prd, 'problem_opportunity', 'problem_statement')}",
        ),
        _assert(
            "State file exists with status=complete",
            _get(state, "status") == "complete",
            f"status={_get(state, 'status')}",
        ),
        _assert(
            "State session_id preserved across resume",
            _get(state, "session_id") == "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
            f"session_id={_get(state, 'session_id')}",
        ),
    ]


def grade_eval_4(tp: Path) -> List[dict]:
    """existing-prd-merge"""
    prd = _load_yaml(tp / "docs" / "PRD.yaml")
    claude_md_path = tp / "CLAUDE.md"
    claude_md = claude_md_path.read_text(encoding="utf-8") if claude_md_path.exists() else None
    rc, vout = _validator_exit(tp / "docs" / "PRD.yaml")
    return [
        _assert("PRD.yaml exists", prd is not None, str(tp / "docs" / "PRD.yaml")),
        _assert("Validator exits 0", rc == 0, f"exit={rc}; {vout[:120]}"),
        _assert(
            "Existing key preserved: product_identity.name == 'Existing Product'",
            _get(prd, "product_identity", "name") == "Existing Product",
            f"name={_get(prd, 'product_identity', 'name')}",
        ),
        _assert(
            "Custom key preserved: custom_team_metadata.squad",
            _get(prd, "custom_team_metadata", "squad") == "platform",
            f"value={_get(prd, 'custom_team_metadata', 'squad')}",
        ),
        _assert(
            "Existing optional preserved: business_model.monetization == 'open_source'",
            _get(prd, "business_model", "monetization") == "open_source",
            f"value={_get(prd, 'business_model', 'monetization')}",
        ),
        _assert(
            "New theme written: milestones populated",
            isinstance(_get(prd, "milestones"), dict)
            and any(v is not None for v in _get(prd, "milestones").values()),
            f"milestones={_get(prd, 'milestones')}",
        ),
        _assert(
            "New theme written: success_metrics populated",
            isinstance(_get(prd, "success_metrics"), dict)
            and any(v is not None for v in _get(prd, "success_metrics").values()),
            f"success_metrics={_get(prd, 'success_metrics')}",
        ),
        _assert(
            "metadata.last_updated bumped past 2026-04-01",
            str(_get(prd, "metadata", "last_updated") or "") > "2026-04-01",
            f"last_updated={_get(prd, 'metadata', 'last_updated')}",
        ),
        _assert(
            "CLAUDE.md still has exactly one pointer block",
            _has_pointer_block(claude_md or "") == 1,
            f"count={_has_pointer_block(claude_md or '')}",
        ),
        _assert(
            "CLAUDE.md preserves unrelated 'Architecture' content",
            "## Architecture" in (claude_md or ""),
            "Architecture heading present",
        ),
    ]


def grade_eval_5(tp: Path) -> List[dict]:
    """validation-failure-recovery"""
    prd = _load_yaml(tp / "docs" / "PRD.yaml")
    rc, vout = _validator_exit(tp / "docs" / "PRD.yaml")
    lang = _get(prd, "technical_constraints", "primary_language")
    return [
        _assert("PRD.yaml exists", prd is not None, str(tp / "docs" / "PRD.yaml")),
        _assert(
            "primary_language fixed to 'python'", lang == "python", f"primary_language={lang}"
        ),
        _assert("Validator now exits 0", rc == 0, f"exit={rc}; {vout[:120]}"),
    ]


def grade_eval_6(tp: Path) -> List[dict]:
    """required-field-skipped"""
    prd = _load_yaml(tp / "docs" / "PRD.yaml")
    rc, vout = _validator_exit(tp / "docs" / "PRD.yaml")
    name = _get(prd, "product_identity", "name")
    warnings = _get(prd, "prd_warnings") or []
    name_warned = any("product_identity.name" in (w or "") for w in warnings)
    return [
        _assert("PRD.yaml exists", prd is not None, str(tp / "docs" / "PRD.yaml")),
        _assert("product_identity.name is null", name is None, f"name={name!r}"),
        _assert(
            "prd_warnings mentions product_identity.name", name_warned, f"warnings={warnings}"
        ),
        _assert("Validator exits 0 (warning, not error)", rc == 0, f"exit={rc}; {vout[:120]}"),
    ]


def grade_eval_7(tp: Path) -> List[dict]:
    """claude-md-injection-and-update"""
    claude_md_path = tp / "CLAUDE.md"
    claude_md = claude_md_path.read_text(encoding="utf-8") if claude_md_path.exists() else None
    return [
        _assert("CLAUDE.md exists after both runs", claude_md is not None, str(claude_md_path)),
        _assert(
            "CLAUDE.md has exactly ONE pointer block (no duplicate)",
            _has_pointer_block(claude_md or "") == 1,
            f"count={_has_pointer_block(claude_md or '')}",
        ),
        _assert(
            "Pointer block contains 'sdlc-prd' reference",
            "sdlc-prd" in (claude_md or ""),
            "literal present",
        ),
        _assert(
            "Pointer block references PRD.yaml",
            "`PRD.yaml`" in (claude_md or ""),
            "literal present",
        ),
    ]


GRADERS: dict[int, Callable[[Path], List[dict]]] = {
    1: grade_eval_1,
    2: grade_eval_2,
    3: grade_eval_3,
    4: grade_eval_4,
    5: grade_eval_5,
    6: grade_eval_6,
    7: grade_eval_7,
}


# -----------------------------------------------------------------------------
# Driver
# -----------------------------------------------------------------------------


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

    # Aggregate benchmark.md
    lines = ["# sdlc-prd eval results — iteration " + str(args.iteration), ""]
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
        lines.append(
            f"\n### Eval {r['eval_id']} — {r['eval_name']}  ({r['passed']}/{r['total']})\n"
        )
        for exp in r["expectations"]:
            mark = "[OK]  " if exp["passed"] else "[FAIL]"
            lines.append(f"- {mark} {exp['text']}  \n  *evidence:* `{exp['evidence']}`")
    out = iteration_dir / "benchmark.md"
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nWrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
