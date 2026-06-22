"""Grade subagent outputs for the sdlc-design eval suite.

Usage:
    python sdlc/skills/design/evals/grade.py --iteration 1

For each eval directory under sdlc-design-workspace/iteration-N/, this inspects
test-project/ to check assertion-style claims about the produced DESIGN.yaml +
DESIGN__tokens.yaml + DESIGN__assets.yaml. Writes per-eval grading.json and a
top-level benchmark.md summary. Deterministic — mirrors the atomic assertions in
evals/evals.json.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable, List

import yaml

REPO_ROOT = Path(__file__).resolve().parents[4]
SKILL_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = REPO_ROOT / "sdlc-design-workspace"
VALIDATOR = SKILL_ROOT / "validate_schema.py"

AST_RE = re.compile(r"^AST-\d{3,}$")
WRN_RE = re.compile(r"^WRN-\d{3,}:\s+.+")


def _assert(text: str, ok: bool, evidence: str) -> dict:
    return {"text": text, "passed": bool(ok), "evidence": evidence}


def _load_yaml(path: Path) -> Any:
    if not path.exists():
        return None
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        return {"__parse_error__": str(e)}


def _validator_exit(design_path: Path) -> tuple[int, str]:
    if not design_path.exists():
        return 99, "DESIGN.yaml missing"
    r = subprocess.run(
        [sys.executable, str(VALIDATOR), "--path", str(design_path)],
        capture_output=True,
        text=True,
    )
    return r.returncode, (r.stdout + r.stderr).strip()


def _status(doc: Any) -> Any:
    return (doc.get("metadata") or {}).get("status") if isinstance(doc, dict) else None


def _str(x: Any) -> str:
    return x if isinstance(x, str) else ""


def _briefs_ok(assets_doc: Any, require_acceptance: bool) -> tuple[bool, str]:
    """Every to_be_generated asset has a non-empty generation_brief.prompt (and,
    if require_acceptance, a non-empty acceptance_criteria list)."""
    if not isinstance(assets_doc, dict):
        return False, "no DESIGN__assets.yaml"
    assets = assets_doc.get("assets") or []
    gen = [a for a in assets if isinstance(a, dict) and a.get("source") == "to_be_generated"]
    if not gen:
        return True, "no to_be_generated assets"
    bad = []
    for a in gen:
        gb = a.get("generation_brief")
        ok = isinstance(gb, dict) and bool(_str(gb.get("prompt")).strip())
        if require_acceptance:
            ok = ok and isinstance(gb.get("acceptance_criteria"), list) and len(gb["acceptance_criteria"]) > 0
        if not ok:
            bad.append(a.get("id"))
    return (not bad), f"{len(gen)} generated; missing/incomplete brief: {bad}"


# =============================================================================
# Eval 1 — game-dual-axis
# =============================================================================
def grade_eval_1(tp: Path) -> List[dict]:
    docs = tp / "docs"
    design = _load_yaml(docs / "DESIGN.yaml")
    tokens = _load_yaml(docs / "DESIGN__tokens.yaml")
    assets = _load_yaml(docs / "DESIGN__assets.yaml")
    rc, vout = _validator_exit(docs / "DESIGN.yaml")

    d = design if isinstance(design, dict) else {}
    fs = d.get("functional_structure") or []
    ad = d.get("aesthetic_direction") or {}
    sub = d.get("sub_artifacts") or {}
    asset_list = (assets.get("assets") if isinstance(assets, dict) else None) or []
    taxonomy = (assets.get("asset_taxonomy") if isinstance(assets, dict) else None) or []
    warnings = d.get("design_warnings") or []

    audio_kinds = {"audio_sfx", "audio_music"}
    audio_in_tax = bool(audio_kinds & set(taxonomy))
    audio_asset = any(isinstance(a, dict) and a.get("asset_type") in audio_kinds for a in asset_list)
    briefs_ok, briefs_ev = _briefs_ok(assets, require_acceptance=True)
    ast_ok = all(isinstance(a, dict) and AST_RE.match(_str(a.get("id"))) for a in asset_list) and bool(asset_list)
    wrn_ok = all(isinstance(w, str) and WRN_RE.match(w) for w in warnings)
    status_all = _status(design) == "complete" and _status(tokens) == "complete" and _status(assets) == "complete"

    return [
        _assert("functional_structure has both token_based_ui AND asset_pipeline",
                "token_based_ui" in fs and "asset_pipeline" in fs, f"functional_structure={fs}"),
        _assert("DESIGN__tokens.yaml exists AND sub_artifacts.tokens set",
                (docs / "DESIGN__tokens.yaml").exists() and bool(sub.get("tokens")),
                f"exists={(docs/'DESIGN__tokens.yaml').exists()} sub.tokens={sub.get('tokens')!r}"),
        _assert("DESIGN__assets.yaml exists AND sub_artifacts.assets set",
                (docs / "DESIGN__assets.yaml").exists() and bool(sub.get("assets")),
                f"exists={(docs/'DESIGN__assets.yaml').exists()} sub.assets={sub.get('assets')!r}"),
        _assert("aesthetic_direction.style_family contains 'pixel'",
                "pixel" in _str(ad.get("style_family")).lower(), f"style_family={ad.get('style_family')!r}"),
        _assert("scope sweep caught audio (taxonomy + an asset of that type)",
                audio_in_tax and audio_asset, f"audio_in_taxonomy={audio_in_tax} audio_asset={audio_asset}"),
        _assert("every to_be_generated asset has prompt + acceptance_criteria",
                briefs_ok, briefs_ev),
        _assert("every assets[].id matches AST-NNN", ast_ok,
                f"ids={[a.get('id') for a in asset_list if isinstance(a, dict)]}"),
        _assert("every design_warnings entry matches WRN-NNN", wrn_ok, f"warnings={warnings[:3]}"),
        _assert("validator exits 0 AND status complete in all 3 files",
                rc == 0 and status_all, f"exit={rc} status_all={status_all}; {vout[:160]}"),
    ]


# =============================================================================
# Eval 2 — web-artistic-bridge (THE bridge: token UI + artistic -> assets)
# =============================================================================
def grade_eval_2(tp: Path) -> List[dict]:
    docs = tp / "docs"
    design = _load_yaml(docs / "DESIGN.yaml")
    tokens = _load_yaml(docs / "DESIGN__tokens.yaml")
    assets = _load_yaml(docs / "DESIGN__assets.yaml")
    rc, vout = _validator_exit(docs / "DESIGN.yaml")

    d = design if isinstance(design, dict) else {}
    fs = d.get("functional_structure") or []
    ad = d.get("aesthetic_direction") or {}
    sub = d.get("sub_artifacts") or {}
    asset_list = (assets.get("assets") if isinstance(assets, dict) else None) or []
    contrast = _str(tokens.get("contrast_notes")) if isinstance(tokens, dict) else ""

    style = _str(ad.get("style_family")).lower()
    style_ok = any(s in style for s in ("hand", "drawn", "illustrat", "storybook"))
    illus_or_icon = any(isinstance(a, dict) and a.get("asset_type") in ("illustration", "icon") for a in asset_list)
    briefs_ok, briefs_ev = _briefs_ok(assets, require_acceptance=False)
    wcag_ok = any(s in contrast.lower() for s in ("wcag", "aa"))
    status_all = _status(design) == "complete" and _status(tokens) == "complete" and _status(assets) == "complete"

    return [
        _assert("functional_structure has token_based_ui and NOT asset_pipeline",
                "token_based_ui" in fs and "asset_pipeline" not in fs, f"functional_structure={fs}"),
        _assert("BRIDGE: aesthetic_direction.requires_custom_assets == true",
                ad.get("requires_custom_assets") is True, f"requires_custom_assets={ad.get('requires_custom_assets')!r}"),
        _assert("BRIDGE: DESIGN__assets.yaml emitted despite no asset_pipeline",
                (docs / "DESIGN__assets.yaml").exists() and bool(sub.get("assets")),
                f"exists={(docs/'DESIGN__assets.yaml').exists()} sub.assets={sub.get('assets')!r}"),
        _assert("style_family is hand-drawn/illustrated", style_ok, f"style_family={ad.get('style_family')!r}"),
        _assert("DESIGN__tokens.yaml exists AND contrast_notes mentions WCAG/AA",
                (docs / "DESIGN__tokens.yaml").exists() and wcag_ok, f"contrast_notes={contrast[:80]!r}"),
        _assert("at least one illustration/icon asset", illus_or_icon,
                f"asset_types={[a.get('asset_type') for a in asset_list if isinstance(a, dict)]}"),
        _assert("every to_be_generated asset has a prompt", briefs_ok, briefs_ev),
        _assert("validator exits 0 AND status complete in all 3 files",
                rc == 0 and status_all, f"exit={rc} status_all={status_all}; {vout[:160]}"),
    ]


# =============================================================================
# Eval 3 — cli-headless (no-op headless path)
# =============================================================================
def grade_eval_3(tp: Path) -> List[dict]:
    docs = tp / "docs"
    design = _load_yaml(docs / "DESIGN.yaml")
    rc, vout = _validator_exit(docs / "DESIGN.yaml")

    d = design if isinstance(design, dict) else {}
    fs = d.get("functional_structure") or []
    ad = d.get("aesthetic_direction", "MISSING")
    sub = d.get("sub_artifacts") or {}
    warnings = d.get("design_warnings") or []

    headless_only = fs == ["headless"]
    aesthetic_null = (ad is None) or (ad == "MISSING")
    subs_null = sub.get("tokens") in (None,) and sub.get("assets") in (None,)
    no_tokens = not (docs / "DESIGN__tokens.yaml").exists()
    no_assets = not (docs / "DESIGN__assets.yaml").exists()
    headless_note = any(
        isinstance(w, str) and WRN_RE.match(w)
        and any(k in w.lower() for k in ("not applicable", "headless", "cli", "visual design", "no visual"))
        for w in warnings
    )
    status_complete = _status(design) == "complete"

    return [
        _assert("functional_structure == ['headless'] exactly", headless_only, f"functional_structure={fs}"),
        _assert("aesthetic_direction is null/absent", aesthetic_null, f"aesthetic_direction={ad!r}"),
        _assert("sub_artifacts.tokens and .assets both null", subs_null,
                f"tokens={sub.get('tokens')!r} assets={sub.get('assets')!r}"),
        _assert("DESIGN__tokens.yaml NOT created", no_tokens, f"exists={(docs/'DESIGN__tokens.yaml').exists()}"),
        _assert("DESIGN__assets.yaml NOT created", no_assets, f"exists={(docs/'DESIGN__assets.yaml').exists()}"),
        _assert("a WRN-NNN note explains the headless no-op", headless_note, f"warnings={warnings[:3]}"),
        _assert("validator exits 0 AND status complete", rc == 0 and status_complete,
                f"exit={rc} status={_status(design)!r}; {vout[:160]}"),
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
        print(f"ERROR: {iteration_dir} does not exist — run stage_iteration.py first.")
        return 2

    rows: list[dict] = []
    for eval_dir in sorted(iteration_dir.iterdir()):
        if not eval_dir.is_dir() or not eval_dir.name.startswith("eval-"):
            continue
        meta = json.loads((eval_dir / "eval_metadata.json").read_text(encoding="utf-8"))
        eid = meta["eval_id"]
        grader = GRADERS.get(eid)
        if grader is None:
            print(f"WARN: no grader for eval {eid}, skipping")
            continue
        results = grader(eval_dir / "test-project")
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
        print(f"  eval {eid:>2}: {meta['eval_name']:<24} [{bar}] {passed}/{total}")

    lines = [f"# sdlc-design eval results — iteration {args.iteration}", ""]
    total_p = sum(r["passed"] for r in rows)
    total_t = sum(r["total"] for r in rows)
    lines.append(f"**Overall pass rate:** {total_p}/{total_t} "
                 f"({(total_p/total_t*100 if total_t else 0):.0f}%)")
    lines += ["", "| Eval | Name | Passed | Total |", "|---:|---|---:|---:|"]
    for r in rows:
        lines.append(f"| {r['eval_id']} | {r['eval_name']} | {r['passed']} | {r['total']} |")
    lines.append("\n## Per-eval detail")
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
