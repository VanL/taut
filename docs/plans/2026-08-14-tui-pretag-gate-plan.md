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
