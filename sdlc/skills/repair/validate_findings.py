#!/usr/bin/env python3
"""Pydantic v2 validator for .claude/skills-state/sdlc-findings.yaml — the
cross-skill FND-NNN queue /sdlc:code appends to and /sdlc:repair resolves.

Canonical schema (with the rationale behind each field): FINDINGS.schema.yaml
in this directory. This module enforces it.

Beyond field types it checks the invariants that keep the queue trustworthy:

  * FND ids are unique, well-formed, and never above last_ids.FND (a counter
    that has fallen behind is how two skills reissue the same id).
  * A resolved / wontfix finding carries a resolution block; an open / triaged
    one does not (a "resolved" entry with no record of what changed is worse
    than no entry).
  * duplicate_of is present exactly when status == duplicate, and points at a
    different finding that exists in this file.
  * evidence is non-empty and bounded — a finding nobody can judge without
    re-running the failing command is not evidence, it is a rumour.

Run from the project root:

    python validate_findings.py
    python validate_findings.py --path .claude/skills-state/sdlc-findings.yaml

Exit codes:
    0 — schema valid; the queue is internally consistent.
    1 — schema invalid (pydantic error) or an invariant is violated.
    2 — could not read or parse the file (missing, bad YAML, etc.).
    3 — required dependency missing (pydantic v2 or pyyaml).
"""

from __future__ import annotations

import argparse
import re
import sys
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    import yaml
except ImportError:  # pragma: no cover
    print("ERROR: pyyaml is required.\nInstall with:  pip install pyyaml", file=sys.stderr)
    sys.exit(3)

try:
    from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
except ImportError:  # pragma: no cover
    print("ERROR: pydantic v2 is required.\nInstall with:  pip install 'pydantic>=2'", file=sys.stderr)
    sys.exit(3)

DEFAULT_PATH = Path(".claude/skills-state/sdlc-findings.yaml")
FND_RE = re.compile(r"^FND-\d{3,}$")
MAX_EVIDENCE = 5


class RaisedBy(str, Enum):
    code = "sdlc-code"
    repair = "sdlc-repair"


class Kind(str, Enum):
    # raised during a codegen run
    contract_underdetermined = "contract_underdetermined"
    contract_contradiction = "contract_contradiction"
    test_contradicts_contract = "test_contradicts_contract"
    missing_requirement = "missing_requirement"
    missing_operation = "missing_operation"
    missing_entity = "missing_entity"
    missing_dependency_edge = "missing_dependency_edge"
    wrong_path = "wrong_path"
    impossible_acceptance = "impossible_acceptance"
    drifted_embed = "drifted_embed"
    # raised by the doctor sweep
    validator_error = "validator_error"
    crosscheck_broken_ref = "crosscheck_broken_ref"
    dangling_reference = "dangling_reference"
    other = "other"


class Stage(str, Enum):
    prd = "prd"
    ux = "ux"
    design = "design"
    data = "data"
    api = "api"
    arch = "arch"
    test = "test"
    task = "task"
    code = "code"


class Status(str, Enum):
    open = "open"
    triaged = "triaged"
    resolved = "resolved"
    wontfix = "wontfix"
    duplicate = "duplicate"


class Mode(str, Enum):
    surgical = "surgical"
    re_invoke = "re-invoke"
    none = "none"


class SurfacedAt(BaseModel):
    model_config = ConfigDict(extra="allow")
    qualified_task: Optional[str] = None
    file: Optional[str] = None
    symbol: Optional[str] = None


class Resolution(BaseModel):
    model_config = ConfigDict(extra="allow")
    by: str
    at: str
    located_stage: Optional[Stage] = None
    mode: Optional[Mode] = None
    artifacts_touched: List[str] = Field(default_factory=list)
    downstream_rerun: List[str] = Field(default_factory=list)
    stale_tasks: List[str] = Field(default_factory=list)
    summary: Optional[str] = None


class Finding(BaseModel):
    model_config = ConfigDict(extra="allow")

    fnd_id: str
    raised_by: RaisedBy
    raised_at: str
    detected_by: Optional[str] = None
    surfaced_at: Optional[SurfacedAt] = None
    kind: Kind
    summary: str
    evidence: List[str]
    suspected_stage: Optional[Stage] = None
    suspected_source: Optional[str] = None
    status: Status
    duplicate_of: Optional[str] = None
    resolution: Optional[Resolution] = None

    @field_validator("fnd_id")
    @classmethod
    def _id_format(cls, v: str) -> str:
        if not FND_RE.match(v):
            raise ValueError(f"{v!r} must match FND-NNN (>=3 digits)")
        return v

    @field_validator("summary")
    @classmethod
    def _summary_nonempty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("summary must not be empty")
        return v

    @field_validator("evidence")
    @classmethod
    def _evidence_bounded(cls, v: List[str]) -> List[str]:
        if not v:
            raise ValueError(
                "evidence must have at least one line - a finding nobody can judge "
                "without re-running the failing command is not actionable"
            )
        if len(v) > MAX_EVIDENCE:
            raise ValueError(f"evidence has {len(v)} lines; keep it to at most {MAX_EVIDENCE}")
        return v


