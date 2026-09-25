# Agent Inventory

## Purpose and Scope

This document records which agent families are currently available in the
environment and which ones are preferred for independent review work.

Keep it lightweight and refresh it when tooling changes materially.

## Governing Spec References

- `docs/specs/01-development-documentation-operating-model.md` [DOM-3]
- `docs/specs/01-development-documentation-operating-model.md` [DOM-11]
- `docs/specs/01-development-documentation-operating-model.md` [DOM-13]

## Verification Method

To refresh this inventory:

1. run a small read-only review or no-op prompt against each available agent
   interface
2. record whether it is:
   - verified usable
   - present but blocked by credentials or configuration
   - present but currently failing at invocation time
3. update the refresh date and notes

## Current Observed Availability

Probe mechanics and the review-eligibility rung (liveness +
write-attempt containment) are owned by `skills/call-agent/SKILL.md`
step 6. Claude and Grok were refreshed through that workflow on this machine;
the remaining statuses predate the skill's adoption and should be re-derived
before use.

Last refreshed: 2026-09-25 (Claude model-review timeout and Grok sandbox-blocked probes; details below)

| Agent family | Status | Notes |
|--------------|--------|-------|
| Claude | verified usable; review-eligible | `/opt/homebrew/bin/claude`, version 2.1.207. Liveness and prior plan-mode write-attempt containment remain verified. On 2026-07-15 the default Fable model returned a quota 429 while explicit `--model sonnet` and `--model opus` succeeded. On 2026-08-04 a large review timed out after `--allowedTools "Read,Grep,Glob"` still exposed Bash/Agent and Claude waited on a background agent; `--allowedTools` controls approval, not availability. A corrected probe with both `--tools "Read,Grep,Glob"` and `--allowedTools "Read,Grep,Glob"` exposed exactly those three tools and passed. On 2026-08-14 exact model `claude-fable-5` completed a 7-minute repository plan review with terminal reason `completed`; the invocation deliberately added Bash for user-requested focused tests while retaining the no-edit brief and produced no repository change. Long-review wrappers should use matched `--tools`/`--allowedTools`, disable subagents where supported, and inspect the final result/terminal reason. The MCP implementation owner requires Opus for further Claude reviews in that thread. On 2026-09-14, version 2.1.207 passed fresh liveness and write-attempt probes using `--safe-mode -p --permission-mode plan --tools Read,Grep,Glob --allowedTools Read,Grep,Glob --strict-mcp-config --no-session-persistence --output-format json`. The default resolved to `claude-opus-4-8[1m]`; the write attempt was refused, no probe file appeared, and repository status was unchanged. Both calls exited 0 with `success` / `end_turn`. The subsequent full audit-remediation plan review completed in 377 seconds with the same completion signals, overall PASS and two wording findings; no unexpected repository write. |
| Codex | verified usable; 2026-09-15 review attempts failed on environment | `/opt/homebrew/bin/codex`, version 0.144.1. This 2026-07-11 task and its independent review run through Codex successfully. On 2026-09-15 (version 0.144.3) two bounded read-only plan-review attempts produced no verdict: attempt 1 (900 s) timed out with stderr `Reading additional input from stdin` and no `agent_message`; attempt 2 with `< /dev/null` (1800 s) exited 1 after seven events with `rmcp::transport::worker` fatal `Transport channel closed` on an HTTP request to a configured MCP endpoint (`local.api.modelmonster.ai:18443`). Close stdin explicitly and disable or repair that MCP server configuration before the next Codex review; re-probe with a trivial file-reading prompt first. |
| Gemini | present | `/opt/homebrew/bin/gemini`, version 0.46.0. Version probe passed 2026-07-11; prior credential failure was not re-probed. |
| Qwen | present | `/opt/homebrew/bin/qwen`, version 0.17.0. Version probe passed 2026-07-11; prior model-access failure was not re-probed. |
| Kimi | present | `/Users/van/.kimi-code/bin/kimi`, version 0.23.5. Version probe passed 2026-07-11; prior credential failure was not re-probed. |
| Grok | blocked in current environment; fresh sandbox probe required | `/Users/van/.local/bin/grok`, now 1.0.41. The 2026-09-25 read-only probes fail closed on the Docker socket symlink; details below. Historical 1.0.3 review/containment passed in August, with lowercase `end_turn` completion-signal drift, but those results do not establish current eligibility. Do not bypass the sandbox or treat the old probe as current approval. |

