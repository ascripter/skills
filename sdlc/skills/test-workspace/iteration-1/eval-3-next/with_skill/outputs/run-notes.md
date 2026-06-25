# run-notes — eval-3-next with_skill

## (a) Total TST-NNN tests + count per tier

Total tests in TEST-STRATEGY__backend-api.yaml: **15**

| Tier        | Count | TST-IDs                              |
|-------------|-------|--------------------------------------|
| unit        | 4     | TST-001, TST-003, TST-004, TST-008   |
| integration | 7     | TST-005, TST-006, TST-009, TST-010, TST-011, TST-012, TST-013, TST-014 |
| security    | 2     | TST-002, TST-015                     |

Wait — corrected count:
- unit: TST-001, TST-003, TST-004, TST-007, TST-008 = 5
- integration: TST-005, TST-006, TST-009, TST-010, TST-011, TST-012, TST-013, TST-014 = 8
- security: TST-002, TST-015 = 2

Total: 15

## (b) Tests targeting tasks-controller and digest-settings-controller

**tasks-controller** (component_ref: tasks-controller):
- TST-004: create task returns 201 (acceptance criterion 1 — "Creating a task returns 201 with a persisted task id")
- TST-005: mark task done flips status and reads back (acceptance criterion 2 — "Marking a task done flips its status and is reflected on next read")
- TST-006: list tasks returns all tasks for the authenticated user (FR-001 additional coverage)
- TST-007: create task with missing title returns 400 (negative/validation, seeded from arch_warnings WRN-001)

**digest-settings-controller** (component_ref: digest-settings-controller):
- TST-010: enable digest and set send time persists and reads back (acceptance criterion 1 — "Enabling the digest and setting a send time persists and reads back")
- TST-011: recent digest runs are listed newest-first (acceptance criterion 2 — "Recent digest runs are listed newest-first")
- TST-012: disable digest persists and reads back (additional edge-case coverage for FR-004)

digest-settings-controller has TWO acceptance criteria. YES — each got its own test: TST-010 and TST-011 are distinct tests, one per criterion.

## (c) Negative/validation test for arch_warnings WRN-001 + invalid-input/error-path tests

**arch_warnings WRN-001** ("tasks-controller create has no documented input-validation rule"):
YES — TST-007 directly addresses this warning. It tests that a create-task request with a missing title field returns HTTP 400 and never reaches the persistence layer. This is flagged as `tier: unit, priority: should`, seeded explicitly from arch_warnings WRN-001.

**Other invalid-input/error-path tests beyond failure-mode/security:**
- TST-007: invalid payload (missing title) returns 400 — explicit error-path test for the controller validation gap.
- TST-001: unauthenticated request returns 401 — error path through auth-middleware (no bearer token).
- TST-014: postgres-unavailable failure mode — tests the error-surface path of the repository when the DB is unreachable.

## (d) Resolver behaviour

The --next resolver correctly:
- (a) Found docs/TEST-STRATEGY.yaml with status: complete — did NOT re-run system mode.
- (b) Identified web-frontend and digest-worker as un-specified but NOT ready (no ARCH__web-frontend.yaml, no ARCH__digest-worker.yaml) — skipped both with a note to run /sdlc:arch first.
- (c) Identified backend-api as un-specified AND ready (docs/ARCH__backend-api.yaml exists) — advanced to backend-api.
- Confirmed "Start backend-api" before launching the container interview.

The existing system tests (TST-001..TST-005) in TEST-STRATEGY.yaml are intact and unmodified. The system file's metadata.status remains "complete". The only mutation to the system file was registering backend-api under container_strategies[] and bumping last_updated/changelog — exactly the two fields SKILL.md permits container mode to mutate.

## (e) /sdlc:task fan-out question

From SKILL.md (verbatim):

> "Downstream, `task` maps **one `TST-NNN` → exactly one test task → one authored test** — a strict 1:1 expansion, never a fan-out. The Stage-14 codegen agent writes the single test that a `TST-NNN` describes and nothing more. So **every individual test you want the project to have must be enumerated here, each as its own `TST-NNN`.**"

This means /sdlc:task does NOT fan out tests — it creates exactly one task per TST-NNN. All 15 tests are enumerated individually here; no test was written as a placeholder expecting downstream expansion. Each TST-NNN is a fully specified, independently executable test.

## (f) Final validator verdict

```
[OK] test strategy is valid and complete (TEST-STRATEGY.yaml, TEST-STRATEGY__backend-api.yaml).
```

Both files pass the full validator suite including:
- All required fields present (status: complete)
- TST-NNN format and uniqueness within each file
- component_ref integrity (all refs resolve to ARCH__backend-api.yaml components)
- covers integrity (all FR refs are in the container's + components' implements_requirements; no FR-005)
- Risk target integrity (postgres-unavailable, jwt-forgery, pii-in-logs all targeted)
- Requirement coverage (FR-001, FR-002, FR-003, FR-004 all covered; FR-005 not touched)
- Acceptance coverage (tasks-controller and digest-settings-controller both targeted by component_ref tests)
- Risk coverage (all failure_modes and security_concerns exercised)
- System file workflow coverage still green (WKF-001/002/003 untouched)
