# Merging, validating, and the CLAUDE.md pointer

Detailed rules for Phase 8 (write & validate) and Phase 9 (CLAUDE.md
pointer). Read this when entering Phase 8.

## Merging into an existing PRD.yaml

If `docs/PRD.yaml` already exists at the project root:

- Load it as the baseline.
- Merge the session's confirmed answers on top:
  - **Keys present in both** — overwrite *only* if the user changed the
    value during this session. Otherwise keep the existing value.
  - **New keys** — add them.
  - **Keys the session would remove** (rare; only if the user explicitly
    cleared a value) — ask the user to confirm before deleting.

If the user manually edited `docs/PRD.yaml` between sessions and the state file
disagrees on a specific key, surface the conflict — do NOT silently pick
one:

> "Conflict on `<key>`:
>   PRD.yaml has: `<a>`
>   Interview state has: `<b>` (set at <timestamp>)
> Which should I keep?"

Always preserve **unrelated keys** in `PRD.yaml` even if you don't know
what they are. The validator's `extra="allow"` config means custom keys
are tolerated.

## Writing the file

Write `docs/PRD.yaml` with:

- Inline YAML comments on each top-level key (use `PRD.schema.yaml` as a
  template).
- Updated `metadata.last_updated` (ISO-8601 UTC) and `metadata.session_id`.
- A populated `prd_warnings` list for any required field left null.

## Running the validator

```bash
python .claude/skills/sdlc-prd/validate_prd.py --path docs/PRD.yaml
```

Exit codes:

| Code | Meaning | What the agent does |
|---|---|---|
| 0 | Valid | ✓ pass; warnings (if any) are informational. Proceed to Phase 9. |
| 1 | Schema invalid | Show field-level errors verbatim. Ask: "Want to re-enter just those fields, or finish with errors?" Re-run validation after re-entry. |
| 2 | Cannot read/parse the file | Surface to user (missing file, bad YAML, permission error). Do not retry silently. |
| 3 | Missing dependency | For `pydantic>=2` or `pyyaml`, validator prints `pip install` instructions AND alternatively `pyproject.toml` edit instructions, then calling `uv sync`. Do **not** auto-install — ask the user to install and re-run. |

## CLAUDE.md pointer (Phase 9)

On successful validation, inject (or update) this block in the project
root `CLAUDE.md`. If `CLAUDE.md` does not exist, create it with this block
as the sole content:

```markdown
## Product Requirements
`PRD.yaml` in `docs/` contains the full structured product requirements. Load when working on features, architecture, API design, or user-facing decisions. Last updated by `sdlc-prd` skill on <ISO-8601 timestamp>.
```

**Detection rule**: the block is identified by the heading
`## Product Requirements` followed by a paragraph containing the literal
string `` `PRD.yaml` `` and `sdlc-prd`. If a matching block exists,
**update the timestamp only** and do not duplicate.

If `CLAUDE.md` exists with unrelated content, append the block at the end
with a blank line before it. Never reorder or modify the user's existing
content.

## Closing the session

After Phase 9's CLAUDE.md write succeeds:

- Set `status: complete` in the state file.
- Keep the state file as an audit trail — do **not** delete it.
- Tell the user the workflow finished and where the artifacts live.
