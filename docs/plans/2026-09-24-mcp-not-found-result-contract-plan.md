# MCP Not-Found Result Contract Plan

Status: draft — defect verified by code reading and a live reactor
reproduction; awaiting independent plan review.

Class: 5 (spec-changing) and risky under [DOM-5]: the change revises the
normative [MCP-5]/[MCP-6] result rules for mutating tools, which is a public
protocol contract. Hardening is required. Not process-changing.

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
[MCP-6] empty rule; the CLI gives each an actionable diagnostic. Evidence:
`docs/plans/artifacts/2026-09-23-deep-dive-review.md` §1 item 6 and §2.

## Requested Outcomes

- [ ] `say` to a missing channel/sub-thread or unknown `@route` returns
  `isError:true` with core's diagnostic text; the exact `dm.d_*` miss stays
  a content-free empty result.
- [ ] The spec lists which tools return content-free empties (privacy-
  bearing lookups) and which mutating tools surface not-found as
  `isError`; `reply`, `leave`, and `channel_rename` join the second group.
- [ ] A reactor-level or stdio-level test fires for each of the three `say`
  target forms and for the three other mutating tools.
- [ ] `reply.msg_id` accepts exactly 19 digits, as `message_show`,
  `message_delete`, and `message_react` already do; the [MCP-5] parameter
  row drops the suffix form (follows the CLI plan's suffix removal, decided
  by the owner on 2026-09-24).
- [ ] Two gates [MCP-12] and [MCP-10] already claim exist: a firing test
  for `workspace directory identity unavailable` and an oversized-frame
  probe.
- [ ] The `--claude-channel` research-preview adapter is removed: the flag,
  the legacy-era `experimental["claude/channel"]` capability, the
  reactor's `last_claude_attempted_text` state and `_signal_claude_change`
  path, `_claude_channel.py`, its tests, the [MCP-3]/[MCP-9] text, and the
  README paragraph. The standard `resources/updated` notification on
  `taut://notifications/current` is the one wake mechanism (owner
  direction 2026-09-24, pending confirmation; generalization is the
  recorded rejected alternative).

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
  and get native machine transport), [THEORY-5] A3 (tokens are selectors;
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
- Promotion baseline identifier: recorded after the spec-promotion slice.

## Proposed Spec Delta

Promotion strategy: **A — in-file edit, text before link claims**.

| Spec file | Strategy | Sections touched |
|-----------|----------|------------------|
| `docs/specs/05-taut-mcp.md` | A | [MCP-6] new "empty versus error" table; [MCP-5] `say` sentence; [MCP-3] channel capability sentence (remove); [MCP-9] channel adapter paragraph (remove); `## Related Plans` |

### [MCP-6] — insert a classification table after the paragraph ending
`without route, participant, or existence detail.`

> Empty results are content-free by design only where a nonempty error
> would leak existence or membership. The classification is fixed:
>
> | Tool | Not-found disposition |
> |------|-----------------------|
> | `read`, `log`, `search` with a DM selector; `message_show`; `message_delete`; `message_react`; `say` to an exact `dm.d_*` handle | content-free typed empty result |
> | `say` to a channel, sub-thread, or `@name-or-alias`; `reply`; `leave`; `channel_rename`; `channel_topic`; `channel_show` | `isError:true` carrying core's diagnostic text for that miss, byte-equivalent to the CLI's stderr line, with no dispatch-side identity or activity effect |
>
> A mutating tool never reports success for work it did not do. The
> reactor maps core `NotFoundError` to a tool error for the second row
> before applying the general empty-result rule; the general rule applies
> only to the first row.

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

### [MCP-9] — remove the channel adapter paragraph

Remove the paragraph beginning `An opt-in `--claude-channel` mode declares
the experimental` through `part of the host-specific adapter.` Replace with
one sentence:

> Taut ships no host-specific wake adapter. The standard
> `notifications/resources/updated` on `taut://notifications/current` is
> the only wake hint; a host that gives the agent a turn on some other
> signal maps that signal itself (instruction 6).

Recorded rejected alternative (owner, 2026-09-24): generalizing the
adapter into a per-host wake-cue registry. Rejected because only one host
protocol exists, it is legacy-era only, and the standard resource update
already carries the same information; a registry over one entry is
speculative architecture (engineering principle §7). Reconsider when a
second host protocol with concrete external pull cannot act on the
standard resource notification.

### `## Related Plans` — add

> - `docs/plans/2026-09-24-mcp-not-found-result-contract-plan.md` — fixes
>   mutating tools reporting not-found as empty success, classifies empty
>   versus error per tool, adds the two missing [MCP-12]/[MCP-10] gates,
>   and removes the research-preview Claude channel adapter in favor of the
>   standard resource notification.

## Context and Key Files

Files to modify:

- `extensions/taut_mcp/taut_mcp/_workspace_reactor.py` —
  `_execute_command` (line ~340–365): `except TokenError`, `except
  BlankMessageError`, `except EmptyResultError: pass`, `except (TautError,
  TypeError, ValueError)`, `except Exception` (`[RUFF-SUP-066]`). The
  `EmptyResultError` arm must come after a `NotFoundError` arm that
  applies only to the mutating tool names.
- `extensions/taut_mcp/taut_mcp/_commands.py` — `say` branch (line
  ~60–70) already re-raises `NotFoundError` for non-DM targets; `reply`,
  `leave`, `channel_rename` branches call core directly.
- `extensions/taut_mcp/taut_mcp/_process_reactor.py` —
  `configure_claude_channel` (line ~633), `_signal_claude_change` (line
  ~666), the call at ~723, and `last_claude_attempted_text` state, all to
  remove; frame-size handling for the oversized probe (grep `max_frame`,
  `readline`).
- `extensions/taut_mcp/taut_mcp/_claude_channel.py` (40 lines, delete),
  `tests/test_claude_channel.py` (delete), `cli.py` lines ~19–104 and
  `command.py` line ~20 (`claude_channel` parameter and flag), `server.py`
  lines ~27, ~92–128, ~288 (capability advertisement and configuration).
- `extensions/taut_mcp/tests/test_tools.py` —
  `test_say_normalizes_only_exact_stable_dm_not_found` (false test; move
  its assertion to the reactor level).
- `extensions/taut_mcp/tests/test_stdio_server.py` — add the stdio-level
  cases and the oversized-frame probe.
- `extensions/taut_mcp/tests/test_process_reactor.py` — remove cue
  assertions; keep `last_signalled_text` resource-update proofs.
- `extensions/taut_mcp/README.md` — host registration example and
  token-source pointer ([MCP-9] says the README documents the channel
  opt-in; it does not).
- `taut/_exceptions.py` — read only: `EmptyResultError(TautError)` at
  line ~59, `NotFoundError(EmptyResultError)` at line ~67. Do not change
  the hierarchy; the CLI relies on it.

Read first: [MCP-5] tool table rows for the six mutating tools; [MCP-6] in
full; `_workspace_reactor.py` `_execute_command`; the CLI exit mapping in
`taut/commands/_dispatch.py` for `NotFoundError` (exit 2 with the message
on stderr) so the tool-error text matches byte-for-byte.

Comprehension gate:

1. **Why does the command-layer re-raise not reach the client?** Expected:
   the reactor catches the parent class `EmptyResultError` and returns an
   empty success; the subclass relationship makes the catch match.
2. **Why not change the exception hierarchy?** Expected: the CLI maps both
   to exit 2 deliberately ([TAUT-8.1]); the MCP surface needs a different
   disposition for mutating tools only, so the discrimination belongs in
   the reactor's tool-aware mapping, not in core.
3. **Why do lookups stay content-free?** Expected: [MCP-6] and [TAUT-7.6]
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

Failure policy: a not-found on a mutating tool is a tool error (fatal for
that call, no retry); the workspace stays attached.

## Rollout, Rollback, and One-Way Doors

- Source revert. Hosts that depended on empty-success for a missing channel
  would see errors instead; that is the contract the spec already stated.
  CHANGELOG entry required.
- No one-way door.
- Post-deploy signal: an MCP client calling `say` with a nonexistent
  channel receives `isError:true` and the text `thread not found: <name>`.

## Dependency-Ordered Tasks

1. **Independent plan review** including the [MCP-6] table.
2. **Owner confirmation** of the channel adapter removal (outcome 5).
3. **Spec-promotion slice**; record the promotion baseline.
4. **Red tests.** In `test_stdio_server.py`, drive the real server over
   stdio: `say` to `nochannel`, to `general.1234567890123456789`, and to
   `@nobody`; `reply` to a missing parent; `leave` and `channel_rename` on
   a missing channel. Assert `isError:true` and the CLI stderr text. Assert
   `say` to a well-formed absent `dm.d_*` still returns the empty result.
   All must fail at baseline (empty success). Delete the spy-based false
   test or convert it to a reactor-level test.
5. **Implement the reactor mapping.** Add a `NotFoundError` arm before the
   `EmptyResultError` arm in `_execute_command`, gated on the tool name
   being in the mutating set; map to `command_error = str(exc)`. Stop if
   the mapping needs per-tool string parsing or touches core.
6. **Missing gates.** Add a firing test for `workspace directory identity
   unavailable` (`_workspace_reactor.py:226–230`) by making the directory
   identity call fail through the established fake seam; add the
   oversized-frame probe (a single frame above the SDK/server limit)
   asserting the server stays alive and the client receives a bounded
   error or the connection closes per [MCP-10] — read [MCP-10] for the
   exact promised behavior first.
7. **Remove the channel adapter.** Red: a test that `taut mcp
   --claude-channel` is a usage error (exit 1) and that legacy
   initialization advertises no `experimental` capability. Delete the
   adapter module, its tests, the flag plumbing, the reactor state and
   signal path, and the capability advertisement; keep every
   `resources/updated` proof green. Stop if removal touches the
   `last_signalled_text` path, which the standard notification owns.
8. **README:** add a `claude mcp add`/`mcpServers` example, where a token
   comes from, and the channel opt-in text [MCP-9] promises.
9. **Tool description nits** (optional, same manifest size check):
   `reply` empty-result meaning, `log.since` unit, `token` source hint.
10. **Traceability, CHANGELOG, completed-work review, index flip.**

## Testing Plan

- Layer: real stdio server subprocess for the contract proofs (existing
  `test_stdio_server.py` harness); real `ProcessReactor` with real SQLite
  for the cue test. Do not mock the command layer or the reactor; the only
  fake is the established Win32/directory-identity seam for task 6.
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
`_commands.py`, the false test. Ask: "Is the mutating-tool set complete
and correct? Does any content-free class lose its privacy guarantee?"

## Out of Scope

- Launch-time `--workspace`/`--token-file` defaults (design suggestion in
  the review; separate plan if wanted).
- SIGINT handling of the standalone server (host closes stdin; documented
  path unchanged).
- Rate-admission and workspace-cap behavior.
- Any change to core exception classes or CLI exit codes.

## Assumptions and Open Questions

1. **Owner (leaning delete, 2026-09-24; confirm):** remove the Claude
   channel adapter rather than scope or generalize it. Recommended: delete.
2. **Assumption:** the tool-error text mirrors the CLI stderr line exactly;
   if core's message includes a path or identity detail for a channel
   miss, the reviewer decides whether to keep it (channels are not
   privacy-bearing).

## Deviation Log

| Spec ref | Planned behavior | Actual behavior | Rationale | Spec proposal |
|----------|------------------|-----------------|-----------|---------------|

## Review Log

(append-only)

## Execution Log

(append-only)

- 2026-09-24 — Owner direction: `--claude-channel` is probably the wrong
  path and should be deleted, or at minimum generalized. Plan revised to
  deletion with generalization as the recorded rejected alternative;
  awaiting confirmation.

## Fresh-Eyes Review

The one place an implementer could guess wrong is arm ordering in
`_execute_command`; task 5 states it. The privacy boundary is the
invariant most worth a reviewer's time; the [MCP-6] table makes it
explicit per tool.
