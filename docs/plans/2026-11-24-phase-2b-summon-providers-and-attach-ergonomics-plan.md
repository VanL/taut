# Phase 2B: `taut-summon` Providers, `--status`, `--provider-arg` & Attach Ergonomics Plan

Date: 2026-11-24
Status: completed
Owner: Taut maintainers
Author model family: Agy / Gemini (Google DeepMind)
Reviewer model family: Claude / Anthropic (`claude 2.1.293`) & Codex / OpenAI (`codex-cli 0.170.0`, cross-family Tier-1 per `[DOM-11]` and `docs/implementation/03-agent-inventory.md`)
Class: 5+P (hardened; public `taut_summon` facade + CLI + shared command-syntax + POSIX PTY/process-domain + `taut-tui` form/mirror cross-extension contract changes with Strategy-A spec promotion)
Plan type: implementation with spec revision
Promotion strategy: **A — promote normative spec deltas before implementation code; update implementation mappings and doc links with implementation slices**
Promotion baseline identifier: base 3e89fe7c82d4ce8f18108699280c9392e0cc8edb; unstaged promoted spec diff SHA-256 f270e26b814cba29eb7b299a84eae619020e775e97479f54b0bcb5a31b055dab

## Spec Baseline

- `3e89fe7c82d4ce8f18108699280c9392e0cc8edb` — `docs/specs/02-taut-core.md`, `docs/specs/04-summon.md`, and `docs/specs/10-taut-tui.md` at plan authoring time (committed HEAD; zero local spec diff before Slice 0).

## Goal

Eliminate high-friction adoption and day-to-day operational rough edges in `taut-summon` while staying strictly **taut** (`docs/program-theory.md`: zero slack between problem, boundary, and mechanism; zero third-party dependencies; no daemon `[THEORY-5.A4]`; no wrapper flags for shell multiplexers `[SUM-1]`/`[SUM-2]`; no vendor-specific permission presets `[SUM-1]`; no in-band executable/auth modeling `[THEORY-5.A6]`; and no schema migration):

1. **`agy` & `gemini` PTY provider registrations + lazy `SummonController.provider_names()` + help discovery**: Register `gemini` (Google Gemini CLI) and `agy` (Google Antigravity CLI) alongside existing PTY providers (`claude`, `coder`, `codex`, `grok`, `kimi`, `opencode`, `pi`, `pty`, `qwen`, `scripted`), add `"agy"` to `PER_BASENAME_NAME_POOLS` in `taut/_constants.py`, keep `SummonController` import and `provider_names()` free of runtime `_control`/`_state`/`_driver`/`_pty` imports, and surface the sorted registered provider names directly in `taut summon --help` and `taut-summon run --help`.
2. **Root `taut summon --status [NAME]` parity, NDJSON contracts & passive non-installing controller inspection**: Let operators and scripts inspect live summoned sessions or a named member's correlated `STATUS` directly from `taut summon --status [NAME]` (including `--json` / `taut --json` on both `taut summon --status` and `taut-summon status`, emitting one JSON object per line per `[TAUT-8.2]`), normalize corrupt non-numeric `summon_schema_version` rows to `SummonSchemaVersionError`, and inspect `list_live()`, `status()`, and `stop()` through Phase 2A's non-installing `TautClient(..., install_schema=False)` before opening any writable control client while keeping `post_verb_globals` on `summon` pinned to `{GlobalOption.DB}`.
3. **Vendor-neutral `--provider-arg` pass-through & `[TAUT-8.7]` option-value slot protection**: Add `provider_args: tuple[str, ...] = ()` (`--provider-arg ARG`, repeatable; inline `--provider-arg=VALUE` for option-shaped values) to `SummonRequest`, `PtyAdapter.with_extra_args`, `taut summon` / `taut-summon run`, `taut/commands/syntax.py` + `taut_summon/command_syntax.py`, and `taut-tui`'s `SummonStartScreen` + `:summon` mirror, protecting preceding local option value slots from post-verb global extraction (`--provider-arg --db=other.db` never extracts `--db` or writes load-failure debug records to `other.db`).
4. **Local pre-DB input validation, `y`/`yes`/Enter confirmation, POSIX `TIOCGWINSZ` attach resize sync, and child `SIGHUP` reset**:
   - Validate pure local request inputs (`get_adapter` when `--provider` is explicit, `validate_provider_args`, single UTF-8 `--system-prompt-file` read, and `--attach` host terminal availability) before opening storage or calling `ensure_summon_schema()`, and re-validate the resolved provider's adapter capabilities and `provider_args` in `_bootstrap()` before `replace_legacy_provider()` / `claim_driver()`.
   - Accept Enter, `y`, or `yes` (case-insensitively; EOF `""` and other inputs cancel) in `ShellSummonInteraction.confirm_terminal_attach`.
   - Synchronize valid non-zero host terminal window dimensions (`TIOCGWINSZ` -> `TIOCSWINSZ` + `_TerminalState.resize` clamping tracked cursor coordinates; ignoring `0x0` unset PTY sizes) on `PosixPtyHandle.attach` entry and on its existing 100 ms `select()` wake (`_pty_posix.py`, `[THEORY-3]`).
   - Reset `signal.signal(signal.SIGHUP, signal.SIG_DFL)` inside `_CONTROLLING_TERMINAL_TRAMPOLINE` (`_process_domain_posix.py`) before `TIOCSCTTY` / `os.execvpe` so inherited parent `SIG_IGN` (`nohup`) cannot defeat kernel controlling-terminal `SIGHUP` on driver death (`[SUM-11]`).

## Source Documents

Normative specifications:

- `docs/specs/01-development-documentation-operating-model.md` (`[DOM-5]`, `[DOM-8]`, `[DOM-10]`, `[DOM-10.1]`, `[DOM-10.2.1]`, `[DOM-11]`, `[DOM-15]`)
- `docs/specs/02-taut-core.md` (`[TAUT-6.4]`, `[TAUT-8.1]`, `[TAUT-8.2]`, `[TAUT-8.6]`, `[TAUT-8.7]`, `[TAUT-12.3]`)
- `docs/specs/03-identity-addressing-notifications.md` (`[IAN-3.2]`, `[IAN-4]`)
- `docs/specs/04-summon.md` (`[SUM-1]`, `[SUM-2]`, `[SUM-3]`, `[SUM-4]`, `[SUM-6]`, `[SUM-7.1]`, `[SUM-7.2]`, `[SUM-7.4]`, `[SUM-8]`, `[SUM-9]`, `[SUM-11]`, `[SUM-13]`)
- `docs/specs/07-agent-theory-and-program-theory.md` (`[AT-REF-2]`, `[AT-REF-3]`)
- `docs/specs/10-taut-tui.md` (`[TUI-11.1]`, `[TUI-11.2]`, `[TUI-11.3]`)

Shared context, theory, and runbooks consulted:

- `AGENTS.md`
- `docs/program-theory.md` (`[THEORY-1]`–`[THEORY-8]`)
- `docs/agent-context/README.md`
- `docs/agent-context/decision-hierarchy.md`
- `docs/agent-context/principles.md`
- `docs/agent-context/engineering-principles.md`
- `docs/agent-context/runbooks/writing-plans.md`
- `docs/agent-context/runbooks/hardening-plans.md`
- `docs/agent-context/runbooks/writing-specs.md`
- `docs/agent-context/runbooks/maintaining-traceability.md`
- `docs/agent-context/runbooks/testing-patterns.md`
- `docs/agent-context/runbooks/adversarial-acceptance-probes.md`
- `docs/agent-context/runbooks/review-loops-and-agent-bootstrap.md`
- `docs/implementation/03-agent-inventory.md`
- `docs/lessons.md`
- `skills/call-agent/SKILL.md`

Implementation architecture & retired plan provenance:

- `docs/implementation/05-taut-summon-architecture.md`
- `docs/implementation/06-command-extensions.md`
- `docs/implementation/12-taut-tui.md`
- Retired `2026-08-17-summon-first-attach-handoff-plan.md` (`git show df54c08`) — establishes why `confirm_terminal_attach` runs post-bootstrap inside the reactor with `cancel=self._shutdown` and why cancelled first-attach performs no destructive member/session rollback.
- Promoted `docs/plans/2026-11-10-upstream-port-runtime-hardening-and-theory-wave-plan.md` — exact promoted spans in `docs/specs/02-taut-core.md` and `docs/specs/04-summon.md` MUST remain byte-identical so `bin/check-doc-paths` passes.

## Context and Key Files

### Core (`taut`) and Build/Release Verification (`bin`)
- `taut/_constants.py`: `PER_BASENAME_NAME_POOLS` (already contains `"gemini"`; add `"agy": ("Agatha", "Agnes", "Agis", "Agathon")`).
- `taut/commands/_dispatch.py` & `taut/commands/syntax.py`:
  - In `_prepare_invocation` (`taut/commands/_dispatch.py`), load `command = _load_command(selected)` and build `parser = _build_command_parser(...)` **before** extracting post-verb globals from `tail`: route any load or parser-construction failure's `_capture_boundary_exception` strictly to `db_path=root.db_path` (never scanning an unclassified `tail`), and skip post-verb global extraction when a token sits in the mandatory value slot of a preceding inline-free value-taking local option on the active parser/subparser.
  - In `taut/commands/syntax.py`, consume local options and `post_verb_globals` in one left-to-right pass (deduplicating prefix matches by `option.name` so list-default `OptionSyntax` entries never raise `TypeError`, honoring the literal `--` boundary so `-- --help` / `-- --version` are literal positionals, keeping `_NEGATIVE_NUMBER_RE` intact for integer options, and requiring inline `--opt=VALUE` for option-shaped values).
  - Keep standalone `--db` (`dest == "db_path"`) exact-only on `_SummonArgumentParser._get_option_tuples` (`extensions/taut_summon/taut_summon/cli.py`), matching `CommandArgumentParser._get_option_tuples` and `syntax.py` so `claude --d` resolves to `--detach` across all three command-line surfaces (`taut summon`, `taut-summon run`, and `:summon`).
- `bin/check-core-summon-wheel-matrix.py` & `bin/build-and-check-release-wheels.py`: Extend clean-venv wheel smoke to exercise `taut summon --status --json` and `taut summon --status artifact-probe --json`.

### Summon Extension (`extensions/taut_summon`)
- `extensions/taut_summon/taut_summon/models.py`: Add `provider_args: tuple[str, ...] = ()` to `SummonRequest`.
- `extensions/taut_summon/taut_summon/_providers.py` (new): Zero-runtime-import `PROVIDER_NAMES` (`provider_names()`), keeping `--help` and `SummonController.provider_names()` free of `taut_summon._adapter`.
- `extensions/taut_summon/taut_summon/_adapter.py`: Derive `_FACTORIES` from `PROVIDER_NAMES`, register `agy` and `gemini`, and own `validate_provider_args(provider, provider_args)`.
- `extensions/taut_summon/taut_summon/_state.py`: Keep `SUMMON_SCHEMA_VERSION = 4`; normalize non-integer `summon_schema_version` values in `ensure_summon_schema()` and `get_summon_schema_version()` to `SummonSchemaVersionError`.
- `extensions/taut_summon/taut_summon/controller.py`: Make runtime imports lazy inside methods so importing `SummonController` and calling `provider_names()` loads zero broker/client/driver/PTY/state modules; in `list_live()`, `status(name)`, and `stop(name)`, inspect via `TautClient(db_path=self._db_path, install_schema=False)` first (`NotInitializedError` or `get_summon_schema_version(queue) is None` -> `()` / `NothingSummoned` with zero setup or WAL writes; `validate_summon_schema(queue)` otherwise), opening a writable `TautClient` bound to `probe.target` + `probe.config` only when `status(name)` or `stop(name)` sends a control message to a non-`dead` session.
- `extensions/taut_summon/taut_summon/commands/__init__.py`, `commands/summon.py`, `cli.py`: Shared human + NDJSON status renderers, `taut summon` (`--status [NAME]`, `--provider-arg`, `--json` for `--status`), `taut-summon` (`status [NAME] [--json]`, `run --provider-arg`), and registered provider names in `--help`.
- `extensions/taut_summon/taut_summon/command_syntax.py`: Add repeatable `--provider-arg` (`multiple=True`) for `:summon` while keeping CLI-only `--status` and `--json` out of the TUI mirror AST.
- `extensions/taut_summon/taut_summon/interaction.py`: Accept `Enter`, `y`, or `yes` in `ShellSummonInteraction.confirm_terminal_attach`.
- `extensions/taut_summon/taut_summon/_driver.py`: Validate pure local request inputs before opening `_persistent_client`, re-validate adapter and `provider_args` against the resolved provider in `_bootstrap()` before `replace_legacy_provider()` or `claim_driver()`, and apply `PtyAdapter.with_extra_args(request.provider_args)`.
- `extensions/taut_summon/taut_summon/_pty.py`, `_pty_posix.py`, `_process_domain_posix.py`: `_TerminalState.resize(rows, cols)` (clamping `cursor_row` and `cursor_col`, with cursor tracking active across `observe_output(..., answer_queries=False)`), `PtyAdapter.with_extra_args`, `PosixPtyHandle.attach` `TIOCGWINSZ` -> `TIOCSWINSZ` sync on entry and on its existing 100 ms `select()` pass (ignoring `rows <= 0 or cols <= 0`), and child-trampoline `signal.signal(signal.SIGHUP, signal.SIG_DFL)` before `TIOCSCTTY`.
- `extensions/taut_summon/pyproject.toml`: Register `requires_agy` and `requires_gemini` pytest markers.