class FindingsFile(BaseModel):
    model_config = ConfigDict(extra="allow")

    findings_file_version: str
    last_updated: Optional[str] = None
    last_ids: Dict[str, int]
    findings: List[Finding]

    @field_validator("last_ids")
    @classmethod
    def _has_fnd_counter(cls, v: Dict[str, int]) -> Dict[str, int]:
        if "FND" not in v:
            raise ValueError("last_ids must carry an FND counter")
        return v


def cross_checks(doc: FindingsFile) -> List[str]:
    """Invariants pydantic cannot express field-by-field."""
    errors: List[str] = []
    ids = [f.fnd_id for f in doc.findings]

    dupes = sorted({i for i in ids if ids.count(i) > 1})
    if dupes:
        errors.append(f"duplicate fnd_id(s): {', '.join(dupes)}")

    counter = int(doc.last_ids.get("FND", 0))
    for f in doc.findings:
        n = int(f.fnd_id.split("-")[1])
        if n > counter:
            errors.append(
                f"{f.fnd_id} exceeds last_ids.FND={counter} - the counter has fallen "
                f"behind; reconcile to max(counter, highest id) before appending"
            )

    known = set(ids)
    for f in doc.findings:
        resolved_state = f.status in (Status.resolved, Status.wontfix)
        if resolved_state and f.resolution is None:
            errors.append(
                f"{f.fnd_id}: status={f.status.value} but resolution is null - "
                f"record what changed, or set status back to open/triaged"
            )
        if not resolved_state and f.status is not Status.duplicate and f.resolution is not None:
            errors.append(
                f"{f.fnd_id}: status={f.status.value} but a resolution block is present"
            )
        if f.status is Status.duplicate and not f.duplicate_of:
            errors.append(f"{f.fnd_id}: status=duplicate requires duplicate_of")
        if f.duplicate_of:
            if f.status is not Status.duplicate:
                errors.append(f"{f.fnd_id}: duplicate_of is set but status is {f.status.value}")
            if f.duplicate_of == f.fnd_id:
                errors.append(f"{f.fnd_id}: duplicate_of points at itself")
            elif f.duplicate_of not in known:
                errors.append(f"{f.fnd_id}: duplicate_of {f.duplicate_of} is not in this file")
    return errors


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
        except Exception:
            pass

    ap = argparse.ArgumentParser(description="Validate the sdlc findings queue.")
    ap.add_argument("--path", default=str(DEFAULT_PATH), help=f"Path to the queue (default: {DEFAULT_PATH}).")
    args = ap.parse_args()

    path = Path(args.path)
    if not path.is_file():
        print(f"[FAIL] cannot read {path}: file not found", file=sys.stderr)
        return 2
    try:
        raw: Any = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as e:
        print(f"[FAIL] cannot parse {path}: {e}", file=sys.stderr)
        return 2
    if not isinstance(raw, dict):
        print(f"[FAIL] {path}: top level must be a mapping", file=sys.stderr)
        return 2

    try:
        doc = FindingsFile.model_validate(raw)
    except ValidationError as e:
        print(f"[FAIL] {path} does not match FINDINGS.schema.yaml:\n")
        for err in e.errors():
            loc = " -> ".join(str(x) for x in err["loc"])
            print(f"  - {loc}: {err['msg']}")
        return 1

    errors = cross_checks(doc)
    if errors:
        print(f"[FAIL] {path}: {len(errors)} consistency error(s):\n")
        for msg in errors:
            print(f"  - {msg}")
        return 1

    by_status: Dict[str, int] = {}
    for f in doc.findings:
        by_status[f.status.value] = by_status.get(f.status.value, 0) + 1
    tally = ", ".join(f"{k}={v}" for k, v in sorted(by_status.items())) or "empty"
    print(f"[OK] {path} is valid - {len(doc.findings)} finding(s) ({tally})")
    open_now = [f.fnd_id for f in doc.findings if f.status in (Status.open, Status.triaged)]
    if open_now:
        print(f"     open/triaged: {', '.join(open_now)} - run /sdlc:repair to triage")
    return 0


if __name__ == "__main__":
    sys.exit(main())
