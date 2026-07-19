# SPLAN1 — test→subject seam + shared test infrastructure

Skills touched: **test**, **task**. Findings: SK-06, SK-07, SK-08, SK-09, SK-10 (note),
SK-11, SK-16. Corpus lineage: **F21** (the audit BLOCKER), **F22**, **F23(ii-edge)(iv)**,
the 191+8 placement-advisory baseline.
Status: **EXECUTED 2026-07-19** (see execution ledger; deviations recorded there
and in the reconciliation note below).

> **Reconciliation note (2026-07-19, pre-execution re-baseline against the refreshed
> AICF corpus):**
> - **Corpus versions are self-stamped above the stock schemas** — TEST-STRATEGY
>   system 1.6, `__aicf-cli` **1.9** (191 tests; 163 unit-tier; ZERO
>   `targets_work_unit` fields), `__build-sandbox` 1.3; TASKS containers 1.8/1.9.
>   Step 1b's gate "next test_strategy_container_version" (= 1.3 stock) would
>   hard-fail the corpus with ~163 errors. **Redesigned gate: blocking at
>   version >= 2.0 AND `meta_corpus_dialect` false** (dialect keeps
>   covers∩implements as its coverage mechanism — SK-10/step 1e); below 2.0 or in
>   dialect mode the rule is a warning. See overview convention #3 amendment.
> - **The stock test validator currently FAILS the corpus** — exit 1 with exactly
>   224 missing-`priority` errors (the corpus deleted per-TST priority at its
>   v1.8, PLAN1-D1) + 222 work-unit-coverage advisories. Step 3c (D2 test-side)
>   flips the corpus baseline **red → green**; verification below updated.
> - **Step 5b's four cross-checks land as UNGATED warnings** (convention #3:
>   warn-level needs no version gate; a "next tasks_container_version" gate = 1.6
>   would be already-open on the 1.8/1.9 corpus anyway). All four are no-ops on
>   the corpus: no `targets_work_units`, no `test_infrastructure` kind (its
>   TSK-414 is `kind: implementation` with `target_files: ["tests/"]`), no
>   `gating:` fields, and the scaffolds already carry the cross-file edge
>   (`depends_on: ["TASKS/TSK-001"]`, PLAN4-repaired).
> - **Placement collapse mechanics (step 5c):** the corpus's 199 advisories =
>   191 `kind: test` (targets under `tests/`) + **8 `kind: integration`** whose
>   targets legitimately sit in ANOTHER component's `code_location` (seam files,
>   e.g. TSK-215→`src/aicf/core/graphs/pipeline.py`). The test root fixes the
>   191; the 8 need the integration kind to accept the union of ALL components'
>   code_locations.
> - SPLAN2 took `tasks_container_version` 1.5; the task side of this plan adds no
>   new blocking gate, so 1.5 stays (the new kind is additive vocabulary).

## Why (the one-paragraph story)

The code skill pairs each impl task with "the test task(s) whose `depends_on` reaches
it" so they heal together in one worker (`code/references/execution-loop.md:42-45`), and
the task skill's own guidance mandates that edge ("a `test` task `depends_on` the
`implementation` task whose code it exercises",
`task/references/granularity-and-ordering.md:72`). But the only machine-readable subject
signal — `ContainerTest.targets_work_unit` — is Optional and advisory
(`test/validate_schema.py:227,643-651`), and no task cross-check verifies the edge. Net
result in the AICF corpus: all 191 test tasks were wired to a per-component absorber,
validated green, and needed a 191-row hand-reviewed rewire map (PLAN4). Meanwhile the
strategy's `mock_policy`/`fixture_strategy` (required prose,
`TEST-STRATEGY.schema.yaml:75-80`) name shared deliverables (mock helper, factories,
conftest) that no task ever builds — the corpus hand-authored TSK-414 for that. This
plan makes the subject seam and the infra owner structural.

