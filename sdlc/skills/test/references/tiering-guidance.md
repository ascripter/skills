# Test-strategy guidance (sdlc-test)

General, opinionated guidance for choosing tiers, deciding what to mock, and
shaping a strategy that a downstream AI agent can implement well. This is the
"why" behind the interview. Load it in Phases 3–6.

Contents:
1. The governing principle
2. The pyramid (and when to bend it)
3. The eight tiers — what each is for
4. Choosing the cheapest tier that proves the requirement
5. Mock vs. real
6. Fixtures & test data
7. Coverage as a signal, not a target
8. Determinism & flake avoidance
9. Writing tests an AI agent can implement (the `directives` field)
10. Pattern-specific defaults

---

## 1. The governing principle

> **Enumerate what must be verified, then verify each thing at the cheapest
> tier that still gives you confidence.**

Every test costs something to write, run, and maintain. A test earns its keep
only by catching a class of regression you actually fear. So the strategy is
not "write many tests" — it's "cover every requirement and named risk with the
least, fastest, most stable set of tests that proves them."

"Least" is not "one." Most real features have several distinct things that can
break — the happy path, each acceptance criterion, the boundaries, the error
paths, each named failure mode — and each is its own test. Sizing that cluster
per feature (rather than defaulting to one test per requirement) is in
`test-discovery.md` → "How many tests does a feature need?". This skill is the
*complete* enumeration: `task` realizes one task per `TST-NNN` and codegen
writes one test per task, so no later stage adds the tests you leave out. Pair
breadth (enough tests per feature) with the push-down discipline below (each
test at the cheapest tier that proves it).

## 2. The pyramid (and when to bend it)

The classic **test pyramid**: many fast `unit` tests at the base, fewer
`integration` tests in the middle, very few slow `e2e` tests at the top.
Rationale: lower tiers are faster, more isolated, and pinpoint failures; higher
tiers are slower and flakier but prove the system actually works end to end.

Defaults: `{unit:~70%, integration:~20%, e2e:~10%}`.

Bend it when the architecture says so:

- **I/O-bound / glue-heavy services** (thin controllers over a DB, ETL): the
  "**testing trophy**" shape fits better — fewer pure-unit tests, more
  integration tests, because the bugs live at the seams, not in branch logic.
- **Microservices / event-driven**: add a strong `contract` band. The risk is
  services drifting apart, not internal logic. Lean
  `{unit:~50%, integration:~25%, contract:~15%, e2e:~10%}`.
- **Libraries / pure-logic engines**: pyramid is steep — `{unit:~85%}` with a
  few integration/e2e. Property tests pay off here.
- **UI-heavy frontends**: component/integration tests dominate; a thin e2e
  band covers the critical journeys only.

Record the chosen shape in `pyramid_targets` with a one-line rationale.

## 3. The eight tiers — what each is for

| Tier            | Verifies | Speed | Typical home |
|-----------------|----------|-------|--------------|
| `unit`          | One component/function's logic in isolation | fastest | container file |
| `integration`   | Two+ components wired together inside a container | fast | container file |
| `e2e`           | A whole user/PRD workflow across containers | slow | system file |
| `contract`      | A provider/consumer interface (API op, event schema) won't drift | fast | system (cross-container) or container (intra) |
| `property`      | An invariant holds across a generated input space | fast | container file |
| `load`          | A performance NFR (latency/throughput) under volume | slow | system or container |
| `security`      | An abuse case is blocked (authz, injection, PII leak) | varies | system or container |
| `accessibility` | A UX surface meets a11y conformance | fast | system (surface-owning container) |

## 4. Choosing the cheapest tier that proves the requirement

When a candidate test is proposed at a high tier, ask whether a lower tier
would give the same confidence:

- "Does the e2e test exist to prove **the workflow wires up**, or to prove a
  **branch of business logic**?" If the latter, push it down to a unit test on
  the component that owns the logic, and keep the e2e for the happy-path wiring
  only.
- An `e2e` test per business rule is an anti-pattern — it's slow and it
  localizes failures poorly. Cover the rule with a unit test; cover the
  *journey* with one e2e.
- Use `contract` instead of `e2e` to catch interface drift — it's far cheaper
  and fails with a clearer message.

