#!/usr/bin/env python3
"""Pipeline health sweep for the SDLC docs/ chain — the `doctor` behind
/sdlc:repair --check and behind /sdlc:code's component-boundary check.

Every sdlc-* skill validates its OWN artifact at write time, and
crosscheck_artifacts.py validates references ACROSS artifacts. Neither runs
unless someone invokes the owning skill, so a chain can rot quietly between
stages — a hand-edited ARCH, a PRD requirement renamed after TEST-STRATEGY
copied it, a task graph whose embeds no longer match their source. This script
runs the whole set in one pass, reports each check's CAPTURED NUMERIC EXIT CODE,
and can turn every failure into an FND-NNN finding for /sdlc:repair to triage.

Two depths:

  --quick   only the cross-artifact linter (crosscheck_artifacts.py). Cheap
            enough to run at every component boundary during codegen, which is
            exactly what /sdlc:code does with it. Catches the desyncs that
            appear WHILE a long run is in flight (a mid-run hand-edit, a repair
            pass that landed between components).
  (default) the full sweep: every skill validator against its canonical
            artifact, every TASKS__*.json shard, the cross-artifact linter, and
            the docs-index dangling-reference gate.

Every check runs BARE and its exit code is captured directly — never read an
exit status after a pipe (CLAUDE.md §11: an upstream validator once ran
false-green for a full fix-plan cycle behind `cmd | tail -5`, masking 294 real
errors). A pass/fail paraphrase is never recorded in place of the number.

Usage:
    python doctor.py [--docs-dir docs] [--quick] [--json]
    python doctor.py --emit-findings                      # append FND-NNN entries
    python doctor.py --emit-findings .claude/skills-state/sdlc-findings.yaml

Exit codes:
    0 — every check that ran passed (checks skipped for a missing artifact
        count as passed; this script must be runnable at any pipeline stage).
    1 — at least one check failed.
    2 — could not read the docs dir or a required tool is missing from the
        skill tree.
    3 — required dependency missing (pyyaml).
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    import yaml
except ImportError:  # pragma: no cover
    print("[doctor] missing dependency: pyyaml (pip install pyyaml)", file=sys.stderr)
    sys.exit(3)

SKILLS_DIR = Path(__file__).resolve().parent.parent  # sdlc/skills/
DEFAULT_FINDINGS = Path(".claude/skills-state/sdlc-findings.yaml")
FND_RE = re.compile(r"^FND-(\d{3,})$")
MAX_EVIDENCE = 5   # must match validate_findings.py's cap

# skill folder -> its canonical artifact under docs/. A skill whose artifact is
# absent is SKIPPED, not failed: the sweep must be usable halfway through the
# pipeline, when the later artifacts legitimately do not exist yet.
CANONICAL: List[Tuple[str, str]] = [
    ("prd", "PRD.yaml"),
    ("ux", "UX.yaml"),
    ("design", "DESIGN.yaml"),
    ("data", "DATA-MODEL.yaml"),
    ("api", "API.yaml"),
    ("arch", "ARCH.yaml"),
    ("test", "TEST-STRATEGY.yaml"),
    ("task", "TASKS.json"),
    ("code", "CODE-MANIFEST.json"),
]


class Check:
    """One executed check and the number it returned."""

    def __init__(self, name: str, target: str) -> None:
        self.name = name
        self.target = target
        self.exit: Optional[int] = None   # None => skipped
        self.summary: str = ""
        self.output: str = ""

    @property
    def skipped(self) -> bool:
        return self.exit is None

    @property
    def failed(self) -> bool:
        return self.exit is not None and self.exit != 0

    def line(self) -> str:
        if self.skipped:
            return f"  [skip] {self.name:<28} {self.target}  ({self.summary})"
        tag = "[OK]  " if self.exit == 0 else "[FAIL]"
        return f"  {tag} {self.name:<28} {self.target}  exit {self.exit}"


def run_bare(cmd: List[str]) -> Tuple[int, str]:
    """Run a command with NO pipe and return (captured exit code, output).

    subprocess gives us the child's real returncode, which is the whole point:
    the shell idiom this replaces (`cmd | tail`) reports the LAST pipeline
    stage's status and silently hides a red validator.
    """
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    except OSError as e:
        return 2, f"could not execute: {e}"
    return r.returncode, ((r.stdout or "") + (r.stderr or "")).strip()


def tail(text: str, n: int = 12) -> str:
    lines = [ln for ln in text.splitlines() if ln.strip()]
    return "\n".join(lines[-n:])


def first_error(text: str) -> str:
    """The most useful single line of a validator's output."""
    for ln in text.splitlines():
        low = ln.strip().lower()
        if low.startswith(("[fail]", "[err]", "error", "  [err]")) or "error" in low:
            return ln.strip()[:200]
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    return lines[-1][:200] if lines else "(no output)"


