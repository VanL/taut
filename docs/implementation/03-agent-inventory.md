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

Last refreshed: 2026-11-10 (CLI version refresh across installed agent tools plus live `codex` 0.161.0 enclosing-parent read-only plan reviews)

| Agent family | Status | Notes |
|--------------|--------|-------|
| Claude | verified usable; review-eligible | `/opt/homebrew/bin/claude`, version 2.1.293. Liveness and plan-mode write-attempt containment verified via `--safe-mode -p --permission-mode plan --tools Read,Grep,Glob --allowedTools Read,Grep,Glob --strict-mcp-config --no-session-persistence --output-format json` (`skills/call-agent/SKILL.md`). For long reviews, prefer `--output-format stream-json --verbose --include-partial-messages` so active progress is distinguishable from stalls, keep matched `--tools`/`--allowedTools`, close stdin (`< /dev/null`), and check `terminal_reason=completed` independently of exit code. |
| Codex | verified usable; review-eligible | `/opt/homebrew/bin/codex`, version `codex-cli 0.161.0`. Passed fresh liveness probe and completed two bounded enclosing-parent read-only reviews on 2026-11-10 (`codex exec -s read-only --skip-git-repo-check -C /Users/van/Developer -o <out> - < <prompt>`) with zero repository writes (`docs/plans/2026-11-10-upstream-port-runtime-hardening-and-theory-wave-plan.md`). Always close or redirect stdin (`< /dev/null` or `< prompt_file`) so `codex exec` never blocks waiting for additional stdin. |
| Grok | verified usable under named OrbStack profile (`6b0f800`) | `/Users/van/.local/bin/grok`, version `1.0.77 (50ca579fa996) [stable]`. Default bare invocation still hits the macOS `/var/run/docker.sock` symlink restriction recorded on 2026-09-25, whereas invoking with the verified `review-read-only-macos` OrbStack profile documented in `skills/call-agent/SKILL.md` (`6b0f800`) preserves read-only containment cleanly. |
| Agy (Antigravity) | verified usable; review-eligible (`5b8e439`) | `/Users/van/.local/bin/agy`, version `1.5.5` (`agy chat --mode agent --print`, Gemini family such as `gemini-4-argon-medium`; verified in `5b8e439` and `skills/call-agent/SKILL.md`). Replaces standalone `gemini` CLI as the Gemini-family Tier-1 reviewer when the authoring session is non-Gemini. |
| Gemini (standalone CLI) | retired / deprecated for review | `/opt/homebrew/bin/gemini`, version 0.46.0. Retired as a reviewer CLI per `skills/call-agent/SKILL.md`; use `Agy (Antigravity)` for Gemini-family reviews instead. |
| Qwen | present (unprobed for review) | `/opt/homebrew/bin/qwen`, version 0.17.1. Binary present; run liveness + write-containment probes (`skills/call-agent/SKILL.md` step 6) before selecting as a reviewer. |
| Kimi | present (unprobed for review) | `/opt/homebrew/bin/kimi`, version 0.43.1. Binary present; run liveness + write-containment probes (`skills/call-agent/SKILL.md` step 6) before selecting as a reviewer. |

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

A separate scoped instrumentation review used that streamed invocation and
saved exact prompt, with the same 540-second bound and containment. It also
exited 124, but retained 6,314 stream events and 36 assistant messages with
empty stderr: active work, not evidence of an idle CLI. No terminal result or
verdict was returned and none is inferred. The review gate uses an independent
separate-role fallback; future cap calibration should account for observed
review latency rather than describe this attempt as an authentication failure.

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

2026-09-28: Claude CLI 2.1.282 passed fresh liveness and write-containment
probes for the simplification plan using `--safe-mode`, plan permissions,
matched Read/Grep/Glob tools, strict MCP configuration, no session persistence,
JSON output and closed stdin (120-second bounds). The probes returned
`PROBE-OK` and `WRITE-UNAVAILABLE`, exit 0, success/end_turn, completed,
`is_error=false`; no probe file appeared. The default model resolved to
`claude-opus-5-5`. Review outcome belongs in the simplification plan.

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
