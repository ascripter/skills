# AI-directed shorthand notation

Process flows and gate guards inside this skill use a compact arrow
notation. It is written for an LLM agent to read and follow, not for
human-first reading. Lines are short, structure is explicit, and there
are no narrative connectors.

## Why

A six-line natural-language paragraph and a one-line arrow flow encode
the same control flow. The arrow flow is faster to parse, harder to
misread, and survives translation between agents without rewording.

Use this notation in:

- `prompt-templates.yaml` `process:` fields.
- Gate-guard descriptions inside SKILL.md.
- Process flows in any reference file under `references/`.

Do **not** use this notation in artifact content (`ARCHITECTURE.yaml`,
`<container>.yaml`, etc.). Artifacts are declarative — they describe
what the system *is*, not what the skill *does*.

## Grammar

### Nodes

A node is either a bare identifier or an identifier with a parenthesized
intent label.

```
Discover
Normalize
AskUser(why this conflict?)
```

Identifiers use `PascalCase` for steps and `lowerCamel` or
`kebab-case` for variables. The intent label is free text in
parentheses, ≤40 characters, and is informational only.

### Transitions

A transition is `From -> To`.

```
Discover -> Normalize
Normalize -> Ask
```

Use `->` (ASCII hyphen + greater-than). Do not mix in `→` (U+2192) —
the ASCII form is unambiguous and grep-friendly.

### Guarded transitions

A guard goes in square brackets between the arrow and the target.

```
Evaluate ->[missing] Ask
Evaluate ->[enough] Write
Validate ->[ok] Persist
Validate ->[fail] Rollback
```

Guards are short tokens or short phrases. They are read as
"if guard then take this transition". Sibling guards from the same
source are mutually exclusive — the first one whose condition holds
fires.

### Branch lists

Multiple guarded transitions from the same source can be written on one
line, separated by commas:

```
Evaluate ->[missing] Ask, ->[enough] Write
```

This is equivalent to two separate `Evaluate ->[…] …` lines.

### Loops

Use `loop:` to introduce a repeating block, then `until:` for the exit
condition. Inner steps are indented two spaces.

```
loop:
  Generate -> StructuralGate -> AskHuman
until: humanApproves
```

`loop:` without `until:` is invalid — every loop must declare its exit.

### End of flow

Flows end with the last named step or with an explicit `Done` node.
There is no separate terminator symbol.

## Worked examples

A two-step interview with a feedback loop:

```
Discover -> Normalize -> Ask -> Evaluate
Evaluate ->[missing] Ask, ->[enough] Write
Write -> Done
```

A conflict-resolution flow:

```
Load -> Compare
Compare ->[no-conflict] Done
Compare ->[conflict] AskUser -> Merge -> Persist -> Done
```

An edge-derivation flow:

```
Inventory -> Match -> Resolve -> Diff -> Confirm
Confirm ->[approved] Persist -> Done
Confirm ->[edits] Apply -> Persist -> Done
Confirm ->[reject] Done
```

## Anti-patterns

- Don't embed multi-sentence prose inside a node label. Move
  explanation to a `focus:` field next to the `process:` field.
- Don't use Unicode arrows (`→`, `⇒`). ASCII `->` only.
- Don't nest brackets in guards. Keep guards flat tokens or short
  phrases. If a guard needs structure, split into multiple steps.
- Don't write a loop without `until:`.
