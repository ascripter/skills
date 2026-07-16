# SPLAN5 — pipeline integrity + upstream skills + CLAUDE.md delta

Skills touched: **setup, prd, ux, data, api, design** + the D2 downstream loaders in
**ux/data/api/arch/task** + the repo **CLAUDE.md**. Findings: SK-01, SK-05, SK-29,
SK-30, SK-31, SK-32, SK-33, SK-34, SK-35 (+ api/design observations). Execute LAST
(its CLAUDE.md delta documents conventions SPLAN1–4 introduce; its loader re-scope
assumes SPLAN2's task-side changes landed).
Status: **open**. Line numbers = 0.3.6; re-locate at HEAD.

## Steps

### 1. SK-29/SK-01 — setup: upstream the proven index features

`docs_index.py` today emits `generated_from`/`sections`/`shards`/`symbols` only
(:687-736) and indexes symbols for just DATA-MODEL (entities/enums) + PRD
(FR/dossiers) + TASKS JSON (`_EXTRACTORS:456-459`). The AICF meta-repo's fork —
**porting source: AICF repo `src/aicf/ui/_docs_index.py`** (repo owner transfers the
file; it is stdlib-only like the original) — adds everything the corpus work leaned on
daily. Port, keeping `docs_index.py` stdlib-only, the `--hook` stdin protocol, and the
copy-into-consumer-project install model:

a. **Symbol families:** NFR/WKF/INT/AIF list items (PRD), SCR (UX surface inventory),
   OPR (API endpoints), AST (DESIGN assets), PRD `conventions.*` sub-blocks (kind
   `convention`, `context` = owning FR). Today's asymmetry (no NFR/SCR/OPR symbols)
   makes slice-addressed reading impossible for half the pipeline.
b. **`referenced_by` block** — the inbound cross-reference graph per defined id
   (which symbols/sections mention it). This is the blast-radius lookup every corpus
   edit began with ("reconcile every inbound site in the same pass").
c. **`dangling` block** — corpus-id references with no definition; `dangling: []` is
   the clean state. This is the pipeline's first end-to-end id-integrity gate (SK-01);
   it also retires PRD's "no dangling check" disclaimers (see step 3).
d. **`--check` mode** — re-derive and exit non-zero on any dangling reference
   (pre-commit/CI gate). The hook path stays non-blocking (prints a count).
e. **Retired-id allowlist** — a small in-file set (corpus precedent
   `_ALLOWLISTED_IDS = {FR-058}`) so deliberately-retired ids documented in a
   changelog don't surface as dangling; keep the set next to a comment naming the
   sync rule.
f. **`--refs <symbol>` / `--find <filters>` subcommands** (ports of the corpus
   `docs-refs` / `docs-find`): outbound + inbound refs for one symbol; predicate
   search over the symbol table (`--kind/--context/--file/--text/--references/
   --referenced-by`). Update `assets/sdlc-docs-access.md` to document the new blocks +
   commands, and each artifact skill's Phase-2/Phase-8 wording ("check the
   blast-radius via `--refs` before editing a symbol").
g. SK-30 cosmetics in the same pass: header claims matcher `Write|Edit` (:12,
   :664-666) but `wire_setup.py:48` installs `Write|Edit|MultiEdit` — fix the doc;
   fix the self-contradictory `_TSK_LINE_RE` comment (:468-469).
h. Re-running `/sdlc:setup` upgrades installed copies (existing model) — note in
   SKILL.md that consumers should re-run to get `--check`.

### 2. SK-31/SK-05 — prd: flat features (D2)

Blueprint: AICF DATA-MODEL v2.24 `ProductRequirements` (flat `features` +
`parking_lot`, no Milestones). FR ids are STABLE — this changes list shape, never ids.

a. `PRD.schema.yaml`: replace `functional_requirements.must_have_features` +
   `nice_to_have_features` (:172-177) with one `features` list (same `"FR-NNN: …"`
   item format, one continuous counter); delete the `milestones` block (:295-297) —
   its 1–3-sentence narrative folds into `product_vision`; keep `out_of_scope`/
   `integrations_required`/`ai_features` unchanged.
b. `validate_schema.py`: model (:232) + counter registry (`("FR",
   "functional_requirements.must_have_features", "product")` :538 and the sibling
   continuation table :515/:675) re-key to `features`; the ACR advisory (:705-714)
   re-scopes from must-have to ALL FRs. **Back-compat:** the model accepts the legacy
   two lists (parse-and-union into `features` order: must then nice) so old PRDs
   validate; new writes emit only `features`. Version-gate: at the new `prd_version`,
   emitting the legacy split warns.
c. `prd-questions.yaml` (:1288 lines) + `references/importance-flows.md`: the MVP-
   features critical theme becomes the features theme (same critical+synthesis
   machinery, same sweep); de-scoped ideas route to `open_questions.parking_lot`
   (SK-33 — the field already exists, :359-360; the interview just needs the routing
   sentence). Remove the milestones theme/questions; scan `conventions-catalog.md`
   for MVP phrasing.
d. `migrate_ids.py`: confirm no per-list assumptions (it renumbers ids; ids don't
   change here — expect no-op, but verify).

### 3. SK-32 — prd: `mitigation_refs` forward references — ⚠C OPEN

Evidence: "EXISTING cross-stage ids (FR-/NFR-/TST-/SIG-/QUE-…) … no dangling check"
(`PRD.schema.yaml:332-335`) — TST/SIG don't exist at PRD-write time; "EXISTING" is
unsatisfiable forward prose (defer-over-foreshadow: the AICF product spec deleted such
fields after audit, DATA-MODEL v2.19/v2.20).
Options:
- **(i) Restrict (recommended):** `mitigation_refs` admits same-stage/upstream ids
  only (FR/NFR/QUE); a mitigation realized by a later stage is simply the FR/NFR that
  demands it. Validator format-checks the prefixes.
- (ii) Keep cross-stage, but the new `--check` dangling gate (step 1) owns resolution
  once downstream artifacts exist — requires teaching the allowlist that
  PRD-mints-forward is legal-until-test-stage. More machinery for no added truth.

### 4. D2 downstream loader re-scope (all consumers)

Every must-have-keyed loader learns the tolerant read — `features` if present, else
union of the legacy two lists (helper shape is identical in each file; consider one
shared snippet per skill's conventions):
- ux `load_prd_must_have_fr_ids` (`validate_schema.py:827`) — rename to
  `load_prd_fr_ids`.
- data `load_prd_must_have_features` (:1446; coverage sites :1547/:1650) — coverage
  contract text updates from "every PRD must-have FR" to "every PRD FR" (the
  trace-or-defer escape stays and matters MORE now: process-FRs with no entity defer
  via WRN, `data/validate_schema.py:53`).
- api `load_prd_must_have_features` (:641, used :931) — same.
- arch `load_prd_must_have_features` (:1073, check #4 :2482/:2568) + the FR/NFR union
  readers (:1142, :2076) — same; check #4's name "PRD must-have FR coverage" →
  "PRD FR coverage".
- task: already shipped tolerant in SPLAN2 step 1c — verify only.
- test: its NFR/covers resolution reads the PRD catalogue — grep for the two list
  keys and align.
Schema-doc sweeps in each skill for "must-have"/"MVP" phrasing.

### 5. Small upstream items

- **SK-34 (ux):** one comment line on `UX__SURFACE.schema.yaml`'s `cli_args` block
  (:111-123) + `references/cli-ux.md`: *downstream task embeds this block verbatim as
  the handler task's `cli_contract`; keep it complete enough to code a parser from*
  (the task-side field lands in SPLAN2).
- **SK-35 (data) — ⚠D OPEN:** `paradigm` currently defaults to relational when absent
  (`DATA-MODEL.schema.yaml:145-146,169`). Recommendation: at the next
  `data_model_version`, `paradigm` is REQUIRED at `status: complete` (older versions
  keep the default + a warning). The silent-relational fallback is exactly what the
  original AICF DATA-MODEL had to be hand-rewritten to escape.
- **design/api:** one cross-pointer line each — design's "task derives one per-surface
  design task per surface_overrides entry" (`DESIGN.schema.yaml:229-235`) gains
  "(realized by task's design coverage check #15)"; api none-mode needs nothing.

### 6. CLAUDE.md delta

Apply `CLAUDE-MD-DELTA.md` (sibling file) to the repo-root CLAUDE.md: D2 rewordings
(flat features; the "MVP features in prd" critical-tier example; §6a's could-arm),
new conventions §9 (fix-upstream-over-warn), §10 (version-gate new blocking rules),
§11 (measurement rule), §12 (subject-wiring + shared-infra contract summary).

### 7. Fixtures + evals + versions

- prd `_smoke/` (10) + `evals/`: flat-features valid fixture; legacy-split fixture
  still passing (back-compat proof); milestones-present legacy fixture passing.
- setup: index golden test — run `docs_index.py` against a small docs fixture tree
  and assert the new blocks (`referenced_by`, `dangling: []`) + `--check` exit
  behavior (dangling injected → non-zero).
- ux/data/api/arch `_smoke/`: their PRD companion fixtures gain flat-features
  variants (e.g. `arch/_smoke/15_feature_coverage_fail/PRD.yaml`,
  `data/_smoke/10_feature_coverage_fail/PRD.yaml`,
  `api/_smoke/06_feature_coverage_fail/PRD.yaml` — keep a legacy copy each).
- Version bumps: prd + data artifact versions; setup has no artifact version — bump
  the plugin version + `docs_index.py` header.

## Verification / done when

- All touched `_smoke` fixtures exit as documented (legacy PRD shapes still pass
  everywhere).
- Setup golden: new INDEX blocks present; `--check` exits non-zero on an injected
  dangling ref, zero on clean; `--refs`/`--find` answer on the fixture tree.
- Live meta-corpus regression: point the ported `docs_index.py` at the AICF `docs/`
  and diff against its resident `INDEX.yaml` — symbol/`referenced_by`/`dangling`
  parity is the port's acceptance test (the AICF generator is the reference
  implementation).
- Grep the repo for `must_have_features` — remaining hits are back-compat readers and
  legacy fixtures only.

## Execution ledger

- [ ] 1 setup port (a–h) + docs-access asset update
- [ ] 2 prd flat features (schema/validator/questions/flows)
- [ ] 3 ⚠C resolved: ___ (recommendation: restrict)
- [ ] 4 downstream loaders re-scoped (ux/data/api/arch/+task verify/+test grep)
- [ ] 5 small items (ux line · ⚠D resolved: ___ · design/api lines)
- [ ] 6 CLAUDE.md delta applied
- [ ] 7 fixtures/evals/versions · verification green
