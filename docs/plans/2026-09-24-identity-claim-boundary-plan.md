# Identity Claim Boundary Plan

Status: active — findings verified by reproduction; owner chose Option A on
2026-09-24; independent review completed and the owner-requested correction
pass below incorporated its remaining precision findings.

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

- [x] On selector-free first contact, a nested agent process that Taut selects
  as its own anchor is never bound to an agent-candidate ancestor member's
  claim. When that child's claim is unclaimed, `join` or `join --new` followed
  by `whoami` from the same child answers with the newly created member.
  Claims already misassociated by an older release retain step-3 precedence
  and are handled by the explicit recovery rule below; this change does not
  steal or rewrite them.
- [x] Host identity does not depend on `PATH`; when the platform source is
  unavailable, the fallback is explicit and specified, not silent.
- [x] `whoami`, `whoami --explain`, `who`, and `list` resolve read-only:
  they select but never record a claim, heal an anchor, or create a member.
- [x] [IAN-3.2] and [IAN-3.3] state the rules above; the SC-4 Windows
  shell-anchor migration in the active semantic-compatibility plan still
  works.

## Source Documents

Source specs:

- `docs/specs/03-identity-addressing-notifications.md` [IAN-2.3], [IAN-3.2],
  [IAN-3.3], [IAN-3.4], [IAN-9], [IAN-10]
- `docs/specs/02-taut-core.md` [TAUT-5], [TAUT-10] (the "two members in one
  ancestor chain" edge case and the host-id rationale), [TAUT-8.3] (public
  identity/activity seams)
- `docs/specs/04-summon.md` [SUM-7.1] (coarse native activity)
- `docs/specs/05-taut-mcp.md` [MCP-5], [MCP-12] (tool effects and backend
  conformance)
- `docs/specs/01-development-documentation-operating-model.md` [DOM-5],
  [DOM-6], [DOM-15]

Supporting context:

