# Identity Claim Boundary Plan

Status: draft — findings verified by reproduction; owner chose Option A on
2026-09-24; awaiting independent plan review.

Class: 5 (spec-changing) and risky under [DOM-5]: the change revises the
normative [IAN-3.3] step-4 anchor-match rule, specifies host-id derivation
under [IAN-3.2], and changes which selector-free read verbs persist claims.
Identity is a compatibility surface with durable state (`taut_identity_claims`,
member anchors), so hardening is required. Not process-changing.

Plan type: implementation with spec revision.

Owner: implementing engineer. The repository owner chose Option A on
2026-09-24 (see Execution Log).

## Goal

Make selector-free identity behave as [THEORY-2] describes it: deterministic
and inspectable. Two reproduced defects break that today. First, the
[IAN-3.3] step-4 anchor match compares stored member anchors against every
process in the captured ancestor chain, so the first selector-free command
a child agent runs binds that child's claim to its parent agent; after
`join --new` creates a separate member, `whoami` still answers with the
parent. Second, macOS host identity runs a bare `ioreg` and silently falls
back to `hostname:` when the executable is not on `PATH`, so the same
process is "unrecognized" under a cron-style `PATH`. A third, contained
defect is that `whoami`, `who`, and `list` persist a claim on every new
child process even though [IAN-10] says `whoami --explain` captures
evidence "without silently associating it". Evidence and reproduction
commands: `docs/plans/artifacts/2026-09-23-deep-dive-review.md` §1 items
1–2 and §3 A.

## Requested Outcomes

- [ ] A nested agent process is never bound to an ancestor member's claim
  on first contact; `join --new` followed by `whoami` from the same child
  answers with the new member.
- [ ] Host identity does not depend on `PATH`; when the platform source is
  unavailable, the fallback is explicit and specified, not silent.
- [ ] `whoami`, `whoami --explain`, `who`, and `list` resolve read-only:
  they select but never record a claim, heal an anchor, or create a member.
- [ ] [IAN-3.2] and [IAN-3.3] state the rules above; the SC-4 Windows
  shell-anchor migration in the active semantic-compatibility plan still
  works.

## Source Documents

Source specs:

- `docs/specs/03-identity-addressing-notifications.md` [IAN-2.3], [IAN-3.2],
  [IAN-3.3], [IAN-3.4], [IAN-9], [IAN-10]
