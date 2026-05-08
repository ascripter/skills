/skill-creator:skill-creator A skill named "sdlc-ux" that consumes the outputs of "sdlc-prd" (`docs/PRD.yaml`) and "sdlc-arch" (`docs/ARCH.yaml`) and generates `docs/UX.yaml` (plus additional `docs/UX__<surface>.yaml` files if the skill deems necessary).

## Purpose
The ux skill understands the nature of the project so far by interpreting its input files. Then it interviews the user to produce a complete, machine-readable UX specification for a software product. Its outputs are consumed exclusively by AI coding agents and by the `sdlc-arch <container>` skill invocation pattern (or any other pattern involving arguments passed to `sdlc-arch`) — no human reading is assumed. The skill must produce artifacts that are precise enough for a coding agent to implement screens, flows, and interactions without ambiguity.

## Inputs (read at startup, never re-asked)
PRD.yaml — product scope, user types, flows, NFRs
ARCH.yaml — system context and containers, C1 and starting C2 level architecture definition based on C4 model

## Interview behavior
The skill drives an interactive interview based on a well researched and curated question repository as one of its references. It asks focused questions in logical groups, shows a completeness summary after each group, and only advances when the human confirms. It should challenge vague answers (e.g. "clean and simple") by asking for concrete examples or references, but always make sensible suggestions. It tracks open questions explicitly and flags them in the output.
As an orientation, please look up the question inventory and logic used in `/sdlc-prd` skill.

## Outputs

`docs/UX.yaml` — global UX contract: design principles, navigation model, component library choice, theming/tokens, accessibility baseline, content rules, localisation rules, error handling patterns, loading/empty/error states

`docs/UX__<surface>.yaml` — one file per named UI surface (screen, modal, panel, flow step): surface ID, entry/exit conditions, layout description, all states (default, loading, empty, error, success), interaction rules, component list with variants, content placeholders, validation rules, accessibility notes.
The naming of UI-surfaces should be handled the same way as in `/sdlc-arch` skill: kebap-case, and maintained also in a state file `.claude/skills-state/sdlc-ux.state.yaml`.

## State tracking
Maintain a `.claude/skills-state/sdlc-ux.state.yaml` that records: which surfaces have been defined, which are open/draft/confirmed, and which open questions remain unresolved. The skill reads this on startup so sessions are resumable.

## Constraints

Output is pure YAML only — no markdown prose in artifact files

All surface IDs must match container/component naming in ARCH.yaml

Every field that a coding agent needs must have a concrete value or an explicit flag (see question tracking in `sdlc-prd` skill).

The skill must validate that every user flow mentioned in PRD.yaml maps to at least one surface in `docs/UX__<surface>.yaml` before marking itself complete.

## Invocation

The skill is only invoked explicitly by the user. Most likely best with an own subagent (like)