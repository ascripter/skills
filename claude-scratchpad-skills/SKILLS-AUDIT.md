# SKILLS-AUDIT — sdlc plugin skills, audited at 0.3.6 (2026-07-16)

**Immutable evidence document — the SPLANs cite it; do not edit it.**

Method: every finding below was surfaced by *consuming the skills' outputs at scale* —
the AICF meta-corpus (414 + 19 + 28 tasks, 214 work units, 224 tests) was driven to
/sdlc:code-READY through a coding-readiness audit (findings F1–F23, skill-handoff items
K1–K8) and four executed fix plans. Each finding's file:line evidence was then
**re-verified first-hand against the 0.3.6 skill sources** (plugin cache). Line numbers
are 0.3.6; re-locate against skills-repo HEAD before editing.

Severity scale:
- **blocker-class** — produced (or would reproduce) a run-stopping defect downstream.
- **defect** — wrong or contradictory behavior in the skill/validator itself.
- **gap** — a missing rule/field/check that forced manual downstream repair.
- **observation** — healthy or accepted; recorded so future audits don't re-derive it.

Corpus-episode shorthand: `F-NN` = corpus audit finding (AICF
`claude-scratchpad/AUDIT-FINDINGS.md`), `K-N` = original skill-handoff item, `PLANn` =
the corpus fix plan that repaired the downstream damage by hand.

---

## Cross-cutting

### SK-01 — no id-integrity / dangling-reference gate exists anywhere in the pipeline · gap
**Evidence:** `setup/docs_index.py` emits exactly four blocks — `generated_from`,
`sections`, `shards`, `symbols` (`render_index_yaml`, :687-736); grep for
`--check|dangling|referenced_by|allowlist` over the file returns nothing. PRD schema
explicitly disclaims it: mitigation_refs are "References, not a new id family — no
dangling check" (`prd/PRD.schema.yaml:335`). Per-skill validators check only the refs
they load directly; no tool answers "what references X?" or "does every referenced id
exist?" corpus-wide.
**Corpus episode:** AICF had to build its own generator (`referenced_by` graph,
`dangling` block, `--check` non-zero exit, retired-id allowlist, `docs-refs`/`docs-find`
CLIs) because corpus maintenance was impossible without blast-radius lookup and dangling
detection — e.g. a bulk field-strip corrupted 133 `SCR` definition lines and only the
dangling check caught it; every PLAN's edit protocol began with `docs-refs <symbol>`.
**Direction:** SPLAN5 (upstream the proven features into `setup/docs_index.py`).

### SK-02 — unknown-field policy is inconsistent and silent everywhere · defect
**Evidence:** every skill's validator uses `ConfigDict(extra="allow")` (prd :197, ux
:184, design :134, data :433, api :179, arch :294) **except task**, whose models declare
no ConfigDict at all (grep: zero hits) → Pydantic v2 default `extra="ignore"`. So the
same unknown key is silently *retained* in six skills and silently *dropped* by the
seventh; no skill ever flags it.
**Corpus episode:** K8 — the meta-corpus dialect embed fields (`cli_contract`,
`family_contract`, `fixture_briefs`) ride the TASKS files as validator-invisible
payload; a task-model round-trip loses them. Also the root of "typo'd field name
validates green" risk pipeline-wide.
**Direction:** SPLAN2 (task: declare the fields + `extra="allow"`); SPLAN5 (optional
unknown-key lint note).

