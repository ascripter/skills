# Merging, validating, and the CLAUDE.md pointer

Detailed rules for Phase 7 (write & validate) and Phase 8 (CLAUDE.md
pointer). Read this when entering Phase 7.

## Merging into an existing DATA-MODEL.yaml

If `docs/DATA-MODEL.yaml` already exists at the project root:

- Load it as the baseline.
- Merge the session's confirmed answers on top:
  - **Keys present in both** — overwrite *only* if the user changed the
    value during this session. Otherwise keep the existing value.
  - **New keys** — add them.
  - **Keys the session would remove** (rare; only if the user explicitly
    cleared a value) — ask the user to confirm before deleting.

If the user manually edited `docs/DATA-MODEL.yaml` between sessions and
the state file disagrees on a specific key, surface the conflict — do
NOT silently pick one:

> "Conflict on `entities.User.fields.email.unique`:
>   DATA-MODEL.yaml has: `true`
>   Interview state has: `false` (set at <timestamp>)
> Which should I keep?"

Always preserve **unrelated keys** in `DATA-MODEL.yaml` even if you don't
recognize them. The validator's `extra="allow"` config means custom keys
are tolerated.

## Entity rename / removal — the dangerous merge cases

These are where DATA-MODEL merge differs from PRD merge. Entities are
referenced from many places (relationships, data_classification,
bounded_contexts, indexes_and_queries, search_and_analytics,
caching_layer, external_data_sources.maps_to_entity). When the user
**renames** or **removes** an entity in this session, the merge must
either propagate the change or warn loudly.

**Rename `X → Y`**:

1. Rewrite `entities.X` → `entities.Y` (key change).
2. Walk every other block:
   - `relationships[*].from_entity / to_entity / join_table`: replace `X` with `Y`.
   - `data_classification.{pii_fields, regulated_fields, encrypted_at_rest}`:
     replace `X.<field>` with `Y.<field>`.
   - `bounded_contexts.*.entities`: replace `X` with `Y`.
   - `enums_and_lookups.lookup_tables`: replace `X` with `Y`.
   - `indexes_and_queries.{access_patterns, expected_indexes}[*].entity`:
     replace.
   - `integrity_and_constraints.{unique_constraints, check_constraints}[*].entity`:
     replace.
   - `audit_and_lifecycle.applies_to`, `versioning_and_history.applies_to`:
     replace.
   - `scale_and_retention.retention_policies[*].entity`: replace.
   - `caching_layer.cached_entities[*].entity`: replace.
   - `search_and_analytics.indexed_entities[*].entity`: replace.
   - `external_data_sources[*].maps_to_entity`: replace.
   - `entities.*.fields.*.references` strings containing `X.<...>`:
     rewrite to `Y.<...>`.
3. Show the user a summary of the rewrites before saving.

**Remove entity `X`**:

1. Confirm with the user explicitly: *"Removing `X` will affect N other
   blocks. Continue?"*
2. Walk the same blocks above. For each reference to `X`:
   - In `relationships`: drop the entire relationship row.
   - In `data_classification.*`: drop the entry.
   - In `bounded_contexts.*.entities`: drop from the list (and warn if
     it leaves a context empty).
   - In `entities.*.fields.*.references`: set to `null` and warn the user
     that the FK is now dangling.
3. Append a `data_warnings` entry: *"Entity X removed at <timestamp>; N
   downstream references were also removed."*

If the user is uncertain, the safer move is **soft-removal**: keep `X`
in `entities` with a `description: "DEPRECATED — to be removed in next
session"` and let downstream agents see the deprecation marker.

## Writing the file

Write `docs/DATA-MODEL.yaml` with:

- Inline YAML comments on each top-level key (use `DATA-MODEL.schema.yaml`
  as the template).
- Updated `metadata.last_updated` (ISO-8601 UTC) and `metadata.session_id`.
- `metadata.status`:
  - Set to `"complete"` only when **all required fields are filled**,
    **every cross-check passes**, and the validator exits with `[OK]`.
  - Set to `"draft"` on early EXIT, when any required field is still null,
    or when a soft cross-check (feature coverage, volume-vs-scale gate)
    reports issues.
- `data_warnings`: informational notes (low-confidence answers, merge
  conflicts, deferred themes, classification orphans flagged in error
  recovery, etc.) — not used for required-field acknowledgement.

## Running the validator

