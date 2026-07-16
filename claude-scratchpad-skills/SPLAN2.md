# SPLAN2 — task schema & validator repairs (incl. D2 priority removal)

Skills touched: **task** only. Findings: SK-02 (task half), SK-03, SK-12, SK-13, SK-14,
SK-15, SK-17, SK-18, SK-19, SK-20. Corpus lineage: **K1, K5, K6b, K7, K8**, **F10,
F14b, F4**, mech G2. Execute FIRST (it deletes/rewrites regions SPLAN1 lands next to).
Status: **open**. Line numbers = 0.3.6; re-locate at HEAD.

## Steps

### 1. D2 — remove the priority machinery (SK-12)

The paradigm is retired pipeline-wide (decision D2, 2026-07-16: every consumer is
built whole by `/sdlc:code`; no phased MVP slice exists downstream). The AICF corpus
already runs uniform inert `"priority": "must"` awaiting this removal (PLAN1-D1).

a. `validate_schema.py`: delete `priority` from the required-field loops (system :839,
   container :857); delete `_PRIORITY_RANK` (:1142), `_priority_str` (:1145),
   `check_priority_monotonic` (:1151-1208) and its call site + schema-doc entry
   (cross-check #22 — renumber or tombstone the number, don't reuse it); keep
   `ContainerTask.priority`/`SystemTask.priority` (:264/:282) as parsed-but-ignored
   **deprecated** fields (convention: removals stay accepted on old artifacts).
b. Deferral symmetry (#23, :1537-1578): the impl-side escape "is the task
   `priority: could`" (:1565-1567) becomes deferral-only — an impl task whose test was
   deferred TEST-side must itself be deferred in `task_warnings` (or the test
   restored). Update the warning text (:1571-1578) to drop the "Mark this task
   post-MVP (priority: could)" arm.
c. Coverage scope: `FR_MUST` (:422-441) and the union gap report (:1698-1729) re-scope
   to **all** PRD FRs. NOTE the loader must tolerate both PRD shapes — flat `features`
   (post-SPLAN5) and legacy `must_have_features`+`nice_to_have_features` (union them);
   ship the tolerant reader HERE so plan order doesn't matter.
d. `TASKS__CONTAINER.schema.yaml`: drop the `priority` row (:330) + every "MVP exit
   gate" phrase; `TASKS.schema.yaml` likewise.
e. `references/granularity-and-ordering.md`: delete invariant **(a)**
   priority-monotonic (:82-87); rewrite **(b)**/**(c)** (:88-97) without the priority
   vocabulary — they survive as "an aggregator depends only on the predecessors it
   actually consumes" and "an integration/bake task depends on the SET of tasks it
   exercises, never on the last-scheduled tail as a proxy" (both were violated by the
   corpus and remain correct independent of priorities).
f. `task-questions.yaml` (:520 lines): remove/replace the priority question(s);
   `count_work_units.py` / `crosscheck_artifacts.py`: grep `priority` and clean.
g. Migration note (schema header): `priority` deprecated at this artifact version;
   never required again; validators must not warn about its presence on old
   artifacts.

### 2. K8 — declare the dialect embed fields; fix the extra-policy (SK-13, SK-02)

a. Models gain typed Optional fields (+ `ConfigDict(extra="allow",
   str_strip_whitespace=True)` on ALL task models — today they declare none, so
   Pydantic v2 silently DROPS unknown keys; every other skill uses `extra="allow"`):
   - `ContainerTask.cli_contract: Optional[Dict[str, Any]]` — verbatim UX
     `UX__<cmd-surface>.yaml` slice (cli_invocation + cli_args + exit codes) for CLI
     handler tasks. Source seam: SK-34.
   - `ContainerTask.family_contract: Optional[Dict[str, Any]]` — the resolved
     `work_unit_family_contracts` entry (family + shared contract) the unit inherits;
     mirror of arch's declared block (`arch/validate_schema.py:681`).
   - `ContainerTask.fixture_briefs: Optional[List[Dict[str, Any]]]` (scaffold/infra
     tasks) — per-fixture briefs.
   - `SystemTask.touches_entities: Optional[List[str]]` (:269-284 lacks it; corpus
     system tests carry it since PLAN3-F19).
b. `TASKS__CONTAINER.schema.yaml`: document all four as WRITE-TIME COPIES (same
   framing as the existing embed comment :243-246 — "deep-validating a copy would
   over-validate; the #20 drift advisory catches divergence").
c. Check #20 (embedded-copy drift): add a `family_contract` arm — compare against the
   current ARCH `work_unit_family_contracts` entry when present (advisory, like the
   interface_contract arm). `cli_contract` drift vs UX is optional/deferred (UX shards
   are per-surface files; cheap once loaded — implement if low-effort, else note).

### 3. K5 — `inputs[]` fate (SK-14) — ⚠B OPEN

Evidence: schema calls it "the upstream artifacts / contracts / files this task
consumes" (`TASKS__CONTAINER.schema.yaml:298-300`) but NOTHING resolves it — not the
validator, not `topo_order.py --emit` (:305), not the code-skill ladder. It masquerades
as a delivery channel (root cause behind the corpus F12/F13/F18/F19 expectations).
Options:
- **(i) Drop (recommended):** deprecate in schema (parse-and-ignore), remove from
  generation guidance; the v1.4 self-contained-task principle (embeds ON the task)
  already replaced the channel. One honest mechanism instead of two half-mechanisms.
- (ii) Resolve: make `topo_order.py --emit` inline each anchor's slice into the
  packet. Real cost: anchor grammar (`FILE#symbol`), INDEX dependency, packet bloat —
  and it duplicates the embeds.
On (i): also delete the `inputs` examples from `task-discovery.md`/SKILL.md.

### 4. F10 — schema-module → consumer edges (SK-15)

a. Generation rule (`granularity-and-ordering.md`, new subsection after :74): when a
   container has module-kind work units that OWN entity/schema definitions, build an
   entity→owning-module map (each entity is owned by the module task that creates its
   definition file — when several modules re-export it, the EARLIEST module in the
   file ladder owns it; corpus rule PLAN3-D1, applied as `entity_ownership.json`
   316/316). Then: every impl/integration task naming entity E in `touches_entities`
   gains `depends_on` E's owning module task (skip self). Module→module edges follow
   the same ladder (acyclic by construction).
b. New advisory (version-gated): a module-kind implementation task with **zero
   dependents** inside its own file — "schema/module task no consumer depends on;
   schema-before-consumer is holding by id order, not by edge" (corpus: 24 of 26
   schema modules had zero dependents; PLAN4 added 265 edges).
   Implementation hint: module-kind = `unit_kind` in
   `{module}` or target_symbol resolving to a work_unit with `kind: module`.

### 5. K6b/F4 — target_files cardinality + directory pins (SK-17)

a. Document the **directory-pin convention** in `TASKS__CONTAINER.schema.yaml`
   (:301-316 block): a multi-file deliverable (module scaffold, config set, test
   infra) pins its common DIRECTORY as the single `target_files` entry and enumerates
   the file set in `description` + `acceptance` ("all N files exist: …"). Corpus
   precedent: PLAN3-D2/PLAN4 TSK-414.
b. New advisory: `kind: implementation` whose `description` contains ≥2 distinct
   backticked repo-relative paths while `target_files[0]` names a FILE (not a
   directory) — "description enumerates multiple files but the task pins one file —
   multi-file unit? use a directory pin". (Backtick-path extraction already has a
   precedent in the PRD→arch #25 seam — see `prd/PRD.schema.yaml:165-170`.)

### 6. F14b — integration callee deps (SK-18)

`granularity-and-ordering.md` :73 gains: "an integration task also `depends_on` the
impl task of every work_unit its description/`outputs` NAMES as a callee — naming a
callable you don't depend on is a scheduling lie." Optional advisory (only if cheap):
integration task whose description names a `target_symbol` present in the same file
whose task is not in `depends_on` (substring match on known symbols; corpus instance:
TSK-219/220 named record_call_cost / write_artifact / rebuild_read_model without the
edges).

### 7. K1 — validator↔scheduler contract (SK-19, SK-03)

Post-D2 sweep: enumerate the remaining BLOCKING graph rules in `validate_schema.py`
(dep resolution, union acyclicity, …) and assert `topo_order.py` enforces the same set
(it does dep resolution + cycles; after #22's deletion the known divergence is gone).
Add to both module docstrings: "these two tools must agree on what makes a graph
schedulable; a new blocking graph rule lands in BOTH or is version-gated" + the
version-gating convention (SK-03, precedent `TASKS__CONTAINER.schema.yaml:160-161`).

### 8. G2 — acceptance quality guidance (SK-20)

One paragraph in `task-discovery.md`: acceptance criteria must be task-specific and
machine-checkable; N tasks sharing an identical acceptance line is a generation smell
(corpus: 148 boilerplate lines). No validator check.

### 9. Fixtures + evals + versions

- `_smoke/`: priority fields removed from valid fixtures (and one legacy fixture KEPT
  carrying priority → must still validate, proving parse-and-ignore); + broken pairs
  for: zero-dependent module advisory, multi-path/single-file advisory, missing
  family_contract drift arm.
- `evals/` (`_gold/`, `selftest.py`): strip priority from gold artifacts; extend
  selftest for the new fields.
- Bump the TASKS artifact versions (this plan defines the "next version" all new
  gates key on) + SKILL.md phase outline touch-ups.

## Verification / done when

- All `_smoke` fixtures exit as documented; legacy-priority fixture still passes.
- `crosscheck_artifacts.py` + `count_work_units.py` grep-clean of priority.
- Live meta-corpus regression: task validator exit 0 on the AICF corpus (its inert
  uniform `"priority": "must"` now simply ignored — afterwards the corpus can drop
  the field entirely, closing the K7 loop); advisory count change explained (the
  known 191+8 placement advisories remain until SPLAN1).
- `topo_order.py --scope all` still schedules the corpus; `--emit` round-trip shows
  `cli_contract`/`family_contract`/`fixture_briefs`/system `touches_entities`
  surviving a model round-trip (K8 closed).

## Execution ledger

- [ ] 1 D2 removal (validator/schema/references/questions/helpers)
- [ ] 2 K8 fields + extra="allow" + #20 family arm
- [ ] 3 ⚠B resolved: ___ (recommendation: drop)
- [ ] 4 F10 rule + zero-dependent advisory
- [ ] 5 directory-pin doc + cardinality advisory
- [ ] 6 F14b guidance (+advisory if cheap)
- [ ] 7 K1 contract sweep + docstrings
- [ ] 8 acceptance guidance
- [ ] 9 fixtures/evals/versions · verification green