### TUI Extension (`extensions/taut_tui`)
- `extensions/taut_tui/taut_tui/{screens,summon,app}.py`: `SummonStartSubmission`, `SummonStartScreen` (unframed `shlex` tokenization for `Provider arguments`), `TuiSummonOperations.build_request`, and `:summon` mirror forwarding `provider_args`.

## Theory-Versus-Plan Audit (`[AT-REF-2]`, `docs/program-theory.md`)

| Theory commitment | Phase 2B alignment | Status |
|---|---|---|
| `[THEORY-1]` / `[THEORY-4]` Small external surface; humans & agents both first-class; record-oriented commands expose `--json` (NDJSON) | `--status` / `status` emit NDJSON (`[TAUT-8.2]`); foreground `summon`/`run` keeps its native PTY transport and rejects `--json`; registered providers show directly in `--help` without a new `providers` subcommand. | Aligned |
| `[THEORY-2]` & `[SUM-4]` / `[SUM-8]` Workspace is storage; public `who()` lookup, zero private state calls | Passive `list_live()` / `status()` / `stop()` reuse Phase 2A's `TautClient(..., install_schema=False)` + `NoSetupSQLRunner` + public `find_member` (`client.who()`), adding zero parallel storage helpers in `taut/state` and zero duplicate DB preflight passes in `_driver.py`. | Aligned |
| `[THEORY-3]` Live watcher has one wake path; clock work is a deadline on the same wait | `PosixPtyHandle.attach` checks `TIOCGWINSZ` on entry and on its existing 100 ms `select()` loop, adding no `SIGWINCH` wakeup pipe or second reactor. | Aligned |
| `[THEORY-5.A4]` & `[SUM-1]` / `[SUM-2]` No daemon; shell composition owns multiplexers (`tmux`, `docker`, `nohup`) | Dropped `--tmux`; foreground `taut summon` composes directly with `tmux new -s claude -- taut summon claude` in the user's shell. | Aligned |
| `[THEORY-5.A6]` & `[SUM-1]` / `[SUM-7.4]` Out-of-layer enforcement is never simulated in-band; harness owns login & permissions | Dropped `ProviderReadiness` / PE binary scanning / `auth_hint` and vendor-specific `--preset`; OS `exec`/`CreateProcessW` enforces executable resolution, `--provider-arg` forwards raw flags neutrally, and `[SUM-7.4]` attach hands the terminal to the harness. | Aligned |

## Invariants, Hidden Couplings, and What Must Not Change

1. **No daemon, no third-party dependencies, no schema migration, no parallel state layer**:
   - `taut-summon` depends only on `taut-chat` (`[SUM-3]`, `[THEORY-5.A4]`); `SUMMON_SCHEMA_VERSION` stays `4`; `taut/state/_sql.py` and `spawn_windows_pty` remain untouched.
2. **Non-installing passive inspection on `TautClient(..., install_schema=False)` & local pre-DB driver validation (`[SUM-4]`, `[SUM-7.4]`, `[SUM-8]`)**:
   - `SummonDriver._validate_local_request()` validates pure local inputs (`--provider` adapter lookup when explicit, `validate_provider_args`, single UTF-8 `--system-prompt-file` decode, and `--attach` host terminal availability when supported, caching that single availability probe for `_terminal_availability`) before opening storage.
   - `SummonController.list_live()` / `status()` / `stop()` open non-persistent `TautClient(..., install_schema=False)` (`NoSetupSQLRunner`, never running `setup()` or switching rollback-journal SQLite DBs to WAL) and open a writable `TautClient` reusing `probe.target` + `probe.config` only when sending control IPC to a non-`dead` row.
   - `_bootstrap()` re-validates adapter and `provider_args` against the resolved provider before `replace_legacy_provider()` or `claim_driver()` mutates `taut_summon_sessions`.
3. **Lazy-import floor, required coverage markers, terminal-sink inventory, `post_verb_globals` & worktree protection**:
   - Preserve lazy imports (`tests/test_lazy_imports.py`, `test_controller.py`, `test_providers.py`), all 6 required coverage markers (`bin/check-required-coverage-paths.py`), `tests/test_architecture_boundaries.py` terminal-sink inventory, `summon.post_verb_globals = frozenset({GlobalOption.DB})`, and NEVER touch `skills/call-agent/SKILL.md`.
   - **Accepted risk**: scientific-notation negative floats (`-1e3`) remain accepted by `argparse` and rejected as separate tokens by `syntax.py`'s existing `_NEGATIVE_NUMBER_RE` (inline `--provider-arg=-1e3` works everywhere).

## Anti-Mocking Guidance

