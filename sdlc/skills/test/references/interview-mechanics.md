# Interview mechanics (sdlc-test)

The AskUserQuestion batch format, EXIT semantics, and the importance-tier
state machines are **identical across all SDLC skills**. Rather than restate
them, this file points at the canonical spec and notes the test-specific bits.

## Canonical spec — read this

The four importance tiers (`med` / `high` / `critical` / `nested_freeform`),
the per-item `critical` state machine (propose → challenge → detail →
approve → next), iteration caps, the EXIT-mid-flow rules, and the
**scope-completeness sweep** for `critical synthesis: true` themes are
specified once in:

> `sdlc/skills/prd/references/importance-flows.md`

Read it on entering Phase 6. Everything below is the delta for `test`.

## AskUserQuestion batch rules (recap)

- 2–4 questions per call (hard limit 4). Recommended/inferred option first.
- A free-text "Other" is always added by the tool — the user may type `EXIT`
  there to abort (see SKILL.md → "Reserved EXIT command").
- `med` questions batch together. `high` questions each get a draft-then-
  approve mini-section (cap 3 iterations). `critical` questions run the full
  per-item state machine — here, **one test at a time**.
- **Exception for loaded `high` scalars** (`pyramid_targets`, `mock_policy`,
  `fixture_strategy`, coverage floors — any question with an `explainer:`
  block): replace the bare draft→approve with the explain-the-why presentation
  in `references/explaining-choices.md` (plain-language frame, project-tailored
  recommendation at position 1, glossed options, "not sure — explain" hatch).
  The user can still type their own value in "Other".

## The per-test `critical` flow (system_suite / container_suite)

Both suites are `critical synthesis: true`. Run each candidate test through:

1. **propose** — show the draft: `tier`, `name`, and what it `covers`
   (the WKF/FR/NFR/ACR or the failure_mode/security_concern it targets).
   State where the candidate came from ("seeded from WKF-002" / "negative
   case for failure_mode `db-pool-exhausted`").
   **One upstream item often spawns several tests, not one.** When you reach a
   feature/requirement, propose the *whole cluster* it warrants — happy path,
   one test per acceptance criterion, the boundary/edge cases, the
   invalid-input/error paths — then run each through this state machine. A
   single "test FR-012" item that clears the coverage gate but leaves the
   feature's edge and error behaviour unchecked is the failure this flow
   exists to prevent: nothing downstream fans a `TST-NNN` out, so the cluster
   must be enumerated here. The decomposition is `test-discovery.md` → "How
   many tests does a feature need?".
2. **challenge** — confirm the tier is the *cheapest that proves the
   requirement* (push e2e → integration → unit where possible; see
   `tiering-guidance.md`), and confirm scope (`involves_containers` for
   system tests, `component_ref` for unit tests). When you propose pushing a
   test down a tier, **say why in plain language** — the concrete cost of the
   higher tier (slower, and a failure that doesn't tell you *where* it broke)
   vs. what the lower tier buys. This is the highest-leverage teaching moment
   in the whole interview for a user who isn't a test engineer. Full contract:
   `references/explaining-choices.md` §7.
3. **detail** — fill `directives` (the arrange/act/assert sketch the codegen
   agent follows), `setup`, `acceptance`, plus `fixtures`/`mocks` for
   container tests, and `gating: false` + its marker directive for an
   out-of-band eval. (`priority` is retired — D2.)
4. **approve** — set the test's `status: confirmed`; persist state.
5. **next** — move to the next candidate.

After the per-item loop closes, run the **scope-completeness sweep** and then
the **coverage check** — both described in `coverage-and-defer.md`.

## Batching the cheap fields

Within one test's `detail` step you may batch `setup` + `acceptance` (+
`fixtures`/`mocks`) into a single AskUserQuestion call to keep the interview
brisk. Never batch across two different tests — the per-item boundary is what
makes EXIT/resume clean.

## State after every step

Write `.claude/skills-state/sdlc-test.state.yaml` after every confirmed batch,
mini-section, and per-test approval — including Phase 3 suite confirmation and
Phase 5 pre-fill confirmations. The `current_test` and `defined_tests` fields
make resume land exactly where the user left off.
