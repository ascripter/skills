# Interview mechanics

Detailed rules for how the agent runs the question batches in Phase 6.
Read this when entering Phase 6 (the theme interview).

## AskUserQuestion call format

Each batch is **one `AskUserQuestion` call** covering 2–4 questions. Never
fewer than 2 (single-question interactions stall momentum) or more than 4
(the tool's hard limit).

Structure each question in the call as follows:

```
header:   ≤ 12 chars  — abbreviated theme label (e.g. "Problem", "Tech Stack")
question: full question text ending with "?"
options:  2–4 options ranked by relevance
multiSelect: true for list-typed fields (where the user may pick several)
```

### Option layout — the universal pattern

| Position | Content |
|---|---|
| **1** | Recommended / `⚠ inferred` answer — the top suggestion |
| **2** | First viable alternative |
| **3** | Second viable alternative |
| **4** | Third viable alternative. If more options exist beyond position 4, add to this option's `description`: `"Also: <option5>, <option6>, …. Use the text field to enter any of these or a custom answer."` |

The tool auto-adds an "Other" free-text entry below the explicit options.
The user can type any value there, including `EXIT`. Position 4 is the
last *explicit* option — its description surfaces the remaining menu items
so the user knows what's available without seeing them as selectable buttons.

### Free-text-only questions

For questions with no standard options (e.g. `problem_statement`,
`must_have_features`), all 2–4 positions carry `⚠ inferred` suggestions
drawn from the pre-fill map or Phase 3 idea text. The user picks one or
types their own via "Other".

### EXIT handling

The user aborts by typing `EXIT` (case-insensitive) in the "Other" text
field of any `AskUserQuestion` call. After every batch response, check
whether any field's answer equals `EXIT` before processing the values.
If detected, trigger the abort flow: write current state with
`status: aborted`, confirm to user, stop.

### Example batch (problem_opportunity, first 3 questions)

```
AskUserQuestion(questions=[
  {
    header: "Problem",
    question: "What user pain or unmet need does this product address?",
    options: [
      { label: "⚠ inferred: …", description: "Derived from README: '…'" },
      { label: "Manual process pain", description: "Users do this by hand today and it wastes time." },
      { label: "Missing data visibility", description: "Users can't see X without custom tooling." },
      { label: "Integration gap", description: "Two systems don't talk; manual syncing bridges them." }
    ],
    multiSelect: false
  },
  {
    header: "Problem",
    question: "Who specifically feels this pain?",
    options: [
      { label: "Software engineers", description: "Developers and DevOps practitioners." },
      { label: "Data analysts", description: "BI or data science teams." },
      { label: "Product / project managers", description: "Non-technical stakeholders." },
      { label: "Other", description: "Also: end consumers, small business operators, enterprise IT buyers. Use text field for anything else." }
    ],
    multiSelect: true
  },
  {
    header: "Problem",
    question: "How do affected people cope today?",
    options: [
      { label: "Manual / spreadsheets", description: "They track it in Excel or Notion." },
      { label: "Stitching tools", description: "Combining two or more existing tools with manual steps." },
      { label: "Competitor product", description: "Using a direct competitor." },
      { label: "Internal scripts", description: "Also: they simply don't (need goes unmet). Use text field for custom answer." }
    ],
    multiSelect: true
  }
])
```

## Parsing responses

After the `AskUserQuestion` call returns:

- **Picked option**: use the option label/value directly. Set
  `<field>_confidence: confirmed`.
- **"Other" free text**: use the text verbatim (after checking for `EXIT`).
  Set `<field>_confidence: confirmed` (explicit user input).
- **`⚠ inferred` option picked without change**: set
  `<field>_confidence: inferred`.

For `multiSelect` questions: collect all selected labels + any "Other" text
into a list.

If the response is ambiguous (e.g. free text that could map to multiple
fields), ask a single targeted clarifying `AskUserQuestion` before writing.

## Capturing rationale

For questions marked `capture_rationale: true` in `product-questions.yaml`,
immediately follow with a single-question `AskUserQuestion`:

```
header: "Why?"
question: "In one sentence — why this choice?"
options: [
  { label: "Skip", description: "No rationale needed." },
  { label: "Type reason", description: "Use the text field." }
]
```

Skippable. Stored at `<prd_path>_rationale`.

## Type discipline when writing answers

`PRD.schema.yaml` specifies the expected type of every field. Many fields
are *lists* (e.g. `must_have_features`, `core_workflows`, `phases`,
`key_entities`, `regulatory_requirements`).

When the user picks multiple options or types a multi-item free-text answer
(separated by `;`, `,`, "and", or one-per-line), split it into an actual
YAML list. Single-item answers go in as a one-element list.

Never serialize a list-typed field as a single string — the validator will
reject it.

If the user answers "none" for a list-typed field, write an empty list `[]`,
not the string `"none"`.

## product_identity — the synthesis batch

Because `product_identity` comes **last** among required themes, the agent
has rich context by the time it asks. Synthesize candidates from all prior
answers. Every synthesized value surfaces as the **position-1 recommended
option** in its question — not as a separate pre-fill step.

Example:

```
AskUserQuestion(questions=[
  {
    header: "Identity",
    question: "What is the product's name?",
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

**Hallucination guard**: all `⚠`-marked options require explicit pick-or-correct
from the user. Accepting one of them counts as confirmation; the user can also
use the "Other" field to provide a correction. Never treat a non-answer (no
selection) as implicit acceptance of a `⚠` candidate.

Explicitly call out in the batch header or question text that candidates were
synthesized from prior answers — don't present them as facts.

## Conditional promotions (`required_if`)

Some questions in `product-questions.yaml` carry a `required_if:` rule
(an expression evaluated against already-answered fields). Re-evaluate
these at the start of each new theme batch and promote them to required
if the condition holds. Current rules:

| Question | Becomes required when |
|---|---|
| `security_compliance.auth_model` | `data_sensitivity in ['restricted', 'regulated']` |
| `security_compliance.regulatory_requirements` | `data_sensitivity in ['restricted', 'regulated']` |
| `business_model.pricing_model` | `monetization not in ['internal_tool', 'open_source', 'free']` |
| `technical_constraints.browser_support` | `runtime_platform == 'web'` |
| `non_functional_requirements.performance_targets` | `scalability in ['large', 'hyperscale']` |

When a question is promoted, surface this to the user transparently in the
next batch header or as a single AskUserQuestion before starting that theme:

> "Because you set data_sensitivity to `regulated`, the security_compliance
> theme is now required. I'll ask those questions next."
