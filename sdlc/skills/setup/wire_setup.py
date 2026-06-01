"""Wire the docs/INDEX.yaml toolchain into a consumer project.

`sdlc:setup` runs this once, before `sdlc:prd`, to make a project's large SDLC
specs cheap to navigate. It is fully deterministic and idempotent — re-running it
never duplicates anything; it only fills gaps and refreshes the index.

What it installs into the target project root (default: cwd):

  1. .claude/sdlc/docs_index.py        — the stdlib-only navigation-index generator
                                          (copied from this skill folder).
  2. .claude/rules/sdlc-docs-access.md — the slice-don't-slurp retrieval protocol
                                          (copied from this skill's assets/).
  3. .claude/settings.json             — a `Write|Edit` PostToolUse hook that runs
                                          the generator on every docs/*.yaml edit.
                                          Merged in; existing settings preserved.
  4. CLAUDE.md                         — a `## SDLC Documents` section with the
                                          slice-first access note + the INDEX.yaml
                                          pointer. Coexists with the per-artifact
                                          bullets the prd/ux/data/arch skills add.
  5. docs/INDEX.yaml                    — generated once now (no-op if docs/ empty).

Run from the project root:

    python <skill>/wire_setup.py
    python <skill>/wire_setup.py --dry-run
    python <skill>/wire_setup.py --project-root /path/to/project --python "uv run python"

Exit codes:
    0 — success (installed | already-wired | dry-run).
    2 — could not read/write a target file (permission error, bad JSON, etc.).
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import shutil
import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent
GENERATOR_SRC = SKILL_DIR / "docs_index.py"
RULE_SRC = SKILL_DIR / "assets" / "sdlc-docs-access.md"

GENERATOR_DEST_REL = ".claude/sdlc/docs_index.py"
RULE_DEST_REL = ".claude/rules/sdlc-docs-access.md"
HOOK_MATCHER = "Write|Edit|MultiEdit"
HOOK_TOKEN = "docs_index.py"  # idempotency marker inside the hook command
SECTION_HEADING = "## SDLC Documents"
INDEX_MARKER = "`docs/INDEX.yaml`"

# The intro paragraph that opens the section. Its first line is the idempotency
# sentinel — we detect it by the `Access them via` substring.
ACCESS_NOTE = (
    "**Access the docs below via `docs/INDEX.yaml`, sliced — never load "
    "`PRD.yaml` or `DATA-MODEL.yaml` whole.** `INDEX.yaml` is a generated "
    "location map (file + line range + summary per symbol); look a symbol up "
    "there and `Read` only its range. Full protocol: "
    "`.claude/rules/sdlc-docs-access.md`."
)


def _iso_utc_now() -> str:
    return _dt.datetime.now(tz=_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _index_bullet(timestamp: str) -> str:
    return (
        f"- {INDEX_MARKER}: GENERATED navigation map — entrypoint for the SDLC "
        f"docs. Refreshed by the `docs-index` PostToolUse hook; never hand-edit. "
        f"`python .claude/sdlc/docs_index.py --show <symbol>` prints one symbol's "
        f"slice. Wired by `sdlc-setup` on {timestamp}."
    )


# ---------------------------------------------------------------------------
# settings.json hook merge (pure function + I/O wrapper)
# ---------------------------------------------------------------------------


def _hook_command(python_cmd: str) -> str:
    return f'{python_cmd} {GENERATOR_DEST_REL} --hook'


def merge_hook(settings: dict, python_cmd: str) -> "tuple[dict, str]":
    """Return (new_settings, action). Pure — no I/O.

    Ensures a single PostToolUse entry whose command runs the generator. If one
    already references the generator, the command is refreshed (in case the
    python invocation changed) but no duplicate is added.
    """
    settings = json.loads(json.dumps(settings))  # deep copy
    hooks = settings.setdefault("hooks", {})
    post = hooks.setdefault("PostToolUse", [])
    if not isinstance(post, list):
        raise ValueError("hooks.PostToolUse is not a list")

    command = _hook_command(python_cmd)
    for entry in post:
        for h in entry.get("hooks", []) if isinstance(entry, dict) else []:
            if isinstance(h, dict) and HOOK_TOKEN in str(h.get("command", "")):
                if h["command"] == command:
                    return settings, "no-op"
                h["command"] = command
                entry["matcher"] = HOOK_MATCHER
                return settings, "updated_command"

    post.append(
        {
            "matcher": HOOK_MATCHER,
            "hooks": [{"type": "command", "command": command}],
        }
    )
    return settings, "added_hook"


# ---------------------------------------------------------------------------
# CLAUDE.md section upsert (pure function)
# ---------------------------------------------------------------------------


def _find_section(lines: "list[str]", heading: str) -> "tuple[int, int] | None":
    for i, line in enumerate(lines):
        if line.strip() == heading:
            j = i + 1
            while j < len(lines) and not lines[j].startswith("## "):
                j += 1
            return i, j
    return None


def upsert_claude_md(content: str, timestamp: str) -> "tuple[str, str]":
    """Insert/refresh the SDLC Documents section's access note + INDEX bullet.

    Coexists with the per-artifact bullets that prd/ux/data/arch add to the same
    section — only touches the access note and the `docs/INDEX.yaml` bullet.
    """
    bullet = _index_bullet(timestamp)
    if not content:
        body = f"{SECTION_HEADING}\n\n{ACCESS_NOTE}\n\n{bullet}\n"
        return body, "created"

    had_trailing_newline = content.endswith("\n")
    lines = content.split("\n")
    if had_trailing_newline:
        lines.pop()

    section = _find_section(lines, SECTION_HEADING)
    if section is None:
        if lines and lines[-1].strip() != "":
            lines.append("")
        lines += [SECTION_HEADING, "", ACCESS_NOTE, "", bullet]
        action = "appended_section"
    else:
        start, end = section
        body = lines[start + 1 : end]
        has_note = any("Access the docs below via" in ln for ln in body)
        idx_pos = next(
            (k for k in range(start + 1, end) if INDEX_MARKER in lines[k]), None
        )
        action = "no-op"
        if idx_pos is not None:
            if lines[idx_pos] != bullet:
                lines[idx_pos] = bullet
                action = "updated_bullet"
        else:
            insert_at = start + 1
            prefix = []
            if not has_note:
                prefix = [ACCESS_NOTE, ""]
            lines[insert_at:insert_at] = prefix + [bullet]
            action = "inserted_bullet"

    out = "\n".join(lines)
    if had_trailing_newline or action == "appended_section":
        out += "\n"
    return out, action


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def _copy(src: Path, dest: Path, dry: bool, log: "list[str]") -> None:
    same = dest.exists() and dest.read_bytes() == src.read_bytes()
    verb = "no-op (identical)" if same else ("would copy" if dry else "copied")
    log.append(f"  [{verb}] {dest}")
    if dry or same:
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, dest)


def run(project_root: Path, python_cmd: str, dry: bool) -> "tuple[int, list[str]]":
    log: list[str] = []
    if not GENERATOR_SRC.is_file() or not RULE_SRC.is_file():
        return 2, [f"[ERR] skill assets missing under {SKILL_DIR}"]

    # 1 + 2: copy generator + rule file.
    _copy(GENERATOR_SRC, project_root / GENERATOR_DEST_REL, dry, log)
    _copy(RULE_SRC, project_root / RULE_DEST_REL, dry, log)

    # 3: merge settings.json hook.
    settings_path = project_root / ".claude" / "settings.json"
    try:
        settings = (
            json.loads(settings_path.read_text(encoding="utf-8"))
            if settings_path.exists()
            else {}
        )
    except (OSError, ValueError) as e:
        return 2, log + [f"[ERR] cannot read {settings_path}: {e}"]
    try:
        new_settings, hook_action = merge_hook(settings, python_cmd)
    except ValueError as e:
        return 2, log + [f"[ERR] {settings_path}: {e}"]
    log.append(f"  [{'would ' + hook_action if dry else hook_action}] {settings_path} (PostToolUse hook)")
    if not dry and hook_action != "no-op":
        settings_path.parent.mkdir(parents=True, exist_ok=True)
        settings_path.write_text(
            json.dumps(new_settings, indent=2) + "\n", encoding="utf-8"
        )

    # 4: CLAUDE.md pointer.
    claude_md = project_root / "CLAUDE.md"
    try:
        original = claude_md.read_text(encoding="utf-8") if claude_md.exists() else ""
    except OSError as e:
        return 2, log + [f"[ERR] cannot read {claude_md}: {e}"]
    new_md, md_action = upsert_claude_md(original, _iso_utc_now())
    log.append(f"  [{'would ' + md_action if dry else md_action}] {claude_md} (## SDLC Documents)")
    if not dry and md_action != "no-op":
        claude_md.write_text(new_md, encoding="utf-8")

    # 5: initial index generation.
    docs_dir = project_root / "docs"
    if dry:
        log.append(f"  [would generate] {docs_dir / 'INDEX.yaml'}")
    else:
        sys.path.insert(0, str(SKILL_DIR))
        import docs_index  # local import; SKILL_DIR is on sys.path

        if docs_dir.is_dir():
            target = docs_index.write_index(docs_dir)
            log.append(f"  [generated] {target}")
        else:
            log.append(f"  [skipped] {docs_dir} does not exist yet — index will be built on first doc write")
    return 0, log


def _force_utf8_stdio() -> None:
    """Best-effort: keep prints working on a non-UTF-8 console (e.g. Windows cp1252)."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
        except Exception:
            pass


def main(argv: "list[str] | None" = None) -> int:
    _force_utf8_stdio()
    ap = argparse.ArgumentParser(description="Wire docs/INDEX.yaml into a project.")
    ap.add_argument("--project-root", default=".", help="Target project root (default: cwd).")
    ap.add_argument("--python", default="python", help='Python invocation for the hook (e.g. "uv run python").')
    ap.add_argument("--dry-run", action="store_true", help="Print planned changes without writing.")
    args = ap.parse_args(argv)

    root = Path(args.project_root).resolve()
    code, log = run(root, args.python, args.dry_run)
    header = "[DRY-RUN] " if args.dry_run else ""
    print(f"{header}sdlc:setup wiring -> {root}")
    print("\n".join(log))
    print(f"{header}{'OK' if code == 0 else 'FAILED'}")
    return code


if __name__ == "__main__":
    sys.exit(main())