- **Lazy imports & provider registry**: Fresh-interpreter `subprocess.run([sys.executable, "-c", ...])` proving zero runtime module imports on `SummonController().provider_names()` and bidirectional `adapter_names()` parity.
- **Non-installing controller inspection & local driver validation**: Real SQLite (missing DB, broker-only `.taut.db`, rollback-journal `PRAGMA journal_mode = DELETE`) and live Docker PostgreSQL (`extensions/taut_pg/tests/test_pg_sidecar.py`) proving zero Summon tables installed and rollback-journal SQLite DBs remain in `journal_mode == 'delete'`.
- **PTY resize & child `SIGHUP` reset**: Real POSIX `pty.openpty()` verifying `TIOCGWINSZ` -> `TIOCSWINSZ` sync, `0x0` guard, detached DSR `ESC[6n` cursor clamping after shrink, and inherited `SIG_IGN` arriving as `SIG_DFL` in the spawned child.
- **TUI**: Real Textual `TautApp` / `SummonStartScreen` pilot sessions.

## Rollback, Rollout, and Compatibility Sequencing

- **Storage & rollback compatibility**: `SUMMON_SCHEMA_VERSION` stays `4` (`taut_summon/_state.py`). Existing `0.9.12` binaries read and resume schema-4 rows unchanged for all pre-existing providers. **Named rollback limit**: durable `taut_summon_sessions` rows created under `'agy'` or `'gemini'` cannot be resumed by a rolled-back `0.9.12` binary because re-summon resolves the stored provider and refuses provider switching; after a rollback, operators summon a new member name under a `0.9.12`-supported provider.
- **Cross-package source & wheel atomicity**: `taut`, `taut-summon`, `taut-pg` tests, and `taut-tui` land together in one commit, verified via isolated `-n auto --dist load` process tests, combined parallel coverage (`bin/combine-coverage.py` + `bin/check-required-coverage-paths.py`), and freshly built wheels (`bin/build-and-check-release-wheels.py`).

## Proposed Spec Delta (Strategy A — Applied in Slice 0)

### 1. `docs/specs/02-taut-core.md`

#### 1a. `[TAUT-8.1]` CLI verb summary

Replacement (`docs/specs/02-taut-core.md`):
```markdown
| `summon PROVIDER_OR_NAME [THREAD ...] \| summon --status [NAME]` | Provided by the separately installed `taut-summon` command package through [TAUT-8.6]. Without a compatible provider, exit 1 with a one-line install hint. Behavior lives in spec 04. | per spec 04 |
| `dismiss NAME` | Provided by the same package and command interface; maps to Summon's stop operation. | per spec 04 |
```

#### 1b. `[TAUT-8.7]` Literal `--` boundary and ordered option-value slot protection

Replacement (`docs/specs/02-taut-core.md`):
```markdown
Taut command syntax is a typed, surface-neutral contract adjacent to the
version-1 `CommandSpec` manifest. It describes canonical command paths,
nested subcommands, positional values, options, value kinds, quoting,
literal `--` separator behavior (tokens after `--` are literal positionals and
never trigger `-h`/`--help`/`--version` actions), left-to-right option-value
slot classification (post-verb globals require exact spellings and are never
extracted from a preceding local option's mandatory value slot; option-shaped
values use inline `--opt=VALUE`), and deterministic completion metadata. It
does not describe a surface's renderer, form layout, gesture, lifecycle, or
output transport.
```

#### 1c. `## Related Plans`

Replacement (`docs/specs/02-taut-core.md`):
```markdown
- `docs/plans/2026-11-24-phase-2b-summon-providers-and-attach-ergonomics-plan.md` —
  adds `agy` automatic-name pool entries in `taut/_constants.py`, [TAUT-8.7]
  ordered post-verb global/local option-value slot classification and
  `root.db_path`-scoped load-failure debug capture across
  `taut/commands/_dispatch.py` and `taut/commands/syntax.py`, and updates the
  [TAUT-8.1] `summon` summary for `--status` parity under spec 04 while keeping
  `summon` `post_verb_globals` pinned to `{GlobalOption.DB}`.
```

### 2. `docs/specs/04-summon.md`

#### 2a. `[SUM-3]` Packaging, CLI `--status` + NDJSON parity, and `--provider-arg`

Replacement (`docs/specs/04-summon.md`):
````markdown
```text
taut summon PROVIDER_OR_NAME [THREAD ...] [flags]   # default thread: general
taut summon --status [NAME] [--json]
taut dismiss NAME
```

  Core supplies only the absent-package install hint; it contains no Summon
  domain logic and does not delegate to an older extension CLI. Current
  Summon entry points own both reserved command slots, keeping `post_verb_globals`
  pinned to `{GlobalOption.DB}` so undeclared root-global lookalikes remain in
  the Summon parser's tail.
- The extension also installs `taut-summon run|stop|status`. Both console
  surfaces are adapters over the public [SUM-13] controller. They share
  request models, provider/name resolution, registered-provider help text,
  status/stop results, error semantics, and tests; neither console surface
  invokes the other's `main()` or parses the other's output.

  Both first-party console surfaces use `taut.escape_terminal_text` for
  Taut-owned dynamic human text and diagnostics under [TAUT-6.4]. JSON/domain
  values remain exact. For administrative/inspection commands (`status` /
  `--status`, `stop` / `dismiss`) and pre-attach failures of foreground `run`,
  every non-zero exit (`1` or `2`) leaves `stdout` empty and writes its
  diagnostic to `stderr` even when `--json` is active. JSON output (`--json` or
  root `taut --json`, emitting one JSON object per line in NDJSON framing per
  [TAUT-8.2]) is supported on:
  - `taut summon --status` / `taut-summon status`: projects
    `SummonController.list_live()` (every non-`dead` ledger claim, including
    `"indeterminate"` rows, matching human `<name>\t<provider>\tlive`); exit `0`
    emits one `{"member_id": str, "name": str, "provider": str, "status":
    "live"}` JSON object per line, and exit `2` (nothing summoned) emits nothing
    on `stdout`. Bare `list_live()` failures carry `fault_plane=None`.
  - `taut summon --status NAME` / `taut-summon status NAME`: resolves any
    non-`dead` ledger claim (`"live"` or `"indeterminate"`) and performs a
    correlated `STATUS` control round-trip; a valid correlated reply exits `0`
    with one line `{"member_id": str, "name": str, "driver": str, "provider":
    str, "thread_count": int, "cursor_lag": dict[str, int], "details": dict[str,
    JSONPrimitive]}`, while exit `2` (nothing summoned) or `1` (error or
    `DriverUnresponsive` timeout, carrying `STATUS_FAULT_PLANES` when
    `TAUT_SUMMON_STATUS_FAULT_PLANE=1`) emits nothing on `stdout`.
  Passing `--json` to an interactive foreground `summon`/`run` invocation
  without `--status` is a usage error (exit `1`).

  `taut summon X ...` remains behaviorally equivalent to
  `taut-summon run X ...`, `taut summon --status [NAME]` is equivalent to
  `taut-summon status [NAME]`, and `taut dismiss X` remains equivalent to
  `taut-summon stop X`. Both run surfaces surface the sorted registered provider
  names in `--help` and accept repeatable `--provider-arg ARG` (using inline
  `--provider-arg=--flag` for option-shaped values). Both surfaces share one
  resolution contract:
