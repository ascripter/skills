# Coverage & defer — the trace-or-defer contract (sdlc-test)

This is the heart of what makes a `test` artifact trustworthy: **nothing the
upstream declared important goes silently untested.** Every gated item is
either covered by a `TST-NNN` test or explicitly, reviewably deferred. Read
this when closing each suite in Phase 6 and at Phase 7.

It implements CLAUDE.md §6 ("Coverage contract: trace every upstream item OR
defer it"). The validator enforces both halves — a strategy that omits an item
without deferring it cannot reach `status: complete`.

**Coverage is a floor, not a quota.** The gate is satisfied by *one* test (or a
deferral) per gated item, but one test per item is the *minimum* that makes the
validator green — it is rarely the *right* number. A feature with three
acceptance criteria, two edge cases, and an error path needs roughly six tests,
not one; the gate would pass with one and leave five behaviours unchecked. And
because `task` maps **one `TST-NNN` → one task → one authored test** (no
fan-out), the count you write here is the count the project gets. So a green
gate is necessary, not sufficient. Run the **per-feature sufficiency check**
(below) alongside the sweep before you close a suite.

---

## Per-feature sufficiency check (after the gate is green)

The coverage gate proves *every item is touched*. This check proves *every item
is touched enough*. For each gated feature/requirement/component, ask:

- Is the **happy path** plus **each acceptance criterion** its own test, or are
  several criteria crammed into one test's assertions?
- Are the **boundary/edge cases** (incl. every PRD `use_cases.edge_cases`) and
  the **invalid-input/error paths** covered, or only the success case?
- Does each **failure mode / security concern** have its own negative test?

Where the honest answer is "one happy-path test and nothing else" for a feature
that clearly has more surface, propose the missing tests (the sweep below is the
vehicle). Where one test genuinely suffices (a trivial getter, a pure mapping),
that's fine — say so. The point is a *deliberate* count per feature, decided by
reasoning about the behaviour, not the accident of "one test cleared the gate."
The decomposition checklist is `test-discovery.md` → "How many tests does a
feature need?".

---

## What is gated

### System file (`TEST-STRATEGY.yaml`)

- **Cross-container workflows.** Every PRD `WKF-NNN` that spans more than one
  container (≥2 containers list it in `ARCH.yaml.containers[].traces_prd_workflows`)
  must be in some system test's `covers` OR deferred.

### Container file (`TEST-STRATEGY__<container>.yaml`)

Drawn from `ARCH.yaml.containers[<id>]` and `docs/ARCH__<id>.yaml`:

- **Requirements.** Every `FR-NNN`/`NFR-NNN` in the container's (and its
  components') `implements_requirements` must be in some test's `covers` OR
  deferred.
- **Acceptance.** Every component that declares `acceptance_criteria` must be
  targeted by ≥1 test (a test whose `component_ref` is that component) OR
  deferred.
- **Risks.** Every `failure_modes[].id` and `security_concerns[].id`
  (container- and component-level, structured entries only) must be exercised
  by a test (`targets_failure_mode` / `targets_security_concern`) OR deferred.
- **Work units (advisory, never blocks).** Every component `work_units[].name`
  SHOULD be exercised by a test (`targets_work_units`, with `component_ref` set —
  unit names are unique only within their component). A gap emits a
  WARNING, not a block — a test strategy is risk-driven, so a trivial work unit
  (a plain getter) may legitimately go untested. Seed one unit test per work
  unit so the suite is atomic by default, and defer the genuinely-trivial ones
  with a `WRN-NNN` that names the unit to silence the warning intentionally.
  (A pre-1.2 `targets_operation` / `OPN-NNN` is a deprecated alias: the
  validator warns and never blocks.)
- **Test subjects (v2.0, BLOCKS at `complete`).** The mirror of the layer
  above, per-test instead of per-unit: every **unit-tier** test must name its
  subject(s) in `targets_work_units` OR be deferred via a `WRN-NNN` naming its
  `tst_id` (check 12). The seam is what the `task` skill wires each test
  task's `depends_on` from — a subject-less unit test forces the absorber
  pattern that cost the corpus a 191-row hand rewire. Blocks only at
  `test_strategy_container_version >= 2.0`; warns below; silent in the
  meta-corpus dialect (the per-unit advisory above carries the signal there).

(Container-level `acceptance_criteria` in `ARCH.yaml` and bare-string
failure-modes/concerns without a stable id are surfaced as seeds but are
non-blocking — they have no id to key a gate on.)

---

## How to TRACE (the normal path)

Reference the item from a test:

- requirements & workflows → the test's `covers` list (by stable id).
- a component's acceptance → a test with `component_ref: <that component>`.
- a failure mode → a test with `targets_failure_mode: <id>`.
- a security concern → a test with `targets_security_concern: <id>`.

The validator counts the item as covered.

### Meta-corpus dialect (covers-based tracing)

A **sharded / no-API-layer meta-corpus** (a CLI factory dogfooding these
skills) may set `meta_corpus_dialect: true` on the **system** strategy file and
trace coverage with just `covers` + `component_ref` — populating none of the
per-target fields (`targets_work_units`, `targets_component`,
`targets_failure_mode`). A generated app OMITS the flag and keeps the strict
rules above. In the dialect the validator additionally treats an item as
covered when:

- **component acceptance** — a test's covered FRs intersect the component's
  `implements_requirements` (covers-targeting), not only when `component_ref`
  names it;
- **NFRs** in a test's `covers` — resolved against the **PRD NFR catalogue**,
  not a component's `implements_requirements` (which by house style lists only
  FRs), so an NFR-only test does not need the NFR echoed into ARCH;
- **failure modes** — the owning component is covers-targeted (or the usual
  `targets_failure_mode`, or a WRN-NNN deferral).

Everything else (requirement/workflow coverage, the WRN-NNN defer path, global
TST uniqueness) is unchanged. The relaxations are opt-in and monotonic — they
only *add* ways to satisfy a gate; a genuinely uncovered requirement still
fails, and the same shapes without the flag fail the strict checks.

## How to DEFER (the escape hatch)

Some items genuinely warrant no automated test in *this* artifact:

- a process FR with no observable behaviour to assert (pure config loading);
- a workflow that is manual/operator-driven with no automatable path;
- an NFR verified by a tool outside the test suite (a license scan, a SAST
  pass) rather than a `TST-NNN`;
- a risk mitigated structurally (a type makes the failure unrepresentable).

Record the deferral by **naming the id in a `test_strategy_warnings` entry**:

```yaml
test_strategy_warnings:
  - "WRN-014: FR-029 is config loading with no behaviour to assert beyond startup; covered by the startup smoke test in the e2e suite, not a unit test here."
  - "WRN-015: failure_mode db-pool-exhausted is mitigated by a connection-pool config invariant; no runtime test — deferred."
```

The validator scans warnings for the id token (FR/NFR/ACR/WKF tokens, or the
literal kebab-case failure-mode / security-concern / component id) and counts
a named id as covered. **Always give a reason** — a bare "WRN-016: FR-031" is
valid to the regex but useless to a reviewer. Don't defer to dodge work; defer
when a test would be noise.

The user can trigger a deferral mid-interview by typing `defer <id>` — log the
WRN-NNN with the reason they give.

### Deferring a test obliges a matching impl deferral downstream (CLAUDE.md §6a)

Deferring a behaviour's **test** here is not a local decision — it has a
**downstream partner**. `task` emits one impl task per work_unit; if you defer
the test for a behaviour but its impl task still ships as MVP, the branch is
built with **no test** while both artifacts claim full coverage. That asymmetry
is exactly what CLAUDE.md §6a ("paired deferral") forbids.

