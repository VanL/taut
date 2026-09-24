# MCP Not-Found Result Contract Plan

Status: completed — implementation, local verification, independent review,
and targeted commit complete.

Class: 5 (spec-changing) and risky under [DOM-5]: the change revises the
normative [MCP-5]/[MCP-6] result rules for non-private not-found outcomes,
which is a public protocol contract. Hardening is required. Not
process-changing.

Plan type: implementation with spec revision.

Owner: implementing engineer.

## Goal

Make MCP write tools tell the truth about failure. Today `say` to a missing
channel, a missing sub-thread, or an unknown `@name` returns
`isError:false` with `{"records":[]}`. [MCP-5] says only an exact
`dm.d_*` miss is content-free for `say` and that route-addressed targets
"keep their existing error". The command layer honors that
(`_commands.py` re-raises `NotFoundError` for non-DM targets), but
`NotFoundError` subclasses `EmptyResultError`, and the workspace reactor's
`except EmptyResultError: pass` (`_workspace_reactor.py:357`) converts the
re-raised error into an empty success. The test meant to prove the rule
(`test_say_normalizes_only_exact_stable_dm_not_found`) checks the command
layer with a spy and never reaches the reactor, so it cannot fail for this.
`reply`, `leave`, and `channel_rename` have the same shape by the general
[MCP-6] empty rule; the CLI gives each an actionable diagnostic.
`channel_show` and `channel_topic` deliberately normalize a channel miss in
the command adapter today, but channels are not privacy-bearing and the fixed
classification below revises both to the same truthful diagnostic policy.
Evidence:
`docs/plans/artifacts/2026-09-23-deep-dive-review.md` §1 item 6 and §2.

## Requested Outcomes

- [x] `say` to a missing channel/sub-thread or unknown `@route` returns
  `isError:true` with core's diagnostic text; the exact `dm.d_*` miss stays
  a content-free empty result.
- [x] The spec lists which tools return content-free empties (privacy-
  bearing lookups) and which non-private misses surface not-found as
  `isError`; `reply`, `leave`, `channel_rename`, `channel_topic`, and
  `channel_show` join the second group.
- [x] A reactor-level or stdio-level test fires for each of the three `say`
  target forms and for the five other tools in the error row.
- [x] `reply.msg_id` accepts exactly 19 digits, as `message_show`,
  `message_delete`, and `message_react` already do; the [MCP-5] parameter
  row drops the suffix form (follows the CLI plan's suffix removal, decided
  by the owner on 2026-09-24).
- [x] Two gates [MCP-12] and [MCP-10] already claim exist: a firing test
  for `workspace directory identity unavailable` and a one-mebibyte
  large-frame continuity probe. The latter proves the SDK-owned unbounded
  framing path remains protocol-clean; it does not invent a server limit.
- [x] The `--claude-channel` research-preview adapter is removed: the flag,
  the legacy-era `experimental["claude/channel"]` capability, the
  reactor's `last_claude_attempted_text` state and `_signal_claude_change`
  path, `_claude_channel.py`, its tests, the [MCP-3]/[MCP-9] text, and the
  README paragraph. The standard `resources/updated` notification on
  `taut://notifications/current` is the one wake mechanism (owner
  confirmation 2026-09-24; generalization is the recorded rejected
  alternative).

## Source Documents

Source specs:

- `docs/specs/05-taut-mcp.md` [MCP-5] (tool table; the `say` sentence at
  line ~1137), [MCP-6] (result and empty-result rules, line ~870–880 and
  ~1085–1160), [MCP-3] (channel capability, line ~105 and ~187), [MCP-9]
  (channel adapter paragraph, line ~1600–1619), [MCP-10], [MCP-12]
- `docs/specs/02-taut-core.md` [TAUT-8.1] (CLI exit classes the tools
  mirror)
- `docs/specs/01-development-documentation-operating-model.md` [DOM-5],
  [DOM-6], [DOM-15]

Supporting context:

- `docs/program-theory.md` [THEORY-4] principle 1 (agents are first-class
  and get native machine transport), [THEORY-5.A3] (tokens are selectors;
  no auth — unchanged here).
- `docs/agent-context/runbooks/designing-agent-facing-interfaces.md`
  (every error carries its next action).
- `2026-08-10-stable-dm-send-plan` (retired plan; source `c0a4616`) review log: the reviewer
  asked to keep the empty result stable-DM-only "without changing
  `@route`"; this plan restores that decision in code.
- `2026-09-15-mcp-result-simplification-plan` (retired plan; source `3037971`) (completed;
  CLI-shaped records, 21,000-byte manifest ceiling — unchanged here).
- `docs/implementation/07-taut-mcp-architecture.md`.
- `docs/plans/artifacts/2026-09-23-deep-dive-review.md` §1 item 6.

## Spec Baseline

- `c0a4616e76e954e3f9fbea93fbf487c3ee660cbe` — `docs/specs/05-taut-mcp.md`
  at plan authoring time; unchanged through `c894059` (0.9.9 release SHA).
- Promotion baseline identifier: `cfd87999c3ed75a1112e8c2d2c019c4fb3fe5da2`
  plus the uncommitted `docs/specs/05-taut-mcp.md` worktree diff with SHA-256
  `01c26dcdcbafae2621dd0c388e5d720bb4ab8f6c3e1a8e99d105109337781df6`.

## Proposed Spec Delta

Promotion strategy: **A — in-file edit, text before link claims**.

| Spec file | Strategy | Sections touched |
|-----------|----------|------------------|
| `docs/specs/05-taut-mcp.md` | A | [MCP-2]/[MCP-3]/[MCP-8]/[MCP-9]/[MCP-12] remove every Claude-adapter contract; [MCP-6] new "empty versus error" table and revised channel-metadata outcome; [MCP-5] `say` sentence; [MCP-10]/[MCP-12] concrete large-frame probe; implementation mapping; `## Related Plans` |

### [MCP-6] — insert a classification table after its opening result-shape
paragraph ending `clients that do not consume structured output.`

> Empty results are content-free by design only where a nonempty error
> would leak existence or membership. The classification is fixed:
>
> | Tool | Not-found disposition |
> |------|-----------------------|
> | `read`, `log`, `search` with a DM selector; `message_show`; `message_delete`; `message_react`; `say` to an exact `dm.d_*` handle | content-free typed empty result |
> | `say` to a channel, sub-thread, or `@name-or-alias`; `reply`; `leave`; `channel_rename`; `channel_topic`; `channel_show` | `isError:true` carrying core's diagnostic text for that miss, the same message the CLI prints, with no dispatch-side identity or activity effect |
>
> Except for the first row's privacy-preserving empty results, a mutating tool
> never reports success for work it did not do, and a non-private channel
> metadata lookup does not disguise a missing channel as an empty success. The
> command adapter preserves `NotFoundError` for the second row, and the reactor
> maps it to a tool error before applying the general empty-result rule. Every
> tool not named in the second row keeps that general rule; the first row
> enumerates the privacy-bearing cases whose content-free behavior is invariant.

Later in [MCP-6], replace `An absent or wrong-kind channel returns exactly
{ "records": [] }.` with:

> An absent or wrong-kind channel returns `isError:true` with core's
> diagnostic under the fixed table above. It has no identity, activity,
> queue, cursor, topic, or notification effect.

### [MCP-5] — tighten the `reply.msg_id` parameter row

Replace `Parent message id, or a unique suffix of at least 4 digits among
the channel's most recent 1000 ids.` (line ~811) with `Exact 19-digit
parent message id; the schema rejects any other shape, as for
`message_show`.`

### [MCP-5] — amend the `say` sentence

Current: `For `say`, a well-formed exact stable `dm.d_*` target that is
absent, inaccessible, or structurally invalid returns the same empty
`message` result; route-addressed `@name-or-alias` keeps its existing error
and creation behavior.`

