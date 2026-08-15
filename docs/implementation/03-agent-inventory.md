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

Last refreshed: 2026-08-14

| Agent family | Status | Notes |
|--------------|--------|-------|
| Claude | verified usable; review-eligible | `/opt/homebrew/bin/claude`, version 2.1.207. Liveness and prior plan-mode write-attempt containment remain verified. On 2026-07-15 the default Fable model returned a quota 429 while explicit `--model sonnet` and `--model opus` succeeded. On 2026-08-04 a large review timed out after `--allowedTools "Read,Grep,Glob"` still exposed Bash/Agent and Claude waited on a background agent; `--allowedTools` controls approval, not availability. A corrected probe with both `--tools "Read,Grep,Glob"` and `--allowedTools "Read,Grep,Glob"` exposed exactly those three tools and passed. On 2026-08-14 exact model `claude-fable-5` completed a 7-minute repository plan review with terminal reason `completed`; the invocation deliberately added Bash for user-requested focused tests while retaining the no-edit brief and produced no repository change. Long-review wrappers should use matched `--tools`/`--allowedTools`, disable subagents where supported, and inspect the final result/terminal reason. The MCP implementation owner requires Opus for further Claude reviews in that thread. |
| Codex | verified usable | `/opt/homebrew/bin/codex`, version 0.144.1. This 2026-07-11 task and its independent review run through Codex successfully. |
| Gemini | present | `/opt/homebrew/bin/gemini`, version 0.46.0. Version probe passed 2026-07-11; prior credential failure was not re-probed. |
| Qwen | present | `/opt/homebrew/bin/qwen`, version 0.17.0. Version probe passed 2026-07-11; prior model-access failure was not re-probed. |
| Kimi | present | `/Users/van/.kimi-code/bin/kimi`, version 0.23.5. Version probe passed 2026-07-11; prior credential failure was not re-probed. |
| Grok | verified usable; review-eligible; completion-signal drift observed | `/Users/van/.local/bin/grok`, version 1.0.3. A Class 5 plan review completed under the OS-enforced read-only sandbox on 2026-08-14 with no sandbox fail-open warning or repository write; focused tests ran and the response contained an explicit `BLOCKED` verdict with source-backed findings. JSON still reported lowercase `end_turn` rather than the `EndTurn` spelling documented by `skills/call-agent/SKILL.md`. Do not treat the lowercase signal alone as a passing gate until the invocation guidance is reconciled; inspect the explicit verdict and select another review-eligible family when a required PASS is unavailable. Write-attempt containment was verified when the skill was adopted. |

## Review Preference

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
