# VS Code Integrated Terminal Misclassified as Agent

Date: 2026-07-07
Owner: maintainer
Area: identity classification ([IAN], `taut/identity.py`)

## Problem

A human using a VS Code **integrated terminal** is classified as an `agent`.
`select_anchor()` walks the caller's process chain (leaf→root, closest to
`taut` first) and selects the first process that is not a shell or wrapper as an
"agent anchor". In a VS Code integrated terminal the chain is
`taut → shell → Code Helper → …`; `Code Helper` is not in
`INFRASTRUCTURE_BASENAMES`, so it is selected and `capture.kind` becomes
`"agent"` ([identity.py:192](../../taut/identity.py), capture at
[identity.py:108](../../taut/identity.py)).

`kind` is not cosmetic. It drives (confirmed by reading the code): `who`/`whoami`
output and the TUI presence footer; presence computation (agent presence is
process-anchor liveness: here/gone/remote); identity **recovery** (agents recover
by anchor match, humans by host+uid fallback — a misclassified human loses the
uid fallback path); and agent rejoin-candidate ranking. It does **not** affect
permissions (membership, cursors, sending, DMs, notifications) — those key off
`member_id`.

## Root cause and why the chosen fix works

`INFRASTRUCTURE_BASENAMES` already lists terminal emulators / session hosts
(`terminal`, `iterm2`, `wezterm`, `alacritty`, `kitty`, `ghostty`, `tmux`,
`screen`, …) as "hosts a session, not an actor → human fallback". VS Code's
integrated terminal is a terminal emulator hosted by Electron helper processes.
**The bug is a missing list entry, not a missing concept.**

This fix does not blind us to real agents, because of chain direction: a genuine
agent runtime (codex, claude, cursor-agent, a node extension host) runs as its
own process *between* `taut` and `Code Helper`, so `select_anchor` reaches and
selects it first. `Code Helper` is only considered when nothing agent-like sits
below it.

Rejected alternatives (see conversation): agent-only allowlist (inverts the
model; new agents silently become human), split anchor-from-kind (schema/model
change that does not fix the classification decision, only relocates it), prompt
on ambiguity (violates the "agents never hang" ethos).

## Plan

### C1 — Add VS Code / Electron hosts to `INFRASTRUCTURE_BASENAMES`

`taut/_constants.py`: add `electron`, `code`, `code helper`. `basename` is
`Path(argv0-or-exe).name.lower()`, so `Code Helper.app/.../Code Helper` →
`code helper`; the Linux binary is `code`; the dev/main process is `electron`.

`codex` is safe: the entries are exact-match and `"codex" != "code"`. The
existing `select_anchor` test already asserts `codex` is selected as an agent;
that stays green.

### C2 — Collapse Electron helper role suffixes so one entry covers all variants

VS Code helper processes append a role suffix: `Code Helper (Renderer)`,
`Code Helper (Plugin)`, `Code Helper (GPU)` → basenames
`code helper (renderer)` etc. Rather than enumerate every variant (fragile
across versions), normalize in `select_anchor`: strip a single trailing
` (...)` group before the infrastructure membership test, so a lone
`code helper` entry matches every role.

- Add a small module-level helper in `taut/identity.py`:
  `_ROLE_SUFFIX_RE = re.compile(r"\s*\([^)]*\)$")` and test the stripped name
  in addition to the raw `proc.basename`.
- Safe against agents: `codex`/`claude`/`cursor-agent` carry no trailing
  ` (...)` group, so stripping is a no-op for them; and stripping only affects
  the infra comparison, never the shell/wrapper skip or anchor selection of a
  real process.
- The human-fallback rule string keeps the *raw* basename (accurate: it names
  the real process that was seen).

Confirm `re` is imported in `taut/identity.py`; add if absent.

### Tests (red-green) — `tests/test_identity.py`

Extend the `select_anchor` coverage:

1. `shell → code helper` ⇒ `(None, "human fallback at infrastructure process code helper")`.
2. `shell → code helper (renderer)` ⇒ human fallback (suffix normalization).
3. `shell → electron` and `shell → code` ⇒ human fallback.
4. `shell → codex → code helper` ⇒ agent anchor at `codex` (real agent nested
   under VS Code is still caught — the load-bearing assertion).
5. Guard: `codex` alone is still selected as an agent (regression pin that the
   `code` entry / suffix strip does not swallow `codex`).

Anti-mock: pure `ProcessInfo` fixtures through the real `select_anchor`, matching
the existing test at `tests/test_identity.py:333`.

### Docs

If `docs/specs/03-identity-addressing-notifications.md` enumerates
infrastructure/host processes, add editor/Electron terminal hosts to that list
so the spec matches behavior. Otherwise no spec change.

## Scope / non-goals

- **No migration.** This changes *future* captures only. An `alexa` member
  already stored as `agent` under the old heuristic stays `agent`; that is the
  maintainer's own dev DB, and a classification heuristic does not warrant a
  data migration. Re-joining from a plain terminal after the fix creates/reuses
  a human identity.
- **No `--kind` override, no anchor/kind split.** Recorded as possible future
  work; neither is needed to fix this defect.
- Cursor / Windsurf (same Electron shape) are included: `cursor`,
  `cursor helper`, `windsurf`, `windsurf helper`. Their in-editor agents
  (`cursor-agent`) run as their own process below the host and are still
  selected first — pinned by a `cursor-agent` guard test.

## Verification (2026-07-07)

- `pytest tests/test_identity.py` — 43 passed (5 new assertions red before the
  fix, green after). `ruff` and `mypy` clean on `taut/identity.py` +
  `taut/_constants.py`.
- Full-suite run: **375 passed, 0 failed**. The 2 `tests/test_watcher.py`
  failures seen mid-work were **pre-existing / unrelated** — environment drift
  (local `.venv` had `simplebroker 4.10.0`; `pyproject.toml` requires `>=5.1.0`,
  which added `PollingStrategy.detach_activity_waiter`). Cleared by refreshing
  the venv (`uv pip install -e '.[dev]'` → simplebroker 5.1.0), not by any code
  change here.
