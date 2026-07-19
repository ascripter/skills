# Merge, validate & close (sdlc-test)

Read on entering Phase 7. Covers: the merge flow for an existing artifact, the
full cross-check suite (summary + pointer to the validator), the recovery flow
on `[FAIL]`, the CLAUDE.md pointer rules, and the downstream-rejection rule.

---

## Merge flow (output already exists, upstream unchanged)

If the active mode's output yaml already exists (and the Phase-2
upstream-change detection found no upstream drift), this is a deliberate
refine/extend — not a reconcile. Merge rather than overwrite:

- Load the on-disk yaml as the **baseline** (it is the source of truth for
  *answers*; it may have been hand-edited).
- Overwrite a key only where the user changed its value in **this** session.
- Add new tests / fields the session produced.
- For a test the session would **remove**, confirm with the user first — never
  silently drop a `TST-NNN` (a downstream `task`/codegen run may already
  reference it).
- Preserve unrelated keys you don't recognize (manual additions).
- Surface conflicts between the on-disk yaml and the state file's
  `partial_answers` — ask the user which wins; never auto-resolve.
- **Preserve `tst_id`s.** Renaming a test's `name` or re-tiering it keeps its
  id. The id is the stable contract downstream consumes.
- **Mint new `tst_id`s from the GLOBAL counter** (`state.last_ids_global.TST`,
  reconciled to `max(all on-disk TEST-STRATEGY*.yaml, state)` first) — never
  from the highest id in the file being merged. Per-file restarts are how
  three colliding TST-001s happen.
- **Refresh derived counts in prose (CLAUDE.md §8).** If the file's
  `overview`/notes or header comments restate test counts ("181 tests",
  "14 unit / 5 integration") that this merge changed, re-derive or delete
  them in the same write.

If Phase-2 detected an upstream change, run the delta-review first
(`sdlc/skills/ux/references/upstream-reconciliation.md`), then merge. Run the
**ARCH `implements_requirements` staleness check** (SKILL.md Phase 2) even
when provenance is absent — a promoted FR with no test is the drift this
skill exists to catch.

## The cross-check suite

`validate_schema.py` validates `docs/TEST-STRATEGY.yaml` + every sibling
`docs/TEST-STRATEGY__*.yaml` together (it reads PRD.yaml, ARCH.yaml, and each
ARCH__*.yaml for the checks). The authoritative list lives in the two
`.schema.yaml` headers; in summary:

**Blocking (force `status: draft` if violated while claiming complete):**

1. Required-field completeness.
2. `TST-NNN` format + uniqueness per file + **global uniqueness across the
   system file and every container file** (one continuous namespace —
   downstream `Task.test_refs` assumes it); `WRN-NNN` format (per-artifact).
3. `covers` are FR/NFR/ACR/WKF and resolve to PRD ids.
4. `involves_containers` / `container_strategies.container_id` resolve to ARCH.
5. `component_ref` resolves to the matching `ARCH__<container>.yaml`; unit
   tests set it.
6. `targets_failure_mode` / `targets_security_concern` resolve to ARCH ids.
7. A container test's covered FR/NFR ⊆ the container's + component's
   `implements_requirements`.
8. Coverage gates (trace-or-defer) — workflow (system), requirement,
   acceptance, and risk (container). See `coverage-and-defer.md`.
9. `targets_work_units` entries resolve to the `component_ref`'s
   `work_units[].name` (the legacy singular `targets_work_unit` is folded in
   as an alias); **test→subject seam** (v2.0): every unit-tier test names its
   subject(s) or is deferred by tst_id — blocks at
   `test_strategy_container_version >= 2.0` (warns below; silent in the
   meta-corpus dialect).
10. `shared_infrastructure` item shape (path + purpose + `realizes` ⊆
    {mock_policy, fixture_strategy, test_data_strategy}, ≥1) when the field is
    used.

**Non-blocking warnings:** missing optional enrichers; a
`container_strategies` file_path not on disk; an upstream
`metadata.status != complete` (the skill itself refuses to run in that case,
but a standalone validator run surfaces it); the legacy singular
`targets_work_unit` alias at ≥ 2.0 (migrate to the plural); a `gating: false`
test whose directives don't mention its exclusion marker, or at unit tier
(SK-07); mock/fixture policy prose naming deliverables while
`shared_infrastructure` is empty (SK-08); work-unit coverage (a unit no test
exercises).

## Recovery flow on `[FAIL]`

When the validator reports `[FAIL]` (a file claims `complete` but a check
failed):

1. Read the printed errors — they name the exact field/id.
2. For a **coverage** gap: either add the missing test in a short per-item
   drill, or `defer <id>` with a reason (logs the WRN-NNN). Re-validate.
3. For a **reference** error (a bad `covers`/`component_ref`/target id): fix
   the reference or correct the upstream typo, with the user's confirmation.
4. For **missing required**: re-enter the field via `AskUserQuestion`.
5. Re-run the validator. Only set `status: complete` once it prints `[OK]` and
   complete.

If the user wants to stop with gaps outstanding, write `status: draft` — the
draft is valid (exit 0) and resumable later.

## CLAUDE.md pointer rules (Phase 8)

Call `set_claude_md_pointer.py` (it implements these deterministically):

- One shared `## SDLC Documents` section; create it if missing.
- The bullet is detected by the substrings `` `docs/TEST-STRATEGY.yaml` `` and
  `` `sdlc-test` ``. If present → update the timestamp only; else → append at
  the section end. Never reorder or modify other skills' bullets or unrelated
  content.
- `--dry-run` prints the result without writing.

Then refresh `docs/INDEX.yaml` (`python .claude/sdlc/docs_index.py`) if the
generator exists, and set the active sub-session `status: complete` in the
state file.

## Downstream-rejection rule

Downstream skills/agents (`task`, the code-generation and verification stages)
**MUST reject** a `TEST-STRATEGY*.yaml` input if `metadata.status != "complete"`
OR if `validate_schema.py` exits non-zero. A draft or invalid test strategy is
not a contract — consuming it would scaffold tests against an unverified spec.
The per-container file and the system file are judged independently: `task` may
proceed for a container whose `TEST-STRATEGY__<container>.yaml` is complete even
while another container's is still draft, provided the system
`TEST-STRATEGY.yaml` it inherits from is itself complete.
