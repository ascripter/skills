A review of the sdlc skills which used AICF `docs/` as a reference project that was created via those skills also pointed out some issues with 

```md
# Demo-docs findings — a fix prompt for a separate agent

> **Audience:** an agent working *inside the AICF demo project* whose `docs/`
> live at this repo's root (`docs/PRD.yaml`, `docs/DATA-MODEL.yaml`,
> `docs/ARCH*.yaml`, `docs/TEST-STRATEGY*.yaml`, `docs/UX*.yaml`). These are
> **demo-content** findings, **not** SDLC-skill bugs — the skills in
> `sdlc/skills/**` are correct; the demo artifacts diverge from them. Do **not**
> "fix" a validator to accept the demo; fix (or consciously waive) the demo.
>
> Surfaced as a byproduct of the 2026-07-08 SDLC-skills audit. Every item below
> was reproduced by running the stock validators against the demo docs. None of
> these failures were introduced by the audit's skill changes — they are
> pre-existing and were merely made visible.

## How to reproduce

```bash
# from repo root
export PYTHONUTF8=1
python sdlc/skills/prd/validate_schema.py  --path docs/PRD.yaml
python sdlc/skills/ux/validate_schema.py   --path docs/UX.yaml
python sdlc/skills/data/validate_schema.py --path docs/DATA-MODEL.yaml
python sdlc/skills/arch/validate_schema.py --path docs/ARCH.yaml
python sdlc/skills/test/validate_schema.py --path docs/TEST-STRATEGY.yaml
```

All five currently exit non-zero. The findings are grouped by root cause.

---

## Finding 1 — DATA-MODEL: the "authors no DDL" claim contradicts its own read-model store  (semantic, high)

`docs/DATA-MODEL.yaml`, `persistence` block:

- **Line ~89** — `paradigm_rationale: "... AICF authors no DDL."`
- **Line ~98** — checkpoint secondary store: `"... Library-managed schema (AICF authors no DDL) ..."`
- **Line ~104** — the FR-098 read-model secondary store: `"... a SQLite file at <...>.readmodel.db (... AICF authors THIS DDL). ..."`

The global paradigm rationale asserts AICF authors *no* DDL, but one of its own
secondary stores explicitly says AICF authors *this* DDL. Both can be true only
if the rationale is scoped ("the **primary** store authors no DDL; the derived
read-model does"). As written they read as a flat contradiction.

**Also (same block):** the `knowledge/market.db` secondary store (line ~99–101)
carries `role: source_of_truth` and is described as *"The ONE db-PRIMARY store
in AICF"* — a **source-of-truth / primary** store filed under `secondary_stores`.
That is a role/placement mislabel: a source-of-truth store is by definition not
secondary.

**Fix (pick one, then reconcile the prose):**
1. Reword `paradigm_rationale` to scope the "no DDL" claim to the primary
   file_native store, and acknowledge the derived read-model + market.db DDL; **and**
2. Either promote `market.db` out of `secondary_stores` (it is a primary/authoritative
   store for the FR-092 knowledge base) or change its `role` to something that
   matches "secondary" semantics. Keep whichever is true, not both.

---

## Finding 2 — DATA-MODEL: empty `pii_fields` / `regulated_fields` despite a first-class Compliance Agent  (consistency smell, medium)

`docs/DATA-MODEL.yaml`, `data_classification` block (lines ~115–116):

```yaml
pii_fields: []
regulated_fields: []
```

Yet the same corpus ships a **Compliance Agent** (FR-044), a `ComplianceReport`
entity, `ComplianceFinding`, a `security_compliance` PRD block that *"Drives …
Compliance Agent (FR-044)"*, and a `ConceptComplianceTrust` concept block. A
system with a dedicated compliance pipeline declaring **zero** PII and **zero**
regulated fields is internally consistent only if the internal-tool posture
(changelog v2.1: *"internal-tool posture: no PII/regulated/encrypted fields"*)
is truly correct.

This is a **smell, not a proven bug** — a single-user local CLI factory
genuinely may hold no PII. Action: **confirm consciously.** If correct, add a
one-line `data_classification` note (or a `WRN-NNN` in `data_warnings`) stating
"no PII/regulated fields by design — compliance agent governs generated-app
output, not AICF's own data," so the emptiness reads as a decision rather than
an oversight. If *not* correct (e.g. repo paths, user prompts, or API keys count
in your threat model), populate the lists.

---

## Finding 3 — Pervasive malformed `WRN-NNN` ids across artifacts  (format, high — blocks validation)

The universal warnings contract is `"WRN-NNN: <message>"` — a zero-padded
3-digit number followed **immediately** by a colon. Multiple demo artifacts
instead write a parenthetical version/annotation **between** the number and the
colon, which fails the format check and makes the file invalid:

- `docs/TEST-STRATEGY.yaml` → `test_strategy_warnings[0]`:
  `"WRN-005 (v1.3, doctor-review Q1): ACR-### tracing is MECHANISM-ONLY ..."`
- `docs/ARCH__aicf-cli.yaml` → `arch_warnings[5]`:
  `"WRN-006 (v1.11): schema-foundation is LAYER-0 ..."`

(Grep the corpus for `WRN-\d+ \(` to find the rest — this is a house style, so
expect several.)

**Fix:** move the annotation to *after* the colon:
`"WRN-005: (v1.3, doctor-review Q1) ACR-### tracing is MECHANISM-ONLY ..."`.
The id → colon → message shape must be exact; everything else is free text.

---

## Finding 4 — UX: entity ids filed into `implements_requirements`  (wrong id family, high — blocks validation)

`docs/UX__cmd-show.yaml`, `docs/UX__cmd-status.yaml` (and likely more):

```
implements_requirements: 'ENT-049' does not match 'FR-NNN' or 'NFR-NNN'
implements_requirements: 'ENT-003' does not match 'FR-NNN' or 'NFR-NNN'
```

`implements_requirements` traces **requirements** (FR-NNN / NFR-NNN) only.
`ENT-###` are DATA-MODEL entity ids and belong in an entity-reference field, not
a requirements-trace field. (Note: DATA-MODEL changelog v2.20 *removed*
`SurfaceEntry.references_entities`; these entity refs may be orphaned leftovers
from that removal that landed in the wrong field.)

**Fix:** drop each `ENT-###` out of `implements_requirements`.
Leave only FR/NFR ids in `implements_requirements`.

---

## Finding 5 — DATA-MODEL: `WorkUnit` entity unassigned to any bounded context  (coverage, high — blocks validation)

`docs/DATA-MODEL.yaml`:

```
bounded_contexts: entity 'WorkUnit' is not assigned to any context
```

Every entity must live in exactly one bounded context. `WorkUnit` (introduced by
the read-model split, changelog v2.22) was never assigned. **Fix:** add
`WorkUnit` to the appropriate `bounded_contexts` context (likely the read-model /
traceability context alongside the edge graph).

---

## Finding 6 — ARCH: edge + work-unit consistency slips  (consistency, high — blocks validation)

`docs/ARCH__aicf-cli.yaml`:

- `external_edges[8].via_unit='run_headless_install_test'` targets `to='build-sandbox'`
  (a **container**), but `via_unit` requires a `'<container_id>/<component_id>'`
  component-level target. **Fix:** point the edge at the specific component that
  exposes `run_headless_install_test`, or drop `via_unit` if the edge is
  genuinely container-level.
- `components[1]='schema-foundation'.work_units[0].touches_entities
  'StageRevisionEntry'` is not in that component's `traces_data_entities`.
  **Fix:** add `StageRevisionEntry` to `schema-foundation.traces_data_entities`
  (or correct the work-unit's `touches_entities` if it shouldn't touch it).
- Plus the malformed `WRN-006 (v1.11): …` from Finding 3.

---

## Finding 7 — PRD: `top_risks` are structured objects, not strings  (schema divergence, medium — blocks stock validator)

`docs/PRD.yaml`:

```
risks_assumptions.top_risks.0: Input should be a valid string
```

The demo PRD (changelog-driven, DATA-MODEL v2.17) retyped `top_risks` from
`list[str]` to a structured `RiskItem` (statement + disposition +
mitigation_refs). The **stock `sdlc-prd` schema** still expects
`top_risks: list[str]`, so the richer demo shape is rejected.

This is a genuine **fork** between the AICF meta-corpus (which intentionally
carries a richer risk model) and the shipped `sdlc-prd` skill. Two honest
resolutions:

- **If the demo should validate against the stock skill:** flatten each
  `RiskItem` back to a string (e.g. `"<statement> — <disposition>"`) in
  `docs/PRD.yaml`.
- **If the structured risk model is desirable in the product:** that's a
  *skill* enhancement (add an optional structured `RiskItem` shape to
  `prd/PRD.schema.yaml` + validator) — out of scope for a demo-content fix, but
  worth filing as a skill feature request. Until then the demo won't pass the
  stock PRD validator.

---

## Suggested order of work

1. **Findings 3, 4, 5, 6** — mechanical, unambiguous, and each unblocks a
   validator (`WRN` format, entity-family, bounded-context assignment, edge
   targets). Do these first.
2. **Finding 1** — reword + reclassify the persistence prose/roles.
3. **Finding 2** — a conscious confirm + a one-line note.
4. **Finding 7** — decide fork direction (flatten in demo, or file a skill
   feature request); don't silently drop the disposition data.

Re-run the five validators after each group; target exit 0 (or exit 0 with only
advisory warnings, e.g. the work-unit-coverage advisories, which never block).
```