def sweep(docs: Path, quick: bool) -> List[Check]:
    checks: List[Check] = []

    if not quick:
        for skill, artifact in CANONICAL:
            validator = SKILLS_DIR / skill / "validate_schema.py"
            target = docs / artifact
            c = Check(f"{skill}/validate_schema", target.as_posix())
            if not validator.is_file():
                c.summary = "validator not present in this skill tree"
                checks.append(c)
                continue
            if not target.is_file():
                c.summary = "artifact absent — stage not reached"
                checks.append(c)
                continue
            c.exit, c.output = run_bare([sys.executable, str(validator), "--path", str(target)])
            c.summary = first_error(c.output) if c.exit else "valid"
            checks.append(c)

        # Container task shards: the bulk of a real graph lives here, not in
        # TASKS.json, so a sweep that only validated the system file would miss
        # almost everything.
        task_validator = SKILLS_DIR / "task" / "validate_schema.py"
        if task_validator.is_file():
            for shard in sorted(docs.glob("TASKS__*.json")):
                c = Check("task/validate_schema", shard.as_posix())
                c.exit, c.output = run_bare([sys.executable, str(task_validator), "--path", str(shard)])
                c.summary = first_error(c.output) if c.exit else "valid"
                checks.append(c)

    # Cross-artifact linter — the only check --quick runs, because it is the one
    # that catches drift BETWEEN artifacts, which is what moves during a run.
    crosscheck = SKILLS_DIR / "task" / "crosscheck_artifacts.py"
    c = Check("crosscheck_artifacts", docs.as_posix())
    if not crosscheck.is_file():
        c.summary = "linter not present in this skill tree"
    else:
        c.exit, c.output = run_bare([sys.executable, str(crosscheck), "--docs-dir", str(docs)])
        c.summary = first_error(c.output) if c.exit else "all cross-artifact refs resolve"
    checks.append(c)

    if not quick:
        index_gen = Path(".claude/sdlc/docs_index.py")
        c = Check("docs_index --check", index_gen.as_posix())
        if not index_gen.is_file():
            c.summary = "project never ran /sdlc:setup — no index to check"
        else:
            c.exit, c.output = run_bare([sys.executable, str(index_gen), "--check"])
            c.summary = first_error(c.output) if c.exit else "no dangling id references"
        checks.append(c)

    return checks


# --------------------------------------------------------------------------
# Findings emission
# --------------------------------------------------------------------------

def kind_for(check: Check) -> str:
    if check.name.startswith("crosscheck"):
        return "crosscheck_broken_ref"
    if check.name.startswith("docs_index"):
        return "dangling_reference"
    return "validator_error"


def stage_for(check: Check) -> Optional[str]:
    """The pipeline stage a check belongs to, or None when it spans several.

    A skill validator localizes to its own stage. The cross-artifact linter and
    the index gate do NOT — they compare two artifacts, and guessing a stage
    here would seed the finding with a suspicion the raiser has no basis for.
    None is the honest answer; /sdlc:repair localizes properly.
    """
    if "/" in check.name:
        return check.name.split("/", 1)[0]
    return None


ARTIFACT_RE = re.compile(r"\b([A-Z][A-Z0-9-]*(?:__[a-z0-9-]+)?\.(?:yaml|json))\b")
ERROR_LINE_RE = re.compile(r"^\s*(?:\[FAIL\]|\[ERR\]|-\s)")


def error_lines(text: str) -> List[str]:
    """The lines that actually report a defect.

    Validators and the linter both interleave their errors with progress and
    `[note] … skipped` lines. Taking a blind tail as evidence buries the one
    line a reader needs, so pick the error lines and only fall back to the tail
    when nothing matches.
    """
    hits = [ln.strip() for ln in text.splitlines() if ERROR_LINE_RE.match(ln) and "[note]" not in ln]
    return hits or [ln for ln in tail(text, 3).splitlines() if ln.strip()]


def artifact_in(line: str, default: str) -> str:
    """Pull the artifact filename a defect line names, if any."""
    m = ARTIFACT_RE.search(line)
    return m.group(1) if m else default


# Checks whose output lists INDEPENDENT defects, one per line: each may localize
# to a different stage, so each earns its own finding. A skill validator's
# errors, by contrast, are all about one artifact and travel together.
PER_LINE_CHECKS = ("crosscheck_artifacts", "docs_index --check")
MAX_PER_CHECK = 20


def load_findings(path: Path) -> Dict[str, Any]:
    if not path.is_file():
        return {"findings_file_version": "1", "last_ids": {"FND": 0}, "findings": []}
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as e:
        raise SystemExit(f"[doctor] cannot read findings file {path}: {e}")
    data.setdefault("findings_file_version", "1")
    data.setdefault("last_ids", {})
    data["last_ids"].setdefault("FND", 0)
    data.setdefault("findings", [])
    return data


