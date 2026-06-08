# sdlc-task eval suite

Four evals exercise the two interview modes, the `--next` resolver, and the
cross-file stitch. The task graph is the one sdlc artifact written as **JSON**
(machine-generated and machine-consumed by the codegen stage); the upstream specs
it reads stay YAML.

| # | name | invocation | what it gates |
|---|------|------------|---------------|
| 1 | `system-stitch-and-build-order` | `/sdlc:task` | the system file `docs/TASKS.json`: a topological `build_order` (provider-before-consumer per ARCH edges), a repo `scaffold` task, the **system-test coverage gate** (every `TST-NNN` in `TEST-STRATEGY.yaml` realized or deferred), union-graph **acyclicity**, system-kind vocabulary, TSK/WRN id formats |
| 2 | `container-coverage-gate` | `/sdlc:task backend-api` | the container file `docs/TASKS__backend-api.json` and the full **trace-or-defer gate**: every `ARCH__backend-api` component realized (`component_ref`) or deferred; every `TST-001..TST-008` realized (`implements_tests`) or deferred; no task `implements: FR-005`; every `implementation` task scoped; subgraph acyclic |
| 3 | `next-builds-container-before-system` | `/sdlc:task --next` | the resolver's **reversed order** — containers FIRST, system stitch LAST (the opposite of `sdlc:test`). The binary canary: it produces `TASKS__backend-api.json` and **must NOT** produce `TASKS.json`. Skips not-ready `web-frontend`/`digest-worker`; same container coverage gate applies |
| 4 | `cross-file-stitch-system-over-existing-container` | `/sdlc:task` (with a pre-built `TASKS__backend-api.json` on disk) | the **two-file stitch end-to-end**: system mode run over an already-built container. Gates that `container_task_graphs[]` registers backend-api, that ≥1 system task carries a **cross-file** `depends_on: backend-api/TSK-NNN` resolving into the container, that the **union graph across both files** resolves and is acyclic, that the container file is left **unchanged** (mode-boundary rule), and that the validator passes on both files with no file_path/unresolved-dep warning |

Two assertions matter most. **Eval 3 / "docs/TASKS.json does NOT exist"**
distinguishes `sdlc:task --next` (build ready containers first, stitch the system
graph last) from `sdlc:test --next` (system first). **Eval 4 / "≥1 system task
depends on `backend-api/TSK-NNN`" + "union graph across both files resolves &
acyclic"** is the only place the cross-file `depends_on` resolution is actually
walked across coexisting files — every other eval produces a single task file, so
the cross-file half of the union-graph check is otherwise dead code.

## Fixtures

The upstream chain is reused from the `sdlc-test` suite's validator-clean
`web-app-with-digest-job` project (tinytrack: a small task tracker with a weekly
digest worker). The task skill consumes the same `PRD`/`DATA-MODEL`/`ARCH`
chain, and crucially consumes the **`test` skill's outputs as its own inputs** —
the system `TEST-STRATEGY.yaml` and the container `TEST-STRATEGY__backend-api.yaml`.

- `fixtures/web-app/docs/` — base chain + the **system** `ARCH.yaml` (no
  container `file_path`) + the system `TEST-STRATEGY.yaml` (TST-001..TST-005).
  Used by eval 1.
- `fixtures/web-app-container/docs/` — the **container** `ARCH.yaml`
  (`backend-api.file_path` set) + `ARCH__backend-api.yaml` (5 components) +
  `TEST-STRATEGY__backend-api.yaml` (TST-001..TST-008). Used by evals 2/3/4.
- `fixtures/web-app-stitch/docs/` — a **pre-built** container task file
  `TASKS__backend-api.json` (byte-identical to the gold container; same-file deps
  only). Eval 4 stages it as an *input* so system mode runs over an
  already-built container and the two files coexist. Used by eval 4.
- `_gold/` — reference *correct* outputs (`TASKS.json`,
  `TASKS__backend-api.json`, and `TASKS.stitched.json` — the system file stitched
  over the pre-built container). **Not** staged as inputs; used only to self-test
  the suite (see below).

An eval may pull files from several scenario dirs as long as no two map to the
same destination — that's how evals 2/3 reuse the base chain while overriding
`ARCH.yaml` with the container variant and adding the per-container test strategy.

## Running

```bash
# 1. stage per-eval test-project dirs under sdlc-task-workspace/iteration-N/
python sdlc/skills/task/evals/stage_iteration.py --iteration 1

# 2. run each eval: a subagent per eval treats its test-project/ as the project
#    root and runs the sdlc-task skill with that eval's prompt, writing outputs
#    into test-project/docs/ (TASKS.json and/or TASKS__*.json).

# 3. grade: structural checks (trace-or-defer coverage, the union-graph
#    acyclicity stitch, build_order ordering) + the validator exit-code, per eval
python sdlc/skills/task/evals/grade.py --iteration 1   # writes benchmark.md
```

The workspace (`sdlc-task-workspace/`) is generated and git-ignored.

## Self-test (validator + grader agree)

`grade.py`'s structural checks mirror the validator's trace-or-defer + stitch
semantics, so before spending subagent runs you can confirm they agree:

```bash
python sdlc/skills/task/evals/selftest.py
```

It stages the three `_gold` outputs, then asserts: the system gold, the
container gold, and the **stitch gold** (the stitched system file + the pre-built
container coexisting) each validate `[OK] complete` **and** score every grade.py
assertion green; and two corruptions each flip **both** the validator (exit 1)
and grade.py (must-assertions fail) — (a) a container gold with an illegal
`implements: [FR-005]` plus a dropped component task, and (b) a **stitch** gold
whose system task points a cross-file `depends_on` at a non-existent
`backend-api/TSK-999`. If either half stays green on a corrupted input, there is
a gap in the validator or the grader. Exit 0 = they agree.

## Coverage note

Evals 1–3 each produce a single task file (system *or* container), mirroring the
`sdlc-test` suite — the *standalone* container files intentionally carry only
same-file dependencies (a container built before the system stitch must stay
internally resolvable; see `references/edge-cases.md`). **Eval 4 closes the
cross-file gap**: it stages a pre-built `TASKS__backend-api.json` as an input and
runs system mode over it, so `docs/TASKS.json` and `docs/TASKS__backend-api.json`
coexist and the union-graph check actually walks a cross-file `depends_on`
(`backend-api/TSK-NNN`) across files — the direction system→container that a real
`--next` run produces once the system stitch comes last. The reverse direction (a
container task pointing at `TASKS/TSK-NNN`) is exercised by the schema/validator
and the self-test gold, but the skill never authors it in the normal flow (system
mode must not edit a container file), so no eval requires the skill to produce it.
