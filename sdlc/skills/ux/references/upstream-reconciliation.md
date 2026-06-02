# Upstream-change re-invocation — canonical mechanics

**This is the shared, canonical specification for what happens when an SDLC
artifact skill is invoked a second (or third…) time for the same output and
one or more of its *upstream* artifacts has changed in between.** It is the
detailed companion to CLAUDE.md cross-skill convention §7. Every consumer
skill (`ux`, `data`, `api`, `arch`, and the future `test`/`task`/`deploy`)
references this file; `prd` does not (it consumes no upstream artifact).

Downstream skills point here with the repo-relative path
`sdlc/skills/ux/references/upstream-reconciliation.md`.

## Contents

- [Three meanings of re-invocation](#three-meanings-of-re-invocation)
- [The provenance record](#the-provenance-record)
- [Step 1 — record provenance at write time (Phase 7/8)](#step-1)
- [Step 2 — detect change on re-run (Phase 2)](#step-2)
- [Step 3 — classify the delta](#step-3)
- [Step 4 — the delta-review pass (one AskUserQuestion sweep)](#step-4)
- [Step 5 — reconcile, then continue the normal flow](#step-5)
- [Edge cases](#edge-cases)

## Three meanings of re-invocation

When a skill is invoked and its output yaml already exists, the user means
one of three things. Disambiguate before doing anything — they are handled
by different machinery:

| Meaning | Trigger | Handled by |
|---|---|---|
| **Resume** an interrupted session | state file `status: in_progress` | the state-file resume prompt (Phase 1) |
| **Refine / extend** deliberately | state `complete`/`aborted`, upstream *unchanged* | the merge/update flow (`references/merge-validate.md`) |
| **Reconcile** because upstream changed | state `complete`/`aborted`, upstream *changed* | **this document** |

The first two are well-defined and uniform across skills. This document
governs only the third — the case the user most often re-invokes for
("the PRD/UX/DATA/API moved under me"). The three are not mutually
exclusive in one run (a resume can also discover upstream drift); run
resume first, then the delta-review below before the theme interview.

## The provenance record

The output artifact carries `metadata.upstream_provenance`: a snapshot,
written at every save, of exactly which upstream artifacts this output was
built against. One entry per upstream artifact consumed:

```yaml
metadata:
  upstream_provenance:
    - {file: docs/PRD.yaml,        session_id: <uuid4>, last_updated: <iso8601>, sha256: <16-hex>}
    - {file: docs/DATA-MODEL.yaml, session_id: <uuid4>, last_updated: <iso8601>, sha256: <16-hex>}
```

Field sources:

- `file` — the upstream artifact path.
- `session_id` — the upstream's `metadata.session_id` at read time.
- `last_updated` — the upstream's `metadata.last_updated` at read time.
- `sha256` — the **16-hex content-hash prefix** of the upstream file. This is
  the *same* primitive `setup`'s `docs_index.py` already computes: read it
  from `docs/INDEX.yaml.generated_from[<file>].sha256`. If `INDEX.yaml` is
  absent (the project never ran `/sdlc:setup`), compute it inline:
  `sha256(file_bytes).hexdigest()[:16]`.

Unlike `changelog` (append-only history), `upstream_provenance` is a
**replace-on-write snapshot** — it always reflects the upstream state of the
*latest* write. The validator type-checks it as a list of mappings only; it
enforces no field shape (manual edits and partial records are tolerated).

Why a content hash and not just `session_id`? `session_id` only changes when
the upstream skill *writes*. It does **not** change when the user hand-edits
`PRD.yaml` directly — the single most common way upstream drifts. The hash
catches hand-edits; `session_id`/`last_updated` are kept as human-legible
context and a fallback when no hash is available.

## Step 1 — record provenance at write time (Phase 7/8) {#step-1}

Whenever the skill writes its output, (re)write `metadata.upstream_provenance`
with the current snapshot of every upstream artifact it consumed this run.
Do this for both fresh writes and merges. For skills with per-item
sub-artifacts that are authored in separate invocations (`arch` containers),
each sub-artifact records the provenance of what *it* consumed at *its* write
time — so a container drilled weeks after the system interview carries its
own, possibly newer, baseline.

## Step 2 — detect change on re-run (Phase 2) {#step-2}

After the input scan, if the output already exists and carries
`upstream_provenance`, classify each upstream artifact:

1. Read the upstream's current hash (from `INDEX.yaml.generated_from`, else
   compute inline) and current `metadata.session_id`.
2. Compare to the recorded provenance entry for that file:
   - **unchanged** — recorded `sha256` equals current. Skip it.
   - **changed** — `sha256` differs (or, if no hash is recorded, `session_id`
     differs). Mark for delta classification.
   - **no-baseline** — the output predates this convention (no
     `upstream_provenance` at all, or no entry for this file). We can't diff;
     recommend a coverage-driven review (Step 4 falls back to "review all
     traces against current upstream") and write a fresh provenance snapshot
     going forward.

If every upstream is **unchanged**, there is no drift: this is a *refine*,
not a *reconcile* — fall through to the normal merge flow and do not run the
delta-review.

## Step 3 — classify the delta {#step-3}

For each **changed** upstream, diff its ID families (the families named in its
`conventions.artifact_ids`) against the ids this output references. Three
buckets:

- **Added** — ids now in the upstream that this output does not yet consume.
  These already surface via the coverage cross-checks; the delta-review names
  them up front so they aren't only discovered at validation time.
- **Removed** — ids this output references that no longer exist upstream.
  This is the existing stale-ref case (CLAUDE.md §4) — never silently delete;
  ask per ref.
- **Modified** — ids present in *both* the recorded and current upstream
  whose **body changed while the id stayed stable** (a requirement reworded,
  an entity gaining fields, a DTO reshaped). File-level hashing tells you the
  upstream moved but cannot pinpoint *which* item; so:
  - If a changed upstream has a non-empty add/remove set, surface those
    precisely (above).
  - If a changed upstream's id *set* is identical to the recorded one, the
    change is purely in item bodies. Surface it honestly: "PRD changed but its
    FR/WKF id set is unchanged — descriptions or fields were edited." Offer to
    walk the upstream items this output traces, re-reading their *current*
    slices (via `INDEX.yaml`), so the user confirms or adjusts.

  Skills MAY upgrade modified-detection to be precise by also recording a
  per-traced-id hash in provenance; this is optional and not required by the
  contract (it trades provenance size for pinpoint accuracy).

## Step 4 — the delta-review pass (one AskUserQuestion sweep) {#step-4}

Present a **single consolidated summary** across all changed upstreams before
the theme interview begins — don't drip-feed one upstream at a time. Lead
with what moved:

> Since this `<OUTPUT>` was last written:
> - `docs/PRD.yaml` changed (added FR-014, FR-015; removed FR-009; bodies of
>   FR-002, WKF-003 may have changed).
> - `docs/DATA-MODEL.yaml` unchanged.

Then resolve each item. Batch with `AskUserQuestion` (multi-select where the
items are independent). For every added / removed / modified item the user
chooses one of:

- **incorporate** — fold it into this session (a new surface/entity/endpoint/
  container for an add; a re-trace or removal for a remove; a re-review for a
  modify).
- **ignore + warn** — leave the output as-is and record a `WRN-NNN` so the
  gap is reviewable rather than silent.
- **defer (todo)** — same as ignore but flagged as intended future work
  (`WRN-NNN` worded as a deferral).

Persist each decision to the state file so an EXIT-then-resume does not
re-prompt already-resolved items. Honour the standard caps and the
anti-padding rule — surface only real deltas, never manufacture them.

## Step 5 — reconcile, then continue the normal flow {#step-5}

After the delta-review:

1. Carry the **incorporate** decisions into the theme interview / merge as
   pre-seeded work (treat them like `⚠ inferred` candidates needing
   confirmation, not silent writes).
2. Append a `WRN-NNN` for every **ignore**/**defer** decision.
3. At write time (Step 1), refresh `metadata.upstream_provenance` to the new
   snapshot — the reconciled output is now built against the *current*
   upstream.
4. Add a `changelog` line, e.g.
   `"<version> (<date>): Re-derived against changed docs/PRD.yaml (added FR-014/015, removed FR-009)."`

This is what makes re-invocation *mean* something precise: instead of
re-walking the whole interview and hoping the merge plus coverage checks
catch the drift, the user sees exactly what moved upstream and decides, per
item, what this artifact should do about it.

## Edge cases {#edge-cases}

- **Output exists, no provenance at all (pre-convention artifact).** Cannot
  diff. Tell the user the artifact predates drift-tracking; offer a
  coverage-driven review (walk current upstream id families against the
  output's traces) and write a provenance snapshot from this run forward.
- **`INDEX.yaml` absent.** Compute hashes inline (`sha256(bytes)[:16]`).
  Everything else is unchanged.
- **Upstream artifact missing entirely.** That is the existing "required
  input missing" abort (each skill's Phase 2 / `edge-cases.md`), not a
  delta — handle it there, before this document applies.
- **Hash differs but the diff is empty** (whitespace/comment-only edit, or a
  re-save with no semantic change). Report "changed, but no id-level delta
  found" and let the user proceed without action; still refresh the snapshot.
- **Provenance present and every hash matches.** No drift — skip the
  delta-review and treat as a plain refine/extend.
- **EXIT mid-delta-review.** Persist resolved decisions and the unresolved
  queue to state; on resume, continue the review where it stopped.
