# Example session

A full `/sdlc-arch` walkthrough: container-level interview, edge
derivation, and confirmation.

```
$ /sdlc-arch web-frontend

→ **/sdlc-arch <container>**
- /sdlc-arch
- /sdlc-arch <container> <component>
- /sdlc-arch <container> <component> <code>
- /sdlc-arch -d
- /sdlc-arch -d <container>
- /sdlc-arch -d [<container>] --auto

[Step 0.5] Checking upstream artifacts...
  docs/PRD.yaml  ... ok
  docs/UX.yaml   ... ok
  docs/DATA.yaml ... ok

web-frontend not found in graph, let's create it now!

  1. What is the purpose of this container?
  2. Who calls or uses this container, and how?
  3. What runtime, language, and key frameworks does it use?

> 1) Browser SPA for the operator console.
> 2) Operators in the office; calls backend-api over HTTPS.
> 3) React 18 + TypeScript, served by a static CDN.

  4. Does it own persistent state? If so, where and what shape?
  5. What are the dominant failure modes, and how are they handled?
  6. Which components must exist inside this container?

> 4) Only client-side: localStorage for session token + UI prefs.
> 5) Backend-api outage → render banner; auth failure → redirect.
> 6) routing, views, api-client, auth-integration.

I derived these edges for web-frontend:
  1. calls       → backend-api
  2. depends_on  → auth-provider

Confirm all, or edit:
> confirm

Wrote docs/ARCH__web-frontend.yaml (status: complete).
Updated .claude/skills-state/sdlc-arch.state.yaml.
Validation: ok.
```

## Notes on the above

- Step 0 replaces the matching signature line with `→` and bolds it.
- Step 0.5 runs silently when all checks pass; only errors are
  verbose.
- Questions are numbered consecutively, batched 3–5 per turn.
- Edge derivation scans the freshly-written content; the user can
  remove, add, or retype proposed edges inline.
- Writes are atomic (`<path>.tmp` rename) and the validator runs
  immediately after.