def next_fnd(data: Dict[str, Any]) -> int:
    """Counter reconciliation (CLAUDE.md §2): the on-disk maximum wins over a
    stale counter, so an EXIT/resume can never reissue an id."""
    highest = 0
    for f in data.get("findings") or []:
        m = FND_RE.match(str(f.get("fnd_id", "")))
        if m:
            highest = max(highest, int(m.group(1)))
    return max(int(data["last_ids"].get("FND") or 0), highest) + 1


def emit_findings(path: Path, checks: List[Check]) -> int:
    """Append one open finding per failed check. Returns how many were added.

    Deduplicates against still-open findings with the same check+target, so
    running the sweep repeatedly does not pile up copies of one defect.
    """
    data = load_findings(path)
    # Dedupe on (check, defect text) so repeated sweeps do not pile up copies of
    # one defect while still admitting a SECOND, different defect from the same
    # check.
    open_keys = {
        (f.get("detected_by"), (f.get("summary") or "")[:200])
        for f in data["findings"]
        if f.get("status") in ("open", "triaged")
    }
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    added = 0
    counter = next_fnd(data)

    for c in checks:
        if not c.failed:
            continue
        lines = error_lines(c.output)
        if c.name in PER_LINE_CHECKS:
            defects = [(ln, artifact_in(ln, c.target), [ln]) for ln in lines[:MAX_PER_CHECK]]
            if len(lines) > MAX_PER_CHECK:
                defects.append((
                    f"{len(lines) - MAX_PER_CHECK} further {c.name} defect(s) not itemized",
                    c.target,
                    [f"exit {c.exit}", f"{len(lines)} total defect lines"],
                ))
        else:
            defects = [(c.summary, c.target, lines[:MAX_EVIDENCE])]

        for defect, where, evidence in defects:
            summary = f"{c.name} exit {c.exit}: {defect}"[:400]
            if (c.name, summary[:200]) in open_keys:
                continue
            open_keys.add((c.name, summary[:200]))
            entry: Dict[str, Any] = {
                "fnd_id": f"FND-{counter:03d}",
                "raised_by": "sdlc-repair",
                "raised_at": now,
                "detected_by": c.name,
                "surfaced_at": {"file": where},
                "kind": kind_for(c),
                "summary": summary,
                "evidence": [e[:300] for e in (evidence or [f"exit {c.exit}"])][:MAX_EVIDENCE],
                "suspected_stage": stage_for(c),
                "suspected_source": where,
                "status": "open",
                "resolution": None,
            }
            data["findings"].append(entry)
            counter += 1
            added += 1
    if added:
        data["last_ids"]["FND"] = counter - 1
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            yaml.safe_dump(data, sort_keys=False, allow_unicode=True, width=100),
            encoding="utf-8",
        )
    return added


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
        except Exception:
            pass

    ap = argparse.ArgumentParser(description="SDLC pipeline health sweep.")
    ap.add_argument("--docs-dir", default="docs", help="Directory holding the artifacts (default: docs).")
    ap.add_argument(
        "--quick",
        action="store_true",
        help="Cross-artifact linter only — the depth /sdlc:code runs at component boundaries.",
    )
    ap.add_argument(
        "--emit-findings",
        nargs="?",
        const=str(DEFAULT_FINDINGS),
        default=None,
        metavar="PATH",
        help=f"Append an FND-NNN entry per failed check (default path: {DEFAULT_FINDINGS}).",
    )
    ap.add_argument("--json", action="store_true", dest="as_json", help="Machine-readable report on stdout.")
    args = ap.parse_args()

    docs = Path(args.docs_dir)
    if not docs.is_dir():
        print(f"[doctor] docs dir not found: {docs}", file=sys.stderr)
        return 2

    checks = sweep(docs, args.quick)
    failed = [c for c in checks if c.failed]

    added = 0
    if args.emit_findings:
        added = emit_findings(Path(args.emit_findings), checks)

    if args.as_json:
        print(json.dumps(
            {
                "docs_dir": docs.as_posix(),
                "depth": "quick" if args.quick else "full",
                "checks": [
                    {"name": c.name, "target": c.target, "exit": c.exit, "summary": c.summary}
                    for c in checks
                ],
                "failed": len(failed),
                "findings_added": added,
            },
            indent=2,
        ))
        return 1 if failed else 0

    print(f"doctor — {'quick' if args.quick else 'full'} sweep over {docs.as_posix()}")
    for c in checks:
        print(c.line())
    ran = [c for c in checks if not c.skipped]
    print(f"\n{len(ran)} check(s) run, {len(failed)} failed, {len(checks) - len(ran)} skipped")
    if failed:
        print("\nfailures (each line is a captured exit code, not a paraphrase):")
        for c in failed:
            print(f"  {c.name} [{c.target}] exit {c.exit}")
            for ln in tail(c.output, 4).splitlines():
                print(f"      {ln}")
    if args.emit_findings:
        print(f"\n{added} finding(s) appended to {args.emit_findings}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
