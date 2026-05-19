/skill-creator:skill-creator Let's review the `arch` skill. Read it and its requirements / inputs. It was created before we had a major overhaul of `prd`, and before `ux` and `data` existed. So many in there might be obsolote.
Scan it for features / aspects that really add additional value compared to the other skills and the basic concept laid out in `CLAUDE.md`.
Consider that this `arch` skill is now different in that it needs to do two things:
1. System architecture, defining system boundaries and containers
2. Container specifics, i.e. component architecture.

My idea is two invocation patterns:
1. `/sdlc:arch` for system
2. `/sdlc:arch <container>` for an existing container name in `docs/ARCH.yaml`. The name should be validated, and that component shall then be created.

But also consider if it makes sense to split both demands into two different skills...

Ask me if anything is unclear before actually starting to make the skill.