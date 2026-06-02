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

If Phase-2 detected an upstream change, run the delta-review first
(`sdlc/skills/ux/references/upstream-reconciliation.md`), then merge.

## The cross-check suite

`validate_schema.py` validates `docs/TEST-STRATEGY.yaml` + every sibling
`docs/TEST-STRATEGY__*.yaml` together (it reads PRD.yaml, ARCH.yaml, and each
ARCH__*.yaml for the checks). The authoritative list lives in the two
`.schema.yaml` headers; in summary:

**Blocking (force `status: draft` if violated while claiming complete):**

1. Required-field completeness.
2. `TST-NNN` format + uniqueness per file; `WRN-NNN` format.
3. `covers` are FR/NFR/ACR/WKF and resolve to PRD ids.
4. `involves_containers` / `container_strategies.container_id` resolve to ARCH.
5. `component_ref` resolves to the matching `ARCH__<container>.yaml`; unit
   tests set it.
6. `targets_failure_mode` / `targets_security_concern` resolve to ARCH ids.
7. A container test's covered FR/NFR ⊆ the container's + component's
   `implements_requirements`.
8. Coverage gates (trace-or-defer) — workflow (system), requirement,
   acceptance, and risk (container). See `coverage-and-defer.md`.

**Non-blocking warnings:** missing optional enrichers; a
`container_strategies` file_path not on disk; an upstream
`metadata.status != complete` (the skill itself refuses to run in that case,
but a standalone validator run surfaces it).

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