Proposed: `For `say`, a well-formed exact stable `dm.d_*` target that is
absent, inaccessible, or structurally invalid returns the same empty
`message` result; a channel, sub-thread, or `@name-or-alias` target that
does not exist returns `isError` with core's diagnostic ([MCP-6] table),
and `@name-or-alias` keeps its creation behavior for existing members.`

### [MCP-3] — remove the channel capability sentence

Remove: `With `--claude-channel`, legacy initialization also advertises the
existing `experimental["claude/channel"]` capability.` and the clause that
names `--claude-channel` as the one host-specific flag (line ~105); state
instead that the server exposes no host-specific capabilities.

Also remove the earlier [MCP-2] reference to optional host-specific callbacks,
the [MCP-3] portability clause that calls the Claude channel an optional
adapter, and the [MCP-8] lifespan sentence's optional
`last_claude_attempted_text` baseline. Retain the standard legacy and modern
resource-update trackers and their existing initialization behavior.

### [MCP-9] — remove the channel adapter paragraph

Remove the paragraph beginning `An opt-in `--claude-channel` mode declares
the experimental` through `part of the host-specific adapter.` Replace with
one sentence:

> Taut ships no host-specific wake adapter. The standard
> `notifications/resources/updated` on `taut://notifications/current` is
> the only wake hint; a host that gives the agent a turn on some other
> signal maps that signal itself (instruction 6).

Revise instruction 15 from duplicate standard/Claude wake coalescing to the
single standard resource-update rule. In [MCP-12], replace the discovery
assertion that the Claude capability is legacy-only with absence of any
host-specific experimental capability, and delete the capability-gated
Claude-emission proof. Update the implementation mapping rows from "dual
notification adapters" and "legacy-only Claude adapter" to the standard
legacy/modern resource-notification adapters and instructions only.

Recorded rejected alternative (owner, 2026-09-24): generalizing the
adapter into a per-host wake-cue registry. Rejected because only one host
protocol exists, it is legacy-era only, and the standard resource update
already carries the same information; a registry over one entry is
speculative architecture (engineering principle §7). Reconsider when a
second host protocol with concrete external pull cannot act on the
standard resource notification.

### [MCP-10]/[MCP-12] — make the oversized-frame probe executable

Replace the unbounded phrase `oversized-frame acceptance probe` with:

> MCP framing remains SDK-owned and Taut adds no frame-size limit. A real
> stdio continuity probe sends one newline-delimited, schema-invalid JSON-RPC
> tool-call frame containing an unknown string argument of at least 1,048,576
> UTF-8 bytes. The server returns the fixed schema-invalid tool result with no
> traceback or echoed payload, then answers a following valid
> `list_workspaces` request on the same connection. This is a large-frame
> continuity floor, not a declared maximum; if the supported SDK later adds a
> smaller documented limit, revise this contract before upgrading it.

### `## Related Plans` — add

> - `docs/plans/2026-09-24-mcp-not-found-result-contract-plan.md` — fixes
>   non-private misses reporting not-found as empty success, classifies empty
>   versus error per tool, adds the two missing [MCP-12]/[MCP-10] gates,
>   and removes the research-preview Claude channel adapter in favor of the
>   standard resource notification.

## Context and Key Files

Files to modify:

- `extensions/taut_mcp/taut_mcp/_workspace_reactor.py` —
  `_execute_command` (line ~340–365): `except TokenError`, `except
  BlankMessageError`, `except EmptyResultError: pass`, `except (TautError,
  TypeError, ValueError)`, `except Exception` (`[RUFF-SUP-066]`). The
  `EmptyResultError` arm must come after a `NotFoundError` arm gated by the
  fixed second-row tool-name set. Add a narrow module-local directory-stat
  callable for the identity-failure test; do not monkeypatch the shared
  `os.stat` module attribute process-wide.
- `extensions/taut_mcp/taut_mcp/_commands.py` — `say` branch (line
  ~60–70) already re-raises `NotFoundError` for non-DM targets; `reply`,
  `leave`, `channel_rename` branches call core directly. Remove the
  `NotFoundError`-to-empty catches from `channel_show` and `channel_topic` so
  the reactor can apply the fixed table.
- `extensions/taut_mcp/taut_mcp/_process_reactor.py` —
  `configure_claude_channel` (line ~633), `_signal_claude_change` (line
  ~666), the call at ~723, and `last_claude_attempted_text` state, all to
  remove. There is no Taut or installed SDK frame-size constant to edit; the
  large-frame probe exercises the existing SDK-owned line reader.
- `extensions/taut_mcp/taut_mcp/_claude_channel.py` (40 lines, delete),
  `tests/test_claude_channel.py` (delete), `cli.py` lines ~19–104 and
  `command.py` line ~20 (`claude_channel` parameter and flag), `server.py`
  lines ~27, ~92–128, ~288 (capability advertisement and configuration).
- `extensions/taut_mcp/tests/test_tools.py` —
  `test_say_normalizes_only_exact_stable_dm_not_found` (false test; move
  its assertion to the reactor level).
- `extensions/taut_mcp/tests/test_channel_tools.py` — replace
  `test_missing_channel_is_an_empty_channel_result`; it encodes the old
  command-layer normalization and must fail first for both channel tools.
- `extensions/taut_mcp/tests/test_stdio_server.py` — add the stdio-level
  cases and the oversized-frame probe.
- `extensions/taut_mcp/tests/test_process_reactor.py` — remove cue
  assertions; keep `last_signalled_text` resource-update proofs.
- `extensions/taut_mcp/README.md` — host registration example and
  token-source pointer; delete the existing `--claude-channel` paragraph.
- `README.md` — remove the root pointer to the deleted launch flag.
- `docs/implementation/07-taut-mcp-architecture.md` — remove the adapter from
  the overview, era-check boundary, process-reactor tracker list, redundant-
  hint invariant, and key-file map; describe only standard legacy/modern
  resource notifications.
- `docs/implementation/02-repository-map.md` — remove the optional legacy
  Claude channel hint from the `extensions/taut_mcp/` row.
- `taut/_exceptions.py` — read only: `EmptyResultError(TautError)` at
  line ~59, `NotFoundError(EmptyResultError)` at line ~67. Do not change
  the hierarchy; the CLI relies on it.

Read first: [MCP-5] tool table rows for the six tools in the error row;
[MCP-6] in full; `_commands.py`'s `channel_show`/`channel_topic` normalization;
`_workspace_reactor.py` `_execute_command`; the CLI exit mapping in
`taut/commands/_dispatch.py` for `NotFoundError` (exit 2 with the message
on stderr) so the tool-error text matches byte-for-byte.

Comprehension gate:

1. **Why does the command-layer re-raise not reach the client?** Expected:
   the reactor catches the parent class `EmptyResultError` and returns an
   empty success; the subclass relationship makes the catch match.
2. **Why not change the exception hierarchy?** Expected: the CLI maps both
   to exit 2 deliberately ([TAUT-8.1]); the MCP surface needs a different
   disposition for a fixed MCP tool set, so the discrimination belongs in
   the command adapter plus reactor's tool-aware mapping, not in core.
3. **Why do privacy-bearing lookups stay content-free?** Expected: [MCP-6]
   and [TAUT-7.6]
   forbid leaking existence or membership of DMs and messages the member
   cannot see; that reason does not apply to a channel the member tried to
   post into.

## Invariants and Constraints

- The manifest stays exactly 21 tools and under the approved 21,000-byte
  ceiling; descriptions may change wording but not add parameters.
- Removing the channel adapter must not change `resources/updated`
  timing, coalescing, or `last_signalled_text`; the wheel-matrix canary
  for the 0.9.5 MCP wheel is rerun because the legacy handshake changes.
- Result schemas in `_result_schemas.py` are unchanged for success paths;
  the error path uses the existing `isError` envelope.
- Dispatch-side identity/activity effects for a miss are unchanged (none).
- Content-free classes for DM and message lookups are unchanged; no error
  text for those may include route, participant, or existence detail.
- Both wire eras behave identically.
- No change to `taut/_exceptions.py`.
- Rate admission, workspace cap, and shutdown paths are untouched.

Hidden couplings:

- `test_stdio_all_cli_shaped_tools_return_schema_valid_canonical_results`
  iterates all 21 tools; the new error path must not break its success
  fixtures.
- The CLI-shaped record contract (completed 2026-09-15 plan) promises
  parity with CLI stdout records; the error text parity promised here is
  with CLI stderr.

Failure policy: a not-found in the fixed non-private error row is a tool error
(fatal for that call, no retry); the workspace stays attached.

## Rollout, Rollback, and One-Way Doors

- Source revert. Hosts that depended on empty-success for a missing channel
  would see errors instead. This restores the existing `say` contract and
  intentionally revises the prior `channel_show`/`channel_topic` contract;
  CHANGELOG entry required.
- No one-way door.
- Post-deploy signal: an MCP client calling `say` with a nonexistent
  channel receives `isError:true` and the text `thread not found: <name>`.

## Dependency-Ordered Tasks

1. **Independent plan review** including the [MCP-6] table.
2. **Owner confirmation** of the channel adapter removal (outcome 5):
   complete 2026-09-24.
3. **Spec-promotion slice**; record the promotion baseline. Reconcile every
   old channel-empty claim and every Claude-adapter reference enumerated in
   Proposed Spec Delta; grep the spec for
   `Claude|claude|host-specific|last_claude|dual notification` before moving
   to red tests.
4. **Red tests.** In `test_stdio_server.py`, drive the real server over
   stdio: `say` to `nochannel`, to `general.1234567890123456789`, and to
   `@nobody`; `reply` to a missing parent; and `leave`, `channel_rename`,
   `channel_topic`, and `channel_show` on a missing channel. Assert
   `isError:true` and the CLI stderr text. Assert
   `say` to a well-formed absent `dm.d_*` still returns the empty result.
   All must fail at baseline (empty success). Delete the spy-based false
   test or convert it to a reactor-level test.
5. **Implement the fixed mapping.** Remove the command-layer empty
   normalization for `channel_show` and `channel_topic`. Add a
   `NotFoundError` arm before the `EmptyResultError` arm in
   `_execute_command`, gated on the exact second-row tool-name set; map to
   `command_error = str(exc)`. Stop if the mapping needs per-tool string
   parsing, catches any first-row privacy-bearing miss, or touches core.
6. **Missing gates.** Add a firing test for `workspace directory identity
   unavailable` (`_workspace_reactor.py:226–230`) through the real resolver:
   add and patch a narrow module-local directory-stat callable so it raises
   `OSError`, without patching the shared `os` module object. Add the exact
   one-mebibyte schema-invalid stdio frame from [MCP-10]/[MCP-12], assert the
   fixed schema error contains none of the payload, then issue a valid
   `list_workspaces` request on the same connection and assert success.
7. **Remove the channel adapter.** Red: a test that `taut mcp
   --claude-channel` is a usage error (exit 1) and that legacy
   initialization advertises no `experimental` capability. Delete the
   adapter module, its tests, the flag plumbing, the reactor state and
   signal path, and the capability advertisement; keep every
   `resources/updated` proof green. Stop if removal touches the
   `last_signalled_text` path, which the standard notification owns. Reconcile
   `docs/implementation/07-taut-mcp-architecture.md` and
   `docs/implementation/02-repository-map.md` in this slice.
8. **README:** delete the existing `--claude-channel` paragraph; add a
   `claude mcp add`/`mcpServers` example and explain where a token comes from.
9. **Tool description nits** (optional, same manifest size check):
   `reply` empty-result meaning, `log.since` unit, `token` source hint.
10. **Traceability, CHANGELOG, completed-work review, index flip.**

## Testing Plan

- Layer: real stdio server subprocess for the contract proofs (existing
  `test_stdio_server.py` harness); real `ProcessReactor` with real SQLite
  for resource-update retention. Do not mock the command layer or reactor.
  Task 6 may patch only the new module-local directory-stat callable while
  keeping the real resolver and attachment path.
- Mutation check: remove the new `NotFoundError` arm and confirm task-4
  tests fail.
- Run `-m "not pg_only"` for the extension; run the PG conformance lane
  via `bin/pytest-pg` if Docker is available.

## Verification and Gates

```bash
cd extensions/taut_mcp && uv run --extra dev pytest -n 0 -m "not pg_only"
cd extensions/taut_mcp && uv run --extra dev ruff check taut_mcp tests && uv run --extra dev mypy taut_mcp tests --config-file pyproject.toml
uv run --extra dev pytest tests/test_core_summon_wheel_matrix.py -n 0   # manifest byte ceiling
bin/check-doc-paths && bin/check-plan-status-index
```

## Independent Review Loop

Reviewer: a different family. Inputs: this plan, the [MCP-6] table, the
`say` sentence, `_workspace_reactor.py` `_execute_command`,
`_commands.py`, the false test, and the installed SDK stdio reader. Ask: "Is
the fixed non-private error set complete and correct? Does any content-free
class lose its privacy guarantee? Does the large-frame probe test the stated
SDK-owned contract without pretending a frame limit exists?"

## Out of Scope

- Launch-time `--workspace`/`--token-file` defaults (design suggestion in
  the review; separate plan if wanted).
- SIGINT handling of the standalone server (host closes stdin; documented
  path unchanged).
- Rate-admission and workspace-cap behavior.
- Any change to core exception classes or CLI exit codes.

## Assumptions and Open Questions

1. **Resolved owner decision (2026-09-24):** remove the Claude channel
   adapter rather than scope or generalize it.
2. **Assumption:** the tool-error text mirrors the CLI stderr line exactly;
   if core's message includes a path or identity detail for a channel
   miss, the reviewer decides whether to keep it (channels are not
   privacy-bearing).

## Deviation Log

| Spec ref | Planned behavior | Actual behavior | Rationale | Spec proposal |
|----------|------------------|-----------------|-----------|---------------|

## Review Log

(append-only)

- 2026-09-24 — Focused independent repair review: BLOCKED on two omissions.
  The plan added `channel_show`/`channel_topic` without enumerating the old
  [MCP-6]/[MCP-12] empty-result text and `test_channel_tools.py` proof, and
  adapter removal did not enumerate all [MCP-2]/[MCP-3]/[MCP-8]/[MCP-9]/
  [MCP-12], implementation-mapping, architecture-note, and repository-map
  references. Accepted and corrected in the plan; scoped round-2 required.
- 2026-09-24 — Scoped round-2: PASS. The reviewer verified the table's real
  [MCP-6] insertion point, old channel-empty spec and test reconciliation,
  and complete enumeration of the adapter's spec, mapping, architecture, and
  repository-map references. No new defect was introduced by the fixes.
- 2026-09-24 — Completed-work review by Claude Opus 5 under read-only tools:
  `blocker: F1`. Dispositions:

  | ID | Severity | Finding | Disposition |
  |----|----------|---------|-------------|
  | F1 | P2 | [MCP-12] promised no identity, activity, queue, cursor, topic, or notification effects for channel misses, but the new tests checked only the error envelope. | Accepted. The reactor test now covers absent and wrong-kind targets for both channel tools and compares member, token-claim, membership/cursor, thread/topic, inbox, and aggregate-resource snapshots before and after each miss. |
  | F2 | P3 | The absolute mutating-tool sentence contradicted the privacy-preserving empty row. | Accepted. Added the explicit first-row privacy carve-out. |
  | F3 | P3 | The fixed table left unlisted tools' general empty-result behavior ambiguous. | Accepted. The spec now says every tool outside the second row keeps the general rule and explains why the first row is enumerated. |
  | F4 | P3 | Byte-equivalence to CLI stderr was too strong because human rendering escapes text. | Accepted. The spec now promises core's diagnostic, the same message the CLI prints, without a byte-equivalence claim. |
  | F5 | P3 | The CHANGELOG named only mutating tools even though `channel_show` also changes. | Accepted. The entry now names non-private misses, mutating tools, and channel metadata lookups. |
  | F6 | nit | An unlisted `NotFoundError` falling through to empty looked accidental. | Accepted. Added a one-line intent comment. |
  | F7 | nit | The now-unused parsed-argument local was immediately deleted. | Accepted. Parse without binding. |
  | F8 | nit | The `reactor()` passthrough remains after adapter removal. | Accepted as no action, matching the reviewer's recommendation: inlining would touch many handlers for no behavior gain. |
- 2026-09-24 — Scoped round-2 over accepted F1–F7 fixes: PASS, no new
  defect. The reviewer also observed two stale documentation references
  outside that round's fix set. The proposed-spec quotation was synchronized
  with the accepted F2–F4 wording, and the root README's pointer to the
  deleted `--claude-channel` flag was removed. A historical retired plan's
  test filename remains history and requires no change.

## Execution Log

(append-only)

- 2026-09-24 — Owner direction: `--claude-channel` is probably the wrong
  path and should be deleted, or at minimum generalized. Plan revised to
  deletion with generalization as the recorded rejected alternative.
- 2026-09-24 — Owner confirmed adapter removal. Fresh-eyes correction aligned
  `channel_show` and `channel_topic` with the fixed error table, replaced the
  nonexistent SDK/server frame-limit premise with an exact one-mebibyte
  continuity floor, specified a narrow directory-stat seam that fires the
  real resolution branch, and removed the stale README opt-in task.
- 2026-09-24 — Promoted [MCP-2]/[MCP-3]/[MCP-5]/[MCP-6]/[MCP-8]/[MCP-9]/
  [MCP-10]/[MCP-12] at HEAD
  `cfd87999c3ed75a1112e8c2d2c019c4fb3fe5da2`; the final uncommitted spec
  diff hash is recorded in Spec Baseline. A stale later [MCP-6] `say`
  sentence and broad ordinary-not-found sentence were found by the
  reconciliation grep and corrected before verification.
- 2026-09-24 — TDD evidence: the first real-stdio `say` case failed as empty
  success; after the reactor arm, six cases passed while the two channel
  metadata cases still failed; removing their command-layer normalization
  made all eight fixed-table cases pass. The reply schema tests first accepted
  an 18-digit id and mismatched the description, then all 29 parameterized
  cases passed. The directory-identity probe failed before the narrow stat
  seam existed, then passed through the real attachment path. Both removed
  launch surfaces first accepted `--claude-channel`, then both rejected it.
- 2026-09-24 — The one-mebibyte continuity probe passed on its first run. This
  is the planned substitute proof that current SDK-owned framing already met
  the clarified contract; no production frame limit or reader change was
  needed.
- 2026-09-24 — Local verification: MCP non-PostgreSQL suite 336 passed, 10
  deselected; MCP PostgreSQL conformance 10 passed, 335 deselected; installed
  wheel matrix 66 passed; Ruff and format clean; strict mypy clean across 23
  files; 21 tools serialize to 20,504 bytes; doc-path, plan-index, and diff
  checks pass.
- 2026-09-24 — Completed-work review F1 reproduced the missing state-proof
  gap. The accepted test now fires for absent and wrong-kind channel targets
  across both channel tools; both parameter cases pass with exact before/after
  semantic snapshots. F2–F7 received the scoped wording and cleanup fixes;
  F8 required no change.

## Fresh-Eyes Review

The two places an implementer could guess wrong are arm ordering in
`_execute_command` and preserving the command-layer exceptions for
`channel_show`/`channel_topic`; task 5 states both. The privacy boundary and
the no-fiction frame-size contract are the invariants most worth a reviewer's
time; the [MCP-6] table and [MCP-10]/[MCP-12] probe text make them explicit.
