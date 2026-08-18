# Skill Repo for Claude Code
Providing skills for software dev. Repo acts as a marketplace for skills

The `sdlc` plugin is an **SDLC factory**: each skill produces a machine-readable spec that the next skill consumes, ending in an execution stage that writes the actual source files. The downstream consumer of every artifact is an AI agent, not a human — so the YAML/JSON is optimized for unambiguous machine consumption (typed enums, stable `ID-NNN` families, explicit `null` for unanswered fields) rather than for reading like a document.

## Install
Execute both commands from the command line:
- Install the marketplace: `claude plugin marketplace add ascripter/skills`
- Install the plugin: `claude plugin install sdlc@ascripter-skills`

## Skills
All skills need to be explicitly invoked. Most of them provide an interview mechanic that lets you define your software project step by step. Three are different: `/sdlc:setup` is a one-off installer, `/sdlc:code` executes the task graph instead of interviewing, and `/sdlc:repair` derives its questions per defect rather than from a fixed inventory.

In general, if an interview skill is invoked, three things are checked:
- Is it first time invocation? → generate initial output
- If previous run was interrupted → resume
- Consecutive invocation AND upstream documents have changed → a **delta review** surfaces every added / removed / modified upstream item before the interview, so you decide per item whether to incorporate, ignore or defer it

Typing `EXIT` into any question's free-text field stops the session; progress is saved and the next invocation offers to resume.

