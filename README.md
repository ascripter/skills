# Skill Repo for Claude Code
Providing skills for software dev. Repo acts as a marketplace for skills

## Install
Execute both commands from the command line:
- Install the marketplace: `claude plugin marketplace add ascripter/skills`
- Install the plugin: `claude plugin install sdlc@ascripter-skills`

## Skills
All skills need to be explicitly invoked and will provide an interview mechanic that lets you define your software project step by step.

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

3. **`/sdlc:data`** → `DATA-MODEL.yaml`
    
   Define data storage (SQL, graph, document, key-value or vector database, or simple filesystem storage), then all data entities and their relations. 

4. **`/sdlc:api`** (optional) → `API.yaml` + `API__<resource>.yaml` 

   If the app has an api, use this skill next. 

5. **`/sdlc:arch --next`** → `ARCH.yaml` or `ARCH__<container>.yaml` (context sensitive)

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

7. **`/sdlc:test <container>`** → `TEST-STRATEGY__<container>.yaml`
  
   Execute once per container to define its test strategy. 

8. **`/sdlc:task <container>`** → `TASKS__<container>.yaml`

   Create ALL coding tasks. 

9. **`/sdlc:deploy`** → `DEPLOY.yaml`
   
   Deployment strategy document. 
   

   

*NOTE: Steps 7 to 9 are not yet implemented*