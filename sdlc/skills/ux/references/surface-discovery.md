# Surface discovery — how to enumerate, name, and deep-dive surfaces

Read this when entering **theme 4 (`surface_inventory`)** or **theme 11
(`per_surface_deepdive`)**. Both are `critical` per-item flows; this
file is the source of truth for how the agent drives them.

The core idea: **a surface is the smallest unit of UI the user
interacts with**. For graphical products that's typically a screen,
modal, panel, drawer, page, tab, dialog, overlay, or toast. For CLI
products that's typically one `cli_command` per verb+noun, plus one
`flow_step` per interactive prompt. A surface always has an `id`, a
`type`, entry/exit conditions, layout, states, and traces back to at
least one PRD flow.

## Step 1 — Generate the candidate list from PRD workflows

`PRD.use_cases.core_workflows` is the seed. For each workflow, propose
1–3 candidate surfaces likely to participate in it. Examples:

| PRD workflow | Likely surface(s) |
|---|---|
| "Add a task in under 3 seconds" (web) | `dashboard` (screen), `quick-add` (modal) |
| "Mark tasks done from the keyboard" (web) | `dashboard` (screen) |
| "Authenticate via SSO" (web) | `login` (screen), `sso-callback` (page) |
| "List my open tasks" (cli) | `task-list` (cli_command) |
| "Add a task" (cli) | `task-add` (cli_command), `task-add-prompt` (flow_step, if interactive) |
| "Bulk-update tasks" (web + cli) | `task-bulk-update-confirm` (modal), `task-update` (cli_command) |

Don't try to be exhaustive — the user will add, remove, or rename
surfaces during the per-item drill-down. Aim for a starter inventory
that covers every PRD flow with at least one candidate.

## Step 2 — Generate `surface_id`s

`surface_id` is kebab-case, unique within the project, and short
(≤ 32 chars). Rules:

- Derive from the dominant noun/verb of the surface, not the PRD flow.
- For CLI surfaces, mirror the invocation: `task add` → `task-add`,
  `project list` → `project-list`.
- For graphical surfaces, use the destination concept: `dashboard`,
  `project-detail`, `quick-add`.
- For modal/dialog/drawer surfaces, prefix with the host surface and
  the action: `task-bulk-update-confirm`, `project-archive-confirm`.
- Renames during the interview are fine — update the
  `state.defined_surfaces` entry and the (unwritten) deep-dive partial
  in one move. If the surface yaml has already been written under the
  old id, ask the user before deleting it.

## Step 3 — Per-surface state machine (theme 4)

For each candidate surface, run one mini-section that confirms the
identity (id, type, traces) but does NOT yet do the layout/states/etc
deep-dive — that's theme 11.

### State machine

Each surface progresses through three states tracked in
`state.defined_surfaces[i].status`:

| state | meaning |
|---|---|
| `defined`   | id + type known, no deep-dive started |
| `draft`     | deep-dive in progress (theme 11) |
| `confirmed` | deep-dive complete + user approved |

Theme 4 produces a list of `defined` surfaces. Theme 11 walks that list
and transitions each from `defined` → `draft` → `confirmed`.

### Per-item flow for theme 4

For each candidate surface from step 1:

#### a) Propose

```
header: "Surface N"
question: "Surface #N — confirm or revise?"
options:
  - { label: "⚠ <inferred id> (<type>)",   description: "⚠ <one-sentence purpose>. Traces PRD flow(s): <flow names>. Confirm or correct in text field." }
  - { label: "Rename surface",              description: "Type a different surface_id (kebab-case) in the text field." }
  - { label: "Change type",                 description: "screen | modal | panel | drawer | cli_command | flow_step | empty_state | toast | overlay | tab | page | dialog | other." }
  - { label: "Drop this candidate",         description: "Remove it from the inventory — no surface will be created." }
```

On accept → record `{ surface_id, surface_type, status: defined,
file_path: docs/UX__<surface_id>.yaml, traces_prd_flows: [<flow>] }`
in `state.defined_surfaces`, persist state.

On rename → re-run step a with the new id.

On drop → record the dropped candidate in
`state.dropped_surface_candidates` (so the agent knows not to re-propose
on resume). Don't write the file.

#### b) Confirm PRD flow trace

If the proposed traces miss a flow you'd expect, or if the user is
likely to add surfaces beyond what the agent inferred, ask a single
clarifying `AskUserQuestion`:

```
header: "Traces?"
question: "Which PRD flow(s) does '<surface_id>' participate in?"
options:
  - { label: "<inferred flow 1>",        description: "<verbatim PRD flow string>" }
  - { label: "<inferred flow 2>",        description: "<verbatim PRD flow string>" }
  - { label: "Other (type)",             description: "Type a flow string verbatim from PRD.use_cases.core_workflows." }
  - { label: "None — non-flow surface",  description: "This surface doesn't trace to any PRD flow. (Will be flagged in ux_warnings.)" }
multiSelect: true
```

#### c) Next or end

When the candidate list is exhausted, ask:

```
header: "More?"
question: "Add another surface, or wrap up the inventory?"
options:
  - { label: "Add another (I'll suggest)", description: "I'll propose a candidate next." }
  - { label: "Add my own",                  description: "Type a surface_id + type in the text field." }
  - { label: "Done — wrap up inventory",    description: "Move on to component_library." }
```

**Caps**: soft 12 surfaces, hard 20. Above the hard cap, refuse politely
and suggest splitting the product or pushing some surfaces to later
phases.

### Coverage hint at end of theme 4

Before finishing theme 4, check whether every
`PRD.use_cases.core_workflows` entry is referenced by at least one
inventory item's `traces_prd_flows`. If any are missing, tell the user
which ones and ask:

```
header: "Coverage?"
question: "These PRD flow(s) aren't covered by any surface yet: <flow names>. Add surfaces for them now?"
options:
  - { label: "Add surface(s) now",      description: "I'll propose one per uncovered flow." }
  - { label: "Leave gap — record in ux_warnings", description: "The flows will be listed in ux_warnings and UX.yaml will save as draft." }
  - { label: "Edit existing traces",    description: "Re-open an existing surface to add the missing flow to its traces." }
```

This is the soft coverage check. The hard check happens in
`validate_schema.py` (Phase 7).

## Step 4 — Per-surface deep-dive (theme 11)

For each surface in `state.defined_surfaces` (in order they were
defined), run the deep-dive. The deep-dive is the `critical` per-item
flow that writes the per-surface yaml.

### State transition

When the deep-dive starts for a surface, set its status to `draft` and
seed `state.partial_surfaces[<surface_id>]` with the known identity
(`surface_id`, `surface_type`, `traces_prd_flows`) plus empty values for
the rest.

When the deep-dive completes (after step e final approval), flip status
to `confirmed`, write the surface yaml to disk
(`docs/UX__<surface_id>.yaml`), and move the contents from
`state.partial_surfaces` into a permanent slot.

### Per-surface mini-interview (5 steps)

For each surface:

#### a) Announce + identity recap

Print to the chat:

> "Now: `<surface_id>` (`<surface_type>`). Traces PRD flow(s):
> `<flow names>`. 5 questions to fill in layout / states / interactions
> / components / accessibility."

(No `AskUserQuestion` here — it's a banner.)

#### b) Layout

Run the `surface.layout` question. For graphical surfaces, propose a
region tree (e.g. `header` + `content` + `footer`); for CLI surfaces,
propose an arg/flag structure. Use `AskUserQuestion` with 2–3 candidate
layouts and an "Other / type" option. Multi-turn iteration allowed (cap
3).

#### c) States

Run the `surface.states` question. By default, every state inherits
from the global `state_patterns` in UX.yaml — only ask the user to
override states that need to differ for this surface. The user can pick
"All five with global defaults" to short-circuit.

If the user picks an override, follow up with a single-question
`AskUserQuestion` for that state's `description` and
`content_outline`.

#### d) Interactions, components, validation_rules

Run these as three back-to-back `high` list[string] flows (per
`interview-mechanics.md`). For each:

- Propose 1–3 items inferred from PRD/feature context.
- Per-item: confirm/revise/drop, one optional clarifying round.
- Soft cap 8, hard cap 12.

`validation_rules` is skippable if the surface has no input fields —
ask the gate question first:

```
header: "Validation?"
question: "Does '<surface_id>' have input fields needing validation rules?"
options:
  - { label: "Yes — list them",        description: "I'll walk through field validations." }
  - { label: "No — skip",              description: "Leave validation_rules empty." }
  - { label: "Inherit from a sibling", description: "Copy validations from another surface (pick which)." }
```

#### e) Final approval

Print the drafted per-surface yaml (or a compact summary if it's long)
and ask:

```
header: "Approve?"
question: "Approve <surface_id> as drafted?"
options:
  - { label: "Approve — write to disk",       description: "Save docs/UX__<surface_id>.yaml and continue." }
  - { label: "Iterate — type changes",        description: "Use the text field to describe what to change. The agent will re-draft." }
  - { label: "Skip for now — keep as draft",  description: "Move on to the next surface; this one stays status: draft and the file is NOT written." }
```

On approve: write the surface yaml, flip status to `confirmed`,
persist state.

On iterate: re-enter step b/c/d with the user's revision context. After
3 iterations on a single surface, write the current draft and add a
`ux_warnings` entry naming the surface.

On skip: leave status `draft`, do NOT write the file (the validator
won't see it, but the entry remains in `state.defined_surfaces` and
`state.partial_surfaces` so the user can resume later).

### State-write timing

Persist state after each per-surface step (b/c/d/e), not just at the
end. This keeps EXIT cheap mid-deep-dive — the partial surface stays in
`state.partial_surfaces` and resumes cleanly.

## When the user EXITs mid-flow

- Mid-theme 4: write all confirmed inventory entries to
  `state.defined_surfaces`, drop the current candidate (it wasn't
  approved). Set `status: aborted`.
- Mid-theme 11 deep-dive on surface N: write the partial yaml content
  to `state.partial_surfaces[<surface_id>]`. Do NOT write the surface
  file to disk (it's incomplete). Set `status: aborted`. The
  `state.defined_surfaces[N].status` stays `draft`.

On resume, the agent picks up at the partial surface — it explicitly
asks the user *"Resume mid-deep-dive of `<surface_id>`?"* before
re-entering theme 11.

## Naming and renaming surfaces mid-flow

If the user renames a surface during theme 11:

1. If no file has been written yet → just update the id everywhere
   (`state.defined_surfaces`, `state.partial_surfaces`,
   `state.current_surface`).
2. If the file already exists → ask the user:
   *"Rename `docs/UX__<old>.yaml` → `docs/UX__<new>.yaml`? This will
   delete the old file."* Wait for explicit confirmation before
   deleting.

Surface ids are immutable post-completion only by convention — the user
can always rename via an update interview, but each rename forces a
file move and a coverage-check re-validation.

## Soft-deletion of dropped candidates

When the user drops a candidate in theme 4 step a:

- Record `{ surface_id, reason: "dropped by user", at: <timestamp> }`
  in `state.dropped_surface_candidates`.
- Don't propose the same id again on resume.
- The dropped surface is NOT written to `UX.yaml.surface_inventory`.