Execute the following skills in order within your project repo. All skills put their output into **`docs/`** in the repo root (fixed; can't be configured currently).

0. **`/sdlc:setup`**

   Bootstrap the project once, before `/sdlc:prd`. Installs a generated `docs/INDEX.yaml` — a line-range location map over the large specs plus a cross-reference graph — together with the generator (`.claude/sdlc/docs_index.py`), a `PostToolUse` hook that refreshes the index on every `docs/*.yaml` and `docs/TASKS*.json` edit, and the slice-don't-slurp access rule. This is what keeps later stages cheap: skills read big specs *by slice* instead of loading them whole. Idempotent — re-running also upgrades an installed copy.

1. **`/sdlc:prd`** → `PRD.yaml`
   
   Product requirements. The skill scans everything already present in the repo, so having already a README or other project docs is beneficial at this stage. 

2. **`/sdlc:ux`** → `UX.yaml` + `UX__<surface>.yaml`
   
   Define frontend type (desktop, mobile, web, cli) and UX surfaces for it.

3. **`/sdlc:design`** → `DESIGN.yaml` (+ `DESIGN__tokens.yaml`, `DESIGN__assets.yaml`)

   Create design manifest (depending on type of software). Token-based UIs additionally get `DESIGN__tokens.yaml`; projects with an asset pipeline get `DESIGN__assets.yaml`.

4. **`/sdlc:data`** → `DATA-MODEL.yaml`
    
   Define data storage (SQL, graph, document, key-value or vector database, or simple filesystem storage), then all data entities and their relations. 

5. **`/sdlc:api`** (optional) → `API.yaml` + `API__<resource>.yaml` 

   If the app has an api, use this skill next. 

6. **`/sdlc:arch --next`** → `ARCH.yaml` or `ARCH__<container>.yaml` (context sensitive)

   On first invocation, define top-level architecture, including all containers (C2 in C4-model). On consecutive invocation, define the next container until all are present.
   
   The skill has more signatures shown below:
   - **`/sdlc:arch`** → `ARCH.yaml`
      
     Explicitly address system architecture
   
   - **`/sdlc:arch <container>`** → `ARCH__<container>.yaml`

     Explicitly address container architecture

   - **`/sdlc:arch -d`** → `ARCH.yaml`

     Update only dependency edges on system level

   - **`/sdlc:arch -d <container>`** → `ARCH__<container>.yaml`

     Update only dependency edges on container level

7. **`/sdlc:test --next`** → `TEST-STRATEGY.yaml` or `TEST-STRATEGY__<container>.yaml` (context sensitive)

   On first invocation, define the system-level test strategy. On consecutive invocations, define per-container test strategies until all containers are covered.

   The skill has more signatures shown below:
   - **`/sdlc:test`** → `TEST-STRATEGY.yaml`

     Explicitly address system test strategy

   - **`/sdlc:test <container>`** → `TEST-STRATEGY__<container>.yaml`

     Explicitly address per-container test strategy

8. **`/sdlc:task --next`** → `TASKS.json` or `TASKS__<container>.json` (context sensitive)

   On first invocation, produce per-container task subgraphs one at a time. Once all containers are done, stitch them into the system task graph. Tasks are **self-contained**: each embeds the contract, test spec or data slice it needs, so the execution stage doesn't re-read the upstream specs per task.

   The skill has more signatures shown below:
   - **`/sdlc:task`** → `TASKS.json`

     Explicitly address system task graph

   - **`/sdlc:task <container>`** → `TASKS__<container>.json`

     Explicitly address per-container task graph

9. **`/sdlc:code`** → source code files

   The execution stage: writes the actual source files the task graph defines. Works container-by-container through `build_order` (repo scaffold first, then one container at a time, then the cross-container integration/e2e tail), checkpointing at every component and container boundary. The session acts as a **manager** that dispatches worker subagents — one work unit each (an implementation task plus its unit-test task, test-first) verified with a test-and-heal loop (up to 3 attempts; the 3rd escalates to a stronger model in a fresh subagent). Re-running is always safe — an execution ledger tracks every finished task, so nothing is regenerated or overwritten without asking.

   The skill has more signatures shown below:
   - **`/sdlc:code <container>`** → that container's source files

     Execute only one container's task subgraph, then stop.

   - **`/sdlc:code --next`** → the next incomplete unit (context sensitive)

     Execute exactly one unit of `build_order`, then report what `--next` would do next.

   Any of the three forms takes the modifier **`--parallel <N>`** (N ≤ 3, default **1**). Dispatch is **serial by default** on purpose: under a per-window token cap, three workers complete the same number of units per window as one — they just burn the budget faster — while an interrupted run loses three in-flight units instead of one. Raise it only when the cap isn't the binding constraint; concurrent units must have disjoint target files, which the scheduler enforces.

   Besides the code itself the skill maintains `docs/CODE-MANIFEST.json` — a machine-readable manifest of every generated file (path, hash, producing task ids, heal telemetry, verification level).

   See [Long codegen runs](#long-codegen-runs) below for checkpoints, budgets and how to resume after an interruption.

10. **`/sdlc:repair`** → edits to whichever `docs/` artifact actually holds the defect

    Not a linear stage — invoke it whenever the chain needs diagnosing. It is the only skill that **walks backward**: it runs a doctor sweep (every validator, the cross-artifact linter, the dangling-reference gate), merges that with the `FND-NNN` findings `/sdlc:code` raised during codegen, then localizes each defect to the *earliest* artifact whose content is actually wrong — not the stage that noticed it — fixes it there, and propagates the fix forward along the computed reference graph.

    Two fix modes: **surgical** when only the content of existing items changes (edit the source, bump its version, re-slice every task embed copied from it), and **re-invoke** when the *set* of downstream items changes — then it fixes the source and hands you the exact downstream command sequence, because those stages are interviews you own.

    The skill has more signatures shown below:
    - **`/sdlc:repair --check`** → report only

      Read-only doctor sweep. Records findings, edits nothing. This is the form to run before starting a long codegen session, and in CI.

    - **`/sdlc:repair FND-003 FND-005`** → those findings only

      Skip the sweep and work only the named findings.

    No special handback is needed: repairing a task artifact changes its fingerprint, so `/sdlc:code` shows the affected tasks as `stale` at its next plan gate and asks whether to regenerate them.

11. **`/sdlc:deploy`** → `DEPLOY.yaml`

    Deployment strategy document.


*NOTE: Step 11 is not yet implemented*

## Long codegen runs

`/sdlc:code` is the only stage that can run for hours, so it's built to be interrupted cheaply.

- **Plan gate.** Before anything is written you approve the plan and set a **session budget** (default: stop after the next component) and a checkpoint policy.
- **Component checkpoints.** At every component boundary the run drains, executes the component test ring, prints a compact summary (tasks, ring exit, heals, escalations, new findings, budget, elapsed) and runs a quick doctor check. The default `adaptive` policy stops and asks only when something needs attention — a red ring, a failed or escalated task, a new finding, a red doctor check, the budget being reached, or a container boundary. Container boundaries always carry a continue/stop gate.
- **Breadcrumbs.** Workers record their progress per phase under `.claude/skills-state/sdlc-code/inflight/`. An interrupted unit resumes at its last completed phase instead of being regenerated — the difference between a few thousand tokens and a hundred thousand.
- **Resume card.** Every stop prints where you are and the exact command to continue. **Start a fresh session to resume** — don't `/resume` the dead one. The ledger is the handoff; a new run re-reads it in a couple of tool calls, whereas `/resume` replays the whole transcript for nothing.
- **Findings, not patches.** When codegen discovers that a *spec* is wrong, it records an `FND-NNN` finding and moves on. It never edits `docs/` itself — patching the copy it can reach would only re-diverge on the next regeneration. Run `/sdlc:repair` to work the queue.

## Where things are written

In the consumer project's repo root:

| Path | What |
|---|---|
| `docs/*.yaml`, `docs/TASKS*.json` | the spec chain — the artifacts each skill produces |
| `docs/INDEX.yaml` | generated navigation map + cross-reference graph (from `/sdlc:setup`) |
| `docs/CODE-MANIFEST.json` | manifest of every generated source file |
| `.claude/skills-state/sdlc-<skill>.state.yaml` | per-skill interview / execution state, kept as an audit trail |
| `.claude/skills-state/sdlc-findings.yaml` | the cross-skill `FND-NNN` queue — written by `code`, resolved by `repair` |
| `.claude/skills-state/sdlc-code/inflight/` | worker breadcrumbs for in-flight units |
| `.claude/sdlc/docs_index.py` | the index generator installed by `/sdlc:setup` |
| `CLAUDE.md` → `## SDLC Documents` | pointers each skill maintains so agents know what to load when |

## Repo layout (for contributors)

This repo is itself a Claude Code marketplace containing one plugin (`sdlc`). Output artifacts are produced at the *consumer* project's root, not here.

- `.claude-plugin/marketplace.json` — top-level marketplace manifest
- `sdlc/.claude-plugin/plugin.json` — the `sdlc` plugin manifest
- `sdlc/skills/<skill>/` — one folder per skill: `SKILL.md`, the question inventory, the canonical `*.schema.yaml`, a pydantic `validate_schema.py`, a `set_claude_md_pointer.py`, and a `references/` folder loaded on demand
- `sdlc/skills/<skill>/_smoke/` — validator fixtures (one valid, several intentionally broken)
- `sdlc/skills/<skill>/evals/` — eval prompts and graders
- `CLAUDE.md` — the authoring contract every skill follows

Install the Python toolchain (validators need `pydantic>=2` and `pyyaml`):

```bash
pip install -e .          # or: uv sync
```

Run a validator or a sweep by hand — script paths are relative to this repo, while
`--path` / `--docs-dir` point at the project you're checking:

```bash
python sdlc/skills/<skill>/validate_schema.py --path docs/PRD.yaml
python sdlc/skills/repair/doctor.py --docs-dir docs           # full sweep
python sdlc/skills/repair/doctor.py --docs-dir docs --quick   # cross-artifact linter only
```

Exit codes are uniform across every validator: `0` valid · `1` invalid (or `complete` with required fields missing) · `2` unreadable/unparseable · `3` missing dependency.
