# Interview mechanics

Detailed rules for how the agent runs the question batches in Phase 6 and
Phase 7. Read this when entering Phase 6 (the required-themes interview)
or Phase 7 (the optional-themes step-through).

## Batch format

For each unanswered question (whose `required: true` or whose `required_if`
condition has fired), present a **batch of 3–5 questions** in this format:

```
## Theme: Problem & Opportunity (3 questions)
You can answer all at once like: "1: Acme, 2: free-text, 3a"
Type EXIT at any time to save and stop.

1) What user pain or unmet need does this product address?
   (free text)

2) Who specifically feels this pain?
   a) End consumers
   b) Small business operators
   c) Engineers / developers
   d) Internal team / coworkers
   e) (your own)

3) Why is this the right moment to build this?
   a) New AI capability makes it possible
   b) Regulatory change forces it
   c) Competitor moved
   d) (your own)
```

Format rules:

- Number each question (`1)`, `2)`, `3)`).
- For multi-choice questions, label options `a)`, `b)`, `c)` etc.
- Always show the "type EXIT" reminder at the top of every batch.
- Always show a one-line example of the batch-answer format.
- Batches are 3–5 questions: never fewer than 3 (waste) or more than 5
  (overwhelm).

## Parsing user replies

Parse flexibly. The user may write:

- `1a, 2b, 3c` — choose option a/b/c for each question.
- `1: Acme Inc, 2b, 3: Move fast` — mix free text and option letters.
- `1, 2, 3 skip` — skip all (writes `null` + warning).
- `EXIT` — abort.

If parsing is ambiguous, ask a single clarifying question rather than
guessing.

After every batch is confirmed, **write state immediately** (do not wait
for the end of the theme). This is what makes EXIT safe.

## Capturing rationale

For questions marked `capture_rationale: true` in `product-questions.yaml`,
after the user picks, immediately ask one follow-up:

> "In one sentence — *why* this choice?"

Skippable. Stored at `<field>_rationale`.

## Type discipline when writing answers

`PRD.schema.yaml` specifies the expected type of every field. Many fields
are *lists* (e.g. `must_have_features`, `core_workflows`, `planned_phases`,
`key_entities`, `regulatory_requirements`).

When the user's free-text answer reads as multiple items (separated by `;`,
`,`, "and", numbered like `1) ... 2) ...`, or one-per-line), split it into
an actual YAML list. Single-item answers go in as a one-element list.

Never serialize a list-typed field as a single string — the validator will
reject it.

If the user answers "none" for a list-typed field, write an empty list
`[]`, not the string `"none"`.

## product_identity — the synthesis batch

Because product_identity comes **last** among required themes (see SKILL.md
Phase 6), the agent has rich context by the time it asks. Synthesize
candidates from all prior answers rather than asking cold:

```
## Theme: Product Identity (5 questions)

Based on what you've told me — a tool for designers to compose AI workflows,
targeting solo creators, with focus on speed and offline use — here are
some candidate names:

1) What is the product's name?
   ⚠ a) flowcraft   — emphasizes the assembly metaphor
   ⚠ b) mosaic       — pieces composing into a whole
   ⚠ c) loom         — weaving workflows
   d) (your own)

2) Preferred slug? (auto-derived from your name choice unless you type one)
   …

3) One-liner (≤140 chars):
   ⚠ a) "Compose AI workflows visually, run them anywhere — even offline."
   d) (your own)

4) Marketing tagline (optional, ≤8 words):
   …

5) Vision (1–3 years out, optional):
   …
```

Each `⚠`-marked candidate is an **inference** and triggers the hallucination
guard — the user must explicitly pick or write their own. Batch-shortcut
acceptance (`ok`, `1a, 2b, 3a`) is forbidden for `⚠` items, same as the
Phase 5 pre-fill confirmation rule.

Explicitly call out in the prompt that candidates were synthesized from the
prior answers. Don't pretend they came from nowhere.

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

When a question is promoted, surface this to the user transparently:

> "Because you set data_sensitivity to `regulated`, the security_compliance
> theme is now required. I'll ask those questions next."
