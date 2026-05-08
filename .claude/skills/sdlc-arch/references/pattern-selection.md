# Architecture pattern selection — narrative guidance

This file contains the narrative guidance for pattern selection at the
root/context level. The machine-readable tradeoff matrix lives in
`references/pattern-selection.yaml`. Load both together when the user
is selecting or revisiting an architecture pattern.

## When to recommend (and when not to)

Do not hard-bias toward any single pattern. A recommendation requires
evidence. If project shape is unclear, ask targeted questions before
recommending. The right inputs are:

- Team count and ownership boundaries — fewer teams tolerates more
  shared state; many teams needs hard service boundaries.
- Independent deployment needs — if teams want to deploy without
  coordinating, event-driven or microservices patterns become attractive.
- Expected scale asymmetry — if one capability dwarfs the rest in load,
  extracting it changes the calculus.
- Domain complexity — rich domain logic with many invariants pushes
  toward DDD-shaped slices; simple CRUD does not need that overhead.
- Number of external integrations — many external systems favor an
  API gateway or adapter layer.
- Async workflow needs — long-running or retryable workflows naturally
  fit event-driven or choreography patterns.
- Plugin / extensibility needs — extensible platforms lean toward
  plugin architectures or clean hexagonal boundaries.
- Ops maturity — a single-pizza-team with no SRE function should not
  choose a pattern that requires distributed tracing to debug.
- Observability tolerance — some patterns produce lots of moving parts
  that require observability investment proportional to their complexity.

## AI-builder considerations

Because this skill is designed for projects built primarily by AI
agents, the `ai-builder-considerations:` section in
`references/pattern-selection.yaml` should be consulted at the context
level. Key axes:

- **Moving parts**: fewer containers means fewer surfaces where an AI
  agent can introduce a subtle integration bug. Prefer monolithic or
  modular-monolith patterns when the domain doesn't require independent
  scaling or deployment.
- **Interface explicitness**: AI-built code benefits from well-typed
  interfaces between components. Patterns that expose boundaries as
  explicit typed contracts (hexagonal, clean architecture) are easier
  for agents to test and verify.
- **Failure locality**: AI-generated code has higher variability in
  error handling. Patterns where a failure in one module cannot cascade
  (e.g. process-isolated services) reduce blast radius, but add
  operational overhead.
- **Tracing**: distributed patterns require tracing to diagnose subtle
  bugs. Weigh the observability investment before choosing them.
- **Testability**: layered / hexagonal patterns with inversion of
  control produce components that are easy to unit-test with mocks.
  AI agents produce more reliable code when the test feedback loop is
  fast and local.
- **Contract stability**: event-driven patterns require stable event
  schemas. AI-generated schema migrations are risky; prefer versioned
  schemas or schema-registry patterns when going async.

## Recommendation process

1. Load `references/pattern-selection.yaml` and identify the 2–3 top
   candidates based on the inputs above.
2. For each candidate, summarize `best-when`, `tradeoffs`, and any
   relevant `disqualifiers` from the YAML.
3. Present the top 2 candidates to the user with a clear recommendation
   and the main tradeoff. Do not recite the full matrix — synthesize.
4. Record the chosen pattern in `docs/ARCH.yaml` under
   `architecture-pattern:`.
5. On subsequent `/sdlc-arch` invocations at the root level (EDIT mode),
   revisit only if the user raises it or if newly discovered containers
   make the current pattern obviously inappropriate.
