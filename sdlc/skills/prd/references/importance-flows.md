# Importance flows — running the interview by tier

Every question in `product-questions.yaml` carries an `importance` field:
`med | high | critical`. The tier dictates how the agent runs the
question — single batch entry, dedicated draft-approval loop, or full
per-item drill-down. Read this file when entering Phase 6 alongside
`interview-mechanics.md`.

The classification was made deliberately:

- **`critical`** is reserved for fields that define the MVP — currently
  only `functional_requirements.must_have_features` and
  `functional_requirements.nice_to_have_features`. These warrant the
  most expensive interaction because every downstream agent will read
  them and treat them as scope-of-record.
- **`high`** covers foundational narrative fields (e.g. `problem_statement`)
  and required list[string] fields (e.g. `core_workflows`, `primary_users`).
  Answers are expected to be longer than a single picked option, so the
  agent drafts the entry and the user approves or iterates.
- **`med`** is everything else — short strings, enums, bools, and well-
  bounded list[string] fields whose option menu covers most cases. These
  run inside ordinary 2–4-question `AskUserQuestion` batches per
  `interview-mechanics.md`.

A question's `importance` does NOT change its `required` semantics —
required `med` fields are still required; optional `high` fields are
still skippable via the now/skip/todo gate.

## How batching changes with tier

`med` questions batch together (2–4 per `AskUserQuestion` call) inside
their theme. `high` and `critical` questions are **never batched with
others** — they each run as their own mini-section, because their flow
is multi-turn and cannot share a call with sibling questions.

Inside a theme, run all `med` questions first (in 2–4-question batches),
then run each `high`/`critical` question as its own mini-section in
the order they appear in `product-questions.yaml`. Write state after
each mini-section completes, exactly like after a normal batch.

## The `med` flow (default)

Unchanged from prior behavior. Each `med` question goes into an
`AskUserQuestion` batch alongside up to 3 sibling `med` questions from
the same theme. The `⚠ inferred` candidate (if any) is the position-1
option; the user picks an option, types free text into "Other", or
types `EXIT`. Set `<field>_confidence: confirmed` (explicit pick or
typed answer) or `inferred` (accepted as-is).

## The `high` flow

### Scalar `high` fields (string)

These are: `problem_opportunity.problem_statement`, `milestones.mvp_scope`.

1. **Propose.** Compose a 2–4-sentence draft from prior context. Print
   it to the chat preceded by a one-line agent comment explaining what
   you drew on, e.g. *"Based on the README excerpt and your earlier
   users_personas answers, here's a draft for problem_statement:"*.
2. **Ask for approval.** `AskUserQuestion` with one question, two
   options:

   ```
   header: "Approve?"
   question: "Approve this <field> as-is, or iterate?"
   options:
     - { label: "Approve as-is", description: "Write this to PRD.yaml and continue." }
     - { label: "Iterate — type changes", description: "Use the text field to describe what to change, add, or remove." }
   ```

3. **On approve.** Write the answer with `<field>_confidence: confirmed`.
4. **On iterate.** Re-draft using the user's free-text guidance. Repeat
   steps 1–3 with the new draft.
5. **Iteration cap.** After 3 iterations on a single field, write the
   current draft, append a one-line `prd_warnings` entry naming the
   field, and move on. The user can always re-run the skill in update
   mode to keep tweaking.

### List[string] `high` fields

These are: `users_personas.primary_users`, `use_cases.core_workflows`,
`use_cases.primary_jobs_to_be_done`,
`functional_requirements.out_of_scope`,
`functional_requirements.integrations_required`,
`functional_requirements.ai_features`,
`non_functional_requirements.other`,
`data_model.key_entities`,
`milestones.phases`,
`risks_assumptions.top_risks`.

Each item gets a lighter version of the per-item flow:

1. **Propose first item.** Suggest a candidate item (title + ≤ 1
   sentence description) drawn from prior context. Use
   `AskUserQuestion`:

   ```
   header: "Item 1"
   question: "First <field-singular> — does this look right?"
   options:
     - { label: "<inferred title>", description: "<one-sentence description>. Confirm to add as-is." }
     - { label: "Alternative 1",    description: "<other candidate>." }
     - { label: "Alternative 2",    description: "<other candidate>." }
     - { label: "Other / type",     description: "Type your own item in the text field." }
   ```