This "push down" is the single highest-leverage move in the per-test
`challenge` step.

## 5. Mock vs. real

The most error-prone decision in testing. Guidance:

- **Never mock the unit under test.** Mock only collaborators that sit across
  a boundary you don't control or that are slow/non-deterministic.
- **Prefer real in-process dependencies** when they're cheap and
  deterministic: an in-memory SQLite, an in-process event bus, a real pure
  function. Real dependencies catch integration bugs mocks hide.
- **Use `testcontainers` / emulators** for integration tests against a real
  database, queue, or cloud service — a mock of a database tests your
  understanding of the database, not the database.
- **Mock at the network/process edge**: third-party HTTP APIs, payment
  providers, email — these should be faked (or contract-tested separately),
  never hit for real in the unit/integration suite.
- **Over-mocking** produces tests that pass while production breaks: they
  assert the code calls the mock the way the test author imagined, not that
  the behaviour is correct. Watch for tests that only verify call arguments.

Capture the default in `mock_policy`; let a container override it in
`container_policy` when its dependencies demand something different.

## 6. Fixtures & test data

- **Factories/builders beat static fixtures** for evolving schemas: a factory
  with sensible defaults, overridable per test, keeps tests readable and
  resilient to schema change. Static fixture files rot.
- **Each test owns its data.** Shared mutable fixtures cause order-dependent
  flakes. Build the minimum each test needs.
- **Synthetic data only — never real PII** in tests. If a realistic shape is
  needed, generate or anonymize.
- **Golden/snapshot files** are useful for serializers and rendered output but
  become rubber-stamps if regenerated blindly — note in `directives` when a
  snapshot must be reviewed, not auto-updated.

## 7. Coverage as a signal, not a target

- Coverage tells you what code ran during tests — **not** that behaviour is
  correct. 100% line coverage with weak assertions proves nothing.
- Use the `coverage_threshold` as a **floor that prevents backsliding**, not a
  goal to chase. A sane default is ~80% line; gate branches (~70%) when
  conditionals carry real risk.
- Raise the floor for money/auth/safety paths; lower it for generated code or
  thin adapters — and say why in the rationale.
- Don't let the number drive test creation. Let **requirements and risks**
  (the coverage gate in `coverage-and-defer.md`) drive it; coverage % is the
  backstop.

## 8. Determinism & flake avoidance

A flaky test is worse than no test — it trains people to ignore red. Bake
these rules into `test_approach.ai_builder_notes` so the codegen agent honours
them:

- No real wall-clock, network, filesystem randomness, or timezone dependence
  without an injected, seeded fake.
- No reliance on test execution order or shared global state.
- No `sleep`-based waits — poll a condition with a timeout instead.
- One behaviour per test; name the test for the behaviour, not the method, so a
  failure reads like a spec violation.

## 9. Writing tests an AI agent can implement (the `directives` field)

Downstream, a code-generation agent turns each `TST-NNN` into actual test code,
and a verification stage runs it. The `directives` field **is the spec** the
agent codes against. Make it executable in prose:

- State the **arrange** (inputs/fixtures), the **act** (the call), and the
  **assert** (the observable outcome) explicitly.
- Name the **edge cases** to include and the **collaborators to stub**.
- For `property` tests, state the **invariant** and the **input space**.
- For `contract` tests, name the exact operation/event and the fields that
  must not change.
- Keep `acceptance` to one machine-checkable sentence — it's the pass
  condition the verification stage keys on.

Vague directives ("test the happy path") produce vague, low-value tests.
Specific directives produce tests that actually pin behaviour.

## 10. Pattern-specific defaults

| Architecture pattern | Lean toward |
|----------------------|-------------|
| `monolith` / `modular_monolith` | unit-heavy pyramid; integration across modules; few e2e |
| `microservices` | strong contract band; integration with testcontainers; thin e2e on key journeys |
| `event_driven` | contract tests on event schemas; integration on publish→consume; idempotency + replay tests |
| `serverless` | unit on handlers; integration via local emulators; e2e against a deployed preview |
| `pipeline` | stage-level unit + golden-file tests; end-to-end on a small fixture corpus |
| `hexagonal` / `plugin` | unit on the core/ports; contract tests on each adapter/plugin interface |

These are starting points to propose, not rules — confirm with the user.