So when you defer a test for a behaviour that has real code (a work_unit / an FR
realized by a callable), **name the behaviour clearly** in the WRN — the
work_unit name and/or the FR id, not just a `TST-NNN` — so the `task` skill's
symmetry check (its cross-check #23) can see the deferral and demand a matching
`task_warnings` deferral of the impl task. A test deferred for a
purely-structural reason (a process FR with no code, an NFR checked by an
external tool) has no impl partner and needs no downstream pairing. Reserve test
deferrals for genuine no-code / elsewhere-covered items — don't defer a test
just because the code is hard to exercise, then let the code ship untested.

---

## The scope-completeness sweep (before closing each suite)

`system_suite` and `container_suite` are `critical synthesis: true`. After the
per-item loop closes, run the **dynamic scope-completeness sweep** exactly as
specified in `sdlc/skills/prd/references/importance-flows.md` (§ "The
`critical` flow → dynamic scope-completeness sweep"). For `test`, reflect on:

- the **draft suite** itself (are whole tiers missing — e.g. zero negative
  tests for a container that has failure modes? does any feature have only a
  happy-path test where its acceptance criteria / edge cases / error paths
  should each be pinned? — see the per-feature sufficiency check above);
- **every upstream ID family**, not just the most direct one — PRD FR/NFR/WKF,
  PRD `use_cases.edge_cases` (`EDG-NNN`) and `success_metrics.acceptance_criteria`
  (`ACR-NNN`), **every upstream artifact's `*_warnings`/`WRN-NNN`** (PRD, DATA,
  ARCH, API, UX), ARCH `failure_modes`/`security_concerns`/`acceptance_criteria`,
  API operations (contract tests), UX surfaces (a11y), DATA entities
  (round-trips) and DATA invariants (property tests);
- **project-type heuristics** (`tiering-guidance.md` §10) — e.g. an
  event-driven system with no idempotency/replay test, a parser with no
  malformed-input test, an auth boundary with no unauthenticated-request test.

Surface concrete candidate tests (not category labels) via one multi-select
`AskUserQuestion`. Caps: at most 2 sweep passes per suite; honour the
anti-padding rule (surface 0 candidates rather than manufacture filler); defer
any leftover gaps to a `WRN-NNN`.

The sweep is the safety net for synthesis gaps — the case where an item implied
by an upstream id (a failure mode whose description names a race condition)
never made it into the draft because seeding only looked at the most obvious
signal. **Skip it at your peril.**

---

## At Phase 7

Run `validate_schema.py`. If a coverage gate fails while `status: complete`,
the validator prints the exact uncovered ids and forces a FAIL. Either add the
missing test or defer the id with a reasoned WRN-NNN, then re-validate. A
`status: draft` artifact lists the same gaps as advisory notes but still exits
0 — so you can always save partial progress.

---

## Non-gating tests: the marker contract (v2.0, SK-07)

A test that must never block PR CI (an out-of-band eval — real-model LLM-judge
runs, nightly load probes) sets `gating: false` and is excluded from the
default suite via ONE pytest marker (`non_gating_marker`, default
`eval_nongating`). Ownership is split across three artifacts — single-home
each piece, duplicate nothing (corpus worked example: PLAN4-D3):

- **This strategy (the TST item):** `gating: false`, plus one directive line
  telling the codegen worker to decorate the test with
  `@pytest.mark.<marker>`. The validator reminds you when the directive is
  missing (advisory).
- **The task graph:** the test task inherits the marker directive via its
  embedded `test_spec`; the **system scaffold task** owns marker registration
  + the default exclusion in the repo-root test config (pytest:
  `[tool.pytest.ini_options] markers` + `addopts = -m "not <marker>"`).
- **The conftest registers nothing** — registration lives in the root config
  only, so a plain `pytest` run deselects the evals and the nightly runner
  opts in with `-m <marker>`.

`gating` is not a coverage mechanism: a `gating: false` test still counts for
covers/acceptance/risk tracing (the behaviour IS verified — just out-of-band).