2. **One clarifying round (only if user typed free text or you flagged
   risk).** If the user typed a free-text item or you see a meaningful
   gap (e.g. ambiguous scope, missing constraint), ask one targeted
   clarifying `AskUserQuestion`. If the user picked a suggested option
   as-is, skip this step.

3. **Add item.** Append to the running list. State-write.

4. **Next item or end.** Either suggest the next likely item (steps 1–3
   again, with item index incremented) or — if you've run out of
   suggestions — ask:

   ```
   header: "Add more?"
   question: "Add another <field-singular>, or wrap up <field>?"
   options:
     - { label: "Add another (I'll suggest)", description: "I'll propose a candidate next." }
     - { label: "Add my own",                  description: "Type the title in the text field." }
     - { label: "Done — wrap up <field>",      description: "Move on to the next question." }
   ```

5. **Cap.** Stop after the user picks "Done" or after 8 items
   (whichever first). For `core_workflows` the natural cap is 7 per
   schema; for others use 8 as a soft cap, then prompt the user
   explicitly if they want more.

After all items are collected, the list is the answer — no final
approval step is needed because every item was confirmed individually.

## The `critical` flow

Currently applies to `functional_requirements.must_have_features` and
`functional_requirements.nice_to_have_features`. This is the full
per-item state machine. Every item is challenged before it's accepted.

### Per-item state machine

For each item in the list:

#### Step a — propose or accept a candidate

`AskUserQuestion` with the inferred candidate as position-1, 2–3
alternatives the agent considers plausible, and "Other / type your own"
as the last option. The item at this stage is *title + ≤ 1 sentence
description only* — detail comes later.

```
header: "Feature N"
question: "Must-have feature #N — pick one or type your own."
options:
  - { label: "⚠ <inferred title>",   description: "⚠ <one-sentence description>. Drawn from <prior-answer source>." }
  - { label: "<alt candidate 1>",    description: "<one-sentence description>." }
  - { label: "<alt candidate 2>",    description: "<one-sentence description>." }
  - { label: "Other — type your own", description: "Use the text field. The agent will challenge it before accepting." }
```

If the user picks a suggested option → go to **step b** (skip a-2).
If the user types free text → go to **step a-2** (challenge it first).

#### Step a-2 — challenge (free-text only)

Look at the user's typed item against everything answered so far. If
you see a meaningful risk — scope ambiguity, dependency conflict,
contradiction with `out_of_scope` or `users_personas`, technical
infeasibility under the chosen stack — surface it in **one**
`AskUserQuestion`:

```
header: "Risk check"
question: "Before adding '<user's text>', one concern: <risk>. How do you want to handle it?"
options:
  - { label: "<proposed resolution 1>", description: "<one-sentence explanation>." }
  - { label: "<proposed resolution 2>", description: "<one-sentence explanation>." }
  - { label: "Keep as-is anyway",       description: "Accept the item without changing it. A note will be added to prd_warnings." }
  - { label: "Reword — type",           description: "Type a revised title/description in the text field." }
```

If you don't see a concrete risk, skip this step. Don't manufacture
risks — challenge is for adding signal, not for forcing iteration.

#### Step b — detail it further

Now expand the item from title → full entry. Surface 2–3 detail
candidates the agent considers plausible (scope notes, acceptance
criteria, dependencies) plus a free-text option:

```
header: "Detail"
question: "Detail for '<title>' — pick the framing or write your own."
options:
  - { label: "⚠ <detailed candidate 1>", description: "⚠ <2–3 sentence detailed feature spec>." }
  - { label: "<detailed candidate 2>",    description: "<alternative framing>." }
  - { label: "<detailed candidate 3>",    description: "<alternative framing>." }
  - { label: "Other — type the full detail", description: "Use the text field." }
```

If the user picks a suggested option → go to **step c** (skip b-2).
If the user types free text → go to **step b-2**.

#### Step b-2 — second-pass clarification (free-text only)

If the user's free-text detail leaves a meaningful gap (e.g. doesn't
say what success looks like for the feature, or contradicts something
earlier), ask **one** more `AskUserQuestion` to pin it down. Otherwise
proceed to step c. Do not loop here — at most one b-2 round.

#### Step c — finalize

Print the drafted feature entry to the chat as a YAML snippet — title +
detail, exactly as it would appear in `must_have_features`. Then ask:

```
header: "Approve?"
question: "Add this feature to must_have_features?"
options:
  - { label: "Approve — add it",         description: "Append the drafted entry to the list and move on." }
  - { label: "Iterate — type changes",   description: "Use the text field to describe what to change. The agent will re-draft." }
```

On iterate: re-enter step b with the user's revision as new context.
**Iteration cap**: after 3 c-iterations on a single item, append the
current draft, add a `prd_warnings` entry naming the feature, and
proceed to step d.

#### Step d — next item or end

Once an item is approved (or capped):

- If you can think of another likely must-have from the user's prior
  answers, propose it directly via step a again (with the next item
  index).
- If you've exhausted your suggestions, ask:

  ```
  header: "Add more?"
  question: "Add another must-have, or are we done with this list?"
  options:
    - { label: "Add another (I'll suggest)", description: "I'll propose a candidate next." }
    - { label: "Add my own",                  description: "Type the title; we'll work through it from step a-2." }
    - { label: "Done — wrap up the list",     description: "Move on to nice_to_have_features." }
  ```

### Caps

- **Soft cap**: 10 items per critical list (per the schema hint
  `must_have_features` = 3–10).
- **Hard cap**: 15. After that, refuse politely and suggest moving the
  rest to `nice_to_have_features`.

### State-write timing

Write state after each item's step c approval, not at the end of the
list. This keeps `EXIT` cheap.

### Confidence

Items added via step a (user picked a suggestion as-is) get
`confidence: inferred`. Items that went through any free-text
iteration get `confidence: confirmed`. The whole list inherits the
*lowest* confidence of its items if you record list-level confidence.

## product_identity — the synthesis batch

`product_identity` is asked LAST among required themes so the agent has
rich context by the time it runs. All `product_identity` fields are
`med` (the heavy lifting was already done by `product_identity.idea_text`,
captured verbatim in Phase 3). They run as a single `AskUserQuestion`
batch where every candidate option is `⚠ inferred` from prior answers.

Example:

```
AskUserQuestion(questions=[
  {
    header: "Identity",
    question: "What is the product's name? (Synthesized from your prior answers.)",
    options: [
      { label: "⚠ flowcraft", description: "⚠ Inferred from your assembly metaphor. Pick to confirm or use text field to correct." },
      { label: "⚠ mosaic",    description: "⚠ Pieces composing into a whole." },
      { label: "⚠ loom",      description: "⚠ Weaving workflows together." },
      { label: "Custom name", description: "Type your preferred name in the text field." }
    ]
  },
  {
    header: "Identity",
    question: "Preferred URL/package slug? (kebab-case)",
    options: [
      { label: "⚠ flowcraft", description: "⚠ Auto-derived from inferred name. Confirm or correct." },
      { label: "Custom slug", description: "Type a kebab-case slug in the text field." }
    ]
  },
  {
    header: "Identity",
    question: "Describe the product in one sentence (≤ 140 chars).",
    options: [
      { label: "⚠ Inferred one-liner", description: "⚠ \"Compose AI workflows visually, run them anywhere — even offline.\" Confirm or correct." },
      { label: "Custom one-liner", description: "Type your own in the text field." }
    ]
  }
])
```

**Hallucination guard**: all `⚠`-marked options require explicit
pick-or-correct from the user. Accepting one counts as confirmation;
the user can also use the "Other" field to correct. Never treat a
non-answer as implicit acceptance.

Explicitly call out in the batch header that candidates were
synthesized from prior answers — don't present them as facts.

## When the user EXITs mid-flow

`EXIT` works at every `AskUserQuestion` call regardless of tier. On
exit:

- For a `med` question: no special handling; state is written after the
  batch the question lived in, so the question's prior batch is saved.
- For a `high` mini-section: write whatever has been collected so far
  (e.g. the partial list for list[string] fields, or no value at all
  if no item was approved). Mark the field's `<field>_confidence` as
  `assumption` if any partial content was written.
- For a `critical` mini-section: write the partially-approved items
  to the list. The unfinished current item is dropped (not written
  partial). Set `<field>_confidence: assumption`. Add a `prd_warnings`
  entry: `"<field>: list incomplete — EXIT received mid-item N"`.

Then proceed with the normal abort flow from `interview-mechanics.md`:
set `status: aborted`, save state, confirm to user, stop.
