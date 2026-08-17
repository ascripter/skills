# Forward-propagation — fixing at the source and carrying it downstream (sdlc-repair)

Read this on entering Phase 4. Back-propagation found *where* the defect lives;
this file covers *how* to fix it there and how far the fix has to travel.

---

## Blast radius is computed, never guessed

Before editing anything, ask the index who depends on the symbol you are about
to change:

```bash
python .claude/sdlc/docs_index.py --refs <symbol>
```

`setup` wires this graph precisely so an edit's inbound sites can be reconciled
in the same pass (CLAUDE.md, Phase 2 of the canonical flow). The `referenced_by`
set **is** the forward-propagation scope: every artifact in it either changes
with the source or is checked and found unaffected. Nothing outside it needs to
change.

If the project never ran `/sdlc:setup` there is no index. Fall back to
`crosscheck_artifacts.py`'s own reference walk plus a targeted grep for the
symbol across `docs/`, and say in the resolution record that the radius was
derived without the index.

## Two modes

The choice turns on one question: **does the fix change the SET of downstream
items, or only their CONTENT?**

| | `surgical` | `re-invoke` |
|---|---|---|
| **When** | content of existing items changes: a field added to a contract, a threshold corrected, a statement disambiguated, a stale embed re-sliced | the set of items changes: a new/removed component, work_unit, entity, operation, surface, TST, or task; a renamed id; a restructured boundary |
| **Who edits** | this skill, directly | the owning skill, re-invoked by the user |
| **Cost** | minutes, no interview | a delta-review pass per downstream stage |
| **Risk** | none if the radius was computed | none — the skills' own gates apply |

When in doubt, prefer `re-invoke`. A surgical edit that *should* have been a
re-invocation leaves a downstream artifact internally consistent but missing an
item, and no validator will catch it — coverage gates only check the items that
exist.

## Surgical mode

Order matters: source first, then outward along the reference graph, then
verify. Editing a downstream copy before its source leaves a window where the
two disagree and a concurrent doctor run reports a defect that is mid-repair.

1. **Edit the source artifact.** Make the smallest change that records the
   missing or corrected fact.
2. **Bump its metadata in the same write** — `metadata.<name>_version` and one
   appended `changelog` line in the canonical format
   (`"<version> (<YYYY-MM-DD>): <one-line summary>"`, most-recent first,
   append-only). A repair that leaves no changelog trace is indistinguishable
   from a hand-edit later.
3. **Re-derive any prose the change invalidated** (CLAUDE.md §8): if the source
   carries a sentence restating a count you just changed, fix the sentence or
   delete it in the same write.
4. **Re-slice every embed copied from the changed symbol.** This is the step
   that makes the fix stick. `task` artifacts embed `interface_contract`,
   `test_spec`, `operation_contract`, `entity_slice`, `design_spec` and
   `config_keys`; each one copied from the symbol you edited must now be
   updated to match. This does **not** contradict CLAUDE.md §9 — that rule
   forbids patching an embed *instead of* its source. Fixing the source and
   re-slicing in the same pass is exactly what it asks for. Patching only the
   embed is what it forbids.
5. **Walk the rest of the `--refs` set.** For each inbound artifact, either
   apply the corresponding edit or record why it is unaffected.
6. **Verify** — see below.

## Re-invoke mode

This skill does not run other skills. It produces the **exact command sequence**
and stops, because those skills are interviews and the user owns them.

- Order the sequence by pipeline position (`prd → ux → design → data → api →
  arch → test → task`), including only the stages the radius actually touches.
- Use the per-container form where the skill has one (`/sdlc:arch <cid>`,
  `/sdlc:test <cid>`, `/sdlc:task <cid>`) — re-running a whole stage when one
  container moved is wasted interview time.
- Say what each stage will do: every downstream skill already carries the §7
  **upstream-change reconciliation** contract, so on re-invocation it detects
  the changed content hash, classifies the delta (added / removed / modified),
  and runs a delta-review before its interview. That machinery is why repair
  does not need to drive those edits itself.
- Fix the source artifact first (steps 1–3 of surgical mode) so the
  re-invocations have something correct to reconcile against.
- Record the sequence in the finding's `resolution.downstream_rerun`, and leave
  the finding `triaged` — not `resolved` — until the user reports the
  re-invocations done. A finding marked resolved while its downstream stages are
  still stale is a lie the next doctor sweep will catch anyway.

## Verification (every mode, every time)

Run each command **bare** and record the captured numeric exit code — never read
an exit status after a pipe (CLAUDE.md §11):

```bash
python "${CLAUDE_SKILL_DIR}/../<stage>/validate_schema.py" --path docs/<ARTIFACT>
python "${CLAUDE_SKILL_DIR}/../task/crosscheck_artifacts.py" --docs-dir docs
python .claude/sdlc/docs_index.py                 # regenerate the index
python .claude/sdlc/docs_index.py --check         # dangling-reference gate
```

Validate **every artifact touched**, not just the source. A surgical edit that
fixes the source and breaks a downstream coverage gate is a worse state than the
one you started in.

If a validator that was already red before this repair is still red for an
unrelated reason, say so explicitly and do not claim the repair caused or fixed
it. Record the before/after exit codes.

## Handback to codegen

There is no bespoke handback mechanism, and there should not be. Editing a task
artifact changes each affected task's JSON, which changes its
`task_fingerprint`, which `/sdlc:code` already classifies as **`stale`** and
gates at its plan approval (regenerate / keep). The chain closes itself.

To report it concretely, list the tasks that moved:

```bash
python "${CLAUDE_SKILL_DIR}/../code/topo_order.py" --scope <cid> --state .claude/skills-state/sdlc-code.state.yaml
```

Its `stale` section is the answer. Put those ids in
`resolution.stale_tasks` and name them in the close report, so the user knows
what the next `/sdlc:code` run will offer to rebuild.

Then the close report's next step is a plain command:

```
Next:  /sdlc:code <cid>          ← in a NEW session
       3 tasks are now stale and will be offered for regeneration.
```

Fresh session for the same reason it always is: `/sdlc:code`'s handoff is its
ledger, not a transcript (`../../code/references/session-and-limits.md`).
