"""Validate docs/CODE-MANIFEST.json against the sdlc-code schema.

The manifest is the CodeBundle-analogue from the demo PRD's FR-014: a
machine-readable ledger of every source file the codegen stage emitted (path +
sha256 + producing tasks + heal telemetry). Like the task graph it mirrors, it
is JSON, not YAML (machine-generated, machine-consumed).

Run from the project root:

    python sdlc/skills/code/validate_schema.py
    python sdlc/skills/code/validate_schema.py --path docs/CODE-MANIFEST.json

Blocking checks (schema-invalid, or force status: draft):
    1. Required-field completeness (metadata block; files[] entry shape).
    2. Path safety — every files[].path repo-relative: no absolute paths, no
       drive letters, no "..".
    3. Qualified-id format on every producing_tasks entry:
       ^(TASKS|[a-z0-9][a-z0-9-]*)/TSK-\\d{3,}$.
    4. WRN-NNN format on every code_warnings entry.
    5. No duplicate path across files[].

Advisory checks (warn, never block — the disk moves independently):
    6. Each files[].path exists on disk and its current sha256 matches the
       recorded one (mismatch = hand-edit after generation; legitimate, but
       consumers should know).
    7. When task files are readable in the same docs/ directory: every
       producing_tasks id resolves to a real task, and every implementation
       task's single target_files entry appears as some files[].path.

Exit codes:
    0 — schema valid; either status='complete' with all required fields filled,
        or status='draft' (with or without missing required fields).
    1 — schema invalid (pydantic error), OR status='complete' but required
        fields are missing.
    2 — could not read or parse the file (missing, bad YAML, etc.)
    3 — required dependency missing (pydantic v2 or pyyaml).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    from pydantic import BaseModel, ValidationError
except ImportError:
    print(
        "ERROR: pydantic v2 is required.\nInstall with:  pip install 'pydantic>=2'",
        file=sys.stderr,
    )
    sys.exit(3)


QUALIFIED_TSK_RE = re.compile(r"^(TASKS|[a-z0-9][a-z0-9-]*)/TSK-\d{3,}$")
WRN_RE = re.compile(r"^WRN-\d{3,}:\s+.+")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


# =============================================================================
# Pydantic models — kept in lockstep with CODE-MANIFEST.schema.yaml.
# =============================================================================


class Metadata(BaseModel):
    code_manifest_version: str
    last_updated: str
    generated_by: str
    session_id: str
    status: str  # draft | complete — checked below so drafts stay loadable
    changelog: Optional[List[str]] = None
    upstream_provenance: Optional[List[Dict[str, Any]]] = None


VERIFIED_LEVELS = {"unit_ring", "static_only", "static_format", "none"}

# files[].verified became REQUIRED at this manifest version; older manifests
# get a warning instead of an error.
VERIFIED_MIN_VERSION = (1, 1)


class FileEntry(BaseModel):
    path: str
    sha256: str
    producing_tasks: List[str]
    heal_attempts: int
    generated_by_model: Optional[str] = None
    verified: Optional[str] = None  # unit_ring | static_only | static_format | none
    created: bool


class Manifest(BaseModel):
    metadata: Metadata
    files: List[FileEntry]
    code_warnings: Optional[List[str]] = None


# =============================================================================
# Checks
# =============================================================================


def _unsafe_path(p: str) -> Optional[str]:
    """Return the reason a path is unsafe, or None if it is fine."""
    if not p or p != p.strip():
        return "empty or padded"
    norm = p.replace("\\", "/")
    if norm.startswith("/") or re.match(r"^[A-Za-z]:", norm):
        return "absolute"
    if ".." in norm.split("/"):
        return "contains '..'"
    return None


def run_checks(m: Manifest, docs_dir: Path, project_root: Path) -> tuple[List[str], List[str]]:
    """Return (blocking_errors, warnings)."""
    errors: List[str] = []
    warnings: List[str] = []

    if m.metadata.status not in ("draft", "complete"):
        errors.append(f"metadata.status must be 'draft' or 'complete', got {m.metadata.status!r}")
    if m.metadata.generated_by != "sdlc-code":
        warnings.append(f"metadata.generated_by is {m.metadata.generated_by!r}, expected 'sdlc-code'")

    try:
        version = tuple(int(x) for x in (m.metadata.code_manifest_version or "0").split(".")[:2])
    except ValueError:
        version = (0, 0)
    verified_required = version >= VERIFIED_MIN_VERSION

    seen_paths: set[str] = set()
    for i, f in enumerate(m.files):
        where = f"files[{i}] ({f.path!r})"
        reason = _unsafe_path(f.path)
        if reason:
            errors.append(f"{where}: unsafe path — {reason}")
        if f.path in seen_paths:
            errors.append(f"{where}: duplicate path")
        seen_paths.add(f.path)
        if not SHA256_RE.match(f.sha256):
            errors.append(f"{where}: sha256 is not 64 lowercase hex chars")
        if not f.producing_tasks:
            errors.append(f"{where}: producing_tasks is empty")
        for t in f.producing_tasks:
            if not QUALIFIED_TSK_RE.match(t):
                errors.append(f"{where}: producing task {t!r} is not a qualified id (TASKS/TSK-NNN or <cid>/TSK-NNN)")
        if f.heal_attempts < 0:
            errors.append(f"{where}: heal_attempts must be >= 0")
        if f.verified is not None and f.verified not in VERIFIED_LEVELS:
            errors.append(f"{where}: verified {f.verified!r} is not one of {sorted(VERIFIED_LEVELS)}")
        elif f.verified is None:
            msg = f"{where}: missing verified level (unit_ring | static_only | static_format | none)"
            (errors if verified_required else warnings).append(
                msg if verified_required else msg + " (advisory: manifest predates v1.1)"
            )

    for i, w in enumerate(m.code_warnings or []):
        if not WRN_RE.match(w):
            errors.append(f"code_warnings[{i}]: does not match 'WRN-NNN: <message>' — {w!r}")

    if m.metadata.status == "complete" and not m.files:
        errors.append("status is 'complete' but files[] is empty")

    # --- advisory: disk cross-checks -------------------------------------
    for f in m.files:
        if _unsafe_path(f.path):
            continue
        disk = project_root / f.path
        if not disk.is_file():
            warnings.append(f"{f.path}: recorded in manifest but not found on disk")
        else:
            actual = hashlib.sha256(disk.read_bytes()).hexdigest()
            if actual != f.sha256:
                warnings.append(f"{f.path}: content hash differs from manifest (hand-edited after generation?)")

    # --- advisory: task-file cross-checks ---------------------------------
    task_files: Dict[str, Path] = {}
    system = docs_dir / "TASKS.json"
    if system.is_file():
        task_files["TASKS"] = system
    for p in sorted(docs_dir.glob("TASKS__*.json")):
        task_files[p.stem.replace("TASKS__", "", 1)] = p

    if task_files:
        known_ids: set[str] = set()
        impl_targets: Dict[str, str] = {}  # qualified id -> target_files[0]
        for key, path in task_files.items():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as e:
                warnings.append(f"{path.name}: unreadable for cross-checks ({e})")
                continue
            for t in data.get("tasks", []):
                tid = t.get("tsk_id")
                if not tid:
                    continue
                q = f"{key}/{tid}"
                known_ids.add(q)
                tf = t.get("target_files") or []
                if t.get("kind") == "implementation" and len(tf) == 1:
                    impl_targets[q] = tf[0]

        for f in m.files:
            for t in f.producing_tasks:
                if t not in known_ids:
                    warnings.append(f"{f.path}: producing task {t} not found in any task file")

        manifest_paths = {f.path.replace("\\", "/") for f in m.files}
        for q, target in sorted(impl_targets.items()):
            if target.replace("\\", "/") not in manifest_paths:
                warnings.append(f"implementation task {q}: target file {target!r} not in the manifest (not yet generated?)")

    return errors, warnings


# =============================================================================
# CLI
# =============================================================================


def main() -> int:
    ap = argparse.ArgumentParser(description="Validate docs/CODE-MANIFEST.json (sdlc-code).")
    ap.add_argument("--path", default="docs/CODE-MANIFEST.json", help="Path to the manifest (default: docs/CODE-MANIFEST.json).")
    ap.add_argument("--project-root", default=None, help="Repo root for disk checks (default: the manifest's docs/ parent).")
    args = ap.parse_args()

    manifest_path = Path(args.path)
    try:
        raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        print(f"[FAIL] cannot read or parse {manifest_path}: {e}", file=sys.stderr)
        return 2

    try:
        manifest = Manifest.model_validate(raw)
    except ValidationError as e:
        print(f"[FAIL] {manifest_path} — schema invalid:")
        for err in e.errors():
            loc = ".".join(str(x) for x in err["loc"])
            print(f"  - {loc}: {err['msg']}")
        return 1

    docs_dir = manifest_path.parent
    project_root = Path(args.project_root) if args.project_root else docs_dir.parent

    errors, warnings = run_checks(manifest, docs_dir, project_root)

    for w in warnings:
        print(f"  [WARN] {w}")
    for e in errors:
        print(f"  [ERR]  {e}")

    n_files = len(manifest.files)
    n_created = sum(1 for f in manifest.files if f.created)
    n_healed = sum(1 for f in manifest.files if f.heal_attempts > 0)
    summary = (
        f"{n_files} files ({n_created} created, {n_files - n_created} edited, "
        f"{n_healed} healed), {len(manifest.code_warnings or [])} warnings"
    )

    if errors:
        if manifest.metadata.status == "complete":
            print(f"[FAIL] {manifest_path} — status 'complete' with {len(errors)} blocking error(s). {summary}")
            return 1
        print(f"[OK-DRAFT] {manifest_path} — draft with {len(errors)} issue(s) to fix before 'complete'. {summary}")
        return 0

    print(f"[OK] {manifest_path} — status '{manifest.metadata.status}'. {summary}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
