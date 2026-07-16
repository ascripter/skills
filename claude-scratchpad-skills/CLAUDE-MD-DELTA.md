# CLAUDE-MD-DELTA — proposed amendments to the skills-repo CLAUDE.md

Applied by SPLAN5 step 6. Each block anchors on an excerpt of the current CLAUDE.md
(state as pasted 2026-07-16); re-locate at HEAD. Blocks E1–E4 execute decision D2
(pipeline-wide flat priority retirement); blocks N1–N4 add new numbered conventions
continuing the existing §1–§8 series.

---

## E1 — critical-tier example (D2)

FIND (Interview contract → Importance tiers):
> Reserve `critical` for scope-defining fields (e.g. MVP features in `prd`; surface
> inventory in `ux`).

REPLACE:
> Reserve `critical` for scope-defining fields (e.g. the feature inventory in `prd`;
> surface inventory in `ux`).

## E2 — §6a paired deferral loses its priority arm (D2)

FIND (§6a, the first bullet):
> …and `task` still emits the impl task, that impl task MUST be **post-MVP**
> (`priority: could`) or itself **deferred** in `task_warnings`. Otherwise the branch
> is built with no test.

REPLACE:
> …and `task` still emits the impl task, that impl task MUST itself be **deferred** in
> `task_warnings` (or the test restored). Otherwise the branch is built with no test.

Also in §6a's closing sentences, drop the parenthetical priority vocabulary if present
("post-MVP" phrasing) — the two honest resolutions are unchanged: defer both, or
restore the test.

## E3 — state the retirement once, where conventions live (D2)

ADD as a short paragraph at the top of "Cross-skill conventions":

> **No priority tiers, no MVP phases.** Every consumer of this skillset is built whole
> by `/sdlc:code` — an economic must/should/could split has no downstream consumer.
> PRD carries one flat `features` list (de-scoped ideas go to
> `open_questions.parking_lot`); tests and tasks carry no priority field; coverage
> gates scope to ALL FRs. Validators still *accept* legacy artifacts carrying the old
> split/fields (parse-and-ignore, loaders union the legacy lists) but new writes never
> emit them.

## E4 — code-skill row/description touch-ups (post-SPLAN4)

- In the `code` table row and prose: "…the PRD FR/NFR requirement statements…joined
  into each worker packet" → "…the PRD FR/NFR/WKF/ACR requirement statements
  (implementation `implements` and test `test_spec.covers` alike)…".
- In the `code` prose "Waves only contain tasks with pairwise-disjoint
  `target_files`" → append "(path-aware: a directory entry contains every path
  beneath it; directory-pinned tasks run solo)".

---

## N1 — §9. Fix upstream over warn (embedded copies)

ADD after §8:

> #### 9. Embedded-copy drift is repaired at the SOURCE, never on the copy
>
> Several artifacts embed write-time copies of upstream slices (a task's
> `interface_contract`/`test_spec`, family and CLI contracts). When an embedded copy
> must change, **edit the upstream artifact and re-slice** — never patch the embed in
> place. A patched embed re-diverges on the next regeneration and trips the drift
> advisory (task cross-check #20) either way. Corollary: a drift advisory is a signal
> to fix the upstream, not to silence the copy. (Surfaced hardening the AICF corpus:
> patching 10 task test_specs without their TSTs produced 10 drift advisories; the
> fix was authoring the same change on the 10 upstream TST entries.)

## N2 — §10. Version-gate new blocking validator rules

ADD after §9:

> #### 10. New blocking checks are version-gated
>
> A validator rule that can fail an artifact stamped `complete` by an earlier skill
> version must be gated on the artifact's declared `*_version`: older artifacts get a
> WARNING, artifacts at/after the version that introduced the rule get the ERROR. New
> checks over existing fields start as warnings. Precedent: task
> `interface_contract` ("REQUIRED … at artifact version >= 1.3; older artifacts warn
> instead"). Counter-example this rule exists to prevent: 0.3.6 hard-failed graphs
> 0.3.4 had stamped complete — while the same version's scheduler ran them fine.
> Validator and scheduler must agree on what makes a graph schedulable.

## N3 — §11. Measurement rule for gate commands

ADD after §10:

> #### 11. Never read an exit code after a pipe
>
> `cmd | tail -5; echo $?` reports **tail's** exit code, not the validator's. Run
> gate commands bare and capture the code directly
> (`cmd > out.txt 2>&1; echo $?`); record the numeric code, not a pass/fail
> impression. An upstream validator once ran false-green for a full fix-plan cycle
> behind a pipe, masking 294 real errors.

## N4 — §12. The test→subject seam (cross-skill contract)

ADD after §11:

> #### 12. Tests wire to their true subjects; shared test infra has one owner
>
> Cross-skill contract (test → task → code):
> - `test` names each unit-tier test's subject(s) in `targets_work_units`
>   (require-or-defer at `complete`), marks non-gating/eval tests with
>   `gating: false`, and declares shared test deliverables in
>   `shared_infrastructure`.
> - `task` wires each test task's `depends_on` to the impl task(s) of those subjects
>   (never to a per-component absorber or the scheduling tail), emits ONE
>   test-infrastructure task per container that every test depends on, and gives the
>   system scaffold ownership of the non-gating marker registration + default-suite
>   exclusion.
> - `code` relies on that edge: a worker unit is an impl task **plus the test tasks
>   whose `depends_on` reaches it** — mis-wired tests silently break test-first
>   pairing and the heal loop.
> Validator checks on the task side are warn-level and version-gated (§10).
