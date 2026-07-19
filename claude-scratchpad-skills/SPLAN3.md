# SPLAN3 — arch work-unit contract quality

Skills touched: **arch** only. Findings: SK-21, SK-22, SK-23, SK-24. Corpus lineage:
**F2/F11** (the contract-free cluster PLAN2 hand-authored 214 contracts for), the
**294-error traces class** (PLAN4 sign-off repair — its second occurrence; the first
was ARCH v1.15).
Status: **EXECUTED 2026-07-19** (see ledger; deviations noted per step).
Line numbers = 0.3.6; re-locate at HEAD.

> **Execution reconciliation (2026-07-19):** three findings reshaped the steps.
> (i) The **missing-key case is live in the corpus** — `build-test-entrypoint`
> (`ARCH__build-sandbox.yaml`, self-stamped 1.8) has units touching 2 entities and
> no `traces_data_entities` key; step 2b's "error" as written would have flipped
> the corpus exit 0 -> 1, so it landed as an **ungated warning** (convention #3;
> corpus 25 -> 26 advisories, true positive). (ii) Step 3a's "zero hits" claim was
> stale: Gap-1/2/5/6 authoring guidance already lives in `component-discovery.md`
> (:308-320, :322-329, :230-231) and `edge-derivation.md` (:78-121) — only the
> family fold heuristic and the aggregator/dispatcher pattern were missing, and
> they went into `component-discovery.md` (no new reference file). (iii) The
> emptiness advisory gained a **>= 3 callable-DECLARE-units floor** (a 1-unit
> trivial `main()` would fire at 100%; Gap-2 already covers singletons). Corpus
> scan proved it a clean true-negative (zero all-empty units).

