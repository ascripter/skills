# Explaining the choices (sdlc-test)

The person running `/sdlc:test` is often a capable developer who is **not** a
dedicated test engineer. They can make an excellent decision if you hand them
the reasoning; they'll rubber-stamp a default they don't understand — or pick
badly — if you hand them jargon. Several test decisions are also genuinely
consequential and quietly expensive to get wrong. This file is the contract for
**how** the interview presents those decisions.

It is a *delivery* contract, not new content. The substance — why the pyramid
bends, what to mock, why coverage is a signal — already lives in
`tiering-guidance.md`. This file is about getting that substance in front of the
user **at the moment of the question**, in plain language.

Read this when entering Phase 4 (structural questions) and keep it in mind
through Phase 6. Load `tiering-guidance.md` alongside it — that's where the
explanations you'll paraphrase come from.

Contents:
1. Which decisions are "loaded" (and must be explained)
2. The explain-the-why contract (four parts)
3. Recording the reasoning (so a one-click accept still has a "why")
4. Keep it humane — teach, don't lecture
5. Worked example A — the test pyramid
6. Worked example B — mocking
7. The per-test tier "push-down" challenge

---

## 1. Which decisions are "loaded"

A decision is **loaded** when it (a) carries a jargon term the user may not
know, and (b) silently hurts the project if defaulted wrong. Every question
carrying an `explainer:` block in `test-questions.yaml` is loaded. Today that
set is:

| Decision | schema_path | The plain-language stakes |
|---|---|---|
| Test mix ("pyramid") | `test_approach.pyramid_targets` | Wrong mix → slow, flaky suite that tests the wrong layer. |
| Mocking policy | `mock_policy` (+ `container_policy.mock_policy`) | Over-mock → tests pass while prod breaks. Under-mock → slow, flaky. |
| Coverage floor | `coverage_threshold.line_pct` / `coverage_target.line_pct` | Treated as a target → people chase a number with empty tests. |
| Fixture strategy | `fixture_strategy` | Wrong choice → brittle, order-dependent tests that rot. |
| Per-test tier | `system_suite.tier`, `container_suite.tier` | Verifying a rule with a slow e2e instead of a fast unit. |

Everything else in the interview is fine to ask plainly. **Don't** wrap a
straightforward enum (`priority: must/should/could`) in a paragraph of theory —
reserve the explain-the-why machinery for the loaded set, or it becomes noise.

## 2. The explain-the-why contract (four parts)

For each loaded decision, the `AskUserQuestion` call must carry all four:

1. **A plain-language frame** in the question text. One or two sentences: what
   this decision actually controls, and what goes wrong if you choose badly.
   Define the jargon term inline the first time it appears ("the *test pyramid*
   is just the recommended **mix** of test types"). Pull the gloss from the
   question's `explainer.jargon` map; never assume the term is known.

2. **A recommendation tied to *this* project.** The position-1 option is your
   recommendation, and its description must name the concrete upstream fact that
   drove it — not a generic "best practice". Read the signal named in
   `explainer.recommend_from` (e.g. `ARCH.yaml.architecture_pattern`, the
   container archetypes, the PRD NFRs, the project type) and say *why that fact
   points here*: "ARCH.yaml shows 6 services over async events, so contract
   drift is your real risk — that's why I'm boosting the contract band." A
   recommendation the user can trace to their own system is one they can trust
   or override knowingly. Mark it `★` (or `⚠` if the upstream signal was thin
   and you're inferring) at position 1.

3. **Plain-language option descriptions with the tradeoff.** Every option's
   `description` says what it means *and* what it costs you — gloss any jargon
   inline. No bare labels. "London-school" alone is useless; "London-school =
   mock every collaborator, so unit tests are maximally isolated and fast, but
   can pass while real wiring is broken" is a choice the user can actually make.

4. **A "not sure — explain" escape hatch.** Make the last option an explicit
   invitation: *"Not sure — explain the tradeoff."* On that pick (or if the user
   types "why?" / "explain" / "I don't know" into the free-text field), expand
   the relevant section of `tiering-guidance.md` into plain language — ideally
   with an example drawn from *their* containers — then re-ask the same question.
   Never make not-knowing cost the user anything; the whole point is that this
   interview is safe for non-experts.

These four parts apply whether the question's `importance` is `high` (the
pyramid, mock, coverage, fixture scalars) or `critical` (the per-test tier).
For the `high` loaded scalars this **replaces** the bare "draft → Approve /
Iterate" two-option flow from `importance-flows.md` with the richer multi-option
call described here: lead with the tailored recommendation, show the real
alternatives with their tradeoffs, and offer the escape hatch. The user can
still type their own value in "Other".

## 3. Recording the reasoning

Explaining the choice live is the goal; capturing *why the choice was made* in
the artifact is a cheap bonus that makes the strategy self-documenting for the
downstream codegen agent — and means even a one-click accept isn't a black box.

- **User accepts your recommendation as-is** → write your recommendation's
  reasoning (the project-tied "why" from part 2) into the field's `_rationale`
  sibling, with the `_confidence` sibling set to `inferred`. Don't leave it
  blank just because the user clicked rather than typed.
- **User picks a different option or types their own** → ask the single
  `capture_rationale` follow-up ("In one sentence — why?"), but offer a
  plain-language default they can accept so a non-expert is never stuck staring
  at a blank box. Set `_confidence: confirmed`.

The `_rationale` siblings that exist today: `pyramid_rationale`,
`coverage_threshold.rationale`, `coverage_target.rationale`,
`mock_policy_rationale`, `fixture_strategy_rationale`. (The last two were added
for exactly this — see the schema.)

## 4. Keep it humane — teach, don't lecture

The interview is already long; explanation must not bloat it.

- **One or two sentences, not an essay.** The depth lives behind the "explain"
  escape hatch for the user who wants it. The default view is compact.
- **Let experts skip.** An experienced user who picks the recommendation in one
  click should sail through. The teaching is *available*, not forced.
- **Read the room.** If the user types an expert answer ("trophy shape, we're
  IO-bound") or has already shown they know the domain this session, dial the
  framing back to a sentence. Don't re-explain the pyramid three times in one
  session — explain it well once, then reference it ("same pyramid logic as
  before, but for this container…").
- **Never condescend.** "No test-engineering background needed" is welcoming;
  "as you may know…" when they clearly don't is not. Assume intelligence,
  not expertise.

## 5. Worked example A — the test pyramid

This is the decision the user flagged: percentages with no "why". Here's the
shape to follow (`architecture_pattern: event_driven`, 6 services in ARCH):

```
header: "Test mix"
question: >
  Tests come in layers, and the "test pyramid" is just the recommended MIX:
  many small fast tests that check one piece of code (unit), fewer that check
  pieces working together (integration), and a few that drive the whole app
  like a user would (end-to-end). Small tests are fast and point straight at
  the broken line; end-to-end tests are slow and flaky but prove the app
  really works. Your ARCH.yaml shows 6 services talking over async events, so
  your biggest risk is services drifting apart — not logic inside one service.
  That's why I'm suggesting a strong "contract" band (cheap tests that pin the
  message/response shape between services). Pick a mix, or ask me to explain.
options:
  - label: "★ 50 / 25 / 15 / 10 — recommended for your services"
    description: >
      unit 50% / integration 25% / contract 15% / e2e 10%. The contract band
      catches the #1 microservices bug — a provider changes a response shape
      and silently breaks a consumer — far cheaper and clearer than an
      end-to-end test. Recommended because your ARCH is event-driven with 6
      services.
  - label: "70 / 20 / 10 — classic pyramid"
    description: >
      The textbook default. Best when most risk is logic inside one unit;
      lighter on cross-service drift, which is your main exposure here.
  - label: "60 / 25 / 15 — testing trophy"
    description: >
      Fewer pure-unit tests, more integration. Fits glue / IO-heavy code where
      bugs live at the seams. Reasonable if unit tests on thin controllers feel
      low-value.
  - label: "Not sure — explain the tradeoff"
    description: >
      I'll walk through what each layer buys you in plain language, with
      examples from your own services, then re-ask. No test background needed.
```

## 6. Worked example B — mocking

The user's second flag: "how much should I mock and *why*?" (a backend that
uses Postgres and Stripe):

```
header: "Mocking"
question: >
  "Mocking" means swapping a real dependency (a database, another service, an
  email API) for a stand-in during a test. The trade is speed/control vs.
  realism: a stand-in is fast and predictable, but a test full of stand-ins can
  pass while production breaks — because you're testing your ASSUMPTIONS about
  the dependency, not the dependency itself. The rule that ages well: mock only
  what's slow, external, or out of your control (third-party HTTP, payments,
  email); use the real thing in-process when it's cheap (an in-memory database,
  a real pure function). Your backend talks to Postgres and Stripe, so I'd use a
  real throwaway Postgres and mock Stripe. Pick a default, or ask me to explain.
options:
  - label: "★ Mock at the edge; real in-process deps — recommended"
    description: >
      Fake only network/process boundaries (Stripe, email). Use a real
      in-memory DB and real internal objects. Catches integration bugs a mock
      would hide — the safest default for most apps.
  - label: "Mock external services; real DB via testcontainers"
    description: >
      Same idea, but spins up a real Postgres in a container for integration
      tests instead of in-memory. Higher fidelity to prod, a bit slower — good
      because you depend on Postgres-specific behaviour.
  - label: "Mock everything outside the unit (London-school)"
    description: >
      Every collaborator is a stand-in: unit tests are maximally isolated and
      fast, but can pass while real wiring is broken, and they break on every
      refactor. Use sparingly, for pure-logic cores.
  - label: "Not sure — explain mocking"
    description: >
      I'll explain what to mock and why, with examples from your own
      containers, then re-ask.
```

## 7. The per-test tier "push-down" challenge

When you drill each test (the `critical` per-item flow in
`interview-mechanics.md`, step 2 "challenge"), tier choice is a loaded decision
too — and the most valuable place to teach. The move is "push down": verify each
thing at the **cheapest tier that still proves it**.

Make the *why* explicit, in plain language, whenever you propose pushing a test
to a lower tier:

> "This is drafted as an end-to-end test, but it's really checking one business
> rule — that an overdrawn account is rejected. End-to-end tests are slow and
> fail in ways that don't tell you *where* it broke. The same rule proven as a
> unit test on the `LedgerService` runs in milliseconds and points right at the
> line. I'd keep an end-to-end test only for the happy-path *journey* wiring.
> Push this one down to a unit test, or keep it at e2e?"

Give the user the cost in concrete terms (speed, and how clearly a failure
localizes), not just the label. An expert will agree in one click; a non-expert
just learned the single highest-leverage idea in test design. See
`tiering-guidance.md` §4 for the full reasoning you're paraphrasing.
