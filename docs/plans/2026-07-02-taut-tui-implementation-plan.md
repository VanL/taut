# Taut TUI Implementation Plan

Date: 2026-07-02
Status: Reviewed four times — twice by Codex (2026-07-02, independent
sessions), a round-3 full review (Claude) with an independent Codex outside
voice (2026-07-03), and a round-4 external independent agent review
(2026-07-03); revised after each round. Rounds 3–4 findings (R3-1..R3-11,
R4-1..R4-4) are folded in below, including the maintainer-decided
watch-implies-seen unread semantics ([TUI-10.8], Option A). Remaining review
obligations are the standing per-slice reviews after Task 1 and Task 4 (§8).
Author: Claude (Opus 4.8)
Reviewers: Codex (gpt-5.5, `codex exec --sandbox read-only`), rounds 1–3;
Claude (Fable 5), rounds 3–4; an external independent agent (dispatched by
the maintainer), round 4 — see `## Review Log`

## 1. Goal

Build the first Textual-based terminal UI for Taut and ship it behind the
`taut[tui]` optional extra. Bare `taut` launched from an interactive terminal
opens the TUI; every existing CLI verb, JSON contract, exit code, and
non-interactive safety guarantee stays exactly as it is today. The TUI is a
pure consumer of `TautClient` + `TautClient.watch()` — it adds no second copy
of any command, identity, addressing, cursor, or watch semantics.

The build target is wireframe **frame 2a** ("Recommended shape — one screen"):
a three-pane layout `navigation │ transcript (inline foldable threads) +
composer │ presence`, with the active thread openable in a right-side pane on
`t`, the notification inbox as a navigation row, narrow-width degradation per
frame 1d, and the recovery states from frame 1e.

## 2. Source Documents

Source specs (baseline = repository commit `e06167e`, clean worktree at plan
authoring; spec 04 was introduced by that commit):

- `docs/specs/04-taut-tui.md` — the binding TUI behavior spec. Every `[TUI-*]`
  reference in this plan points here. This is the primary source of truth.
- `docs/specs/02-taut-core.md` [TAUT-8.1] (CLI verbs / exit codes),
  [TAUT-8.2] (output + JSON contract), [TAUT-8.3] (Python API surface),
  [TAUT-8.4] (watcher contract), [TAUT-12.4] (TUI is a `TautClient` +
  `TautWatcher` consumer, optional extra, no new core dependency).
- `docs/specs/03-identity-addressing-notifications.md` [IAN-5], [IAN-7] —
  addressing and notification semantics the TUI surfaces but must not
  reimplement.

Design source:

- Wireframe `Taut TUI Wireframe.html` (repository root, provided 2026-07-02).
  This is the same wireframe that `docs/specs/04-taut-tui.md` [TUI-2] was
  authored from. It is a self-unpacking Claude Design *canvas* bundle
  (`.dc.html`-style), **not** a design-system project, so the `claude_design`
  MCP (`DesignSync`, scoped to writable design-system libraries) could not
  import it — `list_projects` returned empty and the project id 404'd — and
  `WebFetch` of the design URL is login-gated (403). The wireframe content in
  this plan was extracted by decoding the bundle's embedded template locally.
  **Baseline rule:** where the wireframe and the spec differ, `04-taut-tui.md`
  is binding; the wireframe is directional for hierarchy, density, labels, and
  glyphs, which the spec explicitly declares non-contractual ([TUI-6.3],
  [TUI-6.6]).

Repo rules consulted (planning standard this document follows):

- `docs/agent-context/runbooks/writing-plans.md`
- `docs/agent-context/runbooks/hardening-plans.md` (this is risky,
  boundary-crossing work — see §4)
- `docs/agent-context/runbooks/testing-patterns.md` (TDD default, rule 5)
- `docs/agent-context/runbooks/review-loops-and-agent-bootstrap.md`

### 2.1 Wireframe content captured (for the implementer)

Frame **2a** is the build target. Frames 1a–1e are design directions that feed
specific behaviors:

- **Legend (all frames):** amber (`#e0af68`) = unread / active target / focused
  pane; filled dot `●` = present, hollow `○` = away. Title bar reads
  `taut · ~/myproject`; a size indicator like `120×34` is shown in the mock
  only.
- **Navigation (2a):** sections in order — `Channels` (`# general` 3,
  `# ops`, `# ci` 1), `Direct` (`● claude` 2, `○ van`), `Threads`
  (`↳ parser · general`), and `⧉ inbox` 2. Unread counts are right-aligned
  integers; DM rows carry a presence dot.
- **Transcript (2a):** header `── #general ─────── 6 members ·` with inline
  hints `m presence · t thread pane`. Rows: notices dimmed and inline
  (`09:13  · van created #general`, `09:15  · claude joined`); messages
  `09:14  van  <text>`; an inline thread affordance `↳ parser · 2 replies`
  with a `z fold` control and indented replies; a `── new messages ──────`
  unread separator.
- **Composer (2a):** anchored below transcript, label `message #general`, a
  `›` prompt glyph.
- **Presence (2a):** `Members · here 2`, rows `● van here`, `● claude here`,
  `○ codex away`; a `Selected identity` block
  (`claude · agent  m_abcd…24ab  presence: here  seen 09:24`); a `You` block
  (`● van  human`).
- **Key bar (2a):** `↑↓ move · ⏎ open · c compose · z fold · t thread pane ·
  m members · / search · g goto · i inbox · ? help · q quit`.
- **1b (side-pane):** opening a thread on `t` pops a right-side
  `↳ thread · parser` pane ("from 'tokenizer choked…' · esc closes") that
  **borrows the presence column**; presence collapses to a one-line header
  summary (`── #general ── 6 · ● van claude ○ codex`). The pane owns its own
  `reply in parser` composer.
- **1c (inline threads):** replies indent under the parent; `z` folds to a
  one-line `↳ parser · 2 replies`. Two-pane, presence on the `m` toggle.
  Directional for the 80–100 col medium mode.
- **1d (narrow):** ~80 cols → panes become tabs (`Nav | #general |
  Members`), transcript always reachable in the middle tab; <60 cols → nav
  shrinks to an icon rail (`# @ ↳ ⧉`), author metadata stacks above wrapped
  text; below the minimum, print a "terminal too small" hint.
- **1e (recovery):** (a) missing extra — `$ taut` → `TUI extra not installed.
  Install it with: pipx inject taut "taut[tui]"  Meanwhile the CLI works:
  taut list, taut watch. (exit 1)`; (b) uninitialized — `no .taut.db here /
  This directory isn't a taut project yet. run taut init` with an
  `↵ init here · q quit` action; (c) lost membership — inline non-blocking
  banner `⚠ lost membership in #ci — watcher removed it. history kept ·
  rejoin with taut join ci`.

## 3. Context and Key Files

### 3.1 Files to read first (with comprehension checks)

1. `docs/specs/04-taut-tui.md` — the whole spec. **Q:** which behaviors are
   binding vs. which visual details are explicitly not a stable contract?
   (Answer: structure/behavior/keyboard/states are binding; exact glyphs,
   hex, spacing, borders are not — [TUI-6.3], [TUI-6.6].)
2. `taut/cli.py` — argparse tree and dispatch. **Q:** what does bare `taut`
   (no subcommand) do today, and at which line? (Answer: `main()` at
   `cli.py:32` calls `build_parser().parse_args(...)`; at `cli.py:34`
   `if not hasattr(args, "func"): build_parser().print_help(); return 1`.
   That is the exact seam the TUI launch dispatch replaces.) **Q:** how are
   global options accepted before/after a verb? (Answer: `_hoist_global_options`
   at `cli.py:529` reorders `--db/--as/--token/--json/-t/-q` ahead of the
   subcommand; `--version`/`--help` are argparse actions that exit before
   `main` inspects `func`.)
3. `taut/client/__init__.py` — `TautClient`, `TautClient.init()`,
   `TautClient.watch(handler, threads=)`. **Q:** does the TUI ever construct
   queues, envelopes, or SQL directly? (Answer: no — it calls client methods
   only; [TUI-4.2].)
4. `taut/client/_models.py` — `Message`, `Thread`, `Member`, `Notification`,
   `InitResult` (frozen dataclasses; the exact fields the TUI renders).
5. `taut/watcher.py` — `TautWatcher`. **Q:** how is a watch loop started and
   stopped? (Answer: `run_forever()` blocks; `stop(*, join=True, timeout=2.0)`
   at `watcher.py:344` stops and joins; `add_queue`/`remove_queue` and the
   data-version + interval refresh converge membership while running,
   [TAUT-8.4].) **Q:** in which thread does the handler run, and who advances
   cursors / claims notifications? (Answer: the handler runs in the watcher's
   own loop thread; cursor advance happens inside taut's handler wrapper after
   the user handler returns, notification queues are claimed by the watch
   runtime — the TUI handler must NOT re-implement either; [TUI-10.5].)
6. `taut/cli.py` command bodies `_cmd_*` and emit helpers `_emit_*` /
   `_message_object` / `_member_object` — these show the exact client calls and
   field mappings the TUI reuses (e.g. `client.say`, `client.reply`,
   `client.list_threads`, `client.log`, `client.who`, `client.inbox`,
   `client.last_created_member`, `client.last_notification_warnings`).
7. `docs/implementation/04-taut-architecture.md` — the client/CLI/watcher
   boundary and the standing grep gates.
8. `pyproject.toml` — `[project.optional-dependencies]` (the `tui` extra and
   the `dev` Textual entry are **already applied** — §4a, finding R2-4;
   Task 0 verifies rather than adds; stale "no `tui` extra yet" claim
   corrected per finding R4-3), `[project.scripts] taut = "taut.cli:main"`,
   and the strict `mypy`/`ruff` gates.

### 3.2 Files to create

- `taut/tui/__init__.py` — defines `run_tui(*, db_path, as_name, token)`.
  **This module imports WITHOUT Textual** (INV-6): `run_tui`'s body probes
  `import textual` and, on failure, raises `MissingTuiExtraError` (defined in
  `taut/tui/_launch.py`, importable without Textual) before importing
  `taut.tui.app`. The launch site (Task 1) catches only `MissingTuiExtraError`,
  so a missing extra becomes the [TUI-5.1] hint while a genuine `ImportError`
  from a broken submodule still propagates as a real error (review finding
  R2-3). There is exactly one lazy Textual import point. `run_tui` does
  **not** construct `TautClient` before the App can render:
  `TautClient.__init__` raises `NotInitializedError` during target resolution
  when no database exists (`_base.py:110/117/119`), so client construction
  happens inside the App and is caught on startup — an uninitialized project
  renders the [TUI-10.1] empty state instead of crashing before a frame
  exists (review finding R3-2; see Tasks 3 and 8).
- `taut/tui/app.py` — the Textual `App` subclass: layout composition,
  key bindings, responsive mode switching, watch-thread wiring.
- `taut/tui/widgets/__init__.py`
- `taut/tui/widgets/navigation.py` — channels/direct/threads/inbox list.
- `taut/tui/widgets/transcript.py` — message rows, notices, inline threads,
  unread separator.
