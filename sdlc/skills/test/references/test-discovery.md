# Test discovery — seeding the suite from upstream (sdlc-test)

A good test strategy is *derived*, not invented. Both modes open by proposing
a draft suite synthesized from the upstream artifacts so the user edits a list
instead of facing a blank page. This file is the seeding algorithm. Read it in
Phase 3. Tag every candidate `✓ found` (a direct upstream signal) or
`⚠ inferred` (a heuristic) — `⚠ inferred` candidates are confirmed one by one.

The governing principle: **enumerate what must be verified, then pick the
cheapest tier that verifies it** (see `tiering-guidance.md`).

**This is the complete enumeration — nothing downstream fans it out.** `task`
realizes **one task per `TST-NNN`**, and codegen writes **one test per task**.
So the suite you seed here *is* the suite the project gets, test for test. The
seeding mindset is therefore "list every test this needs," not "list one test
per requirement and trust a later stage to expand it." A single FR commonly
deserves a *cluster* of `TST-NNN` items — the next section is how to size that
cluster.

---

## How many tests does a feature need?

The most common failure of a seeded suite is **one test per requirement** — a
single happy-path test that makes the coverage gate green while the feature's
real behaviour goes unchecked. The coverage gate
(`coverage-and-defer.md`) asks for *at least one* test per item; that is a
floor, not a target. For each feature/component/requirement, walk this
checklist and seed a separate `TST-NNN` for every line that applies:

- **Happy path** — the primary success case. (1 test.)
- **Each acceptance criterion** — every `acceptance_criteria[]` entry on the
  ARCH component (and PRD `success_metrics.acceptance_criteria`) is a distinct
  observable claim. Seed one test per criterion; don't fold three criteria into
  one test's assertions. (N tests for N criteria.)
- **Boundaries & edge cases** — empty/zero, max/overflow, first/last,
  duplicate, the explicitly enumerated PRD `use_cases.edge_cases`. Each named
  edge case is its own test.
- **Invalid input / error paths** — malformed payloads, missing fields,
  type/range violations, conflicts. A feature that only proves the happy path
  is half-tested; the error handling is usually where the bugs are.
- **Each failure mode & security concern** — every `failure_modes[].id` and
  `security_concerns[].id` is its own negative/abuse-case test (see §3 below).
- **Invariants** — where DATA or the component states an invariant (uniqueness,
  monotonicity, round-trip identity), a `property` test over the input space.

Don't manufacture filler — a genuinely trivial getter may warrant a single
test. But the *default expectation* for a real feature is several tests, and
the per-test interview should propose the cluster, then let the user prune.
Read each ARCH component's `responsibilities` and `acceptance_criteria` as a
list of behaviours to cover, not as one feature to touch once.

---

## System mode — the cross-container suite + global policy

### 1. End-to-end tests from PRD workflows (`✓ found`)

For each `PRD.use_cases.core_workflows` `WKF-NNN`:

- Determine which containers the workflow touches (a container "touches" a
  workflow if it lists the `WKF-NNN` in `ARCH.yaml.containers[].traces_prd_workflows`,
  or sits on an edge between two that do).
- If it touches **>1 container**, seed one `e2e` test. `covers: [WKF-NNN, ...]`,
  `involves_containers: [...]`. This is the system-level **workflow-coverage**
  obligation — every cross-container workflow needs an e2e test or a deferral.
- If it touches exactly one container, leave it to that container's file
  (an integration test there) — don't seed a system e2e for it.

### 2. Contract tests from cross-container calls (`✓ found`)

For each `ARCH.yaml.edges` of type `calls` between two containers:

- Seed a `contract` test that pins the provider's response shape so the
  consumer and provider can evolve independently. Pull `via_resource_id` /
  `via_operation_id` from the edge into `directives` and `covers` (the FR/NFR
  behind that operation). If `docs/API.yaml` is present, name the exact
  `operation_id`; if absent, describe the call and add a WRN noting the API
  spec gap.
- `publishes` / `subscribes_to` edges over an event bus seed a contract test
  on the **event schema** (`via_channel_id`).

### 3. NFR-driven system tests (`⚠ inferred`)

From `PRD.non_functional_requirements`:

- **performance_targets** (latency/throughput/concurrency budgets) → `load`
  tests. `covers: [NFR-NNN]`. The directive states the target and the
  measurement method.
