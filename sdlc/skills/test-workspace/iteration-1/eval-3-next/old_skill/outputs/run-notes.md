# run-notes — eval-3-next (old_skill)

## (a) Total tests in container file + count per tier

Total TST-NNN tests: 18

| Tier        | Count | TST IDs                                  |
|-------------|-------|------------------------------------------|
| unit        | 11    | TST-001..TST-011                         |
| integration | 5     | TST-012, TST-013, TST-014, TST-015, TST-016 |
| security    | 2     | TST-017 (failure-mode), TST-018          |

(TST-017 has `targets_failure_mode: postgres-unavailable` and tier `integration`; TST-018 has `targets_security_concern: pii-in-logs` and tier `security`.)

Corrected tier breakdown:

| Tier        | Count | TST IDs                                        |
|-------------|-------|------------------------------------------------|
| unit        | 11    | TST-001..TST-011                               |
| integration | 6     | TST-012, TST-013, TST-014, TST-015, TST-016, TST-017 |
| security    | 1     | TST-018                                        |

Total: 18 tests.

## (b) Tests targeting tasks-controller and digest-settings-controller

### tasks-controller (component_ref: tasks-controller)
- TST-004: Create task returns 201 with persisted id (acceptance criterion 1)
- TST-005: Mark task done flips status and reads back (acceptance criterion 2)
- TST-006: List tasks returns correct collection
- TST-007: Create task rejects missing title — negative/validation test (WRN-001)
- TST-015: Integration — authenticated create-task persists and lists
- TST-016: Integration — authenticated mark-task-done persists status change

### digest-settings-controller (component_ref: digest-settings-controller)
- TST-010: Enable digest and set send time persists and reads back (acceptance criterion 1)
- TST-011: Recent digest runs listed newest-first (acceptance criterion 2)

**Did each of digest-settings-controller's two acceptance criteria get its own test?**
Yes. TST-010 targets AC1 ("Enabling the digest and setting a send time persists and reads back") and TST-011 targets AC2 ("Recent digest runs are listed newest-first"). Each has its own separate TST-NNN item.

## (c) Negative/validation test for WRN-001 and other error-path tests

**WRN-001 negative test authored?** Yes — TST-007 ("tasks-controller: create task rejects missing required title (WRN-001)") is an explicit unit test that sends a POST /tasks with no title payload and asserts 400 + repository NOT called. The test description names arch warning WRN-001 directly.

**Other invalid-input/error-path tests beyond failure-mode/security:**
- TST-001: auth-middleware rejects a request with no bearer token (missing auth)
- TST-002: auth-middleware rejects a token with an invalid signature (jwt-forgery)
- TST-003: auth-middleware rejects an expired JWT (jwt-forgery)
- TST-007: tasks-controller rejects missing title (WRN-001 validation path)

## (d) Resolver behaviour — did it advance to backend-api without rewriting system tests?

The --next resolver found:
1. docs/TEST-STRATEGY.yaml exists (status: complete) → skip system mode.
2. Testable containers from ARCH.yaml: web-frontend, backend-api, digest-worker (excluding primary-postgres [primary-database] and identity-provider [external]).
3. Specification order (providers before consumers by outgoing edges): backend-api has fewer outgoing container-level calls than web-frontend → backend-api first. digest-worker is also a consumer.
4. web-frontend: no docs/ARCH__web-frontend.yaml → NOT READY → skip with advisory.
5. backend-api: docs/ARCH__backend-api.yaml EXISTS → READY and un-specified → resolve to `/sdlc:test backend-api`.
6. Confirmed "Start backend-api" (simulated: position-1 / recommended choice).

The resolver produced docs/TEST-STRATEGY__backend-api.yaml. The system file's five existing tests (TST-001..TST-005) were left entirely intact. metadata.status in TEST-STRATEGY.yaml remained "complete". The only mutation to the system file was adding the `container_strategies` entry for backend-api and bumping `metadata.last_updated` + appending a changelog line.

## (e) Fan-out vs. enumerate — SKILL.md quote

The skill enumerates all container tests here rather than fanning out to `/sdlc:task`. The relevant SKILL.md sentence is:

> "Downstream agents — `task` (turns each `TST-NNN` into a test task) and the code-generation / verification stages — consume these artifacts as the **executable design contract** for the tests they write and run."

This means `/sdlc:test` is the place to enumerate every test in full detail; `/sdlc:task` then consumes each TST-NNN item and produces implementation tasks from it. The skill does NOT fan tests out or defer enumeration to `/sdlc:task` — it generates the complete, machine-readable test design so the task skill has a concrete item to schedule.

## (f) Final validator verdict

```
[OK] test strategy is valid and complete (TEST-STRATEGY.yaml, TEST-STRATEGY__backend-api.yaml).
```

Exit code: 0. All cross-checks passed: requirement coverage (FR-001..FR-004 each covered), acceptance coverage (tasks-controller and digest-settings-controller each targeted), risk coverage (postgres-unavailable and jwt-forgery and pii-in-logs each exercised), ID-format checks (TST-NNN unique within file, WRN-NNN format), trace integrity (all component_refs, targets_failure_mode, targets_security_concern resolve to ARCH__backend-api.yaml ids). No FR-005 reference appears in the container file.
