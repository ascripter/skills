# run-notes: sdlc-test system mode — tinytrack

## (a) Test counts

Total TST-NNN tests: 12

| Tier          | Count | Test IDs                     |
|---------------|-------|------------------------------|
| e2e           | 3     | TST-001, TST-002, TST-003    |
| contract      | 4     | TST-004, TST-005, TST-006, TST-007 |
| security      | 2     | TST-008, TST-012             |
| load          | 1     | TST-009                      |
| accessibility | 2     | TST-010, TST-011             |

## (b) EDG-001 and PRD WRN-001

**EDG-001** (digest run with zero open tasks): Addressed inline in TST-003's directives as an explicit edge-case step ("repeat the test with zero open tasks; assert recipient_count=0 and no email is sent"). WRN-001 in test_strategy_warnings notes that the expected behaviour should be confirmed with the team before container-mode testing.

**PRD WRN-001** (digest send not idempotent across retries): Addressed directly by TST-012, a dedicated security/resilience test that exercises the double-invocation scenario. The test configures the stub SES to fail on the first call, invokes the digest-worker twice with the same run-slot identifier, and asserts exactly one DigestRun row and at most one successful SES delivery.

## (c) Fan-out vs. enumerate — the SKILL.md sentence that informed this

All 12 intended system-level tests are enumerated here as TST-NNN items in TEST-STRATEGY.yaml. The `/sdlc:task` skill consumes these items and turns each one into a test task (a TASKS.json entry). This skill does not fan tests out; it produces the executable design contract that task and codegen consume.

The relevant SKILL.md sentence: *"The test strategy is not prose. Every test is a typed TST-NNN item with `directives` (an arrange/act/assert sketch the codegen agent follows), `covers` (the upstream ids it verifies), and a machine-checkable `acceptance` line."*

## (d) Final validator verdict

```
[OK] test strategy is valid and complete (TEST-STRATEGY.yaml).
```