> **Reconciliation note (2026-07-19, see README addendum):** the repo HEAD already carries
> the Gap-1/2/5/6 implementations (schema + validator + fixtures) this plan was authored
> blind to — `entrypoint` WorkUnit kind + single-file advisory (Gap-1), the no-code
> policy-unit advisory at `validate_schema.py:1690` (Gap-2), the `via_unit`/`invocation`
> seam + cross-check #27 (Gap-5), and the templated-code_location arm of #20 (Gap-6).
> Cited SK-21/SK-23 line numbers have shifted accordingly. Steps below are annotated;
> the *authoring guidance* for all four gaps is new scope in step 3.

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
   **Reconciliation:** HEAD already has a *per-unit* advisory for the single no-code
   policy unit (Gap-2, `validate_schema.py:1690-1711` — "model it as a security_concern
   + test, not a work_unit"). The new per-component advisory is COMPLEMENTARY (Gap-2 =
   one policy unit; this = an emitter blanket-stamping empties) — land it beside Gap-2,
   don't duplicate or replace it.
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
   - **Gap authoring guidance (new scope, 2026-07-19):** the validator half of
     Gap-1/2/5/6 exists at HEAD but NOTHING teaches the arch agent at authoring time
     (SKILL.md/references grep: zero hits) — the same reference doc carries four
     authoring rules so the advisories stop firing post-hoc:
     * **Entrypoint composition root (Gap-1):** when a component's `code_location` is
       ONE executable file with >1 run-mode branch (CLI/shell archetypes), emit an
       explicit `kind: entrypoint` work_unit owning arg/mode dispatch + step-sequencing
       + setup/teardown — the per-branch units never own the file's control flow.
       Relation to the aggregator pattern above: the entrypoint IS the typical
       dispatcher; its contract lists the branch inventory in inputs.
     * **No policy-only units (Gap-2):** a constraint enforced purely externally
       (platform/runtime/deploy) is a `security_concern` (+ mitigation) and/or
       acceptance criterion covered by a test — never a work_unit (it becomes a
       codegen task with nothing to emit).
     * **Pin the cross-container calls seam (Gap-5):** a cross-container `calls`
       external edge points `via_unit` at the callee's `entrypoint` work_unit (which
       pins argv/mode IN ⇄ exit-code/stdout/stderr OUT for both sides) and records
       the caller-side binding in `invocation` — authoring only the consumer side
       leaves the INPUT contract unpinned (cross-check #27 warns).
     * **Bind template placeholders (Gap-6):** a `code_location` containing
       `<placeholder>` tokens binds the concrete variant being built; further
       variants are their own components/work_units (or a WRN deferral) — codegen
       must not re-derive the binding.
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
  **Reconciliation:** `_smoke/23_entrypoint_valid` and `_smoke/24_seam_and_gaps`
  already exist (Gap-1/2/5/6 coverage) — extend them where they fit, don't recreate.
- `evals/`: extend the grader for the emptiness advisory if the eval set asserts on
  warnings.
- Bump `arch_version`/`arch_container_version` docs; SKILL.md 9b/9c touch-ups.

### 6. Pre-existing fixture defect surfaced 2026-07-19 (fix in this plan)

`sdlc/skills/task/_smoke/work_units_style_selftest.py` FAILS at HEAD on its
"valid mixed-style container passes" arm: the arch validator's #23
DEFER-OR-DECLARE check now errors on
`arch/_smoke/19_work_units_mixed_style/ARCH__api.yaml` (4 errors of the form
"work_units[...]='createTask' traces no schema-bearing contract (no
traces_api_operation) but leaves ['inputs','output','raises'] absent") — the
fixture predates a #23 hardening and no longer satisfies the check it is
supposed to prove green. Repair the fixture (declare the missing contract
fields or add traces_api_operation) as part of this plan's fixture pass, and
re-run the task-side selftest as the cross-skill proof.

## Verification / done when

- `_smoke` exits as documented (advisories don't flip exit codes).
- Live meta-corpus regression: arch validator on the AICF corpus stays **exit 0 with
  the existing 25-advisory baseline** (its components' traces were completed by PLAN4;
  its contracts are real, so the emptiness advisory must NOT fire — that's the
  true-negative proof). **Measurement rule: capture the exit code bare, never after a
  pipe** — this exact validator false-greened for a full corpus plan cycle.

## Execution ledger

- [x] 1 emptiness advisory + docstring + SKILL.md sentence — per-component
      roll-up in #23 with a **>= 3 callable DECLARE units** floor + >= 80%
      all-empty ratio; docstring documents the advisory AND that `signature`
      is deliberately unchecked (PLAN2-D1); SKILL.md 9b sentence + schema #23
      comment. Corpus: 0 hits (true-negative proven by scan).
- [x] 2 derive-at-write rule + error fix-hints — new "Derive component traces
      from unit touches" section in `merge-validate.md` + Phase 7 bullet in
      SKILL.md + schema #21 note; subset error carries the fix-hint;
      missing-key case landed as **ungated WARNING** (DEVIATION from "error" —
      the corpus itself trips it; convention #3). Fires once on the corpus
      (build-test-entrypoint, true positive) -> 26 advisories total.
- [x] 3 family/aggregator guidance + soften — fold heuristic (>= 3 same-shape
      units -> one family; 112/214-on-16-families scale proof) + PLAN2-D3
      aggregator/dispatcher pattern (dispatch inventory in contract inputs,
      never self-edges) added to `component-discovery.md` "Deriving
      work_units" (**no new reference file** — sibling guidance lives there);
      "meta-corpus dialect only" softened in 5 sites (schema x2, validator
      module docstring + model docstring, discovery bullet). Gap-1/2/5/6
      authoring guidance verified ALREADY TAUGHT at HEAD (step 3a's "zero
      hits" was stale) — not re-added.
- [x] 4 prose alignment — `test-discovery.md:125` now says "interface contract
      fields (the flat inputs/output/raises …)"; WorkUnit schema comment
      carries the downstream mapping (kind -> unit_kind, summary ->
      unit_summary, flat fields -> nested interface_contract{...}).
- [x] 5 fixtures/versions · verification green — NEW `_smoke/25_contract_quality/`
      (exit 0; exactly 5 documented warnings: SK-21 roll-up + 3x Gap-2 +
      SK-22 missing-key); `ARCH__CONTAINER.schema.yaml` 1.2 -> 1.3 +
      changelog; SKILL.md changelog + skill_version 1.3; warning-bucket
      labels genericized (they now carry Gap/derive/emptiness advisories, not
      just waivers); NO grader change (grade.py asserts artifact WRN format
      only — verified). All 28 arch fixtures at documented exit codes (bare $?).
- [x] 6 fixture 19 repaired — all 4 units DECLARE contracts, mixed block/flow
      styles preserved (flow entries carry contracts inline; "- name:" grep
      count stays 2 < 4 so the undercount proof holds); fixture 21 header
      cite "17/19/20" -> "17/20 (+19 passes)"; task-side
      `work_units_style_selftest.py` -> **SELFTEST PASS** (incl. the
      previously-failing "valid mixed-style passes [OK]" arm).

**Post-execution baselines:** arch validator on the corpus: exit 0,
**26 advisories** (was 25; +1 = the SK-22 missing-key true positive on
build-test-entrypoint); emptiness advisory absent (true-negative). Selftest
PASS. Fixture sweep: 28/28 at documented codes.