- `taut/tui/widgets/composer.py` — target-labelled input.
- `taut/tui/widgets/presence.py` — members + selected identity + acting member.
- `taut/tui/widgets/thread_pane.py` — right-side thread view + reply composer.
- `taut/tui/_launch.py` — pure (no Textual import) launch-decision logic:
  tty detection, the accepted-global-option set, and the CLI-vs-TUI decision.
- `taut/tui/_bridge.py` — the watcher-thread ↔ Textual marshaling bridge
  (see §4 hidden couplings; kept separate so its threading contract is
  testable without a running App).
- `taut/tui/py.typed` is **not** needed (the package already ships `taut/py.typed`).
- `taut/tui/app.tcss` — Textual CSS (optional; may be inline). Styling is not
  a contract ([TUI-11]).
- `tests/test_tui_launch.py` — launch dispatch / import boundary / non-tty /
  missing-extra / accepted options.
- `tests/test_tui_app.py` — Textual `Pilot`-driven behavior tests.
- `tests/test_tui_responsive.py` — responsive-mode selection.
- `tests/test_tui_recovery.py` — recovery states.
- `docs/implementation/05-taut-tui-architecture.md` — implementation doc.

### 3.3 Files to modify

- `taut/cli.py` — (a) fix the `main()` argv normalization at `cli.py:33`
  (`list(argv or sys.argv[1:])` → treat `argv=[]` as bare, review finding 1);
  (b) replace the bare-invocation branch at `cli.py:34` with the launch
  dispatch (§ Task 1). No change to any `_cmd_*`, JSON, or exit-code behavior.
- `taut/client/_threads.py` and `taut/client/_messaging.py` — add the two
  read-only accessors the TUI needs (`joined_threads()`, `read_cursor()`;
  Task 2, review findings 2 + 3). Additive only; no existing method changes.
- `pyproject.toml` — the `tui` extra and the `dev` Textual entry are **already
  applied** (§4a, review finding R2-4); Task 0 only verifies them and extends
  `[tool.hatch.build]` include globs so any `taut/tui/*.tcss` ships (the
  existing `/taut/**/*.py` glob already covers the Python files). The untracked
  `uv.lock` is a maintainer reconciliation item (§4a).
- `docs/specs/04-taut-tui.md` — the `## Related Plans` backlink is **already
  applied in the working tree** (uncommitted — verify, don't re-add; same
  maintainer-reconciliation class as `uv.lock`, §4a; finding R3-10). Round 3
  also revises this spec with [TUI-10.8] (watch-delivered read semantics) as
  an explicit spec-revision slice (finding R3-1, Deviation Log).