```bash
python "${CLAUDE_SKILL_DIR}/validate_schema.py" --path docs/DATA-MODEL.yaml
```

Exit codes:

| Code | Meaning | What the agent does |
|---|---|---|
| 0 (`[OK]`) | Complete and valid; all cross-checks pass | ✓ Proceed to Phase 8. |
| 0 (`[DRAFT]`) | Draft — structurally valid, possibly missing required fields or with soft-check warnings | Inform user and proceed to Phase 8 (pointer still injected). |
| 1 (`[FAIL]`) | Schema invalid, OR `status: complete` but required fields missing, OR `status: complete` but a hard cross-check failed (relationship integrity, classification integrity, bounded-context partition) | Show field-level errors verbatim. If required fields are missing, offer via `AskUserQuestion`: fill them in now, or accept `status: draft`. If a cross-check failed, walk the user through the offending block (e.g. show the relationship that references a nonexistent entity). Re-run validation after re-entry. |
| 2 | Cannot read/parse the file | Surface to user (missing file, bad YAML, permission error). Do not retry silently. |
| 3 | Missing dependency | Validator prints `pip install` instructions. Do **not** auto-install — ask the user to install and re-run. |

**Downstream-agent contract**: downstream agents (api, arch, test) MUST
reject the DATA-MODEL if `metadata.status != "complete"` OR if
`validate_schema.py` exits non-zero. Document this in CLAUDE.md if the
user asks.

## Cross-check recovery flows

The validator reports eight check categories (the seven explicit
cross-checks plus the required-fields gate). Each has a different
recovery path:

| Cross-check                       | If hard-fail at status:complete   | Recovery |
|-----------------------------------|-----------------------------------|----------|
| Required fields missing           | FAIL                              | Re-enter via AskUserQuestion |
| Relationship integrity            | FAIL                              | Show the relationship, ask user to fix from_entity / to_entity / join_table |
| Field references                  | FAIL                              | Show entity.field.references, ask user to correct |
| Classification integrity          | FAIL                              | Show offending Entity.field in pii_fields/regulated_fields/encrypted_at_rest |
| Bounded-context partition         | FAIL                              | Show unassigned/duplicate entities, ask to reassign |
| Feature coverage                  | Soft — force draft, warn          | Walk uncovered FR-NNN list, ask to assign each to ≥1 entity OR mark out-of-scope-for-data |
| Volume-vs-scale gate              | Soft — force draft, warn          | Prompt user to fill scale_and_retention partitioning/sharding/retention |
| Mode mismatch                     | FAIL (pydantic)                   | Refuse to write; ask user to fix the structural state in Phase 4 |

## CLAUDE.md pointer (Phase 8)

On validation exit code 0 (either `[OK]` or `[DRAFT]`), call
`set_claude_md_pointer.py` (bundled with this skill) to inject or update
the skill's bullet inside the shared `## SDLC Documents` section of the
project root `CLAUDE.md`. The script implements the rules below
deterministically — do not write to `CLAUDE.md` by hand.

**Bullet format**:

```
- `docs/DATA-MODEL.yaml`: persistent data model — entities, fields, relationships, indexes, classification. Load when working on persistence, queries, migrations, or any data-touching code. Last updated by `sdlc-data` on <ISO-8601 timestamp>.
```

**Rules** (mirrored from CLAUDE.md project conventions):

- If `CLAUDE.md` does not exist → create it containing only the
  `## SDLC Documents` heading and this bullet.
- If `CLAUDE.md` exists but the `## SDLC Documents` section does not →
  append a blank line, the heading, and this bullet at the end.
- If the section exists and a bullet whose substring contains both
  `` `docs/DATA-MODEL.yaml` `` and `` `sdlc-data` `` is present → update
  the timestamp only; do not duplicate.
- If the section exists but no matching bullet → append the bullet as
  the last line of the section.
- Never reorder or modify the user's existing CLAUDE.md content.

Invoke as:

```bash
python "${CLAUDE_SKILL_DIR}/set_claude_md_pointer.py"
# add --dry-run to preview the diff without writing
```

## Closing the session

After Phase 8's CLAUDE.md write succeeds:

- Set `status: complete` in the state file.
- Keep the state file as an audit trail — do **not** delete it.
- Tell the user where the artifacts live and which downstream skills
  can now run: *"Done. `docs/DATA-MODEL.yaml` is valid and complete. You
  can now run `/sdlc:api` to define the API contract that fronts these
  entities."*