### SK-03 — version-gating of new blocking rules is practiced ad hoc, not stated · gap
**Evidence:** the task skill gates correctly in one place — `interface_contract` is
"REQUIRED for kind:implementation at artifact version >= 1.3 (older artifacts warn
instead)" (`task/TASKS__CONTAINER.schema.yaml:160-161`) — but the priority-monotonic
gate (task `validate_schema.py:1151-1208`, blocking) and arch #23 (blocking) shipped
ungated.
**Corpus episode:** K1 — 0.3.6 hard-failed artifacts stamped complete by 0.3.4 (17
priority-monotonic errors; 112 arch #23 errors discovered mid-PLAN2), while 0.3.6's own
`topo_order.py` scheduled the same graph without complaint.
**Direction:** SPLAN2 (reconcile) + CLAUDE-MD-DELTA (state the convention: new blocking
checks are version-gated on the artifact's declared version; new checks on existing
fields start as warnings).

### SK-04 — no measurement rule for exit codes; verification can false-green · gap
**Evidence:** `code/references/execution-loop.md` verification rings (:61-63, :76-106)
leave the exit-code capture mechanism implicit; nothing anywhere warns that
`cmd | tail; echo $?` reports the pipe's exit.
**Corpus episode:** the AICF arch-validator run was false-green from PLAN3 to PLAN4's
sign-off because the exit code was read after a pipe — masking 294 real cross-check-21
errors for a full plan cycle.
**Direction:** SPLAN4 (execution-loop rule: run gate commands bare, capture the exit
code directly, record it in the ledger) + CLAUDE-MD-DELTA.

### SK-05 — priority paradigm retired PIPELINE-WIDE (decision D2, 2026-07-16) · decision
**Rationale:** every consumer of this skillset is built whole by `/sdlc:code` — AI
builds the entire graph at once, so an economic must/should/could split has no
downstream consumer; it only feeds the machinery that produced K1's incoherence.
Blueprint: the AICF product spec made the same move for generated apps (DATA-MODEL
v2.24: single flat `features`, `parking_lot`, Milestones deleted, TestSpec.priority
removed), and the AICF corpus already runs priority-free (PLAN1-D1: uniform inert
`"must"` awaiting this very removal).
**Verified blast radius (0.3.6):**
- prd: `must_have_features`/`nice_to_have_features` (`PRD.schema.yaml:172-177`; model
  `validate_schema.py:232`; counter registry :538 + :675; ACR advisory scoped to
  must-have :705-714), `milestones.mvp_scope`/`phases` (`PRD.schema.yaml:295-297`).
- ux: `load_prd_must_have_fr_ids` (`validate_schema.py:827`).
- data: `load_prd_must_have_features` (`validate_schema.py:1446`; coverage :1547,
  :1650).
- api: `load_prd_must_have_features` (`validate_schema.py:641`, used :931).
- arch: `load_prd_must_have_features` (`validate_schema.py:1073`, check #4 :2482,
  :2568; FR/NFR union reader :1142 + :2076 also parses both lists).
- test: per-TST `priority: must|should|could` REQUIRED
  (`TEST-STRATEGY.schema.yaml:122`; `ContainerTest.priority` `validate_schema.py:235`).
- task: `priority` REQUIRED (`validate_schema.py:839/857`), `_PRIORITY_RANK` +
  monotonic blocking gate (:1142, :1151-1208), deferral-symmetry could-arm (:1566),
  `FR_MUST` coverage scope (:422-441, :1698-1729), granularity invariants (a)–(c)
  written around the MVP slice (`references/granularity-and-ordering.md:77-97`).
**Direction:** SPLAN2 (task + test mechanics), SPLAN5 (prd schema + all downstream
must-have-keyed loaders re-scope to the flat `features` list).

---

## test skill

### SK-06 — the TST→subject seam is optional, so tests can't be wired deterministically · blocker-class
**Evidence:** `ContainerTest.targets_work_unit: Optional[str]`
(`test/validate_schema.py:227`), resolution-checked only when set (:643-651, check #11
"never blocks" on the coverage half, `TEST-STRATEGY__CONTAINER.schema.yaml:174-182`).
System tests have no subject field at all (`TEST-STRATEGY.schema.yaml:104-125`:
`covers` + `involves_containers` only). The interview question exists
(`test-questions.yaml:720`) but nothing requires an answer.
**Why it's blocker-class downstream:** `code`'s wave composition *depends* on the
test→impl edge — "a work unit is one implementation task plus the test task(s) whose
`depends_on` reaches it (impl + its tests heal together, so they share a worker)"
(`code/references/execution-loop.md:42-45`). Without a subject signal, `task` wired all
191 corpus tests to a per-component absorber task (F21, the audit's BLOCKER): tests
never pair with their impl, the test-first heal loop breaks, and the repair needed a
191-row hand-reviewed map (PLAN4, `f21_map.json`) built from token-overlap heuristics +
an FR-join — exactly the deterministic signal `targets_work_unit` should have carried.
**Direction:** SPLAN1 (require-or-defer at `status: complete` for unit-tier container
tests, version-gated; task consumes it; validator check on the task side — SK-11).

### SK-07 — non-gating / eval-class tests exist only as prose · defect
**Evidence:** no boolean/enum marks a test non-gating: `tier` enum is
`unit|integration|e2e|contract|property|load|security|accessibility`, `priority` is
importance (and dies with SK-05). The corpus's 10 real-LLM eval tests were identifiable
ONLY by a "NON-GATING" line inside `directives[]`.
**Corpus episode:** F23(iv)/PLAN4-D3 — a marker convention (`eval_nongating`
registration + `addopts` exclusion in the repo-root pyproject, directive on each test)
had to be hand-authored across 10 TSTs + 10 tasks + the system scaffold; patching only
the tasks first produced 10 check-20 drift advisories (fix-upstream-over-warn lesson).
**Direction:** SPLAN1 (structured field, e.g. `gating: bool` or
`execution_class: gating | non_gating_eval`, + the marker/pyproject ownership
convention emitted by task).

### SK-08 — mock_policy / fixture_strategy declare policy nothing realizes · gap
**Evidence:** both are REQUIRED prose strings at system level
(`TEST-STRATEGY.schema.yaml:75-80`), optional inherit-if-null at container level
(`__CONTAINER:68-69`). No structured field names the *deliverables* (conftest,
factories, mock helper), and no downstream rule builds them (SK-16).
**Corpus episode:** F22 — ~180 isolated codegen workers would each have reinvented the
injected-BaseChatModel mock and per-schema factories; PLAN4 hand-authored TSK-414
(`build_test_infrastructure`) embedding both policy levels verbatim, wired as a dep of
all 191 + 25 tests. "Referential integrity ≠ content completeness": a policy with no
owner task is a no-carrier-field artifact class.
**Direction:** SPLAN1 (structured `shared_infrastructure` block: files + purpose +
policy refs; task realizes it as a per-container infra task every test depends on).

### SK-09 — no test-file placement convention anywhere in the test skill · gap
**Evidence:** no TST field carries a file path; no placement rule exists in test
SKILL.md/references (grain guidance only: "one unit test per work unit",
`test-discovery.md:118-121`). Downstream, task's placement advisory expects
`target_files ⊆ component.code_location` (`task/validate_schema.py:1426-1437`) — which
test files structurally violate (they live under `tests/`, not the component's `src/`).
**Corpus episode:** PLAN1-D3 blessed one-file-per-TST placement
(`tests/aicf/<component>/test_tst_cli_<nnn>.py`); the corpus then carries **191 + 8
permanent placement advisories** as known noise because the check has no test-root
concept.
**Direction:** SPLAN1 (test owns the placement convention; task's check 16 learns a
test-root: `kind: test` tasks validate against `tests/` instead of component
code_location).

### SK-10 — meta-corpus dialect is baked in; two subject grains coexist · observation
**Evidence:** `meta_corpus_dialect: Optional[bool]` (`test/validate_schema.py:210`),
`_TST_SHARDED_RE` (:265), covers∩implements coverage arm (:600-606, :671, :692). Note
`load_meta_corpus_dialect` (named in AICF notes) does not exist as a function — the
flag is read inline (:797).
**Point to converge:** the dialect's covers-based coverage and the stock
`targets_work_unit` grain are two different subject signals; SK-06's fix should make
`targets_work_unit` the primary in both modes (covers stays the requirement trace).
**Direction:** SPLAN1 (note only).

---

## task skill

### SK-11 — true-subject test wiring is guidance-only; validator accepts absorber wiring · blocker-class (enforcement gap)
**Evidence:** "a `test` task `depends_on` the `implementation` task whose code it
exercises" (`references/granularity-and-ordering.md:72`); invariant (c) explicitly
bans depending on the tail as a proxy (:93-97); invariant (b) bans absorber fan-in
(:88-92). **No cross-check verifies any of it** — #8 checks resolution+acyclicity only;
nothing compares a test task's deps against its TST's subject
(`implements_tests` → TST → `targets_work_unit`/`component_ref`).
**Corpus episode:** F21 + K6 — all 191 corpus test tasks violated the written guidance
(each depended on one per-component absorber) and validated **green**; scaffold→system
cross-file edge guidance (:69-71) was likewise present-but-unenforced (F23 ii-edge:
the corpus scaffolds lacked the edge until PLAN4).
**Direction:** SPLAN1 (new cross-check, warn-level + version-gated: a `kind: test`
task's `depends_on` must reach a task whose `target_symbol` matches the TST's
`targets_work_unit` — plus the scaffold cross-file edge check).

### SK-12 — priority machinery (dies with D2) · defect (by decision)
**Evidence:** SK-05 blast-radius list, task rows.
**Corpus episode:** K7 + K1's concrete instance (the monotonic gate produced 17 errors
against a graph topo_order scheduled fine).
**Direction:** SPLAN2 (remove field + loops + gate; rework #23's could-arm to
deferral-only; rewrite granularity invariants (a)–(c)).

### SK-13 — dialect embed fields are undeclared task-side and get dropped · defect
**Evidence:** `cli_contract`, `family_contract`, `fixture_briefs` appear nowhere in
`task/validate_schema.py` / `TASKS__CONTAINER.schema.yaml`; with default
`extra="ignore"` (SK-02) a model round-trip silently drops them. `SystemTask`
(:269-284) also lacks `touches_entities` — which the corpus system tests carry
(PLAN3-F19). Contrast: arch already **declares** its dialect block
(`work_unit_family_contracts`, `arch/validate_schema.py:681`) with a documented #23
FAMILY arm (:1823-1827) — the pipeline's two dialect carriers are asymmetric.
**Corpus episode:** K8 — the fields ride today as validator-ignored payload; a full
`/sdlc:task` regeneration would silently lose the PLAN3 enrichment (16 cli_contracts,
112 family stamps, 6 fixture briefs, 9 system touches).
**Direction:** SPLAN2 (declare all four as typed Optional fields + schema.yaml docs +
drift coverage in check #20 where an upstream source exists).

### SK-14 — `inputs[]` is decorative: masquerades as a channel, resolved by nothing · defect
**Evidence:** schema says "OPTIONAL but encouraged — the upstream artifacts /
contracts / files this task consumes" (`TASKS__CONTAINER.schema.yaml:298-300`); model
field `validate_schema.py:259/278`. No cross-check reads it; `topo_order.py --emit`
joins only `implements`/`implements_workflows` (:305); the code-skill ladder uses
`target_files`/`outputs`, never `inputs`.
**Corpus episode:** K5 — the doc-anchors looked like a delivery channel and were the
root cause behind F12/F13/F18/F19 expectations ("the worker will follow the anchor"),
none of which any consumer implements. PLAN3 replaced the channel with structured
embeds.
**Direction:** SPLAN2 ⚠ (resolve-into-packets vs deprecate-and-drop; recommendation:
drop — the v1.4 self-contained-task principle already replaced it).

### SK-15 — no schema-module → consumer dependency rule · gap
**Evidence:** `touches_entities` is copied + subset-validated only
(`TASKS__CONTAINER.schema.yaml:251-258`; entity coverage #13). Dependency edges come
from ARCH `calls`/`depends_on` edges (`granularity-and-ordering.md:74`) — data-shape
dependencies generate no edges.
**Corpus episode:** F10 — 24 of 26 schema-module tasks had ZERO dependents; schema
landed before consumers only by tsk-id tie-break. PLAN4 derived 265 edges from an
entity→owning-module map (`entity_ownership.json`, earliest-ladder rule).
**Direction:** SPLAN2 (generation rule: a task naming entity E in `touches_entities`
depends on E's owning schema/module task; + advisory check "zero-dependent module
task").

### SK-16 — no shared test-infrastructure task concept · gap
**Evidence:** grep across `task/` for conftest/factories/shared-fixture: nothing;
`granularity-and-ordering.md:53` mandates one-task-per-TST but names no infra owner.
**Corpus episode:** F22 (see SK-08 — this is its task-side half; PLAN4's TSK-414 is
the worked example: deps = scaffold + all schema-module tasks, every test depends on
it, both policy texts embedded verbatim).
**Direction:** SPLAN1 (paired with SK-08).

### SK-17 — target_files cardinality vs multi-file reality; directory-pin convention unwritten · gap
**Evidence:** exactly-one `target_files` enforced for `kind: implementation`
(`validate_schema.py:866-872`); nothing cross-references the `description` (a
description enumerating several files with one target_files entry is not flagged); the
directory-pin escape (`target_files: ["tests/"]` + enumerated file set in description)
is a corpus invention (PLAN3-D2/PLAN4) documented nowhere in the skill.
**Corpus episode:** F4 + K6b — multi-file units (module scaffolds, config sets) forced
either a validator-illegal list or an undocumented pin.
**Direction:** SPLAN2 (document the directory-pin convention in schema + task-discovery;
advisory: implementation task whose description names ≥2 backticked paths while
target_files pins one file).

### SK-18 — integration tasks' named callees don't become deps · gap
**Evidence:** guidance covers the two *components* an integration task wires
(`granularity-and-ordering.md:73`) but not the callee units its description names.
**Corpus episode:** F14b — corpus integration tasks named callees (record_call_cost,
write_artifact, rebuild_read_model) they didn't depend on; PLAN4 added the edges.
**Direction:** SPLAN2 (generation guidance + optional advisory).

### SK-19 — validator and scheduler disagree about the same artifact · defect
**Evidence:** `validate_schema.py` hard-fails graphs `topo_order.py` schedules without
complaint (K1's original statement); the priority instance dies with D2, but the two
tools share no contract about which rules gate scheduling.
**Direction:** SPLAN2 (post-D2 sweep: assert the remaining blocking graph rules —
resolution, acyclicity — are exactly the rules topo_order enforces; document the
contract in both files' docstrings).

### SK-20 — acceptance-criteria boilerplate · observation/minor
**Evidence:** `acceptance` REQUIRED non-empty (`TASKS__CONTAINER.schema.yaml:327-329`);
no quality guidance beyond "machine-checkable".
**Corpus episode:** mech G2 — 148 tasks carried near-identical boilerplate acceptance
lines; the corpus fix appended task-specific lines rather than replacing.
**Direction:** SPLAN2 (one guidance paragraph; no check).

---

## arch skill

### SK-21 — #23 lets explicitly-empty contracts satisfy `complete`; no quality bar · defect
**Evidence:** DECLARE accepts explicit empties — "`inputs: []`, `raises: []`,
`output: \"None\"` … what fails is the field being ABSENT" (`validate_schema.py:
1813-1818`, enforcement :1854-1864); `signature` never checked; SKILL.md teaches the
same (:640-645). So an emitter can stamp `inputs: [] / output: "None" / raises: []` on
every unit and ship a contract-free container that validates complete.
**Corpus episode:** F2/F11 — the pre-PLAN2 corpus had 112 units with ABSENT contracts
(0.3.6 #23 correctly erred on those — but only once PLAN4 fixed the exit-code
measurement, SK-04); PLAN2 then authored real per-unit contracts + family contracts.
The *empties* loophole remains open.
**Direction:** SPLAN3 (advisory at complete: a callable DECLARE unit whose three
fields are ALL empty/None-equivalent is flagged for review — advisory, not blocking,
since legitimately-trivial callables exist).

### SK-22 — component traces_data_entities is authored, not derived; subset law breaks corpus-wide on touch-completion · defect
**Evidence:** every `touches_entities` rule is a subset check
(#21, `validate_schema.py:1591`; schema :348, :584); no instruction anywhere derives a
component's `traces_data_entities` from the union of its units' `touches_entities` at
write time.
**Corpus episode:** the 294-error class — PLAN3's per-unit touches completion broke
`unit.touches ⊆ component.traces` on 294 pairs (masked by SK-04's false green);
PLAN4 repaired by completing 17 components to the union (one component,
cli-command-surface, lacked the key entirely). Same repair had already happened once
before (ARCH v1.15) — a recurring class, not an incident.
**Direction:** SPLAN3 (write-time rule in SKILL.md Phase 7: derive-or-verify the union;
validator error message gains the "complete to the union of unit touches" fix hint).

### SK-23 — family contracts + aggregator dispatch pattern are schema-known but untaught · gap
**Evidence:** `work_unit_family_contracts` declared (`validate_schema.py:681`) with the
#23 FAMILY arm (:1823-1827) — but SKILL.md's contract instruction (:640-645) never
mentions authoring a family, and the PLAN2-D3 aggregator pattern (a dispatch/aggregator
unit declares its callee **inventory** in its contract inputs, with NO self-edges) is
documented nowhere.
**Corpus episode:** PLAN2 invented both while authoring 214 contracts; K8's arch half
turned out to be already-declared (this audit) — the residual is guidance.
**Direction:** SPLAN3 (SKILL.md + a reference section: when to fold units into a
family, how an aggregator's contract lists its dispatch inventory).

### SK-24 — naming seams across the arch→task boundary · observation/minor
**Evidence:** ARCH's field is `summary` (`WorkUnit`, `validate_schema.py:527`); task
renames it `unit_summary` at embed time (`TASKS__CONTAINER.schema.yaml:157`); arch has
NO `interface_contract` field yet its own reference prose uses that name for the flat
bundle (`test-discovery.md:125`), which only exists as a nested block on the Task.
**Direction:** SPLAN3 (align prose; do not rename fields).

---

## code skill

### SK-25 — test-task packets ship no requirement grounding; ACR unresolvable · defect
**Evidence:** `emit_packets` joins `implements` + `implements_workflows` only
(`topo_order.py:305`); test tasks carry their FRs in `test_spec.covers` (and TST ids in
`implements_tests`) — neither is read. `_REQ_RE` matches only `FR|NFR|WKF` (:66), so
ACR ids can never resolve even where joined.
**Corpus episode:** K2 — all 224 corpus test-task packets ship an empty
`requirement_context` despite SKILL.md's "the worker has its FR/NFR grounding
in-packet".
**Direction:** SPLAN4 (also resolve `test_spec.covers`; add ACR to the regex + PRD
acceptance-criteria lines to `load_requirements`).

### SK-26 — the worker brief omits the per-kind rendering rules; the only entity-shape channel is outside it · defect
**Evidence:** the brief includes "the provenance-marker and path-safety rules from
`emit-rules.md`" (`execution-loop.md:55-57`; same in SKILL.md:225-228) — but the
touches_entities→"read their INDEX slices" instruction lives in emit-rules'
implementation-rendering Body §4 (`emit-rules.md:94-96`), which the brief does NOT
include. Workers get entity *names* with no instruction to fetch their shapes.
**Corpus episode:** K3 — F3/F5 degrade from "worker fetches the slice" to "worker
invents the shape" for any worker whose brief-builder followed the letter of
execution-loop.
**Direction:** SPLAN4 (make the per-kind rendering rules an explicit brief component —
restructure emit-rules so the brief-included digest carries them).

### SK-27 — wave disjointness is exact-overlap prose; directory pins collide silently · gap
**Evidence:** "The units' combined `target_files` (+ test files) must be pairwise
disjoint" (`execution-loop.md:45-48`) — no path-aware containment rule anywhere in the
code skill; the only prefix-aware helper in the plugin
(`_path_within_any`, `task/validate_schema.py:403`) belongs to a different check.
**Corpus episode:** F9 (accepted, protocol-handled) + the PLAN3-D2/PLAN4 directory-pin
convention: `target_files: ["tests/"]` (TSK-414) vs 191 test files under `tests/…` —
literal set-overlap says disjoint; actual writes collide.
**Direction:** SPLAN4 (rule: a directory entry contains every path beneath it;
when a pin overlaps, serialize or solo).

### SK-28 — INDEX assumed at the consumer root · observation
**Evidence:** emit-rules' fetch instruction presumes `docs/INDEX.yaml` where the worker
runs; fine for a project that ran `setup`, wrong for factory-side generation layouts.
**Corpus episode:** K4 (observation only; FR-098's read-model is the product answer).
**Direction:** SPLAN4 (one documentation line; no behavior change).

---

## setup skill

### SK-29 — the index is a location map only; the pipeline's shared navigation lacks integrity + coverage features · gap
**Evidence:** four blocks only (`render_index_yaml`, `docs_index.py:687-736`); symbol
extractors registered solely for DATA-MODEL (entities/enums) + PRD (FR/dossiers)
(`_EXTRACTORS:456-459`) + TASKS JSON scan — **no NFR/WKF/SCR/OPR/AST symbols**, no
conventions sub-blocks; no referenced_by, no dangling, no `--check`, no allowlist
(SK-01's mechanism half).
**Corpus episode:** AICF's fork (`src/aicf/ui/_docs_index.py` + `docs-refs`/`docs-find`)
implements all of the above and every corpus plan leaned on it (blast-radius protocol,
`docs-index --check` as the post-edit gate, `_ALLOWLISTED_IDS` for retired FR-058).
**Direction:** SPLAN5 (feature-port; the AICF file is the reference implementation —
the repo owner carries it over).

### SK-30 — docstring/comment drift in docs_index.py / wire_setup.py · observation/minor
**Evidence:** header says the hook matcher is `Write|Edit` (:12, :664-666) while
`HOOK_MATCHER` installs `Write|Edit|MultiEdit` (`wire_setup.py:48`); `_TSK_LINE_RE`
comment contradicts itself (:468-469, "key this field `tsk_id` … do not look for
`tsk_id`").
**Direction:** SPLAN5 (cosmetic fixes alongside the port).

---

## prd skill

### SK-31 — flat-features mechanics (executes SK-05/D2 in prd) · decision-execution
**Evidence:** split lists + continuous counter (`PRD.schema.yaml:172-177`), milestones
(:295-297), ACR advisory keyed to must-have (:705-714 in validator), counter registry
rows (:538, :675), and every downstream loader in SK-05's list parses
`functional_requirements.must_have_features`.
**Shape after D2 (blueprint = AICF DATA-MODEL v2.24):** single
`functional_requirements.features` (FR-NNN, one counter — unchanged ids), delete
`milestones` (its narrative moves to `product_vision`), ACR advisory re-scopes to all
FRs, downstream loaders read `features` (+ back-compat: accept the old two lists and
union them, version-gated).
**Direction:** SPLAN5.

### SK-32 — RiskItem.mitigation_refs sanctions forward references to unminted ids · defect
**Evidence:** "`mitigation_refs: [...]` — EXISTING cross-stage ids (FR-/NFR-/TST-/SIG-/
QUE-…) … no dangling check" (`PRD.schema.yaml:332-335`) — TST/SIG ids do not exist at
PRD-write time, so "EXISTING" is unsatisfiable forward prose.
**Corpus episode:** the defer-over-foreshadow principle (AICF DATA-MODEL v2.19/v2.20
corpus-wide sweep): a field naming a not-yet-created downstream id is unresolvable in
the forward pipeline and duplicates what the owning stage derives — such fields were
deleted from the product spec after audit.
**Direction:** SPLAN5 ⚠ (restrict to same-stage/upstream ids (FR/NFR/QUE) — OR keep
cross-stage but make SK-29's dangling gate own it; recommendation: restrict).

### SK-33 — parking_lot already exists and fits the D2 blueprint · observation
**Evidence:** `open_questions.parking_lot: list[OpenQuestionItem]`, shared QUE counter
(`PRD.schema.yaml:359-360`). The v2.24 blueprint's "excluded feature ideas land in a
parking lot" is satisfied; D2 only needs the interview to route de-scoped feature ideas
here (no new field).

---

## ux / data / api / design

### SK-34 — ux: CLI command contracts are structured and are the cli_contract source · observation
**Evidence:** `CLIArg` (`UX__SURFACE.schema.yaml:111-123`), `cli_invocation` (:81-83),
global `cli.exit_codes` with per-code `implements_requirements`
(`UX.schema.yaml:303-333`).
**Corpus episode:** F12 — PLAN3's `cli_contract` embeds were verbatim UX-shard slices;
the seam works, it just needs the task-side field (SK-13) and a pointer in ux docs that
task embeds from here.
**Direction:** SPLAN5 (one documentation line) + SPLAN2 (the field).

### SK-35 — data: paradigm support healthy; absent paradigm defaults to relational · observation/minor
**Evidence:** six paradigms with per-paradigm required-block matrix
(`DATA-MODEL.schema.yaml:148-166`); "Absence of `paradigm` defaults to `relational`"
(:145-146, :169).
**Risk:** for a file-native/CLI project, a forgotten `paradigm` silently re-imposes the
SQL-flavored expectations the paradigm work removed (the original AICF DATA-MODEL v1
was hand-rewritten for exactly this).
**Direction:** SPLAN5 (require `paradigm` at `status: complete` for new artifact
versions; version-gated).

### api / design — no defects found · observation
api: `none` mode is coherent (kind enum + required rationale + coverage skips,
`API.schema.yaml:148-155`). design: outputs/gates coherent; the "task derives one
per-surface design task per surface_overrides entry" contract
(`DESIGN.schema.yaml:229-235`) is convention-prose the task skill honors via its design
coverage check #15 — worth one cross-pointer line (SPLAN5), nothing more.

---

## Traceability matrix

| Handoff / corpus finding | Audit finding | Plan |
|---|---|---|
| K1 validator↔scheduler incoherence | SK-19 (+ SK-03 convention, SK-12 instance) | SPLAN2 |
| K2 test packets no grounding | SK-25 | SPLAN4 |
| K3 worker-brief digest underspecified | SK-26 | SPLAN4 |
| K4 INDEX-at-root assumption | SK-28 | SPLAN4 |
| K5 inputs[] decorative | SK-14 | SPLAN2 ⚠ |
| K6 validator misses F21-/F4-class | SK-11 + SK-17 | SPLAN1 + SPLAN2 |
| K7 remove Priority from task | SK-12 (subsumed by SK-05/D2) | SPLAN2 |
| K8 dialect embed fields dropped | SK-13 (arch half already declared — SK-23 residual is guidance) | SPLAN2 (+SPLAN3) |
| F2/F11 empty work-unit contracts | SK-21 (+ SK-23) | SPLAN3 |
| F3/F5 entity shapes not reaching workers | SK-26 (+ task v1.4 embeds already exist) | SPLAN4 |
| F4 target_files cardinality | SK-17 | SPLAN2 |
| F9 shared-file accretion | SK-27 | SPLAN4 |
| F10 schema modules zero-dependent | SK-15 | SPLAN2 |
| F12 CLI contracts | SK-34 + SK-13 | SPLAN2/5 |
| F13/F17/F18/F19 packet embeds/carriers | SK-13 + SK-14 (+ SK-08 for F17) | SPLAN1/2 |
| F14b integration callees | SK-18 | SPLAN2 |
| F21 absorber test wiring (BLOCKER) | SK-06 + SK-11 | SPLAN1 |
| F22 shared test infra | SK-08 + SK-16 | SPLAN1 |
| F23(ii-edge) scaffold cross-file edge | SK-11 (enforcement of existing guidance) | SPLAN1 |
| F23(iv) eval marker | SK-07 | SPLAN1 |
| PLAN4 sign-off: 294 subset errors | SK-22 | SPLAN3 |
| PLAN4 sign-off: false-green exit codes | SK-04 | SPLAN4 + delta |
| Placement advisory baseline (191+8) | SK-09 | SPLAN1 |
| mech G2 boilerplate acceptance | SK-20 | SPLAN2 |
| PLAN1-D1 priority retirement | SK-05 + SK-12 + SK-31 | SPLAN2 + SPLAN5 |

**Excluded (no skill-side root cause):** F1 (corpus artifact state), F6/F7/F15/F16/F20
(meta-repo-specific: repo strategy, tests-layout rule, version stamps), F8 (corpus
content quality), F23(i)/(ii-content)/(iii) (corpus content edits). F23(iii)'s class
(reachability test depending on all handlers) is generation quality, partially covered
by SK-18's guidance.