- `docs/specs/02-taut-core.md` — the `## Related Plans` backlink is already
  applied in the working tree (uncommitted — verify, don't re-add).
- `docs/implementation/02-repository-map.md` and
  `docs/implementation/04-taut-architecture.md` — add the `taut/tui/` boundary
  row(s) (traceability).
- `docs/implementation/00-implementation-index.md` — index the new
  implementation doc.
- `README.md` — the roadmap "TUI" bullet (line ~445) moves from planned to
  shipped-behind-extra with a one-line usage note.

## 4. Invariants and Constraints

These must stay true. Name each in the task that touches it.

**CLI / contract invariants (highest risk — bare `taut` is a public surface):**

- [INV-1] Every existing CLI verb keeps its current stdout/stderr output, exit
  codes (0/1/2 per [TAUT-8.1]), and `--json` field shapes ([TAUT-8.2]).
  The TUI work touches exactly one branch in `main()`; no `_cmd_*` body,
  `_emit_*`, or `*_object` helper changes.
- [INV-2] `taut --help` and `taut --version` remain CLI operations and never
  launch the TUI ([TUI-5.2], [TUI-5.4]). They are argparse actions that exit
  before the launch branch is reached — do not move them.
- [INV-3] Bare `taut` (and no-verb global-option-only invocations) MUST NOT
  launch or hang the TUI when stdin **or** stdout is not a TTY. In a non-TTY
  context it prints help/a clear message and exits non-zero, exactly as today
  ([TUI-5.3]). This preserves the [TAUT-8.2] "agents never hang on a prompt"
  guarantee — it is a correctness invariant, not cosmetic.
- [INV-4] Accepted no-verb TUI-launch global options are exactly
  `{--db, --as, --token}` (the client-construction options), in both the
  `--opt VALUE` and `--opt=VALUE` spellings argparse already accepts for
  verbs (`_hoist_global_options` hoists both, `cli.py:544-552`; finding
  R4-4). `--help` and
  `--version` are excluded (INV-2). A no-verb invocation that carries an
  output-only flag (`--json`, `-t/--timestamps`, `-q/--quiet`) does NOT launch
  the TUI — it prints help and exits non-zero, because those flags are
  meaningless for an interactive app. This set is documented and gated by a
  firing test per [TUI-5.4] and engineering-principle §12.

**Architecture / dependency invariants:**

- [INV-5] Textual and every TUI-only dependency live only in the `taut[tui]`
  extra. They are never added to `[project.dependencies]` ([TUI-4.1],
  [TAUT-12.4]). The core install (`simplebroker`, `psutil`) stays sufficient
  for the CLI and Python API.
- [INV-6] No normal CLI path imports Textual at module import time
  ([TUI-4.3]). `import taut`, `taut --help`, `taut --version`, and every
  `taut <verb>` must succeed with Textual uninstalled. Textual is imported
  only when the launch dispatch decides to start the TUI, via
  `from taut.tui import run_tui` inside the launch branch, wrapped so a missing
  extra yields the [TUI-5.1] message and exit 1.
- [INV-7] No parallel semantics ([TUI-4.2]). `taut/tui/` MUST NOT contain:
  address/identity resolution, envelope construction, sidecar SQL, notification
  claiming, cursor advancement, or membership-convergence logic. Those come
  only from `TautClient`/`TautWatcher`. If the TUI needs behavior the client
  cannot express, grow the client/API in the same change with a CLI/API
  compatibility check — do not fork it into the UI.
- [INV-8] Live display uses `TautClient.watch()` only; there is no second
  watcher implementation and no second cursor policy ([TUI-10.5],
  [TAUT-8.4]). At-least-once display, poison-message handling (3-strikes), and
  membership convergence remain owned by the watch runtime.
- [INV-9] Thread UI never implies more than one level of sub-threading
  ([TUI-7.1], [TUI-11]). Folding is display-only and must not touch cursors,
  membership, history, or notification state ([TUI-7.2]).
- [INV-10] The TUI reflects client/watch state; it must not keep separate
  optimistic state that can disagree with the client result ([TUI-10.7]). A
  sent message appears through the watch path, not by locally appending.
  Session unread bookkeeping (nav badges, separator anchors) is the one
  permitted display state ([TUI-10.8], finding R3-1): it is seeded from
  cursors snapshotted once at app mount before the watcher starts, updated
  only from watch deliveries, and never written back as a cursor.

**Error-path priorities (fatal vs. best-effort):**

- [INV-11] Fatal (must stop or refuse cleanly): missing `taut[tui]` extra,
  uninitialized project with no init action taken, unresolved identity,
  invalid `--db`. These surface as explicit states/messages, never a crash or a
  hang.
- [INV-12] Best-effort (must NOT downgrade the core op or the app): a
  notification-delivery warning after a successful send
  (`client.last_notification_warnings` — surface as a banner, keep the send
  successful, [TUI-10.6] composer "Partial"); a transient render/handler
  failure (inline banner, watcher liveness rules still apply, [INV-8]); a
  single unreadable/foreign message body (render per [TAUT-6.3], never stall).

### 4a. Dependency: `textual` (APPROVED and already applied 2026-07-02)

Per `docs/lessons.md` Golden Rule 9 ("Agents suggest dependencies; humans add
them"), `textual` was **proposed and human-approved on 2026-07-02**, and the
manifest change is **already in the working tree** (review finding R2-4 — the
plan text is updated here to match reality):

```toml
[project.optional-dependencies]
tui = ["textual>=1.0"]        # already present in pyproject.toml
dev = [ ..., "textual>=1.0" ] # already present — lets the test job import the TUI
```

- **`textual`** — the terminal UI framework named as the required choice in
  [TUI-2] (Van's design note) and [TUI-4.1]. Rationale on record: `curses`
  cannot deliver the spec's focus model, responsive reflow, CSS-driven theming,
  and testable `Pilot` harness without effectively rebuilding Textual; isolated
  to the optional `taut[tui]` extra so core installs are unaffected (INV-5).
- **`uv.lock` reconciliation (review finding R2-4).** The dependency add
  produced a `uv.lock` that is currently **untracked** (the repo did not track a
  lockfile before). Before completion, decide with the maintainer whether to
  (a) commit `uv.lock` (adopt lockfile tracking), or (b) add it to
  `.gitignore` and keep the manifest as the source of truth. This plan does not
  presume either — it flags it as a required maintainer decision and a
  completion-gate item.
- **Pin confirmation:** `textual>=1.0` is a floor chosen at add time; confirm
  the exact/max pin the maintainer wants before release.
- **Stop-and-re-evaluate gate:** if implementation reaches for any *second* new
  dependency (e.g. a separate async, layout, or color library), stop and return
  to this section for a new proposal — do not add it inline.

## 4b. Deviation Log

| Spec ref | Planned behavior | Actual behavior | Rationale | Spec proposal |
|----------|------------------|-----------------|-----------|---------------|
| [TUI-6.3] unread separator | (withdrawn) derive separator from session-open, no client change | Anchor separator on stored `last_seen_ts` via new `TautClient.read_cursor()`; transcript dedups backfill/watch overlap by `ts` | Review finding 3: watch seeds cursors from stored `last_seen_ts` (`watcher.py:582`), so session-open would double-display and mis-mark backlog | n/a — client-internal read-only accessor, spec unaffected (behavior matches [TUI-6.3] as written) |
| [TUI-6.2] navigation | (withdrawn) source nav from `client.list_threads()` | New read-only `TautClient.joined_threads()` | Review finding 2: `list_threads(all_threads=False)` raises when nothing unread (`_threads.py:116`); `all_threads=True` lists non-joined threads | n/a — additive client method, `list_threads`/`taut list` contract unchanged ([TAUT-8.1]) |
| [TUI-6.2]/[TUI-3] unread persistence | Unread counts/separators implicitly persistent (Slack-style) | Watch-implies-seen accepted (maintainer decision 2026-07-03, "Option A"): unread presentation is session state over cursors snapshotted at mount; stored unread is consumed by watch delivery, including background threads and launch backlog | Finding R3-1: the watch runtime advances every joined thread's cursor on delivery (`watcher.py:642`, seeded at `watcher.py:581-582`); `advance_cursor` is forward-only (`_sql.py:910-928`); suppressing advancement would fork the cursor policy (INV-8) | `docs/specs/04-taut-tui.md` [TUI-10.8] added in this change (spec-revision slice, 2026-07-03); delivered-vs-viewed cursor split recorded as out of scope (§9) |

## 5. Tasks

Dependency-ordered. Each slice is independently reviewable ("another engineer
could review this partial result without needing the rest to exist"). Run an
independent review after each meaningful slice and again before completion
(CLAUDE.md; §8).

### Task 0 — Packaging + guarded skeleton + import boundary

- Outcome: the `taut[tui]` extra (already applied — §4a, review finding R2-4)
  ships correctly; an empty `taut/tui/` package exists that imports without
  Textual and defines `MissingTuiExtraError` + a `run_tui` stub that raises it
  when Textual is absent; `[tool.hatch.build]` ships the new files. No launch
  behavior change yet.
- Files: `pyproject.toml` (verify the already-present `tui`/`dev` entries;
  extend `[tool.hatch.build] include` to cover `taut/tui/**/*.py` — the current
  `/taut/**/*.py` glob already matches, but add any `*.tcss` explicitly since
  it is not `.py`), `taut/tui/__init__.py`, `taut/tui/_launch.py`,
  `tests/test_tui_launch.py`.
- Read first: `pyproject.toml` build/deps (note: `tui = ["textual>=1.0"]` and
  the `dev` textual entry are **already there**); INV-5/INV-6; §4a `uv.lock`
  reconciliation item.
- Reuse: nothing new — `_launch.py` is pure Python.
- TDD (write first, watch fail):
  - `import taut` and `taut/cli.py` import succeed without pulling in Textual —
    proven in a **subprocess** (`subprocess.run` of
    `python -c "import taut, taut.cli, sys; assert 'textual' not in sys.modules"`),
    not in-process: an in-process `sys.modules` assertion is order-dependent
    once any Pilot test has imported Textual into the shared interpreter, and
    CI runs `-n auto --dist loadgroup` (finding R3-6).
  - `taut/tui/_launch.py` helpers importable without Textual.
- Done signal: new tests pass; `python -c "import taut; import taut.cli"` with
  no Textual on the path still works (simulate by asserting the import graph,
  not by uninstalling in CI).
- Stop gate: if `taut/tui/__init__.py` needs a top-level `import textual` to be
  useful, you are about to violate INV-6 — keep the Textual import inside
  `run_tui`/`app.py`, imported lazily.

### Task 1 — Launch dispatch [TUI-5] (CLI contract change — one-way-sensitive)

- Outcome: `main()` decides CLI-vs-TUI at the single seam, honoring INV-2/3/4;
  a resolved TUI launch calls `run_tui(...)`; a missing extra prints the
  [TUI-5.1] hint and exits 1.
- Files: `taut/cli.py` (replace only the `cli.py:34` branch), `taut/tui/_launch.py`,
  `tests/test_tui_launch.py`.
- Read first: `cli.py:32-40`, `_hoist_global_options` (`cli.py:529`),
  `_first_command` (`cli.py:559`); INV-1..4.
- Implementation shape (keep the decision pure and testable):
  - **Fix the argv-normalization bug first (review finding 1).** `main()` today
    does `list(argv or sys.argv[1:])` (`cli.py:33`); because `[]` is falsy,
    `main([])` falls back to the process argv and does **not** mean "bare taut".
    Change it to `raw_argv = list(sys.argv[1:] if argv is None else argv)`
    before parsing, so `main([])` is an explicit bare invocation. This is the
    only pre-existing behavior change and it is safe: existing callers pass
    `None` or a non-empty list, whose behavior is unchanged; only the
    empty-list case changes (from "read process argv" to "bare"), which no
    current caller relies on. Add a firing test that `main([])` is treated as
    bare `taut` (before it would have leaked `sys.argv`).
  - Add `_launch.decide(*, has_verb, db_path, as_name, token, json_flag,
    timestamps, quiet, stdin_isatty, stdout_isatty) -> LaunchDecision` (or an
    equivalent narrow value object) — its inputs come **from the argparse
    namespace `main()` already holds**, never from raw argv. It returns
    `RUN_CLI` (a verb, or output-only flags with no verb, or non-tty) or
    `LAUNCH_TUI` (no verb, accepted options only, both TTYs), carrying
    `{db_path, as_name, token}`. `decide` must NOT re-parse argv: argparse
    (after `_hoist_global_options`, `cli.py:529`) is the one canonical parse,
    and it already accepts both `--db X` and `--db=X` spellings
    (`cli.py:544-552`) — a hand-rolled second parser in `_launch` is exactly
    how the equals-form would silently regress (finding R4-4).
    `--help`/`--version` never reach `decide`; they are argparse actions that
    exit first (INV-2).
  - In `main()`: if there is no `func` and `decide(...)` says `LAUNCH_TUI`,
    catch **only a dedicated `MissingTuiExtraError`** (review findings 6 + R2-3
    — a bare `except ImportError` is wrong here, see below):
    ```python
    from taut.tui._launch import MissingTuiExtraError  # no Textual import
    try:
        from taut.tui import run_tui
        return run_tui(db_path=..., as_name=..., token=...)
    except MissingTuiExtraError:
        <print [TUI-5.1] hint to stderr>
        return 1
    ```
  - **`run_tui` owns the missing-extra translation (review finding R2-3, now
    mandatory not optional).** Its first act is a narrow probe:
    ```python
    def run_tui(*, db_path=None, as_name=None, token=None):
        try:
            import textual  # noqa: F401 — probe only
        except ImportError as exc:
            raise MissingTuiExtraError(...) from exc
        from taut.tui.app import TautApp   # real app import; Textual present
        ...
    ```
    This way a genuine `ImportError` from a broken `taut.tui.app` submodule
    propagates as a real error (not silently mis-reported as "extra not
    installed"), while a missing `textual` is the only thing that becomes the
    [TUI-5.1] hint. `MissingTuiExtraError` lives in `taut/tui/_launch.py`
    (importable without Textual). `taut.tui` still imports without Textual
    (§3.2); the lazy import point is inside `run_tui`.
  - Do not import Textual in `cli.py`. Do not change argparse's `--version`
    action.
- TDD (write first): a firing test per INV-4 branch —
  - verb present → CLI (spy that `run_tui` is never imported/called);
  - `--help` / `--version` → CLI (argparse exits; assert via
    `SystemExit`/`--version` output);
  - `main([])` is treated as bare `taut` (regression for finding 1);
  - bare `taut`, both TTYs, extra present → `run_tui` called once with
    `db_path=None, as_name=None, token=None` (exact kwargs — review finding
    R2-5; monkeypatch `taut.tui.run_tui`);
  - bare `taut`, stdin not a tty → help + exit 1, `run_tui` not called (INV-3);
  - bare `taut`, stdout not a tty → help + exit 1 (INV-3);
  - `taut --db X` both TTYs → `run_tui(db_path="X", as_name=None, token=None)`
    (INV-4 accepted);
  - `taut --as NAME` and `taut --token T` (both TTYs) → `run_tui` called with
    the matching kwarg — one firing test per element of the INV-4 accepted
    set, not just `--db` (engineering-principles §12; finding R3-11);
  - `taut --db=X` (equals-form, both TTYs) → `run_tui(db_path="X", ...)`
    (finding R4-4): the hoist already supports equals-form for verbs
    (`cli.py:544-552`), so no-verb launch must not regress it. One
    representative equals-form test is a declared decision, not an
    oversight — because `decide` consumes the argparse namespace rather than
    re-parsing, spelling handling belongs to argparse and is proven once;
  - `taut --json` no verb → help + exit 1, no launch (INV-4 excluded);
  - bare `taut`, both TTYs, Textual missing → `run_tui` raises
    `MissingTuiExtraError` and the guard prints the exact [TUI-5.1] message
    substrings (`taut[tui]`, `pipx inject`, `taut list`, `taut watch`) on
    stderr and exits 1 (simulate by monkeypatching the `import textual` probe
    to raise);
  - a real `ImportError` from inside `run_tui`/`app` is **not** swallowed as
    the missing-extra hint (negative test for review finding R2-3).
- Anti-mock: drive `main(argv)` directly (the real entry point). Only
  monkeypatch `taut.tui.run_tui` (the thing under test is dispatch, not the
  app) and the tty predicates. Do not mock argparse or the client.
- Done signal: all launch tests green; run the full existing
  `tests/test_cli.py` to prove INV-1/INV-2 (no CLI regression).
- One-way-door note: this changes what bare `taut` does. Rollback = revert the
  `cli.py` branch to `print_help(); return 1` (Task 1 is independently
  revertible and carries no storage/format change). Because it is a
  contract-visible change, it holds a higher bar: the non-tty tests (INV-3) are
  release-gating.

### Task 2 — Grow the read-only client surface the TUI needs

Review findings 2 + 3 (round 1) and R3-3 (round 3) proved three data needs the
current client **cannot** satisfy, so this task adds them to `TautClient` (the
[TUI-4.2] "grow the client first, do not fork it into the UI" path). All
additions are read-only and must not move cursors or change any existing
method's behavior.

- Files to touch: `taut/client/_threads.py`, `taut/client/_messaging.py` (or
  wherever the cursor read best fits), `taut/client/_models.py` (Addition C's
  additive `Thread.origin_ts` and `Thread.reply_count` fields),
  `taut/client/__init__.py` (if the public
  surface needs re-export), `tests/test_client.py`, and the public-API test
  `tests/test_public_api.py`.
- Read first: `taut/client/_threads.py::list_threads` (**lines 99-118** — note
  it raises `EmptyResultError("no unread threads")` at line 116-117 when
  nothing is unread, and `all_threads=True` returns *every registered* thread,
  not joined ones); `taut/client/_messaging.py::log`/`read_unread`;
  `taut/state/_sql.py` membership/cursor helpers; [TAUT-7.2], [TAUT-8.3].

- **Addition A — joined-threads accessor (review finding 2).**
  `list_threads(all_threads=False)` raises when no joined thread is unread, and
  `all_threads=True` lists non-joined threads too — so the TUI cannot render
  navigation for a quiet, fully-read project from either call. Add a new
  read-only method, e.g. `TautClient.joined_threads() -> list[Thread]`, that
  returns all threads the acting member has joined with their unread flags,
  **never raising on "all read."** Do **not** change `list_threads` — the
  `EmptyResultError`-when-nothing-unread behavior is the `taut list` exit-code-2
  contract ([TAUT-8.1]) and must stay (INV-1). Reuse the existing
  `list_memberships` + `_thread_from_row` internals `list_threads` already uses.
- **Addition B — read cursor accessor for the unread separator (review
  finding 3).** The watcher seeds each queue cursor from the member's stored
  `last_seen_ts` (`watcher.py:582`), so it re-delivers pre-existing unread
  messages. The transcript therefore needs the stored boundary to (1) place the
  `── new messages ──` separator and (2) de-duplicate the overlap between the
  `log()` backfill and the watch tail. Add a read-only
  `TautClient.read_cursor(thread) -> int | None` returning the acting member's
  `last_seen_ts` for the thread (None if not a member / no cursor). It must not
  advance or write the cursor.

- **Addition C — channel sub-thread summaries for inline threads (review
  finding R3-3).** The transcript's inline thread affordances ([TUI-7.1],
  Task 5) must render, under a parent message, each sub-thread's label, reply
  count, and anchor point — and the thread-pane reply path needs the parent
  channel plus origin message id (Task 5 / finding R3-5). The public `Thread`
  dataclass exposes neither an origin anchor nor a reply count
  (`_models.py:24-34`); the state row's `origin_ts` (`_types.py:38-45`) is
  off-limits to the TUI, and parsing the anchor out of sub-thread names is
  address-resolution work — both INV-7 violations. `joined_threads()`
  (Addition A) is also insufficient here: it returns only *joined* threads, so
  a sub-thread the acting member never joined would be invisible to the
  transcript. Add a read-only accessor, e.g.
  `TautClient.channel_threads(channel) -> list[Thread]`, returning every
  registered sub-thread of a channel (joined or not), with `Thread` extended
  by two additive fields whose defaults leave existing constructions
  unaffected: `origin_ts: int | None = None` and `reply_count: int = 0`
  (field named per finding R4-1). `reply_count` is the **total** message
  count of the sub-thread queue — a capped `peek_many(cap,
  with_timestamps=True)` from timestamp 0, same `cap=1000` bound as
  `_unread_count` (saturating at the cap is acceptable: the count is
  display-only, not a JSON contract). Do **NOT** compute it with
  `_unread_count`: that helper is membership-relative and returns 0 when the
  acting member has no membership (`_threads.py:208-209`), which would zero
  out exactly the non-joined sub-threads this accessor exists to surface.
  The total queue count is a true reply count because `reply()` writes only
  reply messages into the sub-thread queue — the origin message is not
  copied in (`_messaging.py` `reply`: `child_thread = f"{thread}.{origin}"`
  plus a single `_insert_message(kind="message")` per reply). The
  sub-thread's registry row already carries `origin_ts`, and the state
  default `list_threads()` includes sub-thread kinds (`_sql.py:812-825`).
  Mirror the CLI's `_thread_object` field usage so display naming cannot
  drift.

- Known mappings that need **no** new API:
  - transcript backfill ← `client.log(thread, limit=N)` (history, no cursor
    move — [TAUT-7.2]); live tail ← the watch handler;
  - presence + selected identity for **channels and sub-threads** ←
    `client.who(thread)` / `client.whoami()`
    → `Member.name/kind/presence/last_active_ts/member_id/persona`;
  - presence + member detail for **DM targets** ← `client.who()` (no
    argument → all members, `_identity.py:40-41`) filtered by
    `Thread.members` ids. `who(thread)` CANNOT be used for DMs (finding
    R4-2): it validates through `validate_chat_thread_name`, which parses
    with `allow_dm=False` (`_identity.py:35`, `addressing.py:78-86`), so a
    DM name (`dm.d_<id>`, `addressing.py:113`) raises `ThreadNameError`
    before the registry is consulted. This rule covers the Direct nav rows'
    presence dots, the presence pane when a DM is the active target, and the
    DM transcript header;
  - acting member ("You") ← `client.whoami()`;
  - DM participant ids ← `Thread.members`. DM rows flow through
    `joined_threads()` (Addition A) unchanged — verified while folding R4-2
    to rule out a neighboring gap: `_say_dm` creates membership rows for
    both participants and the state default `list_threads()` includes the
    `dm` kind (`_sql.py:813`).
- Superseded decision: the earlier "derive the separator from session-open,
  no client change" plan is **withdrawn** — review finding 3 showed it produces
  duplicate display and mis-marks backlog because watch starts at the stored
  cursor, not at session open. Recorded in the Deviation Log and Review Log.
- TDD (write first, red-green, real `.taut.db` — [TAUT-11] no broker mock):
  - `joined_threads()` on a project where every joined thread is fully read
    returns those threads (does **not** raise), and excludes non-joined
    registered threads; `list_threads()` behavior is unchanged (its existing
    tests still pass).
  - `read_cursor(thread)` returns the stored `last_seen_ts` and a follow-up
    `has_pending`/`log` shows the cursor did **not** move (assert monotonic
    no-op).
  - `channel_threads(channel)` returns every registered sub-thread of the
    channel — including one the acting member has not joined — with a stable
    origin anchor (`origin_ts`); a channel with no sub-threads returns `[]`
    without raising.
  - `reply_count` is the total, not the unread view (finding R4-1): a
    **joined, fully-read** sub-thread with N replies reports
    `reply_count == N` while its `unread_count == 0` (natural fixture — the
    `reply()` path advances the replier's own cursor); a **non-joined**
    sub-thread with N replies also reports `reply_count == N`, not 0.
- Stop gate: if you reach into `taut/state` / sidecar SQL from `taut/tui/`,
  stop — the boundary is a `TautClient` method (INV-7). If either addition
  tempts you to change `list_threads`'s raise-on-empty contract, stop — that is
  an INV-1 CLI regression.

### Task 3 — App skeleton + wide 3-pane layout (static reads, no live watch)

- Outcome: `run_tui(...)` starts a Textual `App` that constructs the
  `TautClient` during startup — **inside** the App, catching
  `NotInitializedError` so an uninitialized project renders the [TUI-10.1]
  empty state (Task 8) instead of crashing before a frame exists
  (`TautClient.__init__` raises during target resolution at
  `_base.py:110/117/119`; finding R3-2). With a client, the App resolves the
  acting member and renders frame 2a at wide width from one-shot client
  reads: nav via `client.joined_threads()` (Task 2 Addition A), transcript
  backfill via `client.log`, presence via `client.who`. **Unread state is
  snapshotted once at mount** ([TUI-10.8]; finding R3-1): capture
  `client.read_cursor(thread)` (Task 2 Addition B) for every joined thread
  into an immutable session snapshot before any watcher exists — Task 4
  starts the watcher strictly after this snapshot. The `── new messages ──`
  separator for any conversation is anchored at the *snapshot* value
  (messages with `ts > snapshot` render below the band), never at a re-read
  cursor: once the watcher runs, a re-read returns a cursor the watch runtime
  has already advanced, which would silently erase the band for threads whose
  backlog was drained. Selecting a nav row switches the active target and
  reloads the transcript. No live updates yet.
- Files: `taut/tui/__init__.py`, `taut/tui/app.py`, all `taut/tui/widgets/*`,
  `taut/tui/app.tcss`, `tests/test_tui_app.py`.
- Read first: `_models.py`; [TUI-6.1..6.6], [TUI-8.1] focus model, [TUI-14]
  user journey.
- Reuse: mirror the CLI's field usage in `_message_object`/`_member_object`/
  `_thread_object` so nothing about the data mapping drifts from the CLI.
- Behavior to build: sectioned nav (Channels/Direct/Threads/Inbox) with
  right-aligned unread counts and DM presence dots; transcript with notices
  inline, `HH:MM` timestamps, author, wrapped text; anchored composer labelled
  `message #<target>`; presence pane with members, selected identity, and the
  `You` acting member; title bar `taut · <project path>`; bottom key bar
  ([TUI-8.2] set). Exactly one focused pane, visibly distinct (INV visual
  distinctness [TUI-8.4]).
- TDD (Textual `Pilot`, write first): assert **structure and behavior, not
  glyphs** ([TUI-6.3], testing-patterns Pattern 5) —
  - the four nav sections exist and list the joined threads from a seeded real
    `.taut.db`;
  - selecting a channel makes it the active target and the transcript shows
    that channel's messages (by author/text substring + ts field), composer
    label updates;
  - a notice message renders as a notice (structural role), a normal message as
    a message;
  - presence pane lists members with presence state as text (not color-only);
  - a seeded DM renders in the Direct section with the counterpart's label
    and a presence hint sourced from `client.who()` + `Thread.members`
    (finding R4-2); no mock needed to prove the negative — if the
    implementation wrongly calls `client.who(dm_name)`, this test fails with
    `ThreadNameError`;
  - the unread separator renders from the mount snapshot: seed a db with read
    and unread messages, mount, and assert the `── new messages ──` band sits
    at the snapshot boundary (structural role, not glyphs; finding R3-1).
- Anti-mock: seed a **real** `.taut.db` in a temp dir via `TautClient`
  (init/join/say), then run the App against it. Do not mock the client.
- Done signal: `Pilot` tests green; app renders without exceptions on an 120×34
  virtual terminal.
- Stop gate: if a widget wants data the client doesn't return, go back to
  Task 2 — do not read state directly.

### Task 4 — Live updates via watch (async/threading hardening slice)

- Outcome: on mount, the app constructs `watcher = client.watch(handler,
  threads=None)` and starts it with `watcher.run_in_thread()` (see finding 5
  below); incoming `Message`/`Notification` items are marshaled onto the Textual
  event loop and update nav unread state, the transcript (if the item's thread
  is active), presence, and the inbox — through client/watch state only
  (INV-10). On exit, the watcher is stopped and its thread joined. The
  watcher starts strictly **after** the Task 3 cursor snapshot ([TUI-10.8];
  finding R3-1): once it runs, deliveries advance stored cursors for every
  joined thread — background threads and launch backlog included — so nav
  unread badges are session display state: seeded from
  `joined_threads()`/the snapshot at mount, incremented by deliveries to
  non-active threads, cleared when the user views the thread. This is the
  INV-10 carve-out; it is never written back as a cursor.
- Files: `taut/tui/_bridge.py`, `taut/tui/app.py`, `tests/test_tui_app.py`.
- Read first: `taut/watcher.py` `TautWatcher.__init__` (cursor seeding at
  `watcher.py:581-582`) and `stop` (`watcher.py:344`); the **installed**
  simplebroker dependency's base (`simplebroker>=4.10.0`, site-packages —
  not vendored; wording fixed per finding R3-10)
  `BaseWatcher.run_in_thread`/`start`/`stop` in
  `simplebroker/watcher.py` (`run_in_thread` at line ~920 creates the thread and
  records `self._thread`; `stop(join=True)` at line ~507 joins **only** that
  recorded thread); `add_queue`/`remove_queue`; [TAUT-8.4]; [TUI-10.3],
  [TUI-10.5]. **Q:** if you start the watcher with your own
  `threading.Thread(target=watcher.run_forever)`, will `watcher.stop(join=True)`
  join it? (Answer: **no** — `stop` only joins the thread `run_in_thread`
  recorded, so use `run_in_thread()`, not a hand-rolled thread. Review
  finding 5.)

- Hidden couplings (call out — these are where this slice fails if rushed):
  - **Synchronous acknowledgment — CHAT MESSAGES ONLY (review findings 4 +
    R2-2).** For a `Message`, the watch runtime advances the chat cursor
    *inside `_make_taut_handler`, immediately after the user handler returns*
    (`watcher.py:642`; the `_advance` call runs unless the handler raised).
    So for a `Message` the TUI handler must hand the item to the UI
    **synchronously via `App.call_from_thread(update_fn)` and let any exception
    propagate out of the handler before it returns** — a UI-update failure then
    leaves the cursor in place and the message is re-seen (at-least-once,
    INV-8). Do **not** fire-and-forget by posting a Textual message and
    returning: that advances the cursor before the UI accepted the item,
    silently dropping it on any display failure.
  - **Notifications are best-effort, NOT at-least-once (review finding R2-2).**
    Notification queues run in `QueueMode.READ` and are *consumed* on read
    (`_make_notification_handler` at `watcher.py:611-617` does not advance a
    cursor and there is no re-delivery); the core spec explicitly allows a
    claimed notification to be lost if the renderer fails while the source chat
    history stays durable (`docs/specs/02-taut-core.md` [TAUT-10],
    lines 668-669; [IAN-7.4]). So the `Notification` branch of the handler is
    best-effort display after claim — do not try to make it at-least-once, and
    do not re-claim. The regression test for this asserts *source chat history
    remains readable* after a notification-display failure, NOT that the
    notification is re-seen.
  - **Backfill/watch overlap dedup (review finding 3).** Because the watcher
    seeds cursors from stored `last_seen_ts`, it re-delivers unread messages
    that the `client.log()` backfill (Task 3) may already show. The transcript
    widget therefore keys rendered messages by `ts` and renders each once; a
    message arriving from both paths is idempotent. This is display-layer
    de-duplication, **not** a second cursor policy (still INV-8-clean).
  - cursor advancement + notification claiming happen inside the watch runtime;
    the handler must not re-advance cursors or re-claim (INV-7/INV-8);
  - membership convergence (`add_queue`/`remove_queue`) happens inside the
    watcher on its interval/data-version signal; the UI learns about add/drop
    by re-reading `client.joined_threads()` (Task 2) at exactly two decided
    trigger points (this was an either/or; fixed per finding R3-8): (a) when
    a watch delivery references a thread the UI does not know, and (b) a
    fallback timer aligned to the watcher's `membership_refresh_interval`.
    No other refresh path; the UI does not drive membership.
- Lifecycle answers (deferred-processing checklist):
  - the "input" is broker-resident; nothing is buffered to disk by the TUI;
  - start with `watcher.run_in_thread()` so the watcher owns and records its
    thread;
  - **shutdown ordering — avoid both deadlock AND a false-ack (review findings
    5 + R2-1).** On quit (`action_quit`/`on_unmount`): (1) set the watcher's
    stop event promptly so the loop stops fetching new messages; (2) set a
    `stopping` flag the handler checks — but note "stop issuing
    `call_from_thread`" must NOT mean "return normally," because a `Message`
    handler that returns lets `_advance` (`watcher.py:642`) mark an undisplayed
    message seen (the R2-1 race). While `stopping`, a `Message` handler that has
    not completed its UI hand-off must **raise a dedicated non-ack shutdown
    exception** so the cursor is not advanced; the message is then re-seen on
    next launch (a one-shot shutdown raise does not hit the 3-strikes
    poison-advance, which needs 3 failures on the same id — and that holds
    **only because** step (1) set the stop event first: with the stop event
    set, the base loop exits via `StopWatching` instead of re-fetching, so
    the same message cannot accumulate three shutdown raises and be
    poison-advanced at `watcher.py:631-638`. Do not reorder steps (1) and
    (2); finding R3-9). (3) call
    `watcher.stop(join=True, timeout=...)` from a path that is **not** the UI
    event loop the handler's `call_from_thread` depends on (run stop+join in a
    Textual worker / thread, or `stop(join=False)` then join off the UI thread
    with a timeout) — otherwise the UI thread blocks joining while a
    `call_from_thread` waits on that same UI thread (deadlock). (4) if the
    thread does not join within the timeout, still exit (liveness wins);
  - only one watcher runs per app; no two-worker contention (single process);
  - **error banners are produced by the TUI, not by a watcher event (review
    finding R2-5).** The watcher's poison rule only *logs* a warning and
    advances after 3 failures on one id (`watcher.py:631-638`); there is no
    watcher API that emits a banner. So the inline banner (INV-12) is the TUI's
    own concern: the handler's `update_fn` (or its `call_from_thread` wrapper)
    catches a display error and shows the banner itself. Do not plan around a
    nonexistent watcher banner/notification-of-failure event.
- Separate wrapper from core: `_bridge.py` holds the pure lifecycle contract
  (own the watcher thread via `run_in_thread`, the `stopping` flag, the
  synchronous marshal callable, and ordered stop+join) with no Textual widget
  knowledge, so it is testable in isolation; `app.py` supplies the marshal
  target (`call_from_thread` wrapper).
- TDD (write first; real client + real watcher, [TUI-12] "at least one real
  watcher-backed proof"):
  - start the app against a real `.taut.db`; from a **separate process/thread**,
    `client.say(active_channel, "live-1")`; assert the transcript shows
    `live-1` within a bounded poll (testing-patterns Pattern 4 — no single
    immediate read), and shows it **exactly once** even though it is newer than
    the seeded cursor (dedup proof, finding 3);
  - assert nav unread count increments for a non-active channel on a live write;
  - assert the [TUI-10.8] semantics is intentional (finding R3-1): run a TUI
    session against a project with unread backlog in a channel the user never
    opens; after a clean exit, `client.list_threads()` raises
    `EmptyResultError("no unread threads")` (the `taut list` exit-2 contract) —
    this pins watch-implies-seen as the decided behavior, not an accident.
    In the same session, assert the separator still renders from the mount
    snapshot for a thread opened *after* its backlog was drained by the
    watcher;
  - assert app exit stops the watcher: the **bridge-owned thread** (the object
    returned by `run_in_thread()`) is not alive afterward — do not assert on a
    nonexistent public `TautWatcher` thread property (finding 5);
  - assert the at-least-once contract for a **chat message** (finding 4;
    assertion shape fixed per finding R3-9): inject a one-shot failure in the
    UI update path for one `Message` and assert **re-delivery** — the message
    is delivered again and ends up displayed exactly once, never silently
    dropped. Do not make "cursor did not advance" the primary assertion:
    after the one-shot failure the watcher refetches and the now-succeeding
    handler legitimately advances the cursor, so that check is racy. Only a
    fail-stop variant (the app exits before any retry) may assert an
    unchanged stored cursor;
  - assert the **shutdown ack race** is closed (finding R2-1): with a `Message`
    fetched while `stopping` is set, prove the stored cursor does not advance
    for that message (it is re-seen on next launch), and that no 3-strikes
    poison-advance fired during the shutdown window (finding R3-9);
  - assert the **notification best-effort** contract (finding R2-2): inject a
    one-shot failure displaying a `Notification` and prove the *source chat
    history is still readable* (durable) — do NOT assert the notification is
    re-seen (it is legitimately consumed).
- Anti-mock: do **not** mock the watcher or client message path — that is the
  exact seam under proof (hardening §6). Use bounded polling helpers already
  present in `tests/test_watcher.py`/`tests/conftest.py`.
- Done signal: live-update tests green; a manual smoke (`taut` in one terminal,
  `taut say` in another) shows messages arriving exactly once.
- Stop gate: if the handler returns before the UI has accepted the item, or you
  add a second polling loop that re-reads history to "catch up," stop — you are
  breaking the acknowledgment contract or drifting into a second cursor/watch
  policy (INV-8).

### Task 5 — Threads: inline foldable (`z`) + side pane (`t`, esc) [TUI-7]

- Outcome: one-level sub-threads render inline under the parent by default
  (label, reply count, indented recent replies); `z` folds/unfolds the active
  inline thread (display-only, INV-9); `t` opens the active thread in the
  right-side pane (frame 1b) which borrows the presence column, shows parent
  context + replies, owns its own reply composer, and closes on Escape.
- Files: `taut/tui/widgets/transcript.py`, `taut/tui/widgets/thread_pane.py`,
  `taut/tui/app.py`, `tests/test_tui_app.py`.
- Read first: [TUI-7.1..7.3], [TUI-8.2] (`z`,`t`,esc), INV-9.
- Reuse: inline affordance data — which sub-threads hang from which parent
  message, labels, reply counts (`Thread.reply_count`) — comes from
  `client.channel_threads(channel)` (Task 2 Addition C, anchored by
  `Thread.origin_ts`); never from `taut/state` reads or sub-thread-name
  parsing (INV-7). Replies use
  `client.reply(parent_channel, origin_msg_id, text)` — the same path as
  `taut reply`. **The composer's label names the sub-thread ([TUI-6.4]
  "reply in parser") but the call passes the PARENT channel and origin
  message id**: `client.reply` validates its thread argument with
  `allow_subthread=False` (`_messaging.py:48`) and raises `ThreadNameError`
  if handed the sub-thread name (finding R3-5). Sub-thread history via
  `client.log(subthread_name, ...)`.
- TDD: folding toggles display state only and leaves cursor/membership
  unchanged (assert via client state before/after); `t` opens a pane whose
  reply composer is *labelled* for the sub-thread and whose send calls
  `client.reply(parent_channel, origin_msg_id, text)` — assert the reply
  lands in the sub-thread via `client.log(subthread)`, the regression for the
  wrong-call shape (finding R3-5); Escape closes it and restores presence;
  the UI never renders a reply-of-a-reply affordance (INV-9).
- Done signal: thread tests green.

### Task 6 — Composer + inbox + presence toggle + search/goto/help

- Outcome: composer sends via `client.say`/`client.reply` per active target
  ([TUI-6.4]); notification warnings surface as a non-blocking banner without
  failing the send (INV-12); `m` toggles presence ([TUI-6.5]); `i` opens the
  inbox ([TUI-6.2], [IAN-7]) — **while the watcher runs, the watch runtime is
  the sole notification consumer** (finding R3-4): pending notifications are
  claimed by the watcher's READ-mode queue (`watcher.py:568-572`) at initial
  drain and on arrival, delivered to the TUI as `Notification` items, and
  accumulated as the inbox view's content. The TUI must NOT call
  `client.inbox()` while the watcher runs — that is a second consumer racing
  the same queue (`_notifications.py:20` `read_many`); it would return empty
  or steal items from the watch path. The inbox nav count is the session
  count of delivered-but-not-yet-viewed notifications and clears when the
  inbox is opened; `/` searches the
  active conversation's loaded content ([TUI-8.3]); `g` opens a goto overlay
  over known targets; `?` opens mode help closable with Escape without changing
  the active target.
- Files: `taut/tui/widgets/composer.py`, `taut/tui/widgets/presence.py`,
  `taut/tui/app.py`, `tests/test_tui_app.py`.
- Read first: [TUI-8.2], [TUI-8.3]; `client.say`/`reply`/`inbox` bodies and
  `client.last_notification_warnings`.
- Invariant focus: INV-10 (sent message appears via the watch path, not a local
  optimistic append) and INV-12 (warning is best-effort).
- TDD: a composer send makes the message appear through the watch path (reuse
  Task 4 harness); `i` shows watch-delivered notifications, each claimed
  exactly once by the watch runtime — assert with a fresh client after the
  watcher stops that `client.inbox()` raises
  `EmptyResultError("nothing pending")` while source chat history stays
  readable ([TAUT-10], [IAN-7.4]; finding R3-4);
  `/` filters visible rows; `?`/Escape round-trip leaves the active target
  unchanged (Pattern: focus not corrupted).
- Done signal: interaction tests green.

### Task 7 — Responsive modes [TUI-9]

- Outcome: wide (≥120 cols) = 3-pane; medium (80–119) = tabbed/two-pane,
  transcript primary, presence via `m` (frame 1c/1d-tabs); narrow (50–79) =
  compact icon rail `# @ ↳ ⧉`, author stacks above wrapped text (frame 1d);
  too-small (<50 cols, or below a minimum height) = "terminal too small" hint.
- Files: `taut/tui/app.py` (+ `app.tcss`), `tests/test_tui_responsive.py`.
- Read first: [TUI-9.1..9.4]; frame 1d.
- **Decision (resolves [TUI-13] Q1):** thresholds are width-driven —
  wide `>=120`, medium `80..119`, narrow `50..79`, too-small `<50` cols; and a
  minimum height of `<20` rows also triggers too-small. Marked tunable
  ([TUI-9] permits tuning); the *structural modes* are the contract, the exact
  numbers are not. Owner: implementer may tune within these bands during
  Textual work and must update the test fixtures + this decision if changed.
- TDD (inspection-gate style, structural not pixel): at representative widths
  (130, 100, 64, 40) the app chooses the expected structural mode without
  incoherent overlap; at <50 cols the too-small hint renders and the app does
  not crash. Height is part of the enumerable threshold contract too
  (engineering-principles §12; finding R3-11): at a wide-enough width but
  height below the minimum (e.g. 130×15) the too-small hint renders.
- Done signal: responsive tests green across the four representative sizes.

### Task 8 — Recovery states [TUI-10]

- Outcome: uninitialized project → empty state ("not a taut project"), an
  `init here` action that calls the same client path as `taut init`
  (`TautClient.init`), and a quit path ([TUI-10.1]); lost membership →
  conversation disabled/removed + non-blocking banner, history not deleted
  ([TUI-10.3]); recoverable runtime errors → inline banners that never corrupt
  cursors/claims ([TUI-10.4]); the [TUI-10.6] state matrix has a visible
  loading/empty/error/success/partial state for each surface. (Missing-extra is
  already handled in Task 1.)
- Files: `taut/tui/app.py`, `taut/tui/widgets/*`, `tests/test_tui_recovery.py`.
- Read first: [TUI-10.1..10.8]; frame 1e; `TautClient.init` at
  `client/__init__.py:65` (line corrected per finding R3-10).
  `TautClient.init` is a **classmethod** — it needs no client instance, which
  is what makes the uninitialized flow work (finding R3-2): the App starts
  without a client (Task 3), `init here` calls `TautClient.init(...)`, and
  only then does the App construct its `TautClient` and proceed to the
  normal layout.
- **Decision (resolves [TUI-13] Q2):** in-app identity/join management stays
  CLI-first for v1 ([TUI-15]); the *only* in-app setup action is `init here`
  ([TUI-10.1]). Lost-membership and DM/join hints point the user at the CLI
  (`taut join ci`) exactly as frame 1e shows — the TUI does not grow join/rejoin
  screens in v1.
- TDD: launching in an empty dir shows the empty state and the `init here`
  action actually initializes a real db (assert `.taut.db` created via the
  client path, not a TUI-local re-implementation), after which the App
  constructs its client and reaches the normal layout (finding R3-2); a
  simulated membership loss disables the conversation and shows the banner
  while history remains readable.
- Done signal: recovery tests green.

### Task 9 — Accessibility, focus, key bar [TUI-8.4] + docs + review

- Outcome: keyboard-complete operation (mouse optional); deterministic focus
  order matching the pane model; selected/focused/unread/disabled states
  distinguishable without color alone; status/errors as text; composer label
  stays visible with content; narrow modes preserve command reachability via
  help/goto/tabs. Then the documentation and traceability updates.
- Files: `taut/tui/app.py`, `tests/test_tui_app.py`;
  `docs/implementation/05-taut-tui-architecture.md` (new),
  `docs/implementation/00-implementation-index.md`,
  `docs/implementation/02-repository-map.md`,
  `docs/implementation/04-taut-architecture.md`,
  `docs/specs/04-taut-tui.md` (Related Plans), `docs/specs/02-taut-core.md`
  (Related Plans), `README.md`.
- Read first: [TUI-8.1], [TUI-8.4], [TUI-11]; `principles.md` traceability
  rules; `writing-implementation-docs.md`.
- TDD/inspection: Tab/Shift-Tab cycles focus in the [TUI-8.1] order; every
  key-bar command in [TUI-8.2] is reachable (help exposes the full set even
  when the narrow key bar hides some); non-color status assertion (status text
  present as text).
- Docs are verified by inspection (docs-only quality gate): the implementation
  doc explains the client-consumer boundary, the watch-thread bridge, the
  launch dispatch, and the responsive thresholds; specs carry backlinks;
  repo map lists `taut/tui/`. **Required content, not optional color**
  (finding R3-1; maintainer decision 2026-07-03): the implementation doc AND
  the README usage note must state the [TUI-10.8] watch-delivered read
  semantics plainly — running the TUI marks delivered messages as seen for
  the acting member, including background conversations and launch backlog;
  unread badges are session-scoped; `taut list` reports no unread after a
  session; cursor advancement is forward-only, so consumed unread state is
  not recoverable per-message.
- Done signal: accessibility tests green; docs cross-link cleanly; grep gates
  (§7) pass.

## 6. Testing Plan

Harness and layers:

- **Launch/dispatch:** call `taut.cli.main(argv)` directly (real entry point),
  monkeypatch only `taut.tui.run_tui` and the tty predicates. This proves the
  [TUI-5] contract and INV-1..4 without a running app.
- **Import boundary:** prove INV-6 in a **subprocess** (`python -c` asserting
  `"textual" not in sys.modules` after importing `taut` and `taut.cli`,
  driven by `subprocess.run`) — never in-process, which is order-dependent
  under a shared interpreter and xdist (finding R3-6). A packaging/inspection
  gate asserts
  `textual` appears only under `[project.optional-dependencies].tui` (and the
  `dev` test job), never in `[project.dependencies]` (INV-5) — an enumerable
  contract, so it gets a firing test (engineering-principle §12).
- **TUI behavior:** Textual's `Pilot` async test harness driving the real
  `App` against a **real `.taut.db`** seeded through `TautClient`
  (init/join/say/reply). Assert structural roles and behavior, never exact
  glyphs/hex/spacing (testing-patterns Pattern 5; [TUI-6.3]).
- **Live updates:** at least one real `TautClient`/`TautWatcher`-backed test
  ([TUI-12]) with a separate writer and bounded polling (Pattern 4). The
  message/watch path is never mocked (hardening §6).
- **Responsive/recovery/accessibility:** structural inspection gates at
  representative sizes and states.

What must stay real (anti-mock, explicit):

- the broker / `.taut.db` (never mocked — [TAUT-11] standing posture);
- `TautClient` and `TautWatcher` in every behavior/live test;
- the real `main()` entry in launch tests.

What may be mocked: only `taut.tui.run_tui` (in dispatch tests, since the app
is not what dispatch is proving) and the two tty predicates.

Contract-focused assertions (bias per hardening §7): CLI exit codes/JSON
unchanged (rerun `tests/test_cli.py`, `tests/test_public_api.py`); the accepted
no-verb option set (INV-4, one firing test per branch); watch-driven visible
state transitions; init-from-empty-state creating a real db.

Commands (per-task: run the touched test file; final gates in §7).

## 7. Verification and Gates

Per-task verification: run the new test file(s) for that task plus the nearest
neighbor (`tests/test_cli.py` after Task 1; `tests/test_watcher.py` after
Task 4).

Final gates before claiming completion (from
`docs/implementation/04-taut-architecture.md`, extended for the TUI):

```bash
uv run --extra dev pytest
uv run --extra dev pytest tests/test_tui_launch.py tests/test_tui_app.py \
  tests/test_tui_responsive.py tests/test_tui_recovery.py  # explicit: proves the TUI tests ran, not skipped
uv run pytest -m shared
uv run ./bin/pytest-pg --fast
uv run ruff check taut tests bin extensions/taut_pg/taut_pg extensions/taut_pg/tests
uv run ruff format --check taut tests bin extensions/taut_pg/taut_pg extensions/taut_pg/tests
uv run --extra dev mypy taut tests bin/release.py extensions/taut_pg/taut_pg extensions/taut_pg/tests --config-file pyproject.toml
uv build
uv build extensions/taut_pg
```

Test-environment note (finding R3-7): `textual` lives only in the `tui`/`dev`
extras, so a plain `uv run pytest` in a core-only environment has no Textual
on the path (the pre-change local `.venv` demonstrably lacked it). TUI test
modules therefore guard with `pytest.importorskip("textual")` so a core-only
checkout still passes the suite, and the final gates above run with
`--extra dev` plus the explicit TUI-test line so a skip can never masquerade
as a pass in the release path. CI's test job installs `.[dev]` and is
unaffected.

Plus TUI-specific grep gates (INV-5..8, mirroring the architecture doc's gate
posture; each must return no unexpected hits):

- `grep -rn "import textual\|from textual" taut/` → hits only under `taut/tui/`
  (INV-6).
- `grep -rn "Queue(\|insert_messages\|sidecar\|generate_timestamp\|Envelope\|encode_envelope" taut/tui/`
  → no hits (INV-7: no queue/SQL/envelope work in the UI).
- `grep -rn "advance_cursor\|last_seen_ts\|claim\|peek_many" taut/tui/` → no
  hits (INV-7/INV-8: no cursor/notification policy in the UI).
- confirm `pyproject.toml` `[project.dependencies]` still lists only
  `simplebroker` and `psutil` (INV-5).

Observable success (post-merge, [TUI-14]): bare `taut` in a project opens the
TUI; bare `taut` piped/in CI still prints help and exits non-zero (agents do
not hang — the load-bearing signal); `pip install taut` without the extra keeps
every CLI verb working and `taut` (bare, tty) prints the install hint. After a
TUI session, `taut list` reporting everything read is the intended [TUI-10.8]
behavior, not a regression.

Rollout / rollback:

- Rollout order: Task 0 (packaging, inert) → Task 1 (dispatch, the only
  contract-visible change) → Tasks 3–9 (app internals, no new contract). Tasks
  3–9 are invisible to anyone who does not install `taut[tui]`.
- Rollback: Task 1 is the only step that changes existing behavior; reverting
  its `cli.py` branch restores `print_help(); return 1`. The `taut/tui/`
  package and the extra can be removed wholesale with no storage, schema, or
  JSON impact (no one-way door in storage or format — the sole one-way-ish edge
  is the bare-`taut` UX change, mitigated by keeping it a single revertible
  branch and gating INV-3 with tests).

## 8. Independent Review Loop

- Reviewer: **Codex** (`codex exec --sandbox read-only`) — the verified
  non-Claude family in `docs/implementation/03-agent-inventory.md` (last
  refresh 2026-06-12). Claude authored this plan, so a different family
  reviews (review-loops runbook §2). If Codex is unavailable at review time,
  fall back to a strict fresh-eyes Claude pass and record the limitation.
- Give the reviewer: this plan, `docs/specs/04-taut-tui.md`,
  `docs/specs/02-taut-core.md` [TAUT-8.*] and [TAUT-10] (notification-loss),
  `taut/cli.py`, `taut/client/__init__.py`, `taut/client/_threads.py`,
  `taut/client/_messaging.py`, `taut/client/_models.py` (Task 2 depends on
  these — review finding R2-5), `taut/client/_identity.py` (the DM presence
  rule — finding R4-2), `taut/watcher.py`, and the installed
  `simplebroker/watcher.py`. (The wireframe `Taut TUI Wireframe.html` was a
  temporary artifact and has been removed; its content is captured in §2.1.)
- Prompt (runbook §4):
  > Read the plan at docs/plans/2026-07-02-taut-tui-implementation-plan.md.
  > Carefully examine the plan and the associated code. Look for errors, bad
  > ideas, and latent ambiguities — especially the launch-dispatch contract
  > (INV-1..4) and the watcher-thread ↔ Textual bridge (Task 4). Don't
  > implement anything, but answer: could you implement this confidently and
  > correctly if asked?
- Handoff: run the review after Task 1 (contract slice) and after Task 4
  (async slice) at minimum, and once before completion. Record each finding and
  its resolution (addressed / rejected-with-reason / out-of-scope-with-reason)
  in a `## Review Log` appended to this plan. The loop is not complete until
  every point is resolved; a "could not implement confidently" verdict is a
  blocker.

## 9. Out of Scope

Explicitly not in this plan (do not "clean up" into these):

- Any change to existing CLI verb behavior, output, JSON shapes, or exit codes
  (INV-1).
- Full command palette; cross-conversation search; a dedicated inbox pane;
  full in-app identity management (join/rejoin/set name/persona); mouse-first
  interaction; recursive/nested thread UI — all deferred by [TUI-15]/[TUI-13]
  and this plan's Task 6/8 decisions.
- Summon/provider lifecycle screens, message editing/deletion, archival,
  retention, notification daemon ([TUI-1]).
- Any `taut-pg` or state-layer change; any watcher-runtime change beyond
  consuming `TautClient.watch()`. If the client cannot express something the
  TUI needs, Task 2 grows a *read-only* client method under review — it does
  not change storage or the watch runtime.
- Adding any second new dependency beyond Textual (§4a stop gate).
- A delivered-versus-viewed read-cursor split (Slack-style persistent unread
  under a running watch). That is a core-spec revision ([TAUT-7.2],
  [TAUT-8.4]) and its own effort; the first TUI ships the [TUI-10.8]
  watch-implies-seen semantics instead (Deviation Log; finding R3-1).

## 10. Fresh-Eyes Review (author self-check)

Re-read as a zero-context engineer:

- File list is explicit (create vs. modify) with the exact edit seam named
  (`cli.py:34`). ✓
- No "update the logic" hand-waving; each task names files, reads, reuse, and a
  done signal. ✓
- Invariants precede tasks and name what must not move (INV-1..12). ✓
- Anti-mock posture is explicit (broker/client/watcher stay real; only
  `run_tui` + tty predicates may be mocked). ✓
- Async/threading lifecycle answered (Task 4): where input lives, stop/join on
  exit, single worker, restart/poison behavior. ✓
- Both [TUI-13] open questions are resolved with an owner (Task 7 thresholds,
  Task 8 identity-scope). ✓
- Dependency was proposed, human-approved, and is already applied; the one
  remaining human decision (`uv.lock` tracking) is flagged (§4a). ✓
  (wording corrected in round 3 — finding R3-10)
- Rollback written before the task detail and tied to a single revertible
  branch. ✓

Residual risk to watch during implementation: the Textual `Pilot` test harness
and the watch-thread bridge are the two places most likely to force a design
tweak; both have stop-gates. If either forces a change to a `TautClient`
contract, stop and re-plan Task 2 rather than working around it in the UI.

## Review Log

### Round 1 — Codex (`gpt-5.5`, `codex exec --sandbox read-only`), 2026-07-02

Verdict as reviewed: **No, not implementable confidently as written** — three
areas needed plan changes first. All six findings were reproduced against the
real source before acting (engineering-principles §8). Each is now resolved;
re-review recommended before implementation begins.

| # | Finding | Verified against | Resolution |
|---|---------|------------------|------------|
| 1 | `main([])` is not "bare taut": `main()` does `list(argv or sys.argv[1:])`, so an empty list falls back to process argv — the planned bare-launch tests would be wrong/flaky | `cli.py:33` (confirmed) | **Accepted.** Task 1 now fixes normalization to `list(sys.argv[1:] if argv is None else argv)` and adds a firing `main([])==bare` test; §3.3 records it. Safe: only the empty-list case changes; no current caller relies on it. |
| 2 | Nav mapping "no new API needed" is false — `list_threads(all_threads=False)` raises `EmptyResultError` when nothing is unread, and `all_threads=True` lists non-joined threads; a quiet project can't render nav | `_threads.py:116-117`, `99-111` (confirmed) | **Accepted.** Task 2 now adds read-only `TautClient.joined_threads()` (Addition A) with a red-green test on a fully-read project; `list_threads`/`taut list` contract left intact (INV-1). Deviation Log row added. |
| 3 | Session-open unread-separator decision is unsafe — the watcher seeds cursors from stored `last_seen_ts`, so `log()` backfill + watch double-display and mis-mark backlog | `watcher.py:581-582` (confirmed) | **Accepted; prior decision withdrawn.** Task 2 adds read-only `TautClient.read_cursor()` (Addition B); Task 3 anchors the separator at the cursor; Task 4 dedups backfill/watch overlap by `ts`. Deviation Log row added. |
| 4 | Task 4 could acknowledge (advance cursor) before the UI accepts a message — cursor advances after the handler returns, so posting-and-returning breaks at-least-once display | `watcher.py:623` (handler def; the advance call itself is `watcher.py:642` — citation corrected in round 3, finding R3-10) + [TAUT-8.4] (confirmed) | **Accepted.** Task 4 now requires a **synchronous** `App.call_from_thread(update_fn)` hand-off that propagates failure before returning; the "post a custom Textual message and return" option is removed; added an at-least-once regression test. |
| 5 | stop/join ownership wrong for the real API — `stop(join=True)` only joins the thread `run_in_thread()`/`start()` recorded, not a hand-rolled `threading.Thread`; and joining from the UI thread can deadlock against `call_from_thread` | `simplebroker/watcher.py` `run_in_thread`~920 / `stop`~507; `watcher.py:344` (confirmed) | **Accepted.** Task 4 now starts via `watcher.run_in_thread()`, adds a `stopping` flag + ordered shutdown off the UI thread to avoid deadlock, and tests assert the bridge-owned thread is not alive (not a nonexistent public property). |
| 6 | Missing-extra `ImportError` seam internally inconsistent — plan said `taut.tui` import pulls in Textual, but INV-6/Task 0 forbid Textual at `taut.tui` import time, so a guard around only the `from` import would miss the failure | Plan-internal (confirmed) | **Accepted.** §3.2 now states `taut.tui` imports without Textual and `run_tui` imports it lazily; Task 1 wraps both the import and the call in one guard, with an optional dedicated `MissingTuiExtraError` to avoid masking real bugs. |

No finding was rejected or deferred. Because the resolutions changed the client
surface (findings 2, 3) and the async contract (findings 4, 5), a **second
review round** is recommended after these plan edits and again after the Task 1
and Task 4 slices land (per §8 and CLAUDE.md's per-slice review rule).

### Round 2 — Codex (`gpt-5.5`, fresh `codex exec` session, no round-1 context), 2026-07-02

Run against the round-1-revised plan to verify the fixes held and hunt for
missed issues. Verdict as reviewed: **No, not confidently yet** — 5 findings,
all reproduced against the real source before acting. The round-1 fixes held;
these are deeper contract/lifecycle points plus drift the round-1 edits and the
already-applied dependency change introduced. All resolved below.

| # | Finding | Verified against | Resolution |
|---|---------|------------------|------------|
| R2-1 | Shutdown ack race: a `Message` handler that *returns* while `stopping` still lets `_advance` mark an undisplayed message seen | `watcher.py:642` (`_advance` runs unless handler raised) | **Accepted.** Task 4 shutdown ordering now sets the stop event first and requires the `Message` handler to **raise a non-ack shutdown exception** (not return) so the cursor is not advanced; added a shutdown-race regression test. |
| R2-2 | At-least-once overstated for notifications — they are `READ`-mode/consumed and the spec permits loss; only chat messages are peek+cursor | `watcher.py:611-617`, `569-571`; `02-taut-core.md:668-669` | **Accepted.** Task 4 now splits the contract: synchronous at-least-once *display* for `Message` only; `Notification` is best-effort after claim. Test asserts source chat history stays durable, not that the notification is re-seen. |
| R2-3 | Missing-extra guard still too broad — bare `except ImportError` around the `run_tui` call would mask real app import bugs as "install taut[tui]" | Plan-internal | **Accepted; `MissingTuiExtraError` is now mandatory (was "if needed").** `run_tui` probes `import textual` and raises `MissingTuiExtraError` only for a missing extra; `cli.py` catches only that; genuine `ImportError`s propagate. Added a negative test. |
| R2-4 | Packaging current-state claims stale — `pyproject.toml` already has `tui`/`dev` Textual (applied on the maintainer's instruction) and `uv.lock` is untracked | `pyproject.toml:37-53`; `git status` (`uv.lock` untracked) | **Accepted.** §4a re-titled "APPROVED and already applied"; Task 0 and §3.3 now *verify* the extra rather than add it, and flag the untracked `uv.lock` as a maintainer commit-vs-gitignore decision + completion-gate item. |
| R2-5 | Misc drift: §8 handoff omitted the client files Task 2 needs; Task 4 implied a nonexistent watcher "banner" event; a launch test used `db=as=token=None` instead of the real `run_tui` kwargs | `watcher.py:631-638` (poison only logs); plan §8/Task 4/Task 1 | **Accepted.** §8 handoff now lists `_threads.py`/`_messaging.py`/`_models.py`; Task 4 states the banner is produced by the TUI's own handler (no watcher event); launch test uses exact `db_path=/as_name=/token=` kwargs. |

No finding rejected. The round-2 fixes are contract-clarifying (notification
best-effort, shutdown non-ack) and drift corrections rather than new
architecture, so the plan shape is stable. **Recommendation:** one more short
confirmation pass (or accept residual risk explicitly) before Task 1 begins,
then the standing per-slice reviews after Task 1 and Task 4.

### Round 3 — Claude full review + Codex outside voice (fresh `codex exec` session), 2026-07-03

The recommended third confirmation pass, run as a full plan review by Claude
(Fable 5) with an independent Codex (gpt-5.5, `codex exec -s read-only`,
fresh context) outside voice — cross-family per the review-loops runbook.
Verdict as reviewed: **No, not confidently yet** — the rounds-1/2 watcher
acknowledgment fixes held, but the UI data contract (Task 2) was under-scoped
for Tasks 3/5/6, and one product-semantics question had survived both prior
rounds. Every finding was reproduced against quoted source before acting
(engineering-principles §8). All are resolved in this revision; finder noted
per row.

| # | Finding (finder) | Verified against | Resolution |
|---|---------|------------------|------------|
| R3-1 | Running the TUI silently consumes stored unread for background threads: the watch runtime advances every joined thread's cursor on delivery — including launch backlog — so separators read at switch-time vanish and `taut list` shows no unread after a session (Claude; missed by rounds 1–2) | `watcher.py:642` (advance after handler), `watcher.py:581-582` (backlog drain from stored cursor), `_sql.py:910-928` (`advance_cursor` forward-only), `_threads.py:201-214` (unread derived from cursor) | **Accepted; maintainer decision 2026-07-03 ("Option A").** Watch-implies-seen adopted as intended semantics. Cursors snapshotted once at mount (Task 3), watcher starts strictly after (Task 4); badges/separators are session display state (INV-10 carve-out); spec revised with [TUI-10.8] as an explicit spec-revision slice; `taut list`-after-session firing test added (Task 4); Task 9 requires the tradeoff stated in the implementation doc and README; delivered-vs-viewed split recorded out of scope (§9). Deviation Log row added. |
| R3-2 | Uninitialized-project state unreachable as sequenced: `TautClient.__init__` raises `NotInitializedError` before any App exists, but Task 3 had `run_tui` construct the client eagerly (Codex) | `_base.py:110/117/119`; `client/__init__.py:65` (`init` is a classmethod) | **Accepted.** Client construction moved inside the App and caught on startup → [TUI-10.1] empty state; `init here` calls the `TautClient.init` classmethod, then the App constructs its client (§3.2, Tasks 3 and 8). |
| R3-3 | Inline threads had no permitted data source: public `Thread` lacks an origin anchor and reply count; `joined_threads()` misses non-joined sub-threads; state reads or name parsing would violate INV-7 (Codex) | `_models.py:24-34`; `_types.py:38-45` (`origin_ts` exists only on the state row) | **Accepted.** Task 2 gains Addition C: read-only `channel_threads(channel)` returning all registered sub-threads of a channel with an additive `Thread.origin_ts` field and reply count; Task 5 consumes it. |
| R3-4 | Notification-queue contention: Task 6's "claims per `client.inbox()`" is a second consumer racing the watcher's READ-mode claim of the same queue (Codex) | `watcher.py:568-572` (notification queue in `QueueMode.READ`); `_notifications.py:16-24` (`read_many`) | **Accepted.** The watch runtime is the sole notification consumer while the TUI runs; `i` displays watch-accumulated items; Task 6 TDD asserts claimed-exactly-once via a fresh client after watcher stop, with source history durable. |
| R3-5 | Reply seam invites the wrong call: `reply()` requires the parent channel + origin message id; Task 5's wording suggested passing the sub-thread name, which raises `ThreadNameError` (Codex) | `_messaging.py:48-49` (`validate_chat_thread_name(..., allow_subthread=False)`) | **Accepted.** Task 5 now states the label-vs-call split explicitly and adds a lands-in-subthread regression test. |
| R3-6 | Import-boundary test order-dependent: an in-process `sys.modules` assertion fails once any Pilot test has imported Textual, especially under xdist (Codex) | plan Task 0/§6; CI `-n auto --dist loadgroup` (test.yml) | **Accepted.** The boundary proof runs in a subprocess (Task 0 TDD, §6). |
| R3-7 | Final gate `uv run pytest` does not guarantee Textual locally, so TUI tests could silently not run; CI installs `.[dev]` and was fine (Codex, refined) | `pyproject.toml` extras; local `.venv` probe (`ModuleNotFoundError`); test.yml:55 | **Accepted.** §7 gates run `--extra dev` with an explicit TUI-test-files line; TUI modules use `pytest.importorskip("textual")`; test-environment note added. |
| R3-8 | Membership-convergence nav refresh left as an either/or ("bounded cadence or posted event") in the riskiest slice (Claude) | Task 4 text | **Accepted; decided.** Exactly two triggers: unknown-thread delivery, plus a fallback timer at the watcher's `membership_refresh_interval`. |
| R3-9 | At-least-once test as worded was racy (retry legitimately advances the cursor after a one-shot failure); the shutdown non-ack raise avoids 3-strikes poison-advance only because the stop event is set first (Codex + Claude) | `watcher.py:619-642` (retry/advance), `watcher.py:631-638` (poison) | **Accepted.** Primary assertion is re-delivery/displayed-exactly-once; a fail-stop variant owns the cursor assertion; step-ordering rationale and a no-poison-advance shutdown assertion added to Task 4. |
| R3-10 | Text drift: §10 still said "dependency proposed, not added"; round-1 log cited `watcher.py:623` for the advance; Task 4 called simplebroker "vendored" (it is the installed `simplebroker>=4.10.0` dependency); `TautClient.init` cited at `:64` (actual `:65`); §3.3's spec backlinks are already applied, uncommitted, in the working tree (Codex + Claude) | plan text vs. `pyproject.toml`, `git status`, source | **Accepted.** All corrected in place; §3.3 now carries the worktree-reconciliation notes alongside §4a's `uv.lock` item. |
| R3-11 | Enumerable-contract gaps: no height-based too-small firing test despite the Task 7 decision including height; only `--db` of the INV-4 accepted set had a named accepted-launch test (Claude) | engineering-principles §12; Task 1/Task 7 TDD | **Accepted.** 130×15 too-small fixture added (Task 7); `--as`/`--token` firing tests added (Task 1). |

No finding rejected. Round 3 changed the Task 2 surface (Addition C), the
Task 3/8 client-ownership model, the Task 6 inbox contract, and revised
`docs/specs/04-taut-tui.md` with [TUI-10.8] as an explicit spec-revision
slice (maintainer-approved 2026-07-03). Because the round-3 fixes were folded
by the reviewing agent itself, the standing per-slice reviews after Task 1
and Task 4 (§8) remain required and should spot-check the folded text against
this table.

### Round 4 — external independent agent review (maintainer-dispatched), 2026-07-03

A fourth pass run by the maintainer through an additional independent agent
against the round-3-revised plan. Verdict as received: "implementation-ready
after a small plan revision, not before" — direction and ethos confirmed,
four plan-level gaps named. Every finding was reproduced against source
before folding (engineering-principles §8); R4-4's premise needed one
correction, noted in its row. Two findings (R4-1, R4-2) refine round-3 text,
so the reviewer's calibration on where drift was likely (Task 2's data
contract, DM rendering) was accurate.

| # | Finding | Verified against | Resolution |
|---|---------|------------------|------------|
| R4-1 | Addition C underspecified reply counts: it pointed at `_unread_count`/`_last_message_ts`, but `_unread_count` is membership-relative and returns 0 with no membership — zeroing exactly the non-joined sub-threads Addition C exists to surface; and no public field was named | `_threads.py:201-215` (returns 0 when `membership is None`; counts after `last_seen_ts`); `_messaging.py` `reply()` (the sub-thread queue holds only reply messages — origin not copied — so a total queue count is a true reply count) | **Accepted.** Addition C now names `Thread.reply_count: int = 0` = total sub-thread message count (capped `peek_many` from timestamp 0, display-only, saturating at `cap=1000`); computing via `_unread_count` is explicitly forbidden with the reason; TDD adds the joined-fully-read (`reply_count == N`, `unread_count == 0`) and non-joined (`reply_count == N`, not 0) fixtures; Task 5 and the Task 2 file list name the field. |
| R4-2 | The "no new API" mapping routed DM presence through `client.who(thread)`, but `who(thread)` validates via `validate_chat_thread_name(..., allow_dm=False)` and raises `ThreadNameError` for `dm.d_<id>` names before consulting the registry | `_identity.py:32-42`; `addressing.py:78-86`; `addressing.py:113` (DM naming) | **Accepted.** The known-mappings rule is split: channels/sub-threads via `who(thread)`; DM targets via `client.who()` (all members) filtered by `Thread.members` — covering Direct nav dots, the presence pane on a DM target, and the DM header. Task 3 TDD adds a DM label/presence test that fails with `ThreadNameError` if the implementation wrongly calls `who(dm_name)`. A neighboring gap was checked and ruled out while folding: DMs do flow through `joined_threads()` (`_say_dm` creates membership rows for both participants; the state default `list_threads()` includes the `dm` kind, `_sql.py:813`). |
| R4-3 | §3.1 read-first item 8 still claimed "only `dev` exists today; there is no `tui` extra yet" — stale against the applied `pyproject.toml` and the plan's own §4a; the round-3 sweep missed it because the claim is line-wrapped and the R3-10 consistency grep did not match across the break | plan §3.1 item 8 vs. `pyproject.toml:37-53` | **Accepted.** Corrected to the applied state. §3.1 is the zero-context implementer's first read, so current-state claims there are held to the same bar as §4a. |
| R4-4 | Task 1 tested accepted globals in space-separated form only; if `_launch.decide()` hand-parsed argv, `taut --db=X` could regress | `cli.py:544-552` — `_hoist_global_options` **does** hoist `--db=X`-form today, so the reviewer's alternative of "declare equals-form unsupported" would itself have introduced an inconsistency with existing verb behavior (premise corrected); the live risk is a second parser inside `_launch` | **Accepted, refined structurally.** `decide()` now consumes the argparse namespace `main()` already holds and never re-parses argv (one canonical parse — INV-4 wording extended to name both spellings); one representative equals-form firing test added (`taut --db=X` → `run_tui(db_path="X", ...)`), declared sufficient because spelling handling belongs to argparse and is proven once. |

No finding rejected. Round 4 changed no architecture: it named one public
field, split one data mapping, corrected one stale current-state claim, and
hardened the launch-decision seam against a parser fork. The standing
per-slice reviews after Task 1 and Task 4 (§8) remain required.

### Per-slice review — Task 1 launch dispatch (Codex `codex exec`, 2026-07-03)

Reviewed commit `4b38572` against INV-1..4. Two findings, both accepted and
fixed in the same slice (follow-up commit):

1. The `run_tui` probe translated **any** `ImportError` into
   `MissingTuiExtraError`, so a broken-but-installed Textual (e.g. missing
   transitive dependency) would be mis-reported as a missing extra — the
   R2-3 failure one level down. Fixed: translate only `exc.name ==
   "textual"`; a broken-install regression test (fake `textual.py` that
   dies on a missing dep) proves real failures propagate.
2. The INV-4 excluded-flag firing tests covered `--json`/`-t`/`-q` but not
   the `--timestamps`/`--quiet` long forms of the enumerable set. Fixed:
   parametrize extended to all five spellings.

Verdict after fixes: pass — `tests/test_tui_launch.py` +
`tests/test_cli.py` green (46 tests), ruff/mypy clean.
