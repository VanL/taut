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

Last refreshed: 2026-07-15

| Agent family | Status | Notes |
|--------------|--------|-------|
| Claude | verified usable; review-eligible | `/opt/homebrew/bin/claude`, version 2.1.207. Liveness and prior plan-mode write-attempt containment remain verified. On 2026-07-15 the default Fable model returned a quota 429 while explicit `--model sonnet` and `--model opus` succeeded. One large tool-less JSON review consumed output but returned an empty top-level result, and resume then hit `cache_control cannot be set for empty text blocks`; bounded direct-text calls with only Read/Grep/Glob completed. The MCP implementation owner requires Opus for further Claude reviews in that thread. Review wrappers must inspect stdout JSON on nonzero exit, not only stderr. |
| Codex | verified usable | `/opt/homebrew/bin/codex`, version 0.144.1. This 2026-07-11 task and its independent review run through Codex successfully. |
| Gemini | present | `/opt/homebrew/bin/gemini`, version 0.46.0. Version probe passed 2026-07-11; prior credential failure was not re-probed. |
| Qwen | present | `/opt/homebrew/bin/qwen`, version 0.17.0. Version probe passed 2026-07-11; prior model-access failure was not re-probed. |
| Kimi | present | `/Users/van/.kimi-code/bin/kimi`, version 0.23.5. Version probe passed 2026-07-11; prior credential failure was not re-probed. |
| Grok | verified usable; review-eligible | `/Users/van/.local/bin/grok`, version 0.2.101. Two plan reviews completed with `EndTurn` on 2026-07-14 under the OS-enforced read-only sandbox; no sandbox fail-open warning or repository write was observed. Write-attempt containment was verified when the `call-agent` skill was adopted. |

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