````

#### 2b. `[SUM-7.2]` Shipped providers and pass-through arguments

Replacement (`docs/specs/04-summon.md`):
```markdown
### [SUM-7.2] Adapters shipped and pass-through arguments

- `pty` is the sole production adapter. It hosts every named provider
  (`agy`, `claude`, `coder`, `codex`, `gemini`, `grok`, `kimi`, `opencode`,
  `pi`, `qwen`, and future interactive CLIs) through the same terminal path.
  Provider entries contain only the executable argv and values already
  represented by `PtySpec`; they are not protocol adapters.
- `scripted` is a packaged test registration for the same PTY adapter. Its
  real interactive child publishes terminal readiness, accepts terminal
  input, records received turns, and exercises explicit Taut commands. It is
  the anti-mocking seam for downstream conformance and contains no second
  adapter or wire protocol.
- Repeatable pass-through arguments (`--provider-arg ARG`, ordered as
  `(*base_argv, *provider_args)`) customize `PtyAdapter` per foreground run
  without schema changes. Explicit `--provider-arg` values must be non-empty
  strings without NUL bytes and are rejected before session-row claim or mutation on
  `scripted`.
```

#### 2c. `[SUM-7.4]` Child `SIGHUP` reset, `PosixPtyHandle.attach` `TIOCGWINSZ` sync, and DSR clamping

