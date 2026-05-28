# Skill Repo for Claude Code
Providing some plugins and skills for software dev.
Repo acts as a marketplace for skills

## Install
Execute both commands from the command line:
- Install the marketplace: `claude plugin marketplace add ascripter/skills`
- Install the plugin: `claude plugin install sdlc@ascripter-skills`

## Skills
All skills need to be explicitly invoked are will provide an interview mechanic that lets you define your software project step by step.

All skills put their output into **`docs/`** (fixed; can't be configured currently).

1. **`/sdlc:prd`** → `PRD.yaml`
   
   Product requirements. The skill scans everything already present in the repo, so if you have already a README or other project docs that's beneficial at this stage. 

2. **`/sdlc:ux`** → `UX.yaml` and `UX__<surface>.yaml`
   
   Define frontend type (desktop, mobile, web, cli) and UX surfaces for it.

3. **`/sdlc:data`** → `DATA-MODEL.yaml`
    
   Define data storage (SQL, graph, document, key-value or vector databse, or simple filesystem storage), then all data entities and their relations. 

4. **`/sdlc:api`** (optional) → `API.yaml` and `API__<resource>.yaml` 

   If the app has an api, use this skill next. 

5. **`/sdlc:arch`** → `ARCH.yaml`

   Define top-level architecture, including all containers (C2 in C4-model). 

6. **`/sdlc:arch <container>`** → `ARCH__<container>.yaml`

   Execute arch skill one per container defined in `ARCH.yaml` to define the components in this container. 

7. **`/sdlc:test <container>`** → `TEST-STRATEGY__<container>.yaml`
  
   Execute once per container to define its test strategy. 

8. **`/sdlc:task <container>`** → `TASKS__<container>.yaml`

   Create ALL coding tasks. 

9. **`/sdlc:deploy`** → `DEPLOY.yaml`
   
   Deployment strategy document. 
   

   

*NOTE: Steps 7 to 9 are not yet implemented*