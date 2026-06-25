# run-notes.md — sdlc-test system mode eval run

## (a) Test count per tier

Total TST-NNN items: **14**

| Tier          | Count | TST ids                        |
|---------------|-------|--------------------------------|
| e2e           | 6     | TST-001, TST-002, TST-003, TST-004, TST-005, TST-006 |
| contract      | 4     | TST-007, TST-008, TST-009, TST-010 |
| load          | 1     | TST-011                        |
| security      | 2     | TST-012, TST-013               |
| accessibility | 1     | TST-014                        |

## (b) EDG-001 and WRN-001 coverage

**EDG-001** (digest run with zero open tasks): Addressed directly by **TST-005**
("E2E — digest run with zero open tasks sends empty-digest email"). The test
arranges a team with no open Task rows, triggers the digest-worker via a fake
clock, and asserts that the DigestRun is recorded without error (and that the
email stub receives 0 or 1 call depending on the product decision to skip/send
an empty digest). This is a `must`-priority test.

**PRD WRN-001** (digest send not idempotent across retries): Addressed directly
by **TST-006** ("E2E — digest worker does not double-send on retry after
transient email failure"). The test configures the email stub to return 503 on
the first call and 200 on the second, then verifies exactly 1 DigestRun row and
exactly 2 stub calls (no duplicate email). This converts the upstream risk
warning into a concrete idempotency canary test. A test_strategy_warnings entry
WRN-001 records that PRD WRN-001 is addressed by TST-006 (no deferral needed).

## (c) Fan-out vs. enumeration — how the skill was applied

Tests were enumerated individually here — every test the project should have is
its own `TST-NNN` item. This follows the SKILL.md sentence:

> "Every individual test you want the project to have must be enumerated here,
> each as its own `TST-NNN`. If a feature warrants a happy-path test plus three
> edge cases plus an auth-rejection case, that is *five* `TST-NNN` items in this
> artifact — not one 'test FR-012' item that a later stage is trusted to split
> apart. There is no later stage that splits it."

The skill is explicit that `/sdlc:task` maps one `TST-NNN` to exactly one test
task (1:1, never fan-out), so all intended system-level tests must be enumerated
here. WKF-003 received two e2e tests (TST-003 for the configure+run action,
TST-004 for the review-history view) rather than one, because these are distinct
observable behaviours. The idempotency canary (TST-006) was added specifically
because PRD WRN-001 flagged it as a risk — the seeding guidance explicitly calls
out upstream `*_warnings` as high-signal seeds that a one-test-per-FR pass
routinely skips.

## (d) Final validator verdict

```
[OK] test strategy is valid and complete (TEST-STRATEGY.yaml).
```
