# C4 model guidance

C4 (Context, Container, Component, Code) is a hierarchical way to describe
software architecture at four zoom levels. Each level adds detail. Each
level should stand on its own as a description that a new engineer can read
without needing the levels above or below.

The skill writes one C4 level per artifact and never blends levels.

## Level 1 — Context

Captures the system as a single black box and its environment.

What to capture:

- System name and one-sentence purpose.
- Primary actors and user types.
- External systems the system depends on or feeds.
- Boundaries: what is explicitly in scope, what is explicitly out of scope.
- Key quality attributes (e.g. availability target, latency budget, cost
  ceiling, compliance constraints).
- Architecture pattern, chosen with justification (see
  `pattern-selection.yaml`).
- Top-level containers required to deliver the system.

## Level 2 — Container

A **container** in C4 is an independently runnable or deployable unit:
applications and data stores. In practice, this skill also accepts
operational primitives that behave as their own deployment unit:
queues / topics, blob storage buckets, schedulers, search indexes, and
managed services that have their own scaling and failure domain.

What to capture per container:

- Canonical name and aliases.
- Purpose and responsibilities.
- Technology / runtime (language, framework, hosting model).
- Persistence (if any).
- Dependencies — other containers, with typed and directional edges.
- Failure modes.
- Scaling and performance expectations.
- Security and privacy concerns.
- Observability hooks (logs, metrics, traces, alerts).
- Ownership and change cadence.
- Components that live inside it.

## Level 3 — Component

A **component** is a logical grouping of related functionality inside a
container, exposed through a well-defined interface. Components are not
deployed independently — they live inside their parent container and share
its runtime.

What to capture per component:

- Canonical name and aliases.
- Purpose and responsibility scope (and what is explicitly out of scope).
- Inputs and outputs.
- Dependencies — other components, repositories, external clients.
- Failure modes.
- Code units that live inside it.

## Level 4 — Code

Code-level entries describe individual interfaces, classes, functions,
handlers, jobs, workflows, schemas, events, API endpoints, queries, or
commands. They are the smallest unit captured by this skill.

What to capture per code unit:

- Canonical name and aliases.
- Kind: one of `interface`, `class`, `function`, `handler`, `job`,
  `workflow`, `schema`, `event`, `api-endpoint`, `query`, `command`.
- Summary.
- Inputs (types, sources) and outputs (types, sinks).
- Invariants that must hold before, during, or after execution.
- Dependencies — other code units, repositories, clients.
- Error behavior — what it raises, retries, or partially completes.
- Side effects — writes, events, external calls.
- Observability — log lines, metrics, span names.
- Auth / security impact.
- Versioning or compatibility constraints (where applicable).

### Storage and the split convention

By default, every code unit lives as one entry in the `code:` array of
its parent component artifact
(`docs/ARCH__<container>__<component>.yaml`). The
component artifact owns the prose; the per-node `status` lives only in
`.claude/skills-state/sdlc-arch.state.yaml`.

When a component accumulates many richly described code units, the
component artifact gets unwieldy. The skill emits a soft-cap warning
when the component file exceeds **40 KB** *or* **800 lines** (whichever
first). On warn, the recommended split:

- Move the offending code unit's full content into a per-code-unit
  file at
  `docs/ARCH__<container>__<component>__<code>.yaml`.
- Keep a stub entry in the parent component's `code:` array with just
  `canonical:`, `aliases:`, `kind:`, and a `split-file:` field whose
  value is the basename of the per-code-unit file. Anyone reading the
  stub knows where to find the rest.
- The per-code-unit file uses `c4-level: code` and a 3-element
  `node-path:`. Its schema is
  `references/artifact-schemas/code.schema.json`.

Splitting is opt-in per code unit, not per component — splitting only
the chatty units keeps the component file scannable while letting deep
detail live in its own file.

## Review checklist

For every element at every level, confirm:

1. It has a clear, distinctive name.
2. Its type is identified.
3. Its purpose is stated in one sentence.
4. Each relationship to another element is explicit, directional, and
   labeled with intent (e.g. `calls`, `reads`, `publishes`,
   `subscribes_to`).
5. It belongs at the level it lives in — not a level above or below.

## Common pitfalls to avoid

- Treating a library as a container.
- Mixing containers and components at the same level.
- Capturing implementation details at the context level.
- Writing prose instead of a structured artifact.
- Inferring containers or components that the repo evidence does not
  support.
- Recording an alias as a path component instead of resolving it to the
  canonical name first.
