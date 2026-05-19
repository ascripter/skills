# Merge, validate, CLAUDE.md pointer — sdlc-arch

Read this on entering Phase 7 of either mode and at the end of Phase 7-D
(`-d` mode).

## Merge behaviour (Phase 7)

### System mode → `docs/ARCH.yaml`

If the file already exists (update flow):

1. Load it as a baseline.
2. For every confirmed answer in the active session: overwrite the
   corresponding key in the baseline.
3. For new keys (new containers / new edges added in this session):
   append.
4. For keys the session would *remove* (e.g. a dropped container or
   edge): ask the user to confirm before deleting. Default: keep.
5. **Preserve unrelated top-level keys** the agent doesn't recognize.
   `arch_warnings` is the only key the agent freely rewrites.
6. Surface conflicts (user-edited yaml vs. state file) — never
   auto-resolve. Ask which to keep.

Container mode is forbidden from touching `docs/ARCH.yaml` *except*:

- May set `containers[<id>].file_path` to point at the new
  `docs/ARCH__<container>.yaml` if the file was just created.
- May update top-level `metadata.last_updated`.

No other field in `ARCH.yaml` may be modified by container mode.

### Container mode → `docs/ARCH__<container>.yaml`

Same merge rules as above:

- Existing answers preserved unless the session changed them.
- New keys appended.
- Removals require user confirmation.
- Unrelated keys preserved.

After writing, run `set_claude_md_pointer.py` (Phase 8) — the bullet's
timestamp is updated regardless of which mode wrote.

## Validation (Phase 7)

Run:

```bash
python "${CLAUDE_SKILL_DIR}/validate_schema.py" --path docs/ARCH.yaml
```

This validates:

1. `docs/ARCH.yaml` against the Arch model.
2. Every sibling `docs/ARCH__*.yaml` against the ArchContainer model.
3. Required-field gates (status: complete cannot land if anything's
   missing).
4. Four cross-checks (always enabled in both modes):

   - **API-resource coverage** — every resource in `docs/API__*.yaml`
     appears in some container's `owns_api_resources`. Uncovered →
     `arch_warnings` and forces `status: draft`.
   - **UX-surface coverage** — every data-bearing surface in
     `docs/UX__*.yaml` appears in some container's `owns_ux_surfaces`.
     Uncovered → forces draft.
   - **DATA-store coverage** — every store in
     `DATA-MODEL.yaml.persistence.*` appears in some container's
     `persistence`. Uncovered → forces draft.
   - **Edge endpoint integrity** — every `edges[].from / to` (system)
     and `internal_edges[].from / to` / `external_edges[].from / to`
     (container) resolves to an existing node. Unresolved → forces
     draft.

5. Three container-vs-system consistency checks:

   - `api_surface` resource_ids ⊆ parent `owns_api_resources`.
   - `ux_surface` surface_ids ⊆ parent `owns_ux_surfaces`.
   - `persistence_bindings` store_ids ⊆ parent `persistence`.

### Exit-code recovery

| Exit | Meaning                                  | Action                                                     |
|------|------------------------------------------|------------------------------------------------------------|
| 0    | `[OK]` valid + complete, OR `[DRAFT]`.   | Proceed to Phase 8.                                        |
| 1    | Schema invalid, OR claims complete but   | Show errors. Offer per-error AskUserQuestion to fix, then  |
|      | required fields missing / checks failed. | re-run validator. If user prefers draft: set status: draft.|
| 2    | File missing or unparseable.             | Abort. Tell user the path that failed.                     |
| 3    | pydantic/pyyaml not installed.           | Tell user to `pip install pydantic pyyaml`. Skip validator.|

## `metadata.status` rules

- `complete` — set only when:
  - all required fields filled;
  - validator returns `[OK]`;
  - all four cross-checks pass (zero uncovered, zero unresolved edges);
  - all three container-vs-system consistency checks pass.
- `draft` — set on early EXIT, on any missing required field, or on
  any failing check.

If the user is about to set `complete` but the validator flags
problems, surface them via AskUserQuestion and let the user choose:

1. Fix now (re-enter the missing fields inline, re-validate).
2. Save as draft (set status: draft, keep going).
3. EXIT (save state, stop).

## CLAUDE.md pointer (Phase 8)

Call `set_claude_md_pointer.py` once Phase 7 succeeds. The script:

- Creates `CLAUDE.md` with the `## SDLC Documents` section if absent.
- Updates the timestamp on the existing `sdlc-arch` bullet if present.
- Appends the bullet to the section if the section exists but the
  bullet doesn't.

Detection rule (encoded in the script): a line matches if it starts
with `- ` AND contains both `` `docs/ARCH.yaml` `` and `` `sdlc-arch` ``.
Other `sdlc-*` bullets are left alone.

The exact bullet text (the script generates this):

```
- `docs/ARCH.yaml` (+ `docs/ARCH__<container>.yaml`): System architecture — pattern, container inventory, identity/auth, and per-container components + typed edges. Load when implementing containers, planning tests, or generating tasks. Last updated by `sdlc-arch` on <ISO-8601 timestamp>.
```

## Downstream-agent rejection rule

Document this so test/task/deploy can enforce it:

> **Downstream skills MUST reject `docs/ARCH.yaml` if
> `metadata.status != "complete"` OR if `validate_schema.py` exits
> non-zero.**

The same applies to each `docs/ARCH__<container>.yaml`. A draft container
file means that container has not been confirmed and is not safe to
generate code from.