- `docs/specs/02-taut-core.md` [TAUT-5], [TAUT-10] (the "two members in one
  ancestor chain" edge case and the host-id rationale)
- `docs/specs/01-development-documentation-operating-model.md` [DOM-5],
  [DOM-6], [DOM-15]

Supporting context:

- `docs/program-theory.md` [THEORY-2] (identity claim is deterministic and
  inspectable, never authenticated), [THEORY-5] A3 (no authentication;
  storage access is membership — this plan adds no verification).
- `docs/plans/2026-08-25-semantic-compatibility-hardening-plan.md` SC-4 and
  its "Hidden Couplings" paragraph: "A live legacy shell anchor may heal
  only through existing ancestor matching when the new capture is still an
  agent." The narrowed rule below preserves exactly that case.
- `docs/plans/2026-08-24-extension-seams-process-containment-coverage-plan.md`
  E1: promoted the read-only selected-member resolution paragraph now in
  [IAN-3.3]. This plan routes the read verbs through that existing mode.
- `docs/plans/artifacts/2026-09-23-deep-dive-review.md` §1 items 1–2.
- README "The Identity Trick".

## Spec Baseline

- `c0a4616e76e954e3f9fbea93fbf487c3ee660cbe` —
  `docs/specs/03-identity-addressing-notifications.md` and
  `docs/specs/02-taut-core.md` at plan authoring time; both unchanged through `c894059` (0.9.9 release SHA).
- Promotion baseline identifier: recorded after the spec-promotion slice.

## Proposed Spec Delta

Promotion strategy: **A — in-file edit, text before link claims**.

| Spec file | Strategy | Sections touched |
|-----------|----------|------------------|
| `docs/specs/03-identity-addressing-notifications.md` | A | [IAN-3.2] host id paragraph (new); [IAN-3.3] step 4; [IAN-3.3] read-only paragraph; [IAN-10] bullet; `## Related Plans` |

### [IAN-3.2] — insert after the "anchor start token" paragraph

> The host id is an opaque platform identity: `machine-id:<value>` from
> `/etc/machine-id` or `/var/lib/dbus/machine-id` on Linux, and
> `ioplatformuuid:<uuid>` on macOS read from the IOKit platform expert
> device by absolute tool path (`/usr/sbin/ioreg`) or an equivalent
> in-process query that does not depend on the caller's `PATH`. Windows
> uses the machine GUID from the registry. When the platform source is
> unavailable, Taut falls back to `hostname:<name>` **and** `whoami
> --explain` reports the fallback rule by name; the fallback is a distinct
> namespace and never silently produces a claim that a platform-sourced
> capture would not.

### [IAN-3.3] — replace step 4

Option A (**adopted 2026-09-24**; preserves SC-4):

> 4. Agent anchor match: when no claim hash matches and the capture is an
>    agent capture, resolution may match a stored member anchor by the
>    stable triple (`host_id`, `anchor_pid`, `anchor_start_time`),
>    comparing the [IAN-3.2] start token by exact equality, against **the
>    selected anchor itself**, or against an ancestor of the selected
>    anchor **only when that ancestor is not itself an agent-family
>    executable** (a shell, wrapper, or infrastructure process whose
>    earlier classification made it an anchor). This recovers continuity
>    when a live anchor process changed mutable claim inputs (working
>    directory, tty, process group) without restarting, and lets a legacy
>    shell-classified anchor heal after a classification change. It never
>    binds a child agent to a parent agent: an agent-family ancestor is not
>    a match, so the child resolves at step 6 and may create or `rejoin`
>    its own member. On a match, the resolver records the current claim
>    hash for that member so subsequent commands resolve at step 3. Anchor
>    match never applies under `join --new`, never overrides steps 1–3, and
>    never matches across hosts.

Option B (**rejected 2026-09-24**; retained as the recorded alternative, not
implementation authority — it keeps whole-chain matching with a second
reported rule):

> 4. …against the captured ancestor chain. A match on the selected anchor
>    records the current claim hash for that member. A match on an
>    ancestor above the selected anchor selects that member for the
>    current operation only, records no claim, and is reported by `whoami
>    --explain` as rule `ancestor anchor match`; a later `join --new` or
>    `rejoin` from the child binds the child's own claim.

### [IAN-3.3] — amend the read-only paragraph

Append to the paragraph beginning `A read-only selected-member resolution`:

> `whoami`, `whoami --explain`, `who`, and `list` use this read-only
> resolution. They report the member the full resolution would select and
> the rule that selected it, but they never record a claim, heal an anchor,
> update activity, or create a member. `whoami --explain` renders the
> captured evidence and the rule in the unrecognized case too.

### [IAN-10] — replace the `whoami --explain` bullet

> - `rejoin` captures and associates the current process claim, while
>   `whoami`, `whoami --explain`, `who`, and `list` capture current evidence
>   without associating it; a test drives three nested read-only commands
>   from a fresh child process and asserts the claim count is unchanged

### `## Related Plans` — add

> - `docs/plans/2026-09-24-identity-claim-boundary-plan.md` — narrows the
>   step-4 anchor match so a parent agent cannot capture a child agent,
>   specifies host-id derivation and its explicit fallback, and routes the
>   read verbs through read-only resolution.

## Context and Key Files

Files to modify:

- `taut/identity.py` — `capture_host_identity()` (line ~132–164): bare
  `["ioreg", ...]` subprocess with a silent `hostname:` fallback;
  `match_anchor(capture, members)` (line ~354–371): iterates the whole
  captured chain comparing `(host_id, pid, start_time)`.
- `taut/client/_identity.py` — `_resolve_member()` (line ~250–300, McCabe
  43, `[RUFF-SUP-047]`): step-4 branch calls `identity.match_anchor` and
  then `_record_claim(row, claim, active)` unless `_heal_claim` is false.
- `taut/commands/whoami.py`, `taut/commands/who.py`,
  `taut/commands/list.py` (or wherever these adapters live; confirm with
  `ls taut/commands/`) — call the client with the default (healing)
  resolver today.
- `tests/test_identity.py` — `test_match_anchor_returns_nearest_matching_member`
  (only the anchor's own position), `test_capture_host_identity_falls_back_to_hostname`
  (locks in the silent fallback), `test_anchor_match_survives_anchor_chdir_in_real_chain`
  (asserts `whoami --explain` heals; must be rewritten to assert it does
  not).

Read first:

- [IAN-3.2] and [IAN-3.3] in full; the E1 read-only resolution paragraph.
- `identity.py` classification helpers (`is_agent_executable` or the
  family tables — grep `family`) that decide "agent-family executable".
- SC-4 in the semantic-compatibility plan, lines ~215–225 and ~245–250.
- README "The Identity Trick" (the candidate diagnostic block).

Comprehension gate (answers in the Execution Log before editing):

1. **Why does SC-4 need ancestor matching at all?** Expected: after the
   Windows `.exe` classification change, a member whose stored anchor was a
   shell can only be recognized because that shell is still an ancestor of
   the newly selected agent anchor; without ancestor matching the member
   would be recreated.
2. **Why does Option A not break SC-4?** Expected: the legacy stored anchor
   is a shell-family executable, not an agent-family one, so it remains
   matchable; only agent-family ancestors are excluded.
3. **Where is the claim actually written in the step-4 path, and under
   which flag is it suppressed?** Expected: `_record_claim` inside
   `_resolve_member`; suppressed when `_heal_claim` is false or
   `_touch_activity` is false (read-only mode).

## Invariants and Constraints

- A3: no authentication is added. Narrowing the match makes a claim less
  likely to be *wrong*, not harder to *spoof*.
- Steps 1–3 and 5–6 of [IAN-3.3] are unchanged. `--as`, `TAUT_AS`, and
  tokens keep precedence and never teach a claim.
- `join --new` still never steals a claimed hash.
- The stored claim table format and member row format do not change.
- The unrecognized-caller diagnostic shape (`unrecognized caller`, the
  candidate block, the closing `or select…` line) is unchanged.
- `who` presence semantics (README-owned) are unchanged; only its
  resolution mode changes.
- The `[RUFF-SUP-047]` complexity suppression on `_resolve_member` must not
  grow; if the change would raise its complexity, extract the step-4 policy
  into a named helper rather than adding branches.
- No new dependency for the macOS platform UUID. `/usr/sbin/ioreg` by
  absolute path is acceptable; an in-process IOKit query via `ctypes` is
  acceptable only if it stays under 40 lines and has its own fake-API
  proof.

Hidden couplings:

- `test_anchor_match_survives_anchor_chdir_in_real_chain` and the
  README-owned "you may be one of these" diagnostic both depend on the
  candidate ranking from `identity.rank_candidates`, which is not changed.
- Summon's driver resolves the summoned member by token, not by process
  evidence; unaffected, but run its identity tests.
- MCP attaches by token and uses the read-only resolver (E1); unaffected.

Failure policy: a failed platform host-id read is best-effort (fallback
plus explicit rule name); a `match_anchor` exception remains fatal as today.

## Rollout, Rollback, and One-Way Doors

- Source revert restores the old rule. Claims recorded under the old rule
  remain valid claim rows; they are not migrated. A child agent already
  bound to its parent stays bound until it runs `join --new` or `rejoin`;
  document this in the CHANGELOG.
- Host-id change: members created under the `hostname:` fallback on macOS
  keep that host id. After the fix, a process on the same machine will
  capture `ioplatformuuid:` and may be unrecognized once; the existing
  candidate diagnostic and `rejoin` are the recovery. No automatic merge.
- One-way door: none in storage. The behavior change is reversible.
- Post-deploy signal: `env PATH=/usr/bin:/bin taut whoami` resolves the
  same member as `taut whoami`; a child process named like an agent binary
  creates its own member on `join --new` and keeps it on `whoami`.

## Dependency-Ordered Tasks

1. **Owner decision on Option A vs B**, recorded in the Execution Log.
2. **Independent plan review** including the delta and SC-4 interaction.
3. **Spec-promotion slice** (strategy A); record the promotion baseline.
4. **Red tests for the anchor rule.** `tests/test_identity.py`: build a
   real process chain (the existing real-chain fixtures) where the selected
   anchor is a child whose executable basename is an agent family (symlink
   `python` as `codex` in `tmp_path`, as the review did) and an ancestor is
   a known member's anchor; assert `join` creates a new member, `join
   --new` then `whoami` answers the new member, and the claim table has no
   row binding the child's hash to the parent. Add a second test with a
   shell-family stored anchor above an agent child and assert it still
   heals (SC-4 guard). Both must fail at baseline for the stated reason.
5. **Implement the rule** in `identity.match_anchor` (or a new
   `match_anchor_policy` helper it calls) and keep `_resolve_member`
   unchanged apart from the call. Stop if the implementation needs the
   classification tables to change; that belongs to SC-4.
6. **Red test then fix for host id.** Monkeypatch `PATH` to
   `/usr/bin:/bin` in a subprocess test on macOS and assert `whoami`
   resolves the same member; assert `whoami --explain` names the rule when
   the fallback is forced (monkeypatch the absolute path to a nonexistent
   file). Implement the absolute path and the rule name. Rewrite
   `test_capture_host_identity_falls_back_to_hostname` to assert the
   explicit rule rather than silent equivalence.
7. **Red test then fix for read-only verbs.** From a fresh child process,
   run `whoami`, `whoami --explain`, `who`, `list` and assert the
   `taut_identity_claims` row count is unchanged and no member was created.
   Route the three adapters through the read-only resolver (the
   `_touch_activity=False, _heal_claim=False` mode that E1 already
   exposes). Make `whoami --explain` render evidence in the unrecognized
   case. Rewrite `test_anchor_match_survives_anchor_chdir_in_real_chain`
   to drive the heal through `say` or `join`, not `whoami --explain`.
8. **README, kernel, and implementation doc.** Update "The Identity
   Trick" (the ancestor sentence and the fallback note), add the kernel
   sentence from open question 2 to `docs/agent-kernel.md` under
   "Identity: who you are", and update
   `docs/implementation/04-taut-architecture.md` identity section with the
   rationale for excluding agent-family ancestors and the statement that
   anchor matching is a heuristic whose explainability is the design goal.
9. **Traceability reconciliation, CHANGELOG, completed-work review,
   status-index flip.**

## Testing Plan

- Layer: real process chains (`tests/test_identity.py` real-chain
  fixtures, symlinked executables under `tmp_path`), real SQLite state,
  subprocess CLI for the `PATH` proof.
- Do not mock `capture_identity`, `match_anchor`, or the state layer in the
  new tests. Only the platform host-id source may be pointed at a
  nonexistent path to force the fallback branch.
- Mutation check: restore the whole-chain comparison in `match_anchor` and
  confirm task-4 test one fails; restore.
- Run `extensions/taut_summon/tests/test_persona.py` and
  `extensions/taut_mcp/tests/test_tools.py -k identity` as neighbors.

## Verification and Gates

```bash
uv run --extra dev pytest tests/test_identity.py tests/test_cli.py -n 0
uv run --extra dev pytest -n auto --dist loadgroup
uv run --extra dev ruff check taut tests && uv run --extra dev mypy taut tests
bin/ruff_suppression_index.py --check
bin/check-doc-paths && bin/check-plan-status-index
```

## Independent Review Loop

Reviewer: a different family from the author. Inputs: this plan, the two
spec-delta options, `taut/identity.py`, `taut/client/_identity.py`, SC-4's
hidden-couplings paragraph, `tests/test_identity.py`. Ask explicitly:
"Does Option A preserve the SC-4 legacy shell-anchor heal? Could you
implement the agent-family exclusion without touching the classification
tables?"

## Out of Scope

- Replacing the seven-flag `_resolve_member` with a named policy object
  (recommended follow-up; noted in the review artifact §3 A).
- Any change to continuity-token semantics or to `rejoin`.
- Windows host-id derivation changes beyond confirming the registry path
  is absolute.
- Presence (`taut who` liveness) semantics.

## Assumptions and Open Questions

1. **Resolved 2026-09-24 (owner): Option A.** Identity matching is a
   heuristic, not a guarantee; the more explainable rule wins. Promote the
   Option A text; Option B stays in this plan as the rejected alternative.
2. **Resolved 2026-09-24 (owner):** subagents that want a separate
   identity must either be launched as distinct CLI invocations from their
   own process (so they select their own anchor) or use `--as` or a
   continuity token. Task 8 records this sentence in `docs/agent-kernel.md`
   and the README "Identity Trick" section; in-process subagents that share
   one process remain indistinguishable without a selector by design.

## Deviation Log

| Spec ref | Planned behavior | Actual behavior | Rationale | Spec proposal |
|----------|------------------|-----------------|-----------|---------------|

## Review Log

(append-only)

## Execution Log

(append-only; comprehension-gate answers precede the first edit)

- 2026-09-24 — Owner decision: Option A adopted. Rationale recorded by the
  owner: identity matching is a heuristic, not a guarantee, and a more
  explainable rule is a win. Owner requirement: document that subagents
  wanting a separate identity are launched as distinct CLI invocations
  from their own process, or use `--as` or a continuity token.

## Fresh-Eyes Review

The riskiest guess is what "agent-family executable" means in code; task 5
points at the classification helpers and forbids changing them. The SC-4
interaction is the hidden coupling most likely to be missed, so it has its
own guard test in task 4.
