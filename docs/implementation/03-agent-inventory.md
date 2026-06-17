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

Last refreshed: 2026-06-12

| Agent family | Status | Notes |
|--------------|--------|-------|
| Claude | verified usable | Authoring agent for the 2026-06-12 foundation docs (this environment) |
| Codex | verified usable | `/opt/homebrew/bin/codex`; performed the 2026-06-12 foundation-docs review (`codex exec --sandbox read-only`) |
| Gemini | present, blocked | `/opt/homebrew/bin/gemini`; 2026-06-12 invocation failed: `GEMINI_API_KEY` not set in environment |
| Qwen | present, blocked | `/opt/homebrew/bin/qwen`; 2026-06-12 invocation failed: configured model unavailable on free tier (API 404) |
| Kimi | present, blocked | `/Users/van/.local/bin/kimi`; 2026-06-12 invocation failed: API key invalid or expired (401) |
| Grok | present, currently unreliable | `/Users/van/.grok/bin/grok`; re-authorized 2026-06-12 and worked for round 4, but the 0.1.1 round 5 implementation-review attempt hung after environment/plugin warnings and returned no findings. Treat as fallback-only until a fresh no-op or review invocation completes. |

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