- `docs/program-theory.md` [THEORY-2] (identity claim is deterministic and
  inspectable, never authenticated), [THEORY-5.A3] (no authentication;
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
- Promotion baseline identifier: uncommitted blobs over repository HEAD
  `cfd87999c3ed75a1112e8c2d2c019c4fb3fe5da2`: core `90ec5de5`, identity
  `05b1f77f`, Summon `daedfe09`, and MCP `beb71886`; publication commit remains
  a completion-boundary owner action.

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
> uses `machine-guid:<value>` from the `MachineGuid` value under the
> `HKEY_LOCAL_MACHINE\SOFTWARE\Microsoft\Cryptography` registry key through
> Python's standard-library `winreg` API. It opens the fixed 64-bit registry
> view with `KEY_READ | KEY_WOW64_64KEY`, so 32-bit and 64-bit Python select
> the same source, and accepts only a non-empty string value after surrounding
> whitespace is removed. A missing key/value, access failure, or empty or
> non-string value takes the specified hostname fallback; it never emits an
> invalid `machine-guid:` id. The Windows path does not invoke a command or
> consult `PATH`. Host capture also carries one exact
> source-rule value: `linux machine-id`, `macOS IOKit platform UUID`, `Windows
> machine GUID`, or `hostname fallback`; `whoami --explain` exposes it as the
> separate `host_rule` field and never overloads the member-resolution `rule`.
> When the platform source is unavailable, Taut falls back to
> `hostname:<name>` with `host_rule` equal to `hostname fallback`; the fallback
> is a distinct namespace and never silently produces a claim that a
> platform-sourced capture would not.

### [IAN-3.2] — insert after the process-selection paragraph

> Process-role classification is one shared operation over both
> classification basenames with this fixed precedence: `skip` when any name is
> in the shell or wrapper families; otherwise `stop` when any name is in the
> infrastructure family; otherwise `unanchorable` when the process has no
> [IAN-3.2] start token; otherwise `agent_candidate`. `select_anchor()` and
> [IAN-3.3] step 4 use that same operation; neither duplicates the family
> checks. "Agent-family executable" in step 4 means `agent_candidate`; it does
> not introduce or imply a hard-coded list of agent product names.

### [IAN-3.3] — replace step 4

Option A (**adopted 2026-09-24**; preserves SC-4):

> 4. Agent anchor match: when no claim hash matches and the capture is an
>    agent capture, resolution may match a stored member anchor by the
>    stable triple (`host_id`, `anchor_pid`, `anchor_start_time`),
>    comparing the [IAN-3.2] start token by exact equality, against **the
>    selected anchor itself**, or against an ancestor of the selected
>    anchor **only when the shared [IAN-3.2] process-role classifier returns
>    `skip` or `stop` for that ancestor**. An `agent_candidate` ancestor is
>    never eligible; an `unanchorable` ancestor cannot satisfy the exact start-
>    token comparison. This permits a shell, wrapper, or infrastructure
>    process whose earlier classification made it an anchor. It recovers
>    continuity
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
> resolution. `whoami` reports the selected member; `who` and `list` use the
> selected member to drive their existing output; and `whoami --explain` also
> reports the rule that selected the member. None records a claim, heals an
> anchor, updates activity, or creates a member. `whoami --explain` renders
> the captured evidence and the rule in the unrecognized case too. An
> unrecognized `whoami --explain` retains `UnrecognizedCallerError` and exit
> code 2. Its diagnostic keeps `unrecognized caller` as the first record and
> the existing `or select...` recovery record as the last, and inserts exactly
> one `identity evidence: <canonical-json>` record immediately after the first.
> The canonical JSON is the ordinary explanation object with `rule` equal to
> `unrecognized` and the separate `host_rule` described in [IAN-3.2]. This
> diagnostic contract is the same with or without global `--json`; `--quiet`
> suppresses it under the existing error-rendering rule. The Python API raises
> `UnrecognizedCallerError` carrying that explanation as an optional
> `explain` mapping; it does not fabricate a `Member` result.

### [IAN-10] — replace the `whoami --explain` bullet

> - `rejoin` captures and associates the current process claim, while
>   `whoami`, `whoami --explain`, `who`, and every `list` mode use read-only
>   resolution and never associate evidence; explicit-name and continuity-
>   token precedence may avoid process capture, while `whoami --explain`
>   always captures for diagnostics. Tests drive all four verbs, including
>   every `list` mode, from a fresh child process and assert the complete
>   read-only state snapshot is unchanged.

### `## Related Plans` — add

> - `docs/plans/2026-09-24-identity-claim-boundary-plan.md` — narrows the
>   step-4 anchor match so a parent agent cannot capture a child agent,
>   specifies host-id derivation and its explicit fallback, and routes the
>   read verbs through read-only resolution.

## Context and Key Files

Files to modify:

- `taut/identity.py` — `capture_host_identity()` (line ~132–164): bare
  `["ioreg", ...]` subprocess with a silent `hostname:` fallback and no
  Windows registry branch despite the proposed contract;
  `match_anchor(capture, members)` (line ~354–371): iterates the whole
  captured chain comparing `(host_id, pid, start_time)`. Add one shared
  process-role classifier used by both `select_anchor()` and `match_anchor()`;
  do not add an agent-brand table. Carry the exact host source-rule value in
  `HostIdentity` and expose it from `explain_capture()` as `host_rule`.
- `taut/client/_identity.py` — `_resolve_member()` (line ~250–300, McCabe
  43, `[RUFF-SUP-047]`): step-4 branch calls `identity.match_anchor` and
  then `_record_claim(row, claim, active)` unless `_heal_claim` is false.
- `taut/commands/whoami.py`, `taut/commands/who.py`,
  `taut/commands/list.py` (or wherever these adapters live; confirm with
  `ls taut/commands/`) — call the client with the default (healing)
  resolver today.
- `taut/_exceptions.py` and `taut/commands/_dispatch.py` — carry and render the
  optional unrecognized explanation without changing the exit code or the
  first/last diagnostic records.
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
4. **What exactly is an agent-family ancestor?** Expected: a process for which
   the one shared process-role classifier returns `agent_candidate`, not a
   basename found in a new product-name list. Ancestor matches are limited to
   the classifier's `skip` and `stop` roles.
5. **Can `join --new` repair a child claim already owned by its parent?**
   Expected: no. Step 3 wins and `join --new` never steals a claim. Restart the
   child to obtain fresh process evidence and then `rejoin` the intended member,
   or keep using `--as` or a continuity token.

## Invariants and Constraints

- [THEORY-5.A3]: no authentication is added. Narrowing the match makes a claim less
  likely to be *wrong*, not harder to *spoof*.
- Steps 1–3 and 5–6 of [IAN-3.3] are unchanged. `--as`, `TAUT_AS`, and
  tokens keep precedence and never teach a claim.
- `join --new` still never steals a claimed hash.
- The stored claim table format and member row format do not change.
- The unrecognized-caller diagnostic keeps its first record, candidate block,
  and closing `or select…` record. Only `whoami --explain` may insert the one
  specified canonical evidence record after the first record.
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
  evidence. Its coarse-liveness write previously rode `whoami()` as an
  implicit side effect; move it to the explicit
  `TautClient.touch_identity_activity()` seam and run its activity tests.
- MCP attaches by token and uses the public client. Its `list`, `who`, and
  `whoami` effect descriptions and backend conformance tests must change from
  activity-writing to fully read-only; attachment itself remains unaffected.

Failure policy: a failed platform host-id read is best-effort (fallback
plus explicit rule name); a `match_anchor` exception remains fatal as today.

## Rollout, Rollback, and One-Way Doors

- Source revert restores the old rule. Claims recorded under the old rule
  remain valid claim rows; they are not migrated, and step 3 continues to
  select their current owner. `join --new` deliberately cannot repair such a
  claim because it never steals an owned hash. Recovery is either to keep using
  `--as` or a continuity token, or to restart the child so it has fresh process
  evidence and then run `rejoin NAME` (or token-selected `rejoin`) for the
  intended member. Document that exact recovery in the CHANGELOG.
- Host-id change: members created under the `hostname:` fallback on macOS or
  Windows keep that host id. After the fix, a process on the same machine will
  capture `ioplatformuuid:` on macOS or `machine-guid:` on Windows and may be
  unrecognized once; the existing candidate diagnostic and `rejoin` are the
  recovery. No automatic merge. The CHANGELOG names both platform migrations,
  both new prefixes, and the one-time recovery path.
- One-way door: none in storage. The behavior change is reversible.
- Post-deploy signal: `env PATH=/usr/bin:/bin taut whoami` resolves the
  same member as `taut whoami`; a child process named like an agent binary
  creates its own member on `join --new` and keeps it on `whoami`. On native
  Windows, 32-bit and 64-bit Python (where both are supported) derive the same
  non-empty `machine-guid:` id from the fixed registry view.

## Dependency-Ordered Tasks

1. **Owner decision on Option A vs B**, recorded in the Execution Log.
2. **Independent plan review** including the delta and SC-4 interaction.
3. **Spec-promotion slice** (strategy A); record the promotion baseline.
4. **Anchor-policy red tests and regression guards.** In
   `tests/test_identity.py`, first add a table test for the shared role helper:
   a process with a shell or wrapper name plus an infrastructure name is
   `skip`; an infrastructure-only process is `stop`; an otherwise ordinary
   process without a start token is `unanchorable`; and an otherwise ordinary
   process with a start token is `agent_candidate`. This test fails until the
   shared helper exists and locks the current family precedence. Add focused
   `match_anchor` cases proving: the selected anchor itself is eligible; only
   `skip` and `stop` entries after the selected anchor in the ancestry are
   eligible; `agent_candidate` and `unanchorable` ancestors are rejected; and
   skipped entries before the selected anchor (descendants of that anchor in
   process-tree terms) are rejected even when their triples match stored state.
   Then build a
   real process chain (the existing real-chain fixtures) where the selected
   anchor is a child whose executable basename is an agent candidate (symlink
   `python` as `codex` in `tmp_path`, as the review did) and an ancestor is
   a known member's anchor. In one fresh-child case, assert selector-free
   `join` creates a child member, the next `whoami` selects it, and no claim
   row binds the child's hash to the parent. In a separate fresh-child case,
   assert `join --new` followed by `whoami` selects the new member. Add a
   legacy shell-family stored anchor above an agent child and assert it still
   heals (SC-4 guard). Add a durable-state case proving that a child hash
   already owned by the parent keeps step-3 precedence and that `join --new`
   neither steals nor repairs it. Only the selector-free `join` parent-capture
   case and the new agent-ancestor/pre-anchor boundary cases are behavioral
   RED at baseline. Fresh `join --new`, selected-anchor continuity, legacy
   shell healing, unanchorable rejection, and durable step-3 ownership are
   characterization/regression guards and must be green before production
   edits.
5. **Implement the rule** by extracting one named process-role classifier
   used by both `select_anchor()` and `identity.match_anchor()`. Preserve the
   current shell/wrapper-before-infrastructure precedence and classification
   basenames. Keep `_resolve_member` unchanged apart from the call. Stop if
   implementation needs a family-table change; that belongs to SC-4.
6. **Red test then fix for host id.** On macOS, monkeypatch `PATH` to
   `/usr/bin:/bin` in a subprocess test and assert `whoami`
   resolves the same member; assert `whoami --explain` preserves its
   member-resolution `rule` while reporting `host_rule: hostname fallback`
   when fallback is forced (point the absolute platform source at a
   nonexistent file through the owned test seam). On Windows, use a fake
   `winreg` API to assert the exact hive, key, value,
   `KEY_READ | KEY_WOW64_64KEY` access mask, and non-shell execution. Add
   separate missing/error, empty-string, and non-string fake-API cases proving
   `hostname fallback` rather than a crash or invalid `machine-guid:` output,
   plus a native Windows subprocess smoke test that empties `PATH` and still
   obtains `machine-guid:` when the registry value is available. Implement the
   absolute macOS path, the in-process Windows registry read, and all four
   exact source-rule values. Rewrite
   `test_capture_host_identity_falls_back_to_hostname` to assert the
   explicit rule rather than silent equivalence. Add human and `--json`
   explanation assertions so `host_rule` is a firing public contract.
7. **Red test then fix for read-only verbs.** From a fresh child process,
   run each of `whoami`, `whoami --explain`, `who`, default `list`, `list
   --all`, and `list --dms` as its own enumerated case. Seed the state needed
   for each mode to return normally; exercise unrecognized callers wherever
   that mode permits guest operation. Snapshot members (including activity,
   anchor, and fingerprint), identity claims, memberships, and cursors before
   each call and assert exact equality afterward. Include a recognized child
   whose selection reaches step 4 and a wholly unrecognized child; assert no
   member is created in the latter case. For unrecognized `whoami --explain`,
   assert exit 2, the unchanged first and last diagnostic records, the one
   canonical evidence record with `rule: unrecognized` and `host_rule`, and
   identical behavior under global `--json`; also assert `--quiet` suppresses
   it.
   Route `whoami()`, `who()`, `list_threads()`, and
   `list_direct_messages()` through the read-only resolver with both
   `_touch_activity=False` and `_heal_claim=False`. Make `whoami --explain`
   render evidence in the unrecognized case. Rewrite
   `test_anchor_match_survives_anchor_chdir_in_real_chain` to drive the heal
   through `say` or `join`, not `whoami --explain`.
8. **Explicit activity seam and extension reconciliation.** Add public
   `TautClient.touch_identity_activity() -> Member`: select read-only, update
   only `last_active_ts`, return the updated member, and expose the exact
   no-argument signature. Add a real-core test proving the timestamp advances
   while claims, anchor, fingerprint, persona, memberships, and cursors remain
   unchanged. Replace Summon's rate-limited `mouth.whoami()` activity write
   with this seam and add a firing driver test. Reverse the SQLite/PostgreSQL
   MCP `list`/`who`/`whoami` activity assertions to require an exact unchanged
   activity/identity snapshot.
9. **README, kernel, and implementation doc.** Update "The Identity
   Trick" (the ancestor sentence and the fallback note), add the kernel
   sentence from open question 2 to `docs/agent-kernel.md` under
   "Identity: who you are", and update
   `docs/implementation/04-taut-architecture.md` identity section with the
   rationale for excluding agent-family ancestors and the statement that
   anchor matching is a heuristic whose explainability is the design goal.
10. **Traceability reconciliation, CHANGELOG, completed-work review,
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
- Mutation check: make `whoami`, `who`, `list_threads`, or
  `list_direct_messages` use the default resolver one at a time and confirm
  that verb or mode's state-snapshot test fails; restore after each mutation.
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

The hosted Windows lane must exercise the real registry smoke test. Where CI
offers both Python architectures, compare their derived host ids; where it
does not, the fake-API access-mask assertion remains the cross-architecture
proof and the limitation is recorded in the execution log.

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
- Changes to Windows identity evidence other than the missing in-process
  `MachineGuid` host-id branch and its explicit fallback/source rule.
- Presence (`taut who` liveness) semantics.

## Assumptions and Open Questions

1. **Resolved 2026-09-24 (owner): Option A.** Identity matching is a
   heuristic, not a guarantee; the more explainable rule wins. Promote the
   Option A text; Option B stays in this plan as the rejected alternative.
2. **Resolved 2026-09-24 (owner):** subagents that want a separate
   identity must either be launched as distinct CLI invocations from their
   own process (so they select their own anchor) or use `--as` or a
   continuity token. Task 9 records this sentence in `docs/agent-kernel.md`
   and the README "Identity Trick" section; in-process subagents that share
   one process remain indistinguishable without a selector by design.

## Deviation Log

| Spec ref | Planned behavior | Actual behavior | Rationale | Spec proposal |
|----------|------------------|-----------------|-----------|---------------|
| [IAN-3.3], [TAUT-8.3], [SUM-7.1], [MCP-5]/[MCP-12] | Plan claimed Summon and MCP were unaffected by making `whoami`/`who`/`list` read-only. | Summon used `whoami()` as an implicit coarse-liveness write; MCP explicitly specified and tested activity writes for all three tools. | Observational verbs cannot remain effect-bearing merely to serve one embedder. Add one narrow, explicit core activity seam for Summon and promote MCP's observational tools to the same read-only contract as CLI/core. | Promoted in the spec slice before production edits; implementation task 8 and extension proofs are required. |

## Review Log

- 2026-09-24 — The owner confirmed the independent plan review was complete.
  Reviewer provenance and the original verdict were not present in the
  repository copy, so this entry does not invent them. A subsequent
  fresh-eyes correction pass returned ADOPT-WITH-EDITS: define the shared
  process-role predicate, specify host-rule and unrecognized-explanation
  output, correct the `join --new` recovery contradiction, and enumerate the
  full read-only state proof. Those edits are incorporated above.
- 2026-09-24 — Fresh read-only review of the corrected plan returned BLOCKED
  on four remaining proof/wording gaps: baseline RED classification, selector
  capture wording, the uncovered `list --dms` activity write, and missing
  classifier/ancestry truth-table tests. The plan now distinguishes RED from
  characterization cases, preserves selector short-circuit capture semantics,
  enumerates all list modes and all four client resolution owners, and fires
  every classifier role and ancestry boundary.
- 2026-09-24 — Re-review closed those four findings and returned BLOCKED only
  on the newly exposed Windows host-id scope. The plan now specifies the fixed
  64-bit registry view, invalid-value fallback matrix, macOS-and-Windows
  migration/recovery note, and native/cross-architecture verification.
- 2026-09-24 — Final independent read-only re-review: PASS, no remaining plan
  blocker.
- 2026-09-24 — Independent completed-work review initially found two stale
  normative activity statements and four plan-explicit proof gaps. The core
  and MCP statements were reconciled; direct unanchorable-ancestor rejection,
  six real fresh-child read cases, forced-fallback JSON explanation, and a
  state-changing legacy shell-heal proof were added. Re-review returned PASS
  with no plan-related production, specification, documentation, or firing-
  test finding. Concurrent unrelated hunks were excluded.

## Execution Log

(append-only; comprehension-gate answers precede the first edit)

- 2026-09-24 — Owner decision: Option A adopted. Rationale recorded by the
  owner: identity matching is a heuristic, not a guarantee, and a more
  explainable rule is a win. Owner requirement: document that subagents
  wanting a separate identity are launched as distinct CLI invocations
  from their own process, or use `--as` or a continuity token.
- 2026-09-24 — Comprehension gate before implementation: (1) SC-4 needs
  ancestor matching because a member stored under the old Windows shell-anchor
  classification can otherwise be recreated after the shell becomes skipped;
  (2) Option A preserves that heal because the legacy shell is `skip`, while it
  excludes only `agent_candidate` ancestors; (3) step 4 writes through
  `_record_claim` inside `_resolve_member`, and read-only mode suppresses it
  through `_touch_activity=False` (with `_heal_claim=False` explicit at call
  sites); (4) agent-family means the shared classifier's `agent_candidate`
  role, never a product-name list; (5) `join --new` cannot repair an already
  owned child hash because step 3 and no-steal semantics remain authoritative.
- 2026-09-24 — Spec-promotion slice applied in the working tree using strategy
  A. Documentation gates passed; promotion baselines over HEAD `cfd8799` are
  core `90ec5de5`, identity `05b1f77f`, Summon `daedfe09`, and MCP `beb71886`.
  The slice remains uncommitted per owner-facing workflow policy.
- 2026-09-24 — Pre-code dependency mapping found two false "unaffected"
  assumptions: Summon depended on `whoami()` to write coarse activity, and MCP
  required activity writes for `list`/`who`/`whoami`. Deviation recorded and
  owning core/Summon/MCP contracts promoted before implementing the explicit
  activity seam.
- 2026-09-24 — Anchor-policy RED/GREEN: the focused parent-agent unit case
  first returned the parent member; the shared four-role classifier and
  selected-anchor boundary then made the focused table and match suite pass.
  Real symlinked-`codex` process cases now prove both ordinary `join` and
  `join --new` create and retain a child member without adding a parent claim.
  Temporarily restoring whole-chain matching made the real nested-agent case
  fail; restoring Option A made both cases pass.
- 2026-09-24 — Host-id RED/GREEN: the macOS test first observed a bare
  `ioreg`; capture now uses `/usr/sbin/ioreg`, Windows reads the fixed 64-bit
  MachineGuid registry view, invalid values take the named hostname fallback,
  and explanations expose `host_rule`. The native macOS empty-`PATH` CLI proof
  passed. The native Windows smoke remains assigned to the hosted Windows
  lane.
- 2026-09-24 — Read-only RED/GREEN: the first step-4 `whoami` snapshot showed
  both activity and claim mutation. All six enumerated modes now preserve the
  complete persistence snapshot and metadata high-water mark for recognized
  and unrecognized callers. Independent mutations of `whoami`, `who`,
  `list_threads`, and `list_direct_messages` back to default resolution each
  made its named snapshot case fail; all were restored and the 12-case matrix
  passed. Unrecognized explanation, JSON-equivalent stderr, quiet suppression,
  and write-driven post-`chdir` healing are covered.
- 2026-09-24 — The explicit `touch_identity_activity()` seam updates only
  `last_active_ts`; Summon uses it for rate-limited provider activity. MCP
  SQLite `list`/`who`/`whoami` snapshots require exact activity and identity
  equality. The matching PostgreSQL test collected but skipped locally because
  `SIMPLEBROKER_PG_TEST_DSN` is unavailable.
- 2026-09-24 — Verification so far: final identity plus CLI suite 281 passed,
  5 platform skips, and 1 backend deselection; full MCP `test_tools.py`,
  Summon `test_persona.py`, and the
  Summon activity-owner test passed; targeted mypy over core and every changed
  root test passed; documentation path and plan-index gates passed. The full
  root suite reached 2,305 passed and 5 platform skips after exposing one
  plan-owned stale DM-directory activity assertion, which was corrected and
  passed. Four remaining failures and the repository-wide Ruff/suppression
  gates are in concurrent unrelated terminal, watcher, and CLI-read work;
  they are recorded as residual workspace blockers rather than altered here.
- 2026-09-24 — Review follow-up added the direct unanchorable-ancestor guard,
  six parameterized real child-process read proofs, forced macOS-fallback
  `whoami --explain --json`, and resolver-level SC-4 shell-anchor healing.
  Their focused tests passed. Targeted Ruff (excluding only pre-existing
  concurrent B023/TRY203 findings), targeted mypy, and `git diff --check`
  passed. Independent completed-work re-review returned PASS.

## Fresh-Eyes Review

The riskiest guess is what "agent-family executable" means in code; task 5
points at the classification helpers and forbids changing them. The SC-4
interaction is the hidden coupling most likely to be missed, so it has its
own guard test in task 4.
