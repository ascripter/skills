/skill-creator:skill-creator Read project conventions in `CLAUDE.md` and the
reference implementation `sdlc/skills/prd/` (its SKILL.md, prd-questions.yaml,
PRD.schema.yaml, validate_schema.py, set_claude_md_pointer.py, and all files
under references/). Do not read any other skills. Then create the second SDLC
skill, `ux`, at `sdlc/skills/ux/`, following the CLAUDE.md contract exactly.

The `ux` skill produces a machine-readable UX specification for a software
product. Outputs are consumed exclusively by downstream AI coding agents
(api → arch → test → task → deploy). No human reading is assumed in the
output files — they must be precise enough for a coding agent to implement
screens, flows, and interactions without ambiguity.

## Inputs (read at startup, never re-asked)

- `docs/PRD.yaml` — must exist and have `metadata.status == "complete"`.
  Validate by running `python sdlc/skills/prd/validate_schema.py --path docs/PRD.yaml`
  before proceeding. Exit early with a clear warning if the file is absent,
  invalid, or `status: draft`.
- `interview` — clarifying questions asked during execution via
  AskUserQuestion.

## Outputs

- `docs/UX.yaml` — global UX contract for the product.
- `docs/UX__<surface>.yaml` — one file per UI surface (screen, modal, panel,
  CLI command, flow step). `<surface>` is kebab-case (same convention
  `sdlc:arch` uses for components).

### `docs/UX.yaml` covers cross-cutting UX

- Surface family (cli | web | mobile | desktop | mixed) — derived from
  `PRD.technical_constraints.runtime_platform`; confirmed with the user.
- Design principles (3–7 tenets).
- Navigation model (sitemap for graphical UIs; command tree for CLI;
  state graph if neither).
- Component library choice + theming tokens (colors, spacing, type).
- Accessibility baseline (WCAG level, keyboard-only paths, etc.).
- Content rules (tone, error-message style, copy guidelines).
- Localisation rules.
- Standard error / loading / empty / success state patterns.
- For CLI products: argument-parsing library, help-text format, exit-code
  conventions, output-format conventions (table / json / plain / yaml).

### `docs/UX__<surface>.yaml` covers one surface

- `surface_id` (kebab-case, unique).
- `surface_type` (screen | modal | panel | cli_command | flow_step | …).
- `entry_conditions` / `exit_conditions`.
- `layout` (region tree for graphical UIs; argument structure for CLI).
- `states`: default | loading | empty | error | success — each with
  concrete rendered content placeholders.
- `interactions`: ordered list of user actions with preconditions,
  effects, and target-surface transitions.
- `components`: list with variants and content slots.
- `validation_rules` (for input fields).
- `accessibility_notes`.
- `traces_prd_flows`: list of PRD `use_cases.core_workflows` entries this
  surface participates in (used by the coverage check below).

## Coverage check (mandatory before `status: complete`)

Before setting `metadata.status: complete` on `docs/UX.yaml`, the skill MUST
verify that every entry under `PRD.use_cases.core_workflows` is referenced
by at least one `UX__<surface>.yaml` via that surface's `traces_prd_flows`
field. Workflows without a surface trace are listed in `ux_warnings` on
`UX.yaml` and force `status: draft`.

## CLI products

When `PRD.technical_constraints.runtime_platform == "cli"`, the skill MUST
run a CLI-specific theme block covering:

- Subcommand tree (root command + verbs + nouns).
- Argument parsing library + conventions (POSIX, GNU, custom).
- Help-text format (auto-generated vs. authored).
- Output formats (table | json | plain | yaml) and the default.
- Exit codes (per-command).
- Interactive mode? (prompt-style? readline?)
- Configuration file location + precedence (cli flag > env > config > default).

Each subcommand or interactive prompt becomes its own `UX__<command>.yaml`.

## Conventions to follow (per CLAUDE.md)

- Skill folder: `sdlc/skills/ux/`. Frontmatter `name: ux`.
- Invocation: `/sdlc:ux` (plugin-namespaced).
- State file: `.claude/skills-state/sdlc-ux.state.yaml`. Extend the base
  state schema with `defined_surfaces: []` (each entry: surface_id,
  surface_type, status ∈ {defined, draft, confirmed}, file_path).
- Question inventory: `ux-questions.yaml` — `themes` + `questions` blocks,
  each question carries `schema_path` (dotted path into the target
  output yaml).
- Schema files: `UX.schema.yaml` (global) and `UX__SURFACE.schema.yaml`
  (per-surface template). Both must be mirrored in `validate_schema.py`.
- Validator: `validate_schema.py` — validates `docs/UX.yaml` and every
  `docs/UX__*.yaml`, plus runs the PRD-flow coverage check. Exit codes
  per CLAUDE.md (0 valid, 1 invalid or status=complete-but-incomplete,
  2 read/parse error, 3 missing dep).