## Review Preference

2026-09-25: Claude 2.1.273's Windows TUI slice-1 model review used the
previously verified safe-mode/plan-mode matched Read/Grep/Glob invocation,
strict MCP configuration, no session persistence, closed stdin and a
540-second bound. It timed out (exit 124) with empty stdout/stderr and no
verdict. This attempt supplies no review gate. The earlier successful
revision review remains valid; use an independent fallback for this model
and diagnose the stalled attempt before changing invocation guidance.

Bounded diagnosis found no flag/authentication/containment failure: one
same-containment file-read probe completed in 4.583 s, success/end_turn,
terminal_reason=completed, with only Glob/Grep/Read exposed. The failed
review's cause remains unknown; prior successful reviews exceeded 540 s.
Final-only JSON cannot distinguish a busy review from a stall. A verified
diagnostic improvement is `--output-format stream-json --verbose
--include-partial-messages`, preserving all containment and checking the
terminal result independently of exit. Save the exact assembled prompt too.
This is an invocation proposal, not permission to increase caps or blindly
retry a full review; the model gate used the independent fallback.

2026-09-25: Grok is now 1.0.41 (`4220f3b224a6`). Both bounded liveness
and write-containment probes refused to start, exit 1: the read-only sandbox
could not resolve `/var/run/docker.sock` because the endpoint is a symlink.
The tool **failed closed**, and no probe file appeared. Grok is blocked for
this environment, not review-eligible on the strength of the old 1.0.3
probe. Do not bypass the sandbox. Proposed follow-up: repair the sandbox's
runtime-socket path handling/configuration, then repeat both probes; this
TUI task does not modify Docker or the global CLI configuration.

2026-09-22: the unchanged Claude 2.1.273 safe-mode/Read-Grep-Glob invocation
completed core/MCP and Summon implementation reviews in 561 and 583 seconds,
both success/end_turn, terminal_reason=completed, is_error=false. An attempted
review write was denied by the restricted tool set. Findings and dispositions
are in the reactor-restoration plan; final integration review uses the same
containment and checks completion signals independently of process exit.

2026-09-19: Claude 2.1.273 passed a combined file-read/write-containment
probe for the reactor-restoration plan. Invocation used safe mode, plan mode,
matched Read/Grep/Glob tool sets, strict MCP configuration, no session persistence,
JSON output, closed stdin and a 120-second bound. Result: PROBE-OK with the
core-spec heading, WRITE-UNAVAILABLE, no probe file, exit 0, success/end_turn,
terminal_reason=completed, is_error=false. Reviewer resolved to
claude-opus-4-8[1m]. Full review outcome is recorded in the restoration plan.

2026-09-16: Claude 2.1.273 passed a fresh combined file-read/write-containment
probe with safe mode, plan mode, matched Read/Grep/Glob tool sets, strict MCP
config, no session persistence, JSON output and closed stdin. It read the
Summon spec heading (PROBE-OK) and reported WRITE-UNAVAILABLE;
`probe-write-test.txt` was absent. Result: success/end_turn, completed,
is_error=false; default reviewer resolved to claude-opus-4-8[1m].
The Windows lifecycle plan review completed in 290 seconds with exit 0,
success/end_turn and terminal_reason=completed, verdict PASS. Findings and
dispositions are recorded in that plan; no unexpected repository write occurred.

2026-09-15 Windows PTY plan review probe: Claude 2.1.207 passed a fresh
read-only file-reading liveness check (`PROBE-OK # Taut Summon Specification`)
with the same safe-mode, matched Read/Grep/Glob tool restrictions, strict MCP
configuration, and plan-mode invocation verified on 2026-09-14. Exit 0,
`success` / `end_turn`, terminal reason `completed`; the prior write-containment
proof applies to this unchanged version and invocation. No model override.

For plan review and final review:

1. prefer a different agent family than the authoring agent
2. if several are available, prefer one that has not already shaped the plan
3. if only one family is available, note that limitation and do a stricter
   fresh-eyes review

## Refresh Guidance

Update this file when:

- the available tool surface changes
- a new agent family becomes available
- an existing agent family is removed
- review workflow preferences change materially

Presence/version probes do not prove authenticated review capability. Before
selecting a merely present family, run the small read-only prompt described
above and promote it to `verified usable` or record the exact blocking error.

### MCP result simplification review refresh (2026-09-15)

Claude's fresh read-only file probe returned `PROBE-OK`; the full MCP result
review completed in 159 seconds with exit 0, success/end_turn, and
`terminal_reason=completed`, using `claude-opus-4-8[1m]`. Matched
Read/Grep/Glob tool sets, safe/plan mode, strict MCP config, closed stdin,
and no session persistence were used. A requested write was unavailable;
no repository review artifact was produced. Verdict: no correctness blocker;
the separately pending manifest ceiling was subsequently approved at 21,000
bytes by the owner. The active plan records the scope and disposition.

### Reported-issues follow-up plan review probe (2026-09-15)

Claude 2.1.207 passed a combined file-reading liveness and write-attempt
probe using `--safe-mode`, matched Read/Grep/Glob tool restrictions, plan
mode, strict MCP config, no session persistence, JSON output and closed
stdin (120-second bound). Result: PROBE-OK and WRITE-UNAVAILABLE;
`probe-write-test.txt` was absent and no repository write resulted. Exit 0,
success/end_turn, terminal reason completed; reviewer model
`claude-opus-4-8[1m]`. The follow-up review is recorded in
`docs/plans/2026-09-15-reported-issues-followup-plan.md`.

The reported-issues plan review completed in two rounds, both PASS with
exit 0, success/end_turn and terminal_reason=completed. Round 1 took
367 seconds under a 540-second bound; round 2 used a 360-second bound
and verified four accepted refinements. Both returned read-only verdicts;
no unexpected repository write occurred.

### BrokerSession plan review probe (2026-09-15)

Claude 2.1.207 passed a fresh file-reading liveness probe (`PROBE-OK # Taut
Core Specification`) and refused the requested repository write with only
Read/Grep/Glob available. No probe file appeared. Both calls exited 0 with
`success`, `end_turn`, and `terminal_reason=completed`; the default resolved
to `claude-opus-4-8[1m]`. Invocation used safe mode, plan mode, matched
Read/Grep/Glob tools/allowedTools, strict MCP configuration, no session
persistence, JSON output, closed stdin, and a 120-second per-probe cap.
The existing unrelated agent-kernel edit was preserved.

The complete BrokerSession plan review passed in 346 seconds (900-second
bound); scoped round-2 verification passed in 342 seconds (540-second bound).
Both exited 0 with success/end_turn and terminal_reason=completed. Findings
and dispositions are recorded in the BrokerSession plan. No unexpected
repository writes occurred.


### Reactor restoration Addendum C review (2026-09-22)

The installed Claude CLI 2.1.273 completed the bounded read-only review with
safe mode, plan permissions, Read/Grep/Glob only, strict MCP configuration and
no session persistence. Exit 0, success subtype, is_error false and end_turn
were checked. Verdict: no blocker. The full response and disposition live in
`docs/plans/2026-09-19-reactor-restoration-plan.md`, Addendum C. The final executor
submission rollback also received an independent slice review and real executor
failure tests after the broad review dispatch.

### Windows TUI determinism plan review probe (2026-09-24)

Claude CLI 2.1.273 passed the bounded read-only probe with safe/plan mode,
matched Read/Grep/Glob tool sets, strict MCP configuration, closed stdin,
and no session persistence. It read the TUI spec heading (`PROBE-OK`) and
reported `WRITE-UNAVAILABLE`; `probe-write-test.txt` was absent. The result
was success, `is_error=false`, `end_turn`, and `terminal_reason=completed`;
the reviewer resolved to `claude-opus-4-6`. Review outcome and dispositions
belong to the Windows TUI determinism root-cause plan's Review Log.
