"""Inject or update the sdlc-test bullet in the shared ## SDLC Documents section
of the project-root CLAUDE.md.

Run from the project root:

    python sdlc/skills/test/set_claude_md_pointer.py
    python sdlc/skills/test/set_claude_md_pointer.py --dry-run
    python sdlc/skills/test/set_claude_md_pointer.py --path some/CLAUDE.md

Behavior (mirrors CLAUDE.md project conventions):
    - If CLAUDE.md does not exist           -> create with the section + bullet.
    - If the section is missing             -> append section + bullet at EOF.
    - If a matching bullet already exists   -> update its timestamp only.
    - Else (section but no bullet)          -> append the bullet at section end.
Never reorders or modifies unrelated content.

Bullet format (exactly as specified by the sdlc:test contract):

    - `docs/TEST-STRATEGY.yaml` (+ `docs/TEST-STRATEGY__<container>.yaml`): Test strategy — pyramid targets, coverage thresholds, mock/fixture policy, the cross-container e2e + contract suite, and per-container unit/integration tests (TST-NNN). Load when generating tests, writing test tasks, or verifying coverage. Last updated by `sdlc-test` on <ISO-8601 timestamp>.

The bullet is detected by the substrings `docs/TEST-STRATEGY.yaml` (in
backticks) and `sdlc-test` (in backticks). Bullets belonging to other sdlc-*
skills are left untouched.

Exit codes:
    0 - success (created | updated_timestamp | appended_bullet | appended_section | no-op).
    2 - cannot read or write the file (permission error, etc.).
"""

from __future__ import annotations

import argparse
import datetime as _dt
import sys
from pathlib import Path

ARTIFACT = "`docs/TEST-STRATEGY.yaml`"
SKILL_TAG = "`sdlc-test`"
SECTION_HEADING = "## SDLC Documents"


def bullet(timestamp: str) -> str:
    return (
        f"- {ARTIFACT} (+ `docs/TEST-STRATEGY__<container>.yaml`): "
        f"Test strategy — pyramid targets, coverage thresholds, mock/fixture "
        f"policy, the cross-container e2e + contract suite, and per-container "
        f"unit/integration tests (TST-NNN). Load when generating tests, writing "
        f"test tasks, or verifying coverage. "
        f"Last updated by {SKILL_TAG} on {timestamp}."
    )


def _iso_utc_now() -> str:
    return _dt.datetime.now(tz=_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _find_section(lines: list[str], heading: str) -> tuple[int, int] | None:
    for i, line in enumerate(lines):
        if line.strip() == heading:
            j = i + 1
            while j < len(lines) and not lines[j].startswith("## "):
                j += 1
            return i, j
    return None


def _matches_bullet(line: str) -> bool:
    stripped = line.lstrip()
    return stripped.startswith("- ") and ARTIFACT in stripped and SKILL_TAG in stripped


def upsert(content: str, timestamp: str) -> tuple[str, str]:
    new_bullet = bullet(timestamp)
    if not content:
        return SECTION_HEADING + "\n" + new_bullet + "\n", "created"

    had_trailing_newline = content.endswith("\n")
    lines = content.split("\n")
    if had_trailing_newline:
        lines.pop()

    section = _find_section(lines, SECTION_HEADING)
    if section is None:
        if lines and lines[-1].strip() != "":
            lines.append("")
        lines.append(SECTION_HEADING)
        lines.append(new_bullet)
        action = "appended_section"
    else:
        start, end = section
        action = None
        for k in range(start + 1, end):
            if _matches_bullet(lines[k]):
                if lines[k] == new_bullet:
                    action = "no-op"
                else:
                    lines[k] = new_bullet
                    action = "updated_timestamp"
                break
        if action is None:
            insert_at = end
            while insert_at > start + 1 and lines[insert_at - 1].strip() == "":
                insert_at -= 1
            lines.insert(insert_at, new_bullet)
            action = "appended_bullet"

    out = "\n".join(lines)
    if had_trailing_newline or action == "appended_section":
        out += "\n"
    return out, action


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--path", default="CLAUDE.md", help="Path to CLAUDE.md (default: ./CLAUDE.md).")
    ap.add_argument("--dry-run", action="store_true", help="Print the result instead of writing.")
    args = ap.parse_args()

    path = Path(args.path)
    ts = _iso_utc_now()

    try:
        original = path.read_text(encoding="utf-8") if path.exists() else ""
    except OSError as e:
        print(f"[ERR] cannot read {path}: {e}", file=sys.stderr)
        return 2

    new_content, action = upsert(original, ts)

    if args.dry_run:
        print(f"[DRY-RUN] action: {action}")
        print(f"[DRY-RUN] target: {path}")
        print("---")
        sys.stdout.write(new_content)
        if not new_content.endswith("\n"):
            sys.stdout.write("\n")
        return 0

    if action == "no-op":
        print(f"[OK] no-op: {path} already up-to-date")
        return 0

    try:
        path.write_text(new_content, encoding="utf-8")
    except OSError as e:
        print(f"[ERR] cannot write {path}: {e}", file=sys.stderr)
        return 2

    print(f"[OK] {action}: {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
