# Run Notes — sdlc-test container mode: backend-api

## (a) Total tests and per-tier counts

Total TST-NNN tests: **22**

| Tier        | Count | TST ids |
|-------------|-------|---------|
| unit        | 15    | TST-001..TST-015 |
| integration | 5     | TST-016..TST-020 |
| security    | 2     | TST-021..TST-022 |

(TST-020 is integration tier targeting the postgres-unavailable failure mode.)

## (b) Per-component test counts

**tasks-controller**: 5 tests (TST-005, TST-006, TST-007, TST-008, TST-009)
+ integration TST-016 (component_ref: tasks-controller) + TST-017 (component_ref: tasks-controller) = **7 tests** reference tasks-controller.

**digest-settings-controller**: 3 unit tests (TST-012, TST-013, TST-014) + integration TST-019 (component_ref: digest-settings-controller) = **4 tests** reference digest-settings-controller.

digest-settings-controller declares TWO acceptance criteria:
1. "Enabling the digest and setting a send time persists and reads back." → covered by TST-012 (unit) and TST-019 (integration).
2. "Recent digest runs are listed newest-first." → covered by TST-013 (unit) and TST-019 (integration, asserts ordering).

Each acceptance criterion received its own dedicated unit test (TST-012 and TST-013 respectively), plus TST-014 covers the disable path.

## (c) WRN-001 negative/validation tests

Yes, WRN-001 from arch_warnings ("tasks-controller create has no documented input-validation rule") was addressed. Two explicit negative/validation tests were authored:
- **TST-008**: POST /tasks with missing title → expect 400
- **TST-009**: POST /tasks with oversized title → expect 400

Beyond the failure-mode test (TST-020) and the security tests (TST-021, TST-022), the following additional invalid-input/error-path tests were authored:
- **TST-008**: missing required field (title)
- **TST-009**: oversized input (title > max length)
- **TST-011**: comment on non-existent task returns 404

## (d) Fan-out decision: enumerate all tests here vs. /sdlc:task

All tests were enumerated individually in this artifact, each as its own TST-NNN item. This follows the SKILL.md sentence:

> "The test strategy is not prose. Every test is a typed `TST-NNN` item with `directives` (an arrange/act/assert sketch the codegen agent follows), `covers` (the upstream ids it verifies), and a machine-checkable `acceptance` line."

And more explicitly:

> "every individual test you want the project to have must be enumerated here, each as its own `TST-NNN`. If a feature warrants a happy-path test plus three edge cases plus an auth-rejection case, that is *five* `TST-NNN` items in this artifact — not one 'test FR-012' item that a later stage is trusted to split apart. There is no later stage that splits it. (This is the exact trap to avoid: assuming `/sdlc:task` will 'fan out' a single test into many. It won't — it realizes one task per `TST-NNN`.)"

`/sdlc:task` maps one TST-NNN → exactly one test task → one authored test (1:1 expansion, no fan-out). All decomposition must happen here.

## (e) Final validator verdict

```
[OK] test strategy is valid and complete (TEST-STRATEGY.yaml, TEST-STRATEGY__backend-api.yaml).
```

Exit code: 0. All coverage cross-checks passed on first run (no iterative fixes needed).