Replacement (`docs/specs/04-summon.md`):
```markdown
The POSIX threaded driver uses `start_new_session=True`, never `preexec_fn` or
`pty.fork()`. Inside the POSIX controlling-terminal child trampoline, `SIGHUP`
is reset to `SIG_DFL` before `TIOCSCTTY` and `os.execvpe` so an inherited
`SIG_IGN` from a `nohup` ancestor cannot defeat controlling-terminal `SIGHUP`
delivery on driver death ([SUM-11]).

During POSIX `attach()`, the bridge reads the leased host terminal's window
dimensions (`TIOCGWINSZ` on `output_fd`, falling back to `input_fd`) on entry
and on its existing 100 ms `select` loop ([THEORY-3]). Unset or non-positive
readings (`rows <= 0` or `cols <= 0`) are ignored; valid size changes are
forwarded to the PTY master (`TIOCSWINSZ`) and applied to
`_TerminalState.resize(rows, cols)`, clamping stored `(cursor_row, cursor_col)`
so detached DSR `ESC[6n` replies after detach never report out-of-bounds
coordinates.

Validation exists only for values constructible through `PtySpec` or the
documented `TAUT_SUMMON_PTY_*` environment variables. Platform setup errors
are normalized to `AdapterError` at `PtyAdapter.spawn()`. The adapter does not
validate speculative provider profiles or unreachable internal states.
```

#### 2d. `[SUM-7.4]` Pre-bootstrap input validation and `y`/`yes`/Enter confirmation

Replacement (`docs/specs/04-summon.md`):
```markdown
**Pre-bootstrap input validation and pre-attach acknowledgement.** Before
opening storage or calling `ensure_summon_schema()`, Summon validates local
request inputs (`--provider` adapter lookup when explicit, `--provider-arg`
values, UTF-8 `--system-prompt-file` readability once, and `--attach` host
terminal availability when attach is supported), and `_bootstrap()` re-verifies
the resolved provider's adapter capabilities and `--provider-arg` constraints
before `replace_legacy_provider()` or `claim_driver()` mutates
`taut_summon_sessions`.

After `_bootstrap()` claims the driver slot, and after resolving that the first
provider generation will actually attach, but before spawning that generation,
Summon asks the host interaction to present a typed terminal-attach notice and
return an explicit proceed/cancel decision. The notice identifies the member
and provider and supplies the Summon-owned detach hint. Every host must make
four facts clear: this screen is provider setup rather than Taut chat; the
user should complete only trust, login, model, or equivalent setup; the user
returns with `Ctrl-\ Ctrl-\`; and the foreground Summon run continues after
detach. The shell accepts a blank Enter, `y`, or `yes` (case-insensitively,
ignoring surrounding whitespace); EOF or any other input cancels. A rich host
may use a native confirmation that was opened by this exact attach decision.
```

#### 2e. `[SUM-11]` Driver crash `SIGHUP` boundary

Replacement (`docs/specs/04-summon.md`):
```markdown
- Driver crash: cursors and ledger make restart safe (at-least-once
  injection); stale session driver evidence is reclaimable. Because the
  PTY slave is the provider's controlling terminal and the POSIX child
  trampoline resets `SIGHUP` to `SIG_DFL` before `TIOCSCTTY` and `exec`,
  closing the master on driver death delivers the operating system's `SIGHUP`
  to the provider's foreground group even when the parent shell ran under
  `nohup`. Taut promises nothing beyond that OS behavior: a provider executable
  that installs its own `SIGHUP` ignore handler after `exec` may survive even
  though ordinary dead-driver evidence permits a new claim, so Taut cannot
  prevent duplicate providers in that case. Taut adds no provider census or
  watchdog for this residual risk.
```

#### 2f. `[SUM-13]` Public `SummonController` lazy imports, `SummonRequest`, and schema-error normalization

Replacement (`docs/specs/04-summon.md`):
```markdown
`SummonController` is bound to one optional database path. Importing
`SummonController` and calling `provider_names()` does not import broker, core
client, control, state, driver, or PTY runtime modules. It exposes sorted
provider names through `provider_names()` without constructing adapters; live
session summaries through `list_live()`; one correlated live status; one
confirmed stop result; and a blocking foreground run with keyword-only
`install_signal_handlers: bool = False` and
`on_ready: Callable[[SummonRunHandle], None] | None = None` that returns no
value on clean completion. `list_live()`, `status()`, and `stop()` inspect
existing state through a non-installing client first so uninitialized,
broker-only, empty, dead, or malformed targets perform no setup or sidecar
writes (`list_live()` returns an empty tuple when no database or no live rows
exist; command adapters translate that empty result to the nothing-summoned
exit class). The request model contains `name`, `threads`, `persona`,
`system_prompt_file`, `rate_limit`, `attach`, `detach`, `provider_flag`,
`takeover`, and `provider_args`; the database path belongs to the controller.
A live summary contains member id, current name, and provider. A stop result
contains member id and current name. Status contains
those identity/provider values plus driver, thread count, cursor lag, and
defensive copies of remaining validated JSON-primitive detail fields; it never
exposes a raw reply.

Public controller operations return typed domain results and raise typed
`NothingSummoned`, `DriverUnresponsive`, or `SummonOperationError` (including
malformed or non-numeric `summon_schema_version` metadata normalized through
`SummonSchemaVersionError`). They do not print, return CLI exit codes, or
require callers to parse human or JSON output. Command adapters own rendering
and map `NothingSummoned` to exit 2 and the other public operation errors to
exit 1.
```

#### 2g. `## Related Plans`

Replacement (`docs/specs/04-summon.md`):
```markdown
- `docs/plans/2026-09-24-summon-controlling-terminal-and-live-lane-plan.md`
  — gives the POSIX provider a controlling terminal through the shared spawn
  owner, states the driver-crash guarantee, reaps fixture process groups on
  every test path, removes live-harness false skips, and adds the real root-CLI
  host-PTY scenario.

- `docs/plans/2026-11-24-phase-2b-summon-providers-and-attach-ergonomics-plan.md`
  — adds `agy` and `gemini` PTY providers, lazy `SummonController`
  `provider_names()` imports, root `taut summon --status [NAME]` + NDJSON
  parity, repeatable `--provider-arg`, non-installing passive controller
  inspection on `TautClient(..., install_schema=False)`, local pre-DB request
  validation, `y`/`yes`/Enter attach confirmation, POSIX `TIOCGWINSZ` attach
  resize sync, and child `SIGHUP` `SIG_DFL` reset.
```

### 3. `docs/specs/10-taut-tui.md`

#### 3a. `[TUI-11.1]` `SummonStartScreen` and `:summon` mirror parity

Replacement (`docs/specs/10-taut-tui.md`):
```markdown
The start form obtains provider names from `provider_names()` and constructs a
typed `SummonRequest`. It exposes name, conversations, provider, persona,
system-prompt file, rate limit, provider arguments, attach/detach, and
takeover without reusing the CLI parser; the selected provider populates
`provider_flag`. Status calls the controller and displays correlated live
status. Dismiss calls confirmed `stop()`. Chat member presence and live
driver status are separate labelled observations.

When `taut-summon` is available, the TUI registers native textual mirror
bindings for `summon` and `dismiss` through the public controller boundary
(including repeatable `--provider-arg`; administrative CLI flags `--status`
and `--json` remain CLI-only because the TUI owns native list/status actions
and in-process foreground supervision).
`:summon grok` is a typed request, not a CLI invocation. The existing
foreground ownership, readiness, terminal lease, logging, and shutdown rules
remain authoritative.
```

#### 3b. `## Related Plans`

Replacement (`docs/specs/10-taut-tui.md`):
```markdown
- `docs/plans/2026-11-24-phase-2b-summon-providers-and-attach-ergonomics-plan.md` —
  extends `SummonStartScreen`, `TuiSummonOperations.build_request`, and the
  `:summon` mirror with `provider_args` (while removing the stale nonexistent
  `terminal` start-form noun from [TUI-11.1] and recording `--status` and
  `--json` on `summon` as CLI-only).
```

## Dependency-Ordered Implementation Slices

### Slice 0 — Normative Spec Promotion (Strategy A)
- Apply all `Replacement` blocks above (`1a`–`1c`, `2a`–`2g`, `3a`–`3b`) to `docs/specs/02-taut-core.md`, `docs/specs/04-summon.md`, and `docs/specs/10-taut-tui.md`.
- Compute `shasum -a 256` of `git diff -- docs/specs/02-taut-core.md docs/specs/04-summon.md docs/specs/10-taut-tui.md`, update `Promotion baseline identifier`, and verify `bin/check-plan-status-index`, `bin/check-doc-paths`, and `bin/check-cli-claims`.

### Slice 1 — `agy` & `gemini` Registration, Lazy `SummonController.provider_names()`, Schema Normalization & `--provider-arg` Model
- Register `agy` and `gemini` in `_adapter.py`, add `"agy"` to `taut/_constants.py`, add `requires_agy`/`requires_gemini` markers in `extensions/taut_summon/pyproject.toml`, create zero-import `_providers.py`, make runtime imports lazy in `controller.py`, normalize non-numeric `summon_schema_version` in `_state.py`, and add `SummonRequest.provider_args` + `PtyAdapter.with_extra_args`.

### Slice 2 — Root `taut summon --status`, NDJSON Parity, Shared `syntax.py` Slot Protection & TUI Alignment
- Implement ordered option-value slot protection and `root.db_path` load-failure debug capture in `taut/commands/_dispatch.py` and `taut/commands/syntax.py` (with name-keyed prefix deduplication), exact-only `--db` `_get_option_tuples` in `extensions/taut_summon/taut_summon/cli.py`, shared NDJSON status rendering and registered-provider help in `extensions/taut_summon/taut_summon/commands/` and `cli.py`, and `provider_args` across `command_syntax.py` and `extensions/taut_tui/taut_tui/{screens,summon,app}.py`.

### Slice 3 — Non-Installing Controller Inspection, Local Pre-DB Validation, `y`/`yes`/Enter Confirmation, POSIX `TIOCGWINSZ` Resize Sync & Child `SIGHUP` Reset
- Inspect `list_live()`, `status()`, and `stop()` via `TautClient(..., install_schema=False)` (reusing `probe.target` + `probe.config` when opening a writable control client), validate local request inputs in `_driver.py` before opening storage and re-validate `provider_args` in `_bootstrap()` before `replace_legacy_provider()` / `claim_driver()`, accept `Enter`/`y`/`yes` in `ShellSummonInteraction.confirm_terminal_attach`, sync `TIOCGWINSZ` -> `TIOCSWINSZ` + `_TerminalState.resize` on `PosixPtyHandle.attach` entry and its 100 ms `select()` wake, and reset `SIGHUP` to `SIG_DFL` in `_CONTROLLING_TERMINAL_TRAMPOLINE`.

### Slice 4 — Wheel Matrix Smoke & Documentation Alignment
- Extend `bin/check-core-summon-wheel-matrix.py` paired control smoke with `taut summon --status --json` and `taut summon --status artifact-probe --json`, and align `docs/implementation/05-taut-summon-architecture.md`, `06-command-extensions.md`, `12-taut-tui.md`, `extensions/taut_summon/README.md`, and `README.md`.

## Verification and Gates

```bash
# 1. Plan, path, CLI-claim, coalescing, kernel sync & Ruff suppression gates
uv run python bin/check-plan-status-index && \
uv run python bin/check-doc-paths && \
uv run python bin/check-cli-claims && \
uv run python bin/check-dom15-fixtures && \
uv run python bin/coalesce-check && \
uv run python bin/ruff_suppression_index.py --check && \
cmp -s docs/agent-kernel.md taut/agent-kernel.md

# 2. Ruff lint, Ruff format check & Mypy across root, taut_summon, and taut_tui
uv run ruff check . && \
uv run ruff format --check taut tests bin extensions/taut_summon/taut_summon extensions/taut_summon/tests && \
uv run mypy taut tests bin/release.py bin/release-artifact.py bin/require-green-workflows.py --config-file pyproject.toml && \
uv run mypy extensions/taut_summon/taut_summon extensions/taut_summon/tests extensions/taut_summon/tests/conftest.py --config-file pyproject.toml && \
uv run --project extensions/taut_summon --extra dev mypy extensions/taut_summon/taut_summon extensions/taut_summon/tests --config-file extensions/taut_summon/pyproject.toml && \
uv run --project extensions/taut_tui --extra dev ruff check extensions/taut_tui/taut_tui extensions/taut_tui/tests && \
uv run --project extensions/taut_tui --extra dev mypy extensions/taut_tui/taut_tui extensions/taut_tui/tests --config-file extensions/taut_tui/pyproject.toml

# 3. Behavioral pytest suites (root, summon unit + isolated -n auto process concurrency, TUI, MCP, and live Docker PostgreSQL)
uv run pytest -q -m "not pg_only" && \
TAUT_SUMMON_LIVE_HARNESS=0 TAUT_SUMMON_LOCAL_LLM=0 uv run --project extensions/taut_summon --extra dev pytest extensions/taut_summon/tests -q -m "not xdist_group and not requires_live_harness and not requires_local_llm and not windows_only" && \
TAUT_SUMMON_LIVE_HARNESS=0 TAUT_SUMMON_LOCAL_LLM=0 uv run --project extensions/taut_summon --extra dev pytest extensions/taut_summon/tests -q -m "xdist_group and not requires_live_harness and not requires_local_llm and not windows_only" -n auto --dist load && \
uv run --directory extensions/taut_tui pytest -q -n 2 --dist loadfile && \
uv run --project extensions/taut_mcp --extra dev pytest extensions/taut_mcp/tests -q -m "not pg_only" && \
uv run ./bin/pytest-pg && \
uv run ./bin/pytest-pg extensions/taut_mcp/tests

# 4. Combined parallel coverage execution gate & Fresh-built release-wheel matrix
python_bin="$PWD/.venv/bin/python" && \
cov_dir="$(mktemp -d)" && \
trap 'rm -rf "$cov_dir" .coverage' EXIT && \
COVERAGE_PROCESS_START="$PWD/pyproject.toml" COVERAGE_FILE="$cov_dir/.coverage.root" "$python_bin" -m coverage run --parallel-mode -m pytest tests/test_cli.py tests/test_required_coverage_paths.py -q -n 0 && \
TAUT_SUMMON_LIVE_HARNESS=0 TAUT_SUMMON_LOCAL_LLM=0 COVERAGE_PROCESS_START="$PWD/pyproject.toml" COVERAGE_FILE="$cov_dir/.coverage.summon" "$python_bin" -m coverage run --parallel-mode -m pytest extensions/taut_summon/tests -q -m "not requires_live_harness and not requires_local_llm and not windows_only" -n 2 --dist load && \
COVERAGE_PROCESS_START="$PWD/pyproject.toml" COVERAGE_FILE="$cov_dir/.coverage.mcp" uv run --project extensions/taut_mcp --extra dev python -m coverage run --parallel-mode -m pytest extensions/taut_mcp/tests/test_process_reactor.py -q -m "not pg_only" -n 0 && \
"$python_bin" bin/combine-coverage.py "$cov_dir" --output .coverage && \
"$python_bin" bin/check-required-coverage-paths.py --data-file .coverage && \
"$python_bin" -m coverage report --include="*/taut_summon/_driver.py" --fail-under=1 && \
"$python_bin" -m coverage report --include="*/taut_summon/_control.py" --fail-under=1 && \
"$python_bin" -m coverage report --include="*/taut_summon/cli.py" --fail-under=1 && \
rm -rf "$cov_dir" .coverage && trap - EXIT && \
uv run pytest tests/test_core_summon_wheel_matrix.py -q && \
uv run python bin/build-and-check-release-wheels.py
```

## Independent Review Loop (`[DOM-5]`, `[DOM-11]`)

- **Author family**: Agy / Gemini (`Google DeepMind`).
- **Reviewer families**: Claude / Anthropic (`claude 2.1.293`) & Codex / OpenAI (`codex-cli 0.170.0`).
1. **Plan & Mid-Point Reviews**: Cross-family Tier-1 `codex` + `claude` reviews + owner theory-alignment pruning.
2. **Final Completed-Work Review (after all verification gates)**: Tier-1 `claude` review checking both correctness and `docs/program-theory.md` tautness across `git status --short`, tracked `git diff`, and untracked `_providers.py` / `test_providers.py` (excluding pre-existing `skills/call-agent/SKILL.md`) until `Verdict: PASS`.

## Out of Scope

- Mandatory background daemon or Taut-owned multiplexer launcher (`--tmux`; shell composition owns process wrapping per `[THEORY-5.A4]`, `[SUM-1]`, `[SUM-2]`).
- Provider-specific wire-protocol adapters, permission presets (`--preset`), or in-band executable/auth inspection (`[SUM-1]`, `[SUM-7.1]`, `[THEORY-5.A6]`).
- Separate-distribution packaging polish (`taut-chat` console alias, `taut-chat[default]` extra, absent-extension hints for `tui`/`mcp`), 2-arg `taut reply`, TUI Day-1 UX polish, and `F8` plan-index harvest hygiene — scheduled next in Phase 3 (Plan 5).

## Execution Log

- `2026-11-24`: Authored initial Class 5+P plan (`Author family: Agy / Gemini`); ran Tier-1 `codex` Rounds 1–17 and Tier-1 `claude` (`claude-opus-5-5[1m]`, CLI `2.1.293`) Theory & Anti-Overengineering Plan Review (`PASS` Round 2).
- `2026-11-24`: Completed Slice 0 spec promotion and Slices 1–2 RED -> GREEN + Tier-1 `claude` Mid-Point Scoped Review Rounds 1–2 (`F1` `OptionSyntax` prefix-match deduplication by `option.name`, `F2` zero-diff `_protocol.py`, `F3` removed `get_session` global in `controller.py`, `N1` `test_architecture_boundaries.py` sink inventory).
- `2026-11-25` (**Owner Theory Re-Alignment — "Tautness" Pruning**): Owner paused on `--tmux` and directed re-reading `docs/program-theory.md` to restore strict tautness. With explicit owner approval (`"Yes, make those adjustments"`), pruned four non-taut items across the plan, promoted specs, and implementation:
  1. Dropped `--tmux` (`_tmux.py`, `_tmux_child.py`, Gate 3b Docker `tmux`): shell composition (`tmux new -s claude -- taut summon claude`) owns multiplexer hosting outside Taut (`[SUM-1]`, `[SUM-2]`, `[THEORY-5.A4]`).
  2. Dropped `ProviderInfo` / `ProviderReadiness` / PE `.cmd` scanner / `auth_hint` / `--list-providers` / `taut-summon providers`: OS `exec` / `CreateProcessW` owns executable resolution (`[THEORY-5.A6]`), and `--help` surfaces `PROVIDER_NAMES` directly.
  3. Dropped `claude`-only `--preset {default,taut-allow}` across `SummonRequest`, CLI, `syntax.py`, and TUI `SummonStartScreen`, keeping vendor-neutral repeatable `--provider-arg ARG` (`[SUM-1]`) and documenting the `claude` `--allowedTools` flag in `README.md` and `extensions/taut_summon/README.md`.
  4. Dropped duplicate DB `_preflight_before_schema()` in `_driver.py`, validating pure local request inputs before DB open, re-validating `provider_args` in `_bootstrap()` before claim, and using non-installing `TautClient(..., install_schema=False)` strictly in passive `SummonController.list_live()`, `status()`, and `stop()`.
- `2026-11-25` (**Slices 3–4, Full Verification Gates & Final Tier-1 Claude Review**):
  - Implemented Slice 3 (passive `TautClient(..., install_schema=False)` inspection in `controller.py`, pre-DB `_validate_local_request()` + `_bootstrap()` `validate_provider_args` + `PtyAdapter.with_extra_args` in `_driver.py`, `Enter`/`y`/`yes` in `interaction.py`, `_TerminalState.resize` + attach cursor tracking + `PosixPtyHandle.attach` `TIOCGWINSZ` -> `TIOCSWINSZ` sync, and child trampoline `SIGHUP` `SIG_DFL` reset) and Slice 4 (`bin/check-core-summon-wheel-matrix.py` `--status [--json]` smoke + docs alignment).
  - Passed all 4 verification gate suites: doc/plan/CLI/coalescing/Ruff-suppression/kernel gates, Ruff + Mypy across root/`taut_summon`/`taut_tui`, full behavioral pytest suites (root, `taut_summon` unit + `-n auto` process lane, `taut_tui`, `taut_mcp`, and live Docker PostgreSQL 18 `./bin/pytest-pg` + `taut_mcp`), and combined parallel coverage + freshly built release-wheel matrix (`bin/build-and-check-release-wheels.py`).
  - Ran Final Tier-1 `claude` Completed-Work & Program-Theory Review (`claude-opus-5-5[1m]`, CLI `2.1.293`, `32` `Read` calls, `0` denials): **`Verdict: PASS`** on both correctness and `docs/program-theory.md` tautness. Applied all 10 non-blocking test/slack-trimming suggestions (`F1` initialized `other_db` + direct `_extract_post_globals` unit test; `F2` reduced `_providers.py` to pure `PROVIDER_NAMES`, derived `_adapter._FACTORIES` from `PROVIDER_NAMES`, and moved `validate_provider_args` into `_adapter.py`; `F3` removed duplicate pre-`run_driver` validation in `controller.py`; `F4`/`F5` trimmed redundant validation and unreachable fallback in `_driver.py`; `F6` factored `_parse_summon_schema_version` and narrowed `validate_summon_schema` catch to `DatabaseError` in `_state.py`; `F7` clarified `y`/`yes` in `interaction.py` prompt; `F8` aligned `[SUM-7.2]` wording on `scripted` `--provider-arg` rejection before session-row claim or mutation; `F9` shared `emit_status_inspection` across `commands/summon.py` and `cli.py`; `F10` dropped redundant empty-string guard in `taut_tui/screens.py:_parse_provider_args`) and re-verified locally.
