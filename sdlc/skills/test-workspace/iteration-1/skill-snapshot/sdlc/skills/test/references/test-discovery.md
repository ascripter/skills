# Test discovery — seeding the suite from upstream (sdlc-test)

A good test strategy is *derived*, not invented. Both modes open by proposing
a draft suite synthesized from the upstream artifacts so the user edits a list
instead of facing a blank page. This file is the seeding algorithm. Read it in
Phase 3. Tag every candidate `✓ found` (a direct upstream signal) or
`⚠ inferred` (a heuristic) — `⚠ inferred` candidates are confirmed one by one.

The governing principle: **enumerate what must be verified, then pick the
cheapest tier that verifies it** (see `tiering-guidance.md`).

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

- Seed `unit` tests for each `responsibilities[]` entry and each
  `acceptance_criteria[]` entry. `component_ref: <component_id>`.
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

## After seeding

Present the draft suite grouped by tier with a one-line count summary. Let the
user accept (`ok`), add, remove, or re-tier. Persist to
`state.sessions[<key>].defined_tests`. Then proceed to Phase 4. The
scope-completeness sweep (after the Phase 6 per-item loop) is the safety net
that catches anything this seeding missed — see `coverage-and-defer.md`.
