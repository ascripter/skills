# Run Notes: sdlc-test container mode — backend-api

## (a) Total test count and breakdown by tier

Total TST-NNN tests in TEST-STRATEGY__backend-api.yaml: **15**

| Tier        | Count | TST IDs                               |
|-------------|-------|---------------------------------------|
| unit        | 10    | TST-001..TST-010                      |
| integration | 3     | TST-011, TST-012, TST-013             |
| security    | 1     | TST-015                               |
| integration (failure-mode) | 1 | TST-014 (tier=integration, targets_failure_mode=postgres-unavailable) |

Restated cleanly: 10 unit, 4 integration (including failure-mode test), 1 security.

## (b) Per-component counts and acceptance-criteria coverage

**tasks-controller** is targeted by `component_ref` in:
- TST-004 (unit: create returns 201)
- TST-005 (unit: mark-done flips status)
- TST-006 (unit: input-validation negative test)
- TST-011 (integration: full create/list/done flow)

**Total for tasks-controller: 4 tests.**

tasks-controller declares **2** acceptance criteria:
1. "Creating a task returns 201 with a persisted task id." → TST-004 (unit, acceptance literally matches criterion 1)
2. "Marking a task done flips its status and is reflected on next read." → TST-005 (unit, acceptance literally matches criterion 2)

Both criteria each got their own dedicated test. Yes.

**digest-settings-controller** is targeted by `component_ref` in:
- TST-008 (unit: enable digest persists)
- TST-009 (unit: recent runs newest-first)
- TST-013 (integration: enable settings and list runs)

**Total for digest-settings-controller: 3 tests.**

digest-settings-controller declares **2** acceptance criteria:
1. "Enabling the digest and setting a send time persists and reads back." → TST-008 (unit, acceptance matches criterion 1)
2. "Recent digest runs are listed newest-first." → TST-009 (unit, acceptance matches criterion 2)

Both criteria each got their own dedicated test. Yes.

## (c) WRN-001 (input-validation) and error-path tests

**Did we author a negative/validation test for arch_warnings WRN-001** ("tasks-controller create has no input-validation rule")?

**Yes.** TST-006 is titled "tasks-controller rejects task create with no title (input-validation)". Its description explicitly references arch_warnings WRN-001 and it verifies that POST /tasks with a missing title returns 400 before reaching the repository (zero Prisma calls).

**Additional invalid-input/error-path tests beyond failure-mode and security tests:**

- TST-001: auth-middleware rejects missing Authorization header (no token → 401)
- TST-002: auth-middleware rejects expired JWT (bad token → 401)
- TST-003: auth-middleware rejects JWT with wrong audience (bad aud → 401)
- TST-006: tasks-controller rejects create with no title (missing required field → 400)

So in total there are **4** error-path/invalid-input tests beyond the failure-mode (TST-014) and security-concern (TST-015) tests.

## (d) Fan-out vs. enumerate — SKILL.md quote

The skill was treated as **enumerating all tests here** in the container artifact. The relevant SKILL.md sentence:

> "Downstream agents — `task` (turns each `TST-NNN` into a test task) and the code-generation / verification stages — consume these artifacts as the **executable design contract** for the tests they write and run."

And from the Container themes section:

> "`container_suite` — `critical` per item, `synthesis: true`. For each test: `tst_id`, `name`, `tier`... Run the scope-completeness sweep after the per-item loop."

The skill does not fan tests out to a separate step; it enumerates every test as a typed `TST-NNN` item in the container file so downstream `sdlc:task` can consume them directly. `/sdlc:task` then turns each `TST-NNN` into a concrete implementation task — it does not discover or generate additional tests.

## (e) Final validator verdict

```
[OK] test strategy is valid and complete (TEST-STRATEGY.yaml, TEST-STRATEGY__backend-api.yaml).
```

Exit code: 0.