- Pointer: `set_claude_md_pointer.py` upserts the single bullet under
  `## SDLC Documents`:

  ```
  - `docs/UX.yaml` (+ `docs/UX__<surface>.yaml`): UX surfaces, flows, components, and states. Load when working on UI implementation, flow wiring, or component contracts. Last updated by `sdlc-ux` on <ISO-8601 timestamp>.
  ```

- References folder (required):
  - `references/interview-mechanics.md` — batch format (mirror prd patterns;
    keep DRY by referencing prd's file only if you intend to factor that
    file out; otherwise copy the relevant rules).
  - `references/surface-discovery.md` — how to enumerate surfaces from PRD
    workflows; how `surface_id`s are generated and renamed; per-surface
    state-machine (defined → draft → confirmed).
  - `references/cli-ux.md` — CLI-specific guidance, loaded only when the
    runtime_platform is `cli`.
  - `references/merge-validate.md` — write/merge rules for `UX.yaml` and
    `UX__<surface>.yaml`, the flow-coverage check, and the CLAUDE.md
    pointer (use the bullet shown above).
  - `references/edge-cases.md` — surfaceless flow, conflicting design
    decisions across surfaces, mid-interview platform change, deleted
    PRD workflows mid-session, etc.

## Frontmatter

```yaml
---
name: ux
description: >
  Explicitly invoked skill. Creates or updates docs/UX.yaml plus one
  docs/UX__<surface>.yaml per UI surface. Trigger only on /sdlc:ux or
  a direct natural-language request to start the UX surface skill. Do
  not auto-trigger from generic UI/design chatter.
user-invocable: true
disable-model-invocation: true
model: opus
effort: xhigh
allowed-tools: Read Write(CLAUDE.md) Write(docs/UX.yaml) Write(docs/UX__*.yaml) Write(.claude/skills-state/sdlc-ux.state.yaml) Bash Bash(ls *) Glob Grep AskUserQuestion
---
```

## Themes for `ux-questions.yaml` (canonical interview order)

1. `platform_and_shell` — required. Confirm/refine runtime platform;
   for CLI capture subcommand model; for web/mobile capture device
   targets and viewport breakpoints.
2. `design_principles` — required. 3–7 tenets that govern all surfaces.
3. `navigation_model` — required. Sitemap / command tree / state graph.
4. `surface_inventory` — required, `synthesis: true`. Synthesized from
   PRD workflows; per-item drill-down (importance: critical) to confirm
   each surface, its type, and its trace back to PRD flows.
5. `component_library` — required. Library choice + rationale; theming
   tokens.
6. `state_patterns` — required. Standard rules for default / loading /
   empty / error / success across all surfaces.
7. `content_rules` — required. Tone, error-message style, copy.
8. `accessibility` — required. WCAG target, keyboard-only paths,
   screen-reader notes.
9. `localisation` — optional (now/skip/todo gate).
10. `cli_specifics` — `required_if: runtime_platform == "cli"`.
11. `per_surface_deepdive` — required, `synthesis: true`. For each
    surface from theme 4: layout, states, interactions, components,
    validation, accessibility notes, `traces_prd_flows`.

Importance tiers:

- Theme 4 and 11 → `critical` (per-item drill-down).
- Themes 2, 3, 5, 7 → mostly `high` (agent drafts; user iterates).
- Remainder → `med` (batched 2–4 per AskUserQuestion call).

## Test cases (per CLAUDE.md test-case guidance, adapted)

1. Empty project + missing PRD → exit early with a clear warning.
2. PRD.yaml present but `status: draft` → exit early, or offer to proceed
   with `ux_warnings` (deliberate behaviour to be defined).
3. PRD.yaml complete (web product) → generate UX.yaml + N UX__<surface>.yaml,
   coverage check passes.
4. PRD.yaml complete (CLI product) → cli_specifics theme runs;
   per-command surfaces generated.
5. Resume from state file (no UX output yet) → resumes at correct
   surface.
6. Resume from state file (with UX outputs present) → merges new answers;
   asks before deleting any surface.
7. Coverage failure → at least one PRD flow has no surface trace →
   status forced to `draft`, flow listed in `ux_warnings`.
8. CLAUDE.md pointer: absent → file created with `## SDLC Documents`
   section and a single UX bullet; bullet present with old timestamp →
   timestamp updated; section present but UX bullet missing → bullet
   appended at section end; existing prd bullet must be left untouched.

## Research to do before writing the skill

1. Existing UX-specification standards downstream agents may benefit from
   (Storybook component metadata, design tokens / DTCG, ARIA roles).
2. Common CLI UX conventions (POSIX argument syntax; Click / Typer /
   argparse for Python; Cobra for Go; oclif for Node).
3. Whether the per-surface yaml should embed component contracts inline
   or reference a separate component-library yaml. Recommendation:
   embed for v1, leave an exit path for a later split.
