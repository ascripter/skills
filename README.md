# Skill Repo for Claude Code
Providing skills for software dev. Repo acts as a marketplace for skills

## Install
Execute both commands from the command line:
- Install the marketplace: `claude plugin marketplace add ascripter/skills`
- Install the plugin: `claude plugin install sdlc@ascripter-skills`

## Skills
All skills need to be explicitly invoked and (except `/sdlc:code`, which executes the task graph instead of interviewing) provide an interview mechanic that lets you define your software project step by step.

In general, if a skill is invoked, three things are checked:
- Is it first time invocation? → generate initial output
- If previous run was interrupted → resume
- Consecutive invocation AND upstream documents have changed → incorporate changes

Execute the following skills in order within your project repo. All skills put their output into **`docs/`** in the repo root (fixed; can't be configured currently).

0. **`/sdlc:setup`**

   Bootstrap the project by adding hooks that downstream skills will need.

1. **`/sdlc:prd`** → `PRD.yaml`
   
   Product requirements. The skill scans everything already present in the repo, so having already a README or other project docs is beneficial at this stage. 

2. **`/sdlc:ux`** → `UX.yaml` + `UX__<surface>.yaml`
   
   Define frontend type (desktop, mobile, web, cli) and UX surfaces for it.

3. **`/sdlc:design`** → `DESIGN.yaml`

   Create design manifest (depending on type of software)

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

   On first invocation, produce per-container task subgraphs one at a time. Once all containers are done, stitch them into the system task graph.

   The skill has more signatures shown below:
   - **`/sdlc:task`** → `TASKS.json`

     Explicitly address system task graph

   - **`/sdlc:task <container>`** → `TASKS__<container>.json`

     Explicitly address per-container task graph

9. **`/sdlc:code --next`** → source code files (context sensitive)

   The execution stage: writes the actual source files the task graph defines. Each invocation of `--next` executes the next incomplete unit in `build_order` (repo scaffold first, then one container at a time, then the cross-container integration/e2e tail). Implementation tasks are interleaved with their unit-test tasks and verified with a test-and-heal loop (up to 3 attempts; the 3rd attempt escalates to a stronger model in a fresh subagent). Re-running is always safe — an execution ledger tracks every finished task, so nothing is regenerated or overwritten without asking.

   The skill has more signatures shown below:
   - **`/sdlc:code`** → all remaining source files

     Execute everything still pending across the whole stitched task graph.

   - **`/sdlc:code <container>`** → that container's source files

     Execute only one container's task subgraph.

   Besides the code itself the skill maintains `docs/CODE-MANIFEST.json` — a machine-readable manifest of every generated file (path, hash, producing task ids, heal telemetry).

10. **`/sdlc:deploy`** → `DEPLOY.yaml`

    Deployment strategy document.


*NOTE: Step 10 is not yet implemented*