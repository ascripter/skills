# SPLAN3 — arch work-unit contract quality

Skills touched: **arch** only. Findings: SK-21, SK-22, SK-23, SK-24. Corpus lineage:
**F2/F11** (the contract-free cluster PLAN2 hand-authored 214 contracts for), the
**294-error traces class** (PLAN4 sign-off repair — its second occurrence; the first
was ARCH v1.15).
Status: **open**. Line numbers = 0.3.6; re-locate at HEAD.

## Steps

### 1. SK-21 — quality bar on #23 (empty-contract loophole)

Today `check_work_unit_contracts` (`validate_schema.py:1800-1880`) blocks only ABSENT
contract fields; explicit empties satisfy DECLARE by design (:1813-1818: "`inputs: []`,
`raises: []`, `output: \"None\"` … what fails is the field being ABSENT"). That design
is right for single units (legitimately-trivial callables exist) but has no defence
against an emitter stamping empties on EVERYTHING.

a. New **advisory** (never blocks; no version gate needed): per component, when ≥80%
   of its callable DECLARE units have the all-empty contract
   (`inputs: []` + `output` in {"None", None-like} + `raises: []`), emit one warning —
   "component '<id>': N/M callable units declare empty contracts — likely an emitter
   filling the shape, not deciding interfaces; verify or add family contracts."
   Per-component (not per-unit) keeps noise bounded and targets the actual failure
   mode (blanket-stamping), not the trivial callable.
b. `signature` stays unchecked and optional (deliberate — the corpus decision PLAN2-D1
   authored contracts without signature fields; the schema calls it "verbatim only
   when the signature IS the contract"). Document that in the #23 docstring so a
   future pass doesn't "fix" it.
c. SKILL.md :640-645 (item 9b) gains one sentence: "Explicit empties are for
   genuinely-trivial callables — an emitter that stamps empties across a component
   will trip the emptiness advisory."

### 2. SK-22 — derive component traces_data_entities from unit touches (the 294-error class)

Every rule today is a subset CHECK (`touches_entities ⊆ component.traces_data_entities`
— #21 :1591; schema :348/:584); nothing derives. Twice now (ARCH v1.15, PLAN4) a
touches-completion pass broke the subset law corpus-wide and was repaired by completing
the component list to the union.

a. **Write-time rule** (SKILL.md Phase 7 + `merge-validate.md`): before writing a
   container file, set every component's `traces_data_entities` to
   `sorted(existing ∪ union of its units' touches_entities)` — the curated list may
   EXCEED the union (entities the component reads without a unit naming them) but
   never lag it. State it as invariant: *the subset law is maintained by derivation,
   not by hand.*
b. Validator: the #21 subset-violation error message gains the fix hint —
   "complete the component's traces_data_entities to the union of its units'
   touches_entities (see Phase 7 derive rule)". Also handle the missing-key case
   explicitly (corpus: cli-command-surface had NO `traces_data_entities` key at all —
   the error should say "add the key", not just "not a subset").

### 3. SK-23 — teach the family-contract + aggregator patterns

The schema/validator already know `work_unit_family_contracts`
(`validate_schema.py:681`; #23 FAMILY arm :1823-1827) — guidance doesn't.

a. New reference section (in `component-discovery.md` or a new
   `references/work-unit-contracts.md`, pointed at from SKILL.md 9b):
   - **When to fold units into a family:** ≥3 units sharing one shape
     (per-stage bodies, per-clause gates, per-command handlers) → declare ONE
     `work_unit_family_contracts` entry (family name + member selector + shared
     inputs/output/raises) instead of N copies. Members may omit their own contract
     fields (the #23 FAMILY arm). Corpus scale-proof: 112 of 214 units rode 16
     families.
   - **Aggregator/dispatcher contract pattern** (PLAN2-D3): a unit that dispatches
     over sibling units (a `run_stage_quality_gate`, a command router) declares its
     **dispatch inventory in its contract inputs** (the list of callees it fans out
     to) and NEVER takes graph self-edges; the inventory is the contract, the edges
     stay lean (granularity invariant (b) on the task side).
b. The schema comment :678-680 currently frames the block as "meta-corpus dialect …
   Absent for a generated app." Soften to: an optional pattern ANY project with
   uniform unit families may use (the dialect merely required it first) — otherwise
   the FAMILY arm is dead code for generated apps while the emptiness advisory (step
   1) pushes emitters toward exactly this mechanism.

### 4. SK-24 — prose/naming alignment (no field renames)

- `references/test-discovery.md:125` calls the flat bundle "its `interface_contract`
  (inputs/output/raises)" — rename the prose to "its interface contract fields"
  (the nested `interface_contract:` block exists only on the downstream Task embed).
- Add one mapping line to `ARCH__CONTAINER.schema.yaml`'s WorkUnit comment: downstream
  task embeds `summary` as `unit_summary` and the four flat fields as
  `interface_contract{...}` — so cross-repo greps stop confusing the two shapes.

### 5. Fixtures + evals + versions

- `_smoke/`: + fixture with a component of blanket-empty contracts → expect the new
  advisory (exit 0, warning present); + fixture with unit touches ⊄ component traces
  and one with the key missing → error text carries the fix hint; + valid fixture
  using `work_unit_family_contracts` outside meta-mode.
- `evals/`: extend the grader for the emptiness advisory if the eval set asserts on
  warnings.
- Bump `arch_version`/`arch_container_version` docs; SKILL.md 9b/9c touch-ups.

## Verification / done when

- `_smoke` exits as documented (advisories don't flip exit codes).
- Live meta-corpus regression: arch validator on the AICF corpus stays **exit 0 with
  the existing 25-advisory baseline** (its components' traces were completed by PLAN4;
  its contracts are real, so the emptiness advisory must NOT fire — that's the
  true-negative proof). **Measurement rule: capture the exit code bare, never after a
  pipe** — this exact validator false-greened for a full corpus plan cycle.

## Execution ledger

- [ ] 1 emptiness advisory + docstring + SKILL.md sentence
- [ ] 2 derive-at-write rule + error fix-hints (incl. missing-key case)
- [ ] 3 family/aggregator reference + schema comment soften
- [ ] 4 prose alignment
- [ ] 5 fixtures/evals/versions · verification green (bare exit codes)
