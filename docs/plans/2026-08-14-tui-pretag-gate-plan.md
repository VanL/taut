# TUI Pre-Tag Gate Plan

Date: 2026-08-14

Class: 4. This changes the exact-SHA workflow evidence required before remote
release tags and publication.

Status: active.

## Goal

Make TUI an independent pre-tag producer for coordinated releases without
duplicating its existing hosted suite. A failed or missing TUI workflow must
leave every release tag untouched.

## Invariants

- Move the retained-lock TUI matrix from the root workflow into
  `.github/workflows/test-tui-extension.yml`; do not clone it.
- Keep the root workflow as the sole release-byte producer for all five
  distributions.
- Require exact-SHA root, PostgreSQL, MCP, and TUI workflow success in both the
  local release observer and every tag gate.
- Preserve `--skip-checks` as a local-only human override. It must not bypass
  TUI workflow evidence.
- Stop the in-flight 0.9.0 release before tags, commit the corrected topology,
  and restart through the normal `release.py` path.

## Verification

- Red-first workflow and release-helper contract tests.
- Full workflow, release-script, and observer test modules.
- Ruff, formatting, mypy, doc paths, plan index, and diff checks.
- Hosted exact-SHA success for all four producer workflows before tags.
- Five successful release gates plus GitHub, PyPI, digest, and Sigstore checks.

## Execution Log

- 2026-08-14: Stopped the first 0.9.0 release while its exact-SHA producer
  observer was still waiting. No tag had been created. Added failing tests for
  the independent TUI workflow and its required presence in the local and tag
  observers.
- 2026-08-14: The first new TUI producer run caught three Ubuntu 3.11 test
  races before tagging. The tests waited for a placeholder row, file creation,
  or any navigation option rather than their actual rendered outcome. Replaced
  those weak waits with semantic conditions for the inspector result, channel
  target, pointer selection, and direct-message target. No product timeout was
  changed and no failed run was rerun.
- 2026-08-14: The next exact-SHA run proved Ubuntu 3.11 green and caught a
  macOS focus-event race in the message-send handler case. The test typed as
  soon as it requested focus, before the app had processed the focus event and
  entered compose mode, so the first character could be consumed as a normal
  gesture. It now waits for both focus and compose mode before typing.
- 2026-08-14: The following run proved the macOS correction and all Ubuntu
  cells green. Windows exposed two more polling races: a drag-out case sent
  Enter before pointer release was applied, and a live-reply case polled for a
  watcher-driven refresh through a one-second wall-clock loop. The former now
  waits for the semantic target, focus, and pointer-release states. The latter
  uses an event fired after the real navigation result applies the reply
  marker, with a bounded fail-safe rather than repeated sleeps.
- 2026-08-14: The next run found a search-result race on Ubuntu 3.14. Its wait
  observed a message row that was already present before the action, then
  asserted the still-pending history anchor. The completion condition now
  requires the exact search-result anchor as well as the row.