- **security / auth / data-residency** NFRs that span containers → system
  `security` tests (e.g. "an unauthenticated request to any backend is
  rejected"). `covers: [NFR-NNN]`.
- **accessibility** NFRs (+ `docs/UX.yaml` surfaces) → `accessibility` tests
  on the user-facing container's key surfaces.

### 4. Global policy (`⚠ inferred`)

Pre-fill, then confirm:

- `pyramid_targets` — default `{unit:'~70%', integration:'~20%', e2e:'~10%'}`,
  adjusted by architecture pattern (`tiering-guidance.md`).
- `coverage_threshold.line_pct` — default 80; raise for safety-critical
  domains, lower for prototypes.
- `mock_policy`, `fixture_strategy` — propose sane defaults from the stack
  (`tiering-guidance.md` → "Mock vs. real", "Fixtures & test data").

---

## Container mode — the unit + integration suite

Load `docs/ARCH__<container>.yaml`. It is the richest seed source in the whole
factory for tests — mine every structured field.

### 1. Unit tests from components (`✓ found`)

For each `components[]`:

- **Seed one `unit` test per component `work_units[]` entry** (name-addressed —
  work units carry no id family) — the atomic test grain, mirroring how the
  `task` skill slices one task per work_unit. Set
  `component_ref: <component_id>` AND `targets_work_units: [<work_units[].name>]`
  (both are needed — unit names are unique only within their component), and
  pull the unit's traces into the test: `covers` ← the unit's
  `implements_requirements`, plus a happy-path assertion from its `summary` /
  `satisfies_acceptance`; its interface contract fields (the flat
  inputs/output/raises on the work_unit — the nested `interface_contract:`
  block exists only on the downstream Task embed) name the
  argument/return/error shapes to assert. **The seeded test carries its
  subject from birth; a hand-added test names its subject(s) or defers** — at
  `status: complete` a unit-tier test with neither blocks (v2.0 check 12; the
  `task` skill wires each test task's `depends_on` from this list). A test that
  exercises two units as one behaviour (a gate's exit + entry adequacy) lists
  both. Every component work unit SHOULD
  get a test (the advisory work-unit-coverage warning flags any that don't);
  defer a genuinely trivial unit (a plain getter) with a `WRN-NNN` naming the
  unit.
- For a component that declares **no** `work_units[]` (waived or plumbing),
  fall back to seeding from each `responsibilities[]` and
  `acceptance_criteria[]` entry (the older grain).
- Map the component's `implements_requirements` (FR/NFR) into the tests'
  `covers` so the **requirement-coverage gate** is satisfied.
- `validator` / `serializer` / `repository` archetypes warrant explicit
  edge-case and round-trip unit tests (malformed input, boundary values,
  encode→decode identity).

### 2. Integration tests from internal edges (`✓ found`)

For each `internal_edges` (`calls` between two components inside the
container) → seed one `integration` test exercising the real wiring across
that boundary, faking only what crosses the container's edge.

`external_edges` (to another container or a data store) → seed an
`integration` test using the container's `test_environment` (testcontainers,
in-memory, emulator) for the dependency.

### 3. Negative / resilience tests from risks (`✓ found`)

This is what makes the strategy trustworthy, and it is the part a blank-page
author always under-does:

- For each `failure_modes[].id` (container-level + component-level) → seed a
  test (usually `unit` or `integration`) that drives the failure and asserts
  the `mitigation` holds. Set `targets_failure_mode: <id>`.
- For each `security_concerns[].id` → seed an abuse-case test (`security`
  tier) that attempts the threat and asserts it's blocked. Set
  `targets_security_concern: <id>`.

Every failure-mode id and security-concern id must end up either targeted by a
test or deferred — that's the **risk-coverage gate**.

### 4. Data round-trips from traced entities (`⚠ inferred`)

For components that `traces_data_entities`, seed persistence round-trip tests
(write → read → assert equality) and, where the DATA model declares
invariants, property tests over them.

### 5. Property tests where invariants exist (`⚠ inferred`)

Pure functions and parsers/serializers with stated invariants are ideal
`property` candidates — propose them but mark inferred (the user decides if
the invariant is worth generative testing).

---

## Upstream warnings & enumerated edge cases (both modes, `⚠ inferred`)

The structured `✓ found` fields above (workflows, edges, components,
requirements, risks) are the obvious seeds. The sources below are the ones a
one-test-per-FR pass routinely skips — yet they are exactly where the upstream
*recorded a concern in writing*. Mine each, then seed a test or make a
deliberate "no test needed, because…" note (don't silently drop them).

- **Every upstream artifact's `*_warnings` / `WRN-NNN`.** `prd_warnings`,
  `data_warnings`, `arch_warnings`, `api_warnings`, `ux_warnings` each hold
  items the upstream skill flagged as a risk, gap, or deferred decision. Read
  each one and ask *"is there a behaviour here a test should pin?"* A warning
  like "WRN-009: digest send is not idempotent across retries" is a direct
  prompt for an idempotency test. A warning that names a deferred validation
  rule is a prompt for the negative test that guards it. These are *not* the
  same as this artifact's own `test_strategy_warnings` (which record *your*
  deferrals) — they are inbound signals from upstream.
- **PRD `use_cases.edge_cases` (`EDG-NNN`).** These are edge cases the PRD
  author enumerated by hand — the single highest-signal under-used source. Each
  one is a test (or a reasoned deferral). A cross-container edge case (e.g.
  "digest run when a team has zero open tasks") seeds a system `e2e`; a
  container-local one seeds a unit/integration test in that container.
- **PRD `success_metrics.acceptance_criteria` (`ACR-NNN`).** Product-level
  acceptance claims — each is an observable outcome a test or e2e should assert
  (or defer). Reference them in `covers` by their `ACR-NNN` token.
- **PRD `risks_assumptions.top_risks` and `open_questions`.** A named risk with
  a testable manifestation (e.g. "email deliverability") may warrant a test
  (e.g. a contract test on the email provider boundary) or an explicit
  deferral to a non-test mitigation.
- **DATA-MODEL invariants & constraints.** Uniqueness, referential, range, and
  state-machine constraints declared on entities seed validation and `property`
  tests (write that violates the constraint is rejected; round-trip preserves
  it).

Tag everything seeded here `⚠ inferred` and confirm one by one — these are
heuristic reads of prose, so the user gets the final say on each. Anything you
decide needs no test gets a one-line reasoned note (and, if it maps to a gated
upstream id, a `WRN-NNN` deferral per `coverage-and-defer.md`).

---

## After seeding

Present the draft suite grouped by tier with a one-line count summary. Let the
user accept (`ok`), add, remove, or re-tier. Persist to
`state.sessions[<key>].defined_tests`. Then proceed to Phase 4. The
scope-completeness sweep (after the Phase 6 per-item loop) is the safety net
that catches anything this seeding missed — see `coverage-and-defer.md`.