## Steps

### 1. test — subject seam becomes require-or-defer (SK-06)

`TEST-STRATEGY__CONTAINER.schema.yaml` + `validate_schema.py`:

a. Widen the field to multi-subject: `targets_work_units: list[str]` (accept legacy
   singular `targets_work_unit: str` as an alias — parse both, warn on the singular at
   new versions). **Multi-subject is real, not hypothetical:** the corpus's 18
   "Stage NN gate — exit + entry adequacy" tests each verify TWO units
   (run_stage_quality_gate + run_input_adequacy_gate) — PLAN4's map rule R1.
b. New blocking rule, **version-gated on the next `test_strategy_container_version`**:
   at `status: complete`, every `tier: unit` test must either set
   `targets_work_units` (each name resolving within `component_ref`'s
   `work_units[].name` — the existing #11 resolution logic, :643-651) **or** be
   covered by a `WRN-NNN` deferral naming the tst_id (trace-or-defer, CLAUDE.md §6).
   Integration/e2e/contract tiers: optional (they target seams, not single units), but
   validated when present. Old artifact versions: warn only.
c. System tests (`TEST-STRATEGY.schema.yaml:104-125`) stay subject-free
   (`involves_containers` is their grain) — document that explicitly in the schema
   comment so nobody "fixes" it.
d. Generation flow: `references/test-discovery.md` already seeds "one `unit` test per
   component `work_units[]` entry" (:118-121) — add one sentence: *the seeded test
   carries `targets_work_units: [<that unit>]` from birth; a hand-added test names its
   subject(s) or defers.* Interview: the existing question
   (`test-questions.yaml:720`) becomes required-with-defer for unit-tier tests.
e. SK-10 note: in meta-corpus dialect mode, covers∩implements remains the *coverage*
   mechanism, but `targets_work_units` is the *wiring* signal in both modes.

### 2. test — structured non-gating flag (SK-07, F23(iv))

a. Schema + model: `gating: Optional[bool] = None` on system + container tests
   (`None`/`true` ⇒ gating; `false` ⇒ excluded from the default suite). Optional
   sibling `non_gating_marker: Optional[str]` (default `eval_nongating`).
b. Validator (warn-level): a `gating: false` test whose `directives` don't mention the
   marker gets a reminder warning; a `gating: false` test at `tier: unit` is suspicious
   (evals are usually e2e/llm) — warn.
c. Consumption contract (document in schema comment + `coverage-and-defer.md`): the
   task skill emits, for each `gating: false` TST, an apply-the-marker directive in the
   test task, and the **system scaffold task owns** marker registration + `addopts`
   exclusion in the repo-root test config (pytest:
   `[tool.pytest.ini_options] markers` + `addopts = -m "not <marker>"`); the conftest
   registers nothing. (Corpus worked example: PLAN4-D3 — system TSK-001 + 10 task
   directives + 10 TST directives.)

### 3. test — structured shared test infrastructure (SK-08, F22)

a. Schema + model, system level (container may override, inherit-if-null like
   mock_policy): 

   ```yaml
   shared_infrastructure:            # OPTIONAL list — the shared deliverables the
     - path: tests/conftest.py      #   mock_policy/fixture_strategy imply. Each:
       purpose: <string>            #   REQUIRED — what it provides
       realizes: [mock_policy]      #   REQUIRED — mock_policy | fixture_strategy |
                                    #     test_data_strategy (≥1)
       contents_hint: <string>      #   OPTIONAL — for the codegen worker
   ```
b. Validator: type-check + `realizes` enum; **advisory at complete when
   `mock_policy` mentions mock/stub/fake or `fixture_strategy` mentions
   fixture/factory AND `shared_infrastructure` is empty** — "policy with no named
   deliverable; downstream workers will each reinvent it" (the F22 lesson verbatim).
c. Remove the per-TST `priority` field in the same edit pass (D2 test-side —
   `TEST-STRATEGY.schema.yaml:122`, `ContainerTest.priority`
   `validate_schema.py:235`, required-field loops that include it): accepted-but-
   ignored on old versions, absent from new schema.

### 4. test — placement convention (SK-09)

a. Schema, system level: `test_file_convention: Optional[str]` — a path template,
   default documented as `tests/<container>/<component_snake>/test_<tst_id_snake>.py`
   (one file per TST; the corpus-blessed PLAN1-D3 layout). Container file may
   override.
b. This is a *convention carrier*, not a per-TST path field — task derives each test
   task's `target_files[0]` from it; test's validator only type-checks.

### 5. task — consume the seam (SK-11, SK-16, F23(ii-edge))

a. **Generation rules** (`references/granularity-and-ordering.md` + SKILL.md pointer):
   - a `kind: test` task's `depends_on` = the impl task(s) whose `target_symbol` ∈ its
     TST's `targets_work_units`, **plus the container's test-infrastructure task**
     (below). The absorber/tail pattern is already banned by invariants (b)/(c) —
     cross-reference them.
   - when TEST-STRATEGY carries `shared_infrastructure`, emit ONE
     test-infrastructure task per container: `target_files` = the common directory pin
     (e.g. `["tests/"]`), description embeds the mock_policy + fixture_strategy texts
     **verbatim** (both levels: system + container override) and enumerates the file
     set; `depends_on` = the container scaffold + every schema/module-kind impl task
     (factories construct every artifact type — corpus worked example TSK-414: deps =
     scaffold + all 26 schema modules, giving every test transitive schema reach);
     every `kind: test` task depends on it.
   - test task `target_files` derived from `test_file_convention` (step 4).

   ⚠A RESOLVED (owner, 2026-07-19): **(i) new task kind `test_infrastructure`** —
   exempt from check #4's target_symbol⊆work_unit pin, allowed a directory
   `target_files`; honest kind, clean exemption, mirrors how `scaffold` is already
   special-cased. (Rejected: (ii) reuse `kind: config` — dishonest semantics; (iii)
   arch re-touch — pipeline-order-unclean, arch runs before test defines the
   deliverables.)
b. **New cross-checks** (warn-level, version-gated on next `tasks_container_version`):
   - **test-subject reachability:** for each `kind: test` task with
     `implements_tests: [TST-x]` where TST-x carries `targets_work_units`, warn when
     `depends_on` (direct) misses an impl task whose `target_symbol` matches a listed
     unit. (Direct, not transitive — the code skill's worker pairing reads direct
     deps.)
   - **infra wiring:** when a test-infrastructure task exists, warn per `kind: test`
     task not depending on it.
   - **scaffold cross-file edge:** when the system `TASKS.json` is present, warn when
     a container scaffold doesn't `depends_on` the system scaffold
     (`TASKS/TSK-NNN`) — enforcement of existing guidance
     (`granularity-and-ordering.md:69-71`; corpus drift F23(ii-edge)).
   - **eval-marker ownership:** for each `gating: false` TST, warn when its test task
     lacks the marker directive or no scaffold task's description/acceptance mentions
     marker registration + exclusion.
c. **Placement check learns the test root** (SK-09): in the check-16 block
   (`validate_schema.py:1426-1437`), `kind: test` (and the infra task) validate
   `target_files` against the `test_file_convention` root (default `tests/`) instead
   of the component's `code_location`. Expected corpus effect: the 191+8 known
   placement advisories collapse to 0.

### 6. Fixtures + evals

- test `_smoke/`: + valid fixture using `targets_work_units`/`gating:false`/
  `shared_infrastructure`/`test_file_convention`; + broken pair (unit-tier test with
  neither subject nor deferral at complete → exit 1 at the new version; same file at
  the old version → warning only).
- task `_smoke/` (+ `evals/_gold` where affected): + fixture with a
  test-infrastructure task and a mis-wired test (deps = absorber) → expect the
  reachability warning; scaffold missing the cross-file edge → warning.
- Update both skills' SKILL.md phase outlines + schema headers; bump both artifact
  versions (this plan defines the "next version" the gates key on).

## Verification / done when

- Both validators: all `_smoke` fixtures produce their header-documented exit codes.
- Live meta-corpus regression (AICF repo beside): test + task validators exit 0;
  placement advisories 199 → ~0; the new warn-checks fire ONLY as warnings on the
  0.x-era corpus (version-gated); no new errors.
- The code skill's wave-pairing prerequisite is now checkable: a fresh
  `topo_order.py --emit` on any corpus test task shows its true subject(s) in
  `depends_on` (already true post-PLAN4; the point is the validator now notices when
  it isn't).

## Execution ledger

- [x] 1 test subject seam · plural `targets_work_units` + singular alias (warns at
      >= 2.0); check 12 require-or-defer BLOCKS at >= 2.0, WARNS below.
      **Deviation:** in `meta_corpus_dialect` mode check 12 is SILENT (not
      advisory) — the per-unit work-unit-coverage advisory (check 11, 222 corpus
      warnings) already carries the wiring signal; a per-test twin would restate
      it 163×. Discovery seed + question updated to plural require-or-defer.
- [x] 2 test gating flag · `gating`/`non_gating_marker` on both test shapes; two
      warn-advisories; consumption contract in schema comment +
      `coverage-and-defer.md` ("Non-gating tests: the marker contract").
- [x] 3 shared_infrastructure (system + container override) + emptiness advisory
      + item-shape check; D2 per-TST priority removal — **corpus test validator
      flipped exit 1 (224 missing-priority errors) → exit 0**; new
      `global_policy` interview questions for both new fields.
- [x] 4 test_file_convention carrier (system + container override; type-check
      only) · both test schemas bumped to **2.0**.
- [x] 5 task consumption · new `kind: test_infrastructure` (⚠A) in
      CONTAINER_KINDS + FILE_PRODUCING_KINDS, scaffold-like exemptions,
      schedules cleanly through topo_order; checks #27/#28/#29/#30 as **ungated
      warnings** (deviation from the "version-gated" parenthetical — see
      reconciliation note); placement advisory kind-aware (test root for
      test/test_infrastructure, any-component union for integration) — **corpus
      placement advisories 199 → 0 (task warnings 207 → 8)**;
      `tasks_container_version` stays 1.5; generation rules in
      `granularity-and-ordering.md` + `task-discovery.md` + SKILL.md kind table.
- [x] 6 fixtures/evals · test `_smoke/10_seam_v2_block` (exit 1) +
      `11_v2_valid` (exit 0, multi-subject + legacy-alias warn + gating:false +
      shared_infrastructure); fixture 05 (v1.0) doubles as the sub-2.0
      warn-only proof; task `_smoke/10_test_wiring` fires all five #27-#30
      warnings at exit 0; test evals: prompt canaries + S13 flipped to
      no-priority, new C29 seam assertion; gold `TEST-STRATEGY__backend-api`
      migrated to 2.0 (priority stripped, plural subjects) and **TST ids
      renumbered 006-013 — pre-existing defect: the gold's 001-008 collided
      with the staged system file's 001-005 under the global-uniqueness gate**
      (grader self-test combo now exit 0). Verification: 11 test + 9 task
      smoke fixtures at documented codes (bare $?); task evals SELFTEST PASS;
      corpus test exit 0 (225 warnings = 222 work-unit-coverage + 3 true-positive
      shared-infra), corpus task exit 0 (8 known warnings); topo_order
      --scope all exit 0 + --emit packet unchanged.
      (`work_units_style_selftest.py` still fails on its ARCH fixture-19 arm —
      pre-existing, owned by SPLAN3 step 6; task-side arms pass.)
