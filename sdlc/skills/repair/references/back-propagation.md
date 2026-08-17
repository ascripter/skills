# Back-propagation — finding to source stage (sdlc-repair)

Read this on entering Phase 2. It answers one question per finding: **which
artifact's content is actually wrong?**

The question matters because the artifact a defect *surfaces in* is almost never
the artifact that *caused* it. A codegen worker cannot see PRD; it sees a task
embed, so every defect looks like a task defect from there. Fixing what you can
see is how a pipeline develops a permanent limp: the same defect returns the
next time anything regenerates.

---

## The rule

> Walk **backwards** along the pipeline from where the finding surfaced, and
> stop at the **earliest artifact whose content is wrong** — the first stage
> where the missing or contradictory fact *should have been recorded and was
> not*.

```
prd ─► ux ─► design ─► data ─► api ─► arch ─► test ─► task ─► code
 ▲                                                              │
 └──────────────── walk back from the surfacing site ───────────┘
```

Two absolutes:

- **Never localize to `code`.** Generated code is an output, never a source. A
  defect *in* generated code is a `failed` task for `/sdlc:code` to heal, not a
  finding. If a finding localizes to `code`, it was mis-raised — close it
  `wontfix` with that reason.
- **Never localize to an embed.** A task's `interface_contract`, `test_spec`,
  `operation_contract`, `entity_slice`, `design_spec` and `config_keys` are
  *write-time copies* of upstream slices. Per CLAUDE.md §9 an embed is never the
  source; the artifact it was copied from is. See "Embed vs source" below.

## Step 1 — Embed vs source

When a finding names a task embed, read the upstream slice it was copied from
and compare. There are only two outcomes, and they localize differently:

| Comparison | What happened | Source |
|---|---|---|
| the source says the **same wrong thing** | the defect was authored upstream and faithfully copied | the **upstream artifact** — fix there, then re-slice |
| the source says **something different** | the embed is **stale**; upstream moved after the slice was taken | the **embed is out of date**, upstream is fine — the fix is a re-slice, not an edit to either |

Both are fixed by editing/regenerating from upstream. Neither is ever fixed by
hand-patching the embed to say what you wish it said — that re-diverges on the
next regeneration and trips the task validator's drift advisory (cross-check
#20) either way.

Note the asymmetry this creates in the resolution record: a same-wrong-thing
case has `located_stage` upstream; a stale-embed case has `located_stage: task`
with `mode: re-invoke` (or a surgical re-slice), because nothing upstream is
wrong.

## Step 2 — "Where should this fact live?"

For a finding of missing or underdetermined information, the source is the
stage that *owns* that class of fact. This table is the whole heuristic:

| The missing fact is… | Owner |
|---|---|
| a callable's inputs / output / raises | `arch` — the component's `work_units[]` entry |
| …unless the work unit `traces_api_operation` | `api` — the operation's request/response/error schemas |
| an HTTP route, status code, payload shape, CLI flag contract | `api` |
| a persisted field, relation, constraint, or index | `data` |
| a screen, CLI surface, field, state, or navigation step | `ux` |
| a design token, theme value, or asset brief | `design` |
| a behaviour rule, threshold, budget, or acceptance criterion | `prd` — an FR / NFR / ACR |
| a test's tier, directive, subject, or acceptance | `test` |
| a file path, dependency edge, or task decomposition | `task` |
| a container, component, boundary, or edge | `arch` |

Walk up the table until you find a stage where the fact **should** appear and
does not. If it appears at a stage and is simply *wrong*, that stage is the
source and you can stop walking.

## Step 3 — Per-kind localization

### `contract_underdetermined`

Start at the ARCH `work_unit`. Three sub-cases:

1. The work_unit declares the fact but ambiguously → **`arch`**.
2. The work_unit defers via `traces_api_operation` → follow it; the operation's
   schemas are the contract → **`api`**.
3. The work_unit is silent *because nothing upstream ever decided the
   behaviour* (the acceptance demands an outcome no requirement describes) →
   **`prd`**. This is the case teams most often mis-file as an ARCH gap; the
   tell is that filling it in ARCH requires inventing product behaviour.

### `test_contradicts_contract`

Two candidates — the TST and the contract — and exactly one adjudicator: trace
**both** to their PRD requirements.

- The FR/NFR/ACR supports the test → the **contract** is wrong (`arch` or
  `api`).
- The FR/NFR/ACR supports the contract → the **test** is wrong (`test`).
- The FR/NFR/ACR supports neither, or is ambiguous enough to support both →
  **`prd`** is the source. The disagreement downstream is a *symptom* of an
  under-specified requirement, and fixing either side alone leaves the other
  free to drift back.

Never resolve this by "the code passes, so the test is wrong". The contract, not
the implementation, is the arbiter.

### `missing_requirement`

A downstream artifact demands behaviour with no FR/NFR behind it. Two honest
readings, and the user picks:

- the behaviour is legitimate and PRD simply missed it → **`prd`**, add the
  requirement (and let coverage propagate);
- the behaviour is **scope the downstream stage invented** → the downstream
  artifact is the source; remove or defer it there.

Do not default to adding an FR. Silently promoting invented scope into the PRD
is how a spec grows features nobody asked for.

### `missing_operation` / `missing_entity`

A call site with no API operation → **`api`**. Persisted state with no
DATA-MODEL entity → **`data`**. But check the upstream direction first: if the
container legitimately should not be reaching for that operation or entity at
all, the source is **`arch`** (a wrong edge or a mis-assigned responsibility),
not a missing definition.

### `wrong_path` / `missing_dependency_edge` / `impossible_acceptance`

Task-graph defects → **`task`**. One exception worth checking: an
`impossible_acceptance` whose text was copied verbatim from an upstream ACR that
is itself unsatisfiable localizes to **`prd`**.

### `validator_error`

The validator names the artifact and the field. That artifact is the source
*unless* the error is a coverage/trace failure pointing at an upstream id — then
walk to the artifact that owns the id.

### `crosscheck_broken_ref` / `dangling_reference`

A reference no longer resolves. Which side is stale? Use the reference graph
rather than guessing:

```bash
python .claude/sdlc/docs_index.py --refs <symbol>
```

- The id is referenced from **many** places but is absent from its definer →
  the definer lost it (a bad edit or a rename that didn't propagate). Source is
  the **defining artifact**.
- **One** dangling reference against an id that was legitimately renamed or
  retired upstream → source is the **referencing artifact**; it holds a stale
  copy.

This is also the cheapest localization in the set — run it before reasoning.

## Step 4 — Confidence, and when to ask

Localization is a judgement, and the queue records a `suspected_stage` from the
raiser that is explicitly **not** authoritative. Present your conclusion to the
user with the walk that produced it (surfacing site → stages examined →
chosen source → why), not just the verdict. A user who disagrees usually knows
something the artifacts do not record.

Ask — do not decide alone — whenever:

- the finding is `missing_requirement` (scope questions are always the user's);
- two stages are equally defensible and the artifacts do not adjudicate;
- the fix would change product behaviour rather than clarify a description;
- the walk terminates at `prd` (a PRD edit ripples through everything
  downstream and deserves an explicit decision).

Proceed without asking when the walk is mechanical and the fix is a
clarification: a stale embed re-slice, a dangling ref whose owner is obvious
from `--refs`, a validator error naming one field.
