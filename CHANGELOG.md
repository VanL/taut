# Changelog

## Unreleased

- Identity resolution is harder to fool and easier to recover. Infrastructure
  classification now consults every classification basename, so a Linux
  daemon that rewrites its argv[0] (`sshd: user@pts/0`, `tmux: server (...)`)
  is still infrastructure rather than an "agent" named `0`. `time`, `nice`,
  `caffeinate`, `stdbuf`, `watch`, and `hyperfine` are recognized wrappers, so
  a first contact under one of them anchors on the real caller instead of
  the wrapper's ephemeral pid. The `unrecognized caller` diagnostic now lists
  members with matching evidence, names `taut rejoin NAME` for the best
  match, and always names `--as NAME` and `TAUT_TOKEN`; first contact prints
  the same reclaim line after its candidate list. `UnrecognizedCallerError`
  is a public `IdentityError` subtype carrying those hints, and the CLI maps
  the type, not the message text, to exit 2 and renders each hint as its own
  line. The macOS start-time token is read with `LC_ALL=C`, so processes
  running under different locales agree about one start time.

- The MCP `tools/list` manifest no longer carries `outputSchema` (about
  80 KB down to about 33 KB serialized); the result contract is proven by
  tests against real results instead. Tool annotations now follow MCP's
  meaning: `readOnlyHint=true` for `list`, `who`, `whoami`, `log`, `search`,
  `channel_show`, and `list_workspaces`; `destructiveHint=true` only for
  `message_delete` and `leave`; every other tool sets it false explicitly.

- Summon's `claude-stream` adapter no longer treats a Claude Code event
  family it does not know as harness death. Unknown top-level event types,
  unknown `system` subtypes, and unknown assistant content blocks are logged
  once per shape at warning level and skipped; `init` or `result` without a
  session id, an assistant event without a content list, and malformed JSON
  still raise `AdapterError`.

- Core schema startup is now a read in the steady state. `ensure_schema`
  reads the stored version and load-guard rows in one ordinary session and
  returns, refuses the guard, or raises the version error from that read;
  only an absent metadata table or version row enters the installing
  transaction and its `taut:schema` advisory lock. Every CLI command
  constructs a client, so ordinary commands no longer wait behind a writer
  holding SQLite's write lock or a Postgres initializer holding the schema
  lock. Fresh installation and load-guard refusal are unchanged.

- The CLI command context now constructs its one-command `TautClient` with
  `persistent=True`, so state and queue calls within a command share one
  broker session instead of bootstrapping a fresh SQLite connection per call.
  The search invalidation enqueue on `say`, `reply`, `delete`, and channel
  rename now uses the client's own queue handle as well, so a persistent
  client releases nothing per write and an ephemeral one still closes its
  one-shot handle. Measured `taut say` drops from 12 connections to 1 and
  from about 12 ms to 3 ms of client work. The dispatcher's existing
  `finally` still closes the client, so no handle outlives the command.

## 0.9.6 - 2026-09-01

- Kept TUI search-result jumps anchored to the exact selected message when a
  live delivery or navigation refresh lands during deferred viewport restore.
  Intent-owned, generation-checked restores now re-establish the physical
  viewport after intervening renders before normal scroll capture resumes.
  CI identity coverage also uses a fixed valid generated member id instead of
  probabilistically rejecting random ids that happen to contain a display-name
  fragment.

- Made pre-readiness PTY exit diagnostics deterministic: a terminal provider
  outcome now reports the specified foreground-readiness abort even when PTY
  closure reaches the supervisor just before pump completion. Control failures
  and explicit shutdown still take precedence, and post-readiness orientation
  failures keep their existing diagnostics. Release tests now fence real child
  lifetime, protocol stage entry, search completion, and platform branches by
  events instead of startup or scheduler timing. The Windows Job Object proof
  also consumes an explicit descendant-ready provider event before inspecting
  the exact direct child, avoiding filesystem sharing races. Every isolated Summon lane
  now runs with `-n auto --dist load`, so host-width concurrency pressure can
  expose resource-ownership defects instead of being hidden by fixed worker
  caps.

- Summon now retires each provider's owned process domain, not only its direct
  child. POSIX adapters keep the session leader unreaped through bounded
  process-group TERM/KILL escalation; Windows stream adapters assign the
  provider to a kill-on-close Job Object before it executes and require zero
  active job processes at finalization. Leader-first exit and inherited stdout
  no longer orphan same-domain descendants or hold the event pump open.
  Background work intended to survive `dismiss` must use an explicit external
  lifetime; accidental same-domain orphaning is no longer persistence behavior.

- Raised the runtime floor to SimpleBroker 8.0.0 and SimpleBroker-PG 4.0.0.
  The coordinated releases preserve Taut's resolved configuration snapshot,
  watcher lifecycle, error propagation, and closeable-iterator cleanup while
  making ascending public message id the default retrieval order. SQL targets
  migrate from schema 5 to schema 6 and require a backed-up downtime cutover;
  v7 and v8 clients must not share a migrated target. Existing Taut oldest
  selection remains oldest by public id. The new precise queue and
  closeable-iterator overloads replace obsolete local type assumptions.

## 0.9.5 - 2026-08-19

- Summon setup recovery is now surfaced as an explicit TUI workflow: when an interactive setup flow exits without a confirmed terminal prompt, users can resume with a bounded attach/recovery path before the flow is auto-classified as detached. This keeps orientation and trust checks visible and avoids silent loss of user intent in terminal-facing providers.

- The Summon give-up path now strips complete-screen escape sequences from the captured tail before showing the bounded recovery message, improving readability while preserving the underlying diagnostic data.

- TUI summon confirmation handling was cleaned up to avoid stale modal races around resolved screens while preserving robust callback ownership and exact state transitions.

- Release tooling and test evidence were updated to ensure the setup-recovery path, ruff-policy tracking, and associated docs/plan records remain in the release ledger.

## 0.9.4 - 2026-08-19

- Added setup-gate recovery for terminal-based Summon providers. A provider
  that settles without presenting a confirmed input prompt can offer one
  acknowledged shell attach before orientation is injected into an unknown
  trust, login, or model-selection screen. Declining keeps the detached flow;
  repeated-exit errors now include a bounded, control-stripped screen tail and
  the exact `taut summon --attach <name>` recovery command. The TUI remains
  non-owning for mid-run terminal setup and surfaces the enriched diagnostic.

- Made MCP resource integration deadlock caps account for Windows process and
  filesystem overhead without changing any event-based behavior deadline,
  pacing assertion, workload, or result assertion. Five 15-second containment
  caps become 45 seconds on Windows and the 60-second bulk cap becomes 180;
  other platforms remain unchanged.

## 0.9.3 - 2026-08-18

- Rebuilt the TUI's two command surfaces per the revised [TUI-7.1]. The `:`
  command line is now a vi-like bottom bar: it owns focus without dimming or
  blocking the live conversation view, completes inline with a ghost shadow
  (Up/Down cycle matches, Tab accepts), and no longer shows a completion
  list. The action browser (Ctrl-P / "Actions") opens with the first enabled
  row highlighted, Up/Down work from the query field, Enter runs exactly the
  highlighted action, a no-match query shows an explicit empty state, and a
  query starting with a known command root offers a "Run as command" handoff
  into the command line. Programmatic draft restores no longer spuriously
  reopen the command line, and keystrokes racing a composer promotion are
  reconciled into the command field instead of surviving as a hidden draft.

- TUI transcript message bodies now decode a closed escape allowlist toward
  sender intent: literal `\n`, `\t`, and the other terminal-escape-policy
  forms (`\xNN`, `\uNNNN`, `\UNNNNNNNN`, lowercase hex) render as the
  characters they denote, with decoded controls other than LF/TAB immediately
  re-escaped by the unchanged display policy. The stored record, CLI output,
  search previews, and metadata keep exact bytes. The summoned-member
  briefing now explains that a quoted `\n` is not a newline and names stdin
  as the multiline path.

- Added `Shift-Enter` as a newline insertion key in the TUI composer,
  matching the common chat-composer convention alongside `Ctrl-Enter` and the
  portable `Ctrl-J`. Like `Ctrl-Enter`, it requires a terminal that reports
  modified Enter distinctly.

- Hardened TUI Summon ownership and exit behavior. Terminal-lease failures now
  leave through normal teardown instead of resuming outside application mode;
  pending owned runs can be cancelled during quit; stale attach confirmations
  dismiss cleanly; and UI-loop shutdown no longer blocks on a worker that is
  waiting to marshal back onto that same loop.

- Preserved TUI transcript and composer state across live re-renders,
  navigation, resizing, and modal transitions. Selected messages no longer
  change merely because scroll position is restored; scrolled-up transcripts
  retain their anchor; the terminal-size shield cannot remain stranded under
  another modal; recoverable native-form errors leave the form usable; and a
  draft written before selecting a conversation carries into the first opened
  conversation.

- Made TUI async result handling more exact. Overlapping dump requests render
  recoverable attached errors, empty read/inbox/log/DM-list results take the
  existing "No results" path, superseded conversation snapshots cannot flash
  stale state, unrelated thread sends do not reset the open composer, and
  reply-thread unread state advances only after the requested open is accepted.

## 0.9.2 - 2026-08-17

- Kept TUI `:` entry text-owned with passive completions, added guarded `:q`
  and `:quit` aliases, and made Ctrl-C/Ctrl-D guarded quit chords from every
  Textual-owned mode or modal. PageDown remains paging after Ctrl-D moved to
  quit.
- Added multiline TUI message composition. `Ctrl-Enter` or `Ctrl-J` inserts a
  newline, `Ctrl-Tab` inserts a literal tab, and Enter sends the exact composed
  text. Transcript rendering now preserves meaningful whitespace and renders
  tabs at stable four-column stops.
- Made leading-colon TUI command entry argument-ready. Exact known root
  commands move into the editable command line, completion inserts the command
  with its argument separator through keyboard selection or one click, and
  unknown leading-colon text remains an ordinary chat message.
- Clarified Summon's first provider attach with an explicit acknowledgement,
  detach instructions, and foreground/chat-terminal handoff. The TUI uses its
  native confirmation boundary before leasing the terminal and restores the
  interface after detach while the summoned run continues.
- Fixed cancellation of Summon's shell acknowledgement on Windows console and
  pipe input. Cancellation now owns one exact synchronous reader, preserves
  complete-line decisions, and reaps the reader before provider spawn without
  applying socket-only `select()` to ordinary input handles.

## 0.9.1 - 2026-08-17

- Added opt-in, workspace-scoped failure capture through
  `taut system debug enable` and `taut system debug disable`. Captures preserve
  bounded traceback, frame-local, runtime, and operation evidence in the
  inspectable `taut.debug` broker queue, or send the same JSON to
  `TAUT_DEBUG_ACTION` over stdin. Capture remains disabled by default and
  best-effort so it cannot replace the original failure or exit behavior.
- Added a textual TUI command mirror: `:` now accepts the supported Taut
  command grammar without spawning the CLI, dispatches supported commands
  through native typed handlers, and discovers the first-party Summon syntax
  provider. The grouped command browser remains available, unsupported paths
  report inline, and terminal-owning Summon commands retain the existing lease
  boundary.
- Made declared TUI action-input requirements authoritative across palette,
  mouse, keyboard, and programmatic dispatch. Disabled reasons now follow the
  declared requirement order, stale dispatch cannot bypass applicability, and
  command-palette dismissal is single-flight.
- Renamed the public command execution-context identity-selector field from
  `auth_token` to `continuity_token`, matching its non-authentication role.
  The CLI `--token` spelling is unchanged; no Python compatibility alias is
  retained.
- Reduced MCP integration-test setup churn by bounding seed clients under
  persistent public lifecycles while keeping external observers independent
  and every product assertion unchanged. Hosted Windows maximum duration for
  the affected tools case fell from 12.781 seconds to 2.331 seconds, with the
  same logical database work. High-volume resource fixtures now use the same
  bounded seed ownership instead of rebuilding a runner for every pointer.
- Fixed watcher probe cleanup so only tests whose success requires forced
  termination opt out of automatic subprocess coverage. Normally exiting
  malformed children are reaped gracefully and retain populated coverage;
  zero-byte shards remain fatal to aggregation.
- Made each independent GitHub release finalizer perform its own bounded exact
  PyPI convergence check before immutable publication, preserving immediate
  failure for malformed state, unexpected files, or digest mismatches. Release
  settings preflights now also retry only bounded GitHub 502/503/504 responses
  while keeping every policy and authentication mismatch fatal.
- Made real CLI subprocess tests separate interpreter/import readiness from the
  unchanged command deadline, with bounded descendant-tree cleanup and an
  out-of-band traceback for genuine post-readiness stalls. Debug-action tests
  now decode the UTF-8 stdin protocol independently of the Windows locale.
- Made the real TUI viewport-reflow test await the exact anchor restoration
  caused by resize, rather than treating one generic event-loop turn as proof
  that nested Textual refresh callbacks had completed.

## 0.9.0 - 2026-08-14

- Isolated Taut's complete SimpleBroker configuration under mechanical
  `TAUT_*` spellings. Ambient `BROKER_*` values no longer affect Taut, while
  immutable resolved config survives repeated lower-layer resolution. Most of
  the newly named defaults mirror SimpleBroker solely to close the namespace.
- Changed workspace dump from quiescence-and-movement refusal to a live,
  H-bounded logical projection. Active writes no longer invalidate export;
  broker messages and copied membership cursors are bounded by SimpleBroker's
  sampled high-water, while atomic owner-only publication and full-file
  preflight remain enforced.
- Raised the runtime floor to SimpleBroker 7.3.2 and SimpleBroker-PG 3.8.0.
  Load restores the broker watermark and rejects excessive future skew through
  public `TAUT_LOAD_MAX_FUTURE_SKEW_SECONDS` (default 300), translated to the
  broker config. Taut exposes no force bypass.
- Added the separate `taut-tui` human-first extension, available through the
  `taut-chat[tui]` convenience extra and the complete `taut-chat[all]` bundle,
  and its explicit `taut tui`
  launch. It reflects public core and Summon capabilities through native
  actions and forms, active-only live reads, vi-like plus conventional and
  mouse input, cursor-neutral search anchoring, responsive reflow, actor-free
  doctor/dump work, CLI-only load guidance, and supervised exact-run Summon
  terminal handoff.
- Added public cursor-neutral `TautClient.history_around()` and public
  `WatcherRejected` handler control so rich hosts can anchor exact search
  results and reject chat shutdown deliveries without advancing the chat
  cursor or importing broker control internals. Notification pointers remain
  consumable and have already been claimed before handler delivery.
- Added Summon's optional exact-once foreground readiness callback and immutable
  exact-run stop handle for rich hosts. Callback-free CLI behavior retains its
  existing lifecycle and signal ownership.
- Fixed identity rejoin so an existing member preserves its unread cursor, and
  made explicit invalid workspace directories and missing PostgreSQL support
  fail with Taut-owned initialization and installation guidance across client,
  doctor, dump, and load paths.
- Hardened MCP lifecycle ownership: degraded reactors now wait instead of
  spinning, shutdown closes new-work admission, abandoned attach failures are
  retrieved, and the public teaching contract is asserted field by field. The
  coordinated release gate now includes live MCP PostgreSQL conformance.
- Hardened Summon cancellation and teardown across blocked stream writes,
  control-loop cleanup, PTY settling, Claude startup, detached text injection,
  and final process-exit confirmation while keeping the original failure as
  the primary diagnostic.
- Tightened TUI behavior and lifecycle handling for native forms, empty
  results, help and inspector state, watcher failures, stale intents, pointer
  routing, executor teardown, and reply-surface preservation after deletion.
  Terminal control escaping is enforced at every display and toast sink, and
  the action registry's declared routes are now authoritative and exhaustively
  exercised through their real producers and handlers.
- Made the retained-lock TUI OS/Python matrix an independent canonical
  workflow. Coordinated releases now require its exact-commit success before
  any tag is created, while the root workflow remains the sole producer of all
  five release artifact bundles.

## 0.8.7 - 2026-08-12

- Added the complete `taut-chat[all]` extension bundle and the protocol-clean
  `taut mcp` main extension path. Standalone extension executables remain
  supported conveniences, while command-bearing extensions are also reachable
  through the primary `taut` executable.

## 0.8.6 - 2026-08-11

- Raised the supported dependency floors to SimpleBroker 7.1.0 and
  SimpleBroker-PG 3.6.0, and refreshed retained development dependencies.

## 0.8.5 - 2026-08-11

- Raised the core dependency floor to SimpleBroker 7.0.0 and the PostgreSQL
  development/runtime floor to SimpleBroker-PG 3.5.2. Public JSON now renders
  message IDs and nanosecond timestamps as exact decimal strings while Python
  and storage keep integer values, preventing silent rounding in JavaScript
  clients.
- Added actor-free `taut system doctor` and `TautClient.doctor()`. Six fixed,
  read-only checks report core schema, load guards, logical core state, broker
  counts, durable extension compatibility, and search-work depth. Complete
  findings use exit 2; access or framework failure remains exit 1 without a
  partial report. Doctor does not repair state, claim work, load a search
  provider, or certify quiescence, and shares one portable SQLite/PostgreSQL
  implementation with credential-safe target labels.

- Added exact stable `dm.d_*` targets to `TautClient.say`, the CLI, and MCP so
  handles returned by DM list/history records can write back to that same
  existing conversation. Person-addressed `@name-or-alias` remains the sole DM
  creator; stable send fully validates actor access, creates or repairs no
  state on a miss, emits no `dm_started`, and retains the ordinary two-person
  mention audience.
- Added actor-free `taut system dump` and `taut system load` maintenance
  commands plus matching `TautClient` class methods. The portable logical
  format reuses SimpleBroker's exact-id message stream, includes core sidecar
  authority and durable Summon sessions, and excludes search indexes, work
  queues, aliases, claimed rows, and live process leases.
- Loads accept only fresh targets, validate the full file before target writes,
  and use a fail-closed guard across sidecar and broker commits. SQLite and
  PostgreSQL share the format and support both-direction restore without a new
  PostgreSQL server extension; maintenance requires operator quiescence and a
  failed guarded target must be recreated.
- Added cursor-neutral full-text search across visible channel and direct-message
  history through the Python client and `taut search`. Search supports stable
  JSON facets, channel and DM scope, author, kind, time, and result-limit
  filters, plus an explicit disposable-index rebuild.
- Kept message writes independent of indexing through durable internal
  SimpleBroker work queues, atomic move-based claims, 60-second stale-claim
  recovery, revision fencing, and source-history reconciliation. Core uses
  SQLite FTS5; `taut-pg` uses PostgreSQL's built-in text search and GIN without
  requiring an optional server extension. Both backends share the public API
  and safety contract while retaining backend-native lexical behavior.
- Added the explicit MCP `search` tool, bringing the fixed surface to 21 tools
  and 18 CLI-shaped operations. It delegates one core search call, preserves
  string message IDs and backend-native lexical behavior, returns empty search
  as typed success, keeps authoritative state neutral, and reports sanitized
  provider failures plus operation-local notification/search warnings.
- Extended `bin/pytest-pg` to route explicit MCP PostgreSQL tests with both
  extension dependency overlays, so the MCP adapter is exercised against real
  PostgreSQL and compared with direct `TautClient.search()` results.
- Reworked the public documentation into explicit product-contract, agent
  recipe, specification, and implementation layers, with a product-section
  registry and program theory naming the owner of each promise.
- Strengthened test evidence across core and every extension by replacing
  count-only, mirrored, timing-sensitive, and private-state assertions with
  behavioral proofs. Added a shared eventual-evidence helper, deterministic
  PTY/pipe and xdist watchdog oracles, and required coverage-path checks; also
  reduced PostgreSQL pagination setup transactions without reducing its paging
  assertions.
- Made the MCP native-activity pacing proof independent of event-loop
  scheduling delays while retaining a deterministic fake-clock assertion for
  the production 0.5-second coalescing boundary.
- Replaced four redundant full Windows source-suite runs with a deterministic
  four-version partition whose executable oracle proves exact coverage and
  preserves xdist groups. Release preparation now waits for exact-commit root,
  PostgreSQL, and MCP producer CI before touching tags, and every coordinated
  PyPI gate uses a Core Metadata 2.5-capable trusted publisher.

## 0.8.2 - 2026-08-05

- Reconstruct a clean verified distribution directory after PyPI upload before
  the exact remote postflight, isolating release bytes from attestation
  sidecars created by the trusted-publishing action.
- Run MCP release tests against ephemeral editable overlays of the prepared
  core and MCP trees, so package metadata cannot come from a stale persistent
  virtual environment while prechecks remain non-mutating.

## 0.8.1 - 2026-07-31

- Raised the supported dependency floors to SimpleBroker 6.0.0 and
  SimpleBroker-PG 3.5.0. Taut does not call the keyword-only
  `simplebroker.commands` surfaces changed in 6.0.0, and its existing advanced
  imports already use the public `simplebroker.ext` facade.
- Changed the public core distribution name from `taut` to `taut-chat` while
  preserving the Taut product name, `taut` import package, `taut` console
  command, existing extension distribution names, and all four release-tag
  families. Current `taut-pg`, `taut-summon`, and `taut-mcp` metadata now
  depends on `taut-chat`.
- Added exact-artifact PyPI Trusted Publishing to the four tag gates. A gate
  stages the canonical Test workflow's wheel and sdist as a draft GitHub
  Release, verifies matching or safely completable PyPI state by filename and
  SHA-256 digest, publishes through the package's top-level workflow identity,
  and makes the GitHub Release public and immutable only after PyPI is
  complete.
- Made the distribution rename an explicit migration boundary. Environments
  must remove the old GitHub-installed `taut` distribution before installing
  `taut-chat`; historical extension wheels requiring `taut` are not presented
  as resolver-compatible.
- Removed the obsolete core-to-legacy-Summon CLI delegation branch. When
  current `taut-summon` entry points are absent, core now owns only the
  installation hint.
- Made release metadata reconciliation accept PyPI-only READMEs that contain
  no legacy versioned GitHub tag or wheel examples, while continuing to update
  every such example when one is present.
- Empty all four package `dist/` directories immediately before release builds
  so stale artifacts cannot be mistaken for the current coordinated release.
- Pin every release build's source and output directory explicitly, preventing
  an ambient parent uv workspace from redirecting root artifacts outside the
  repository, and disable workspace source resolution so builds cannot create
  a forbidden root lockfile.
- Make repository policy tests portable across Windows path and newline rules.
  Run pinned Ruff checks and all release prechecks without dependency syncing,
  so test workers and ambient parent workspaces cannot create a root lockfile.
- Split the reactor SIGINT subprocess proof into startup-readiness and behavior
  phases, keeping the strict deadlock watchdog while avoiding false failures
  when a Windows worker is slow to launch the child.
## 0.8.0 - 2026-07-28

- Migrated `taut-mcp` to one MCP SDK v2 server for legacy `2025-11-25` and
  modern sessionless `2026-07-28` clients. All identity-using tools now carry
  workspace plus continuity token and share one retained ensure lifecycle;
  explicit attach remains an eager optimization. Added modern
  `subscriptions/listen` delivery alongside independent legacy resource
  subscriptions while keeping the Claude channel legacy-only.
- Added top-level channel metadata show and topic set/clear behavior across
  the Python client, CLI, and MCP extension. The two explicit MCP tools bring
  its fixed manifest to 20 and preserve actor-free reads, membership-gated
  mutation, and cursor-neutral uncertain-outcome inspection.
- Added first-class navigation for existing direct-message conversations by
  current `@name-or-alias` or stable `dm.d_*` handle across Python, CLI,
  watcher, and MCP surfaces. Added the actor-scoped `list_direct_messages()`,
  `taut list --dms`, stable notification actions, and cursor-neutral DM
  history without changing the deterministic queue naming scheme.
- Added configured message reactions across the Python client, nested CLI,
  notification inbox/watcher paths, and MCP extension. Reactions advance the
  actor's seen cursor, then use SimpleBroker's atomic exact-name broadcast as
  a best-effort consumable pointer to the current non-actor audience.
- Added packaged `ack` and `blocked` reaction defaults with strict
  `.taut.toml` replacement, frozen client snapshots, duplicate-event semantics,
  and fail-closed DM audience intersection. Raised the SimpleBroker floors to
  5.6.1 for core and 3.3.1 for Taut-PG.
- Aligned the Taut reactor with SimpleBroker 5.6.1 terminal
  `StopWatching` control flow, preserving clean closed-sink and output-policy
  shutdown without advancing an undelivered chat cursor.
- Added exact-id `message show` and `message delete` operations across the
  Python client, CLI, and MCP extension. Show peeks and advances seen metadata;
  delete is limited to the acting author's ordinary messages and performs no
  cascade.

## 0.7.1 - 2026-07-15

- Added macOS and Windows SQLite MCP compatibility jobs at a representative
  Python version, reusing the full non-PostgreSQL suite without claiming live
  backend evidence or multiplying the supported-Python matrix.
- Made direct root and Summon unit coverage collection serial in the canonical
  coverage owner. This removes xdist scheduling from the two lanes whose raw
  artifact retained only one worker and caused the 0.7.0 aggregate to omit 378
  previously covered core and CLI statements.
- Corrected the MCP implementation record to reflect the published 0.7.0
  package and its exact-SHA Test, MCP, release-gate, and GitHub Release
  evidence.

## 0.7.0 - 2026-07-15

- Added the version-coordinated `taut-mcp` extension: a
  connection-scoped stdio server with 15 explicit workspace-scoped tools, one
  owner-thread client per attached workspace, a read-only aggregate
  notification resource, standard resource-update hints, and an opt-in fixed-
  cue Claude channel adapter.
- Added public `TautClient.peek_inbox()`, resolved broker-target/config handoff,
  and explicit ambient-identity inheritance control for safe multi-workspace
  embedding without claiming notification pointers or selecting process-wide
  identity by accident.
- Added per-call `limit` paging to `TautClient.read()` and `read_unread()` with
  exact cursor advancement and a 1,000-message per-thread default.
- Added `taut-mcp` as the fourth GitHub-only release-helper target, including
  coordinated `all` metadata/lock preparation, the `taut_mcp/vX.Y.Z` tag
  family, and an MCP tag observer that requires exact-commit root,
  PostgreSQL, and MCP workflow evidence. This configures the release path; it
  does not itself create a tag or GitHub Release.
- Made the canonical root Test workflow the sole `taut-mcp` release-byte
  owner. It builds and installs the exact core/MCP wheels together, smokes the
  `taut-mcp` console, and uploads an immutable attempt-qualified MCP bundle;
  the dedicated MCP workflow remains the real PostgreSQL and quality owner.
- Added a same-run non-PostgreSQL MCP coverage producer and required its named
  shard plus the unique connection-rate debit line in the existing aggregate
  report. The producer installs local `taut-pg` only for collection-time
  imports and does not claim live-backend evidence.

## 0.6.7 - 2026-07-14

- Made the PostgreSQL cross-table route-race proof scheduler-independent. The
  test now holds the first real advisory lock until both contenders reach the
  same lock-key boundary, proves that lock unavailable from an independent
  connection, then releases them together and still requires exactly one
  commit and one `IntegrityError`.

## 0.6.6 - 2026-07-14

- Filtered empty, built-in Unicode whitespace, and Unicode `Cf`-only `say` and
  `reply` input before routing or state work. The Python API raises public
  `BlankMessageError`; the CLI exits 2 without output; accepted text remains
  exact and existing stored blank or foreign messages remain readable.
- Made Summon terminal mode silently continue after that typed blank result
  while retaining error logs for every other core posting failure.
- Made existing explicit name/alias and continuity-token selectors bypass full
  process capture for ordinary operations without changing durable process
  claim ownership. Selector-free inference remains automatic, token activity
  still refreshes, and `rejoin` remains the explicit association operation.
- Raised the SimpleBroker floors to 5.3.3 for core and 3.2.2 for Taut-PG,
  picking up safe runner cleanup and initialized timestamp-conflict metrics.
- Raised the paired core, Taut-PG, and Summon metadata to 0.6.6 so first-party
  extensions cannot resolve against a core missing the new public exception.

## 0.6.5 - 2026-07-14

- Made Windows `taut init` reject control-bearing SQLite targets before broker
  queue and lock setup, with a fixed path-free diagnostic instead of a delayed
  filesystem failure.
- Made terminal-safety release coverage portable across Windows and POSIX by
  proving unsafe database-target rendering without requiring the filesystem to
  accept control bytes in a filename. Real CLI and storage coverage continues
  to use an explicit valid target, without relying on longer timeouts.

## 0.6.4 - 2026-07-14

- Added the public `taut.escape_terminal_text` display transform and packaged
  `taut/defaults.toml` policy. The default policy renders C0, DEL, and C1
  controls visibly while humans through `.taut.toml` and trusted callers
  through the public function can extend, replace, or disable it.
- Routed core and first-party Summon human text through the shared policy,
  including command diagnostics and non-interactive logs. Storage, Python
  models, NDJSON, and explicit raw PTY transport remain byte-for-byte exact.
- Reduced thread-list work by reusing the latest pending timestamp and skipping
  message scans when it proves that a membership has no unread messages.
- Expanded deterministic coverage for PostgreSQL watcher fallback, client
  membership and cursor state transitions, terminal-control rendering, and
  installed core/Summon wheel compatibility.
- Documented terminal escaping as a safe-default relay control within Taut's
  stated trust domain, not as an authentication or sandbox boundary, and raised
  the paired Summon core floor to 0.6.4.

## 0.6.3 - 2026-07-14

- Made every release target run one universal root, PostgreSQL, and Summon
  precheck sequence by default while retaining `--skip-checks` as an explicit
  human override.
- Forced release live-harness execution and strict prewired mode together, and
  made local Ollama preparation lifecycle-safe for every target.
- Required every package tag to observe both canonical exact-commit workflows
  without dispatching duplicate test matrices or rebuilding release artifacts.

## 0.6.2 - 2026-07-14

- Made signal and PTY integration failures deterministic and diagnostic without
  weakening the strict local-LLM smoke or production recovery behavior.
- Removed duplicate coverage, live-test, installed-wheel, packaging, and
  release-gate execution while preserving every supported Python and operating
  system boundary.
- Bound GitHub releases to canonical exact-commit workflow evidence, immutable
  attempt-qualified artifacts, verified package bytes, and the correct package
  tag family and version.

## 0.6.1 - 2026-07-13

- Fixed the Summon STOP/release race where an expected STOP-interrupted PTY
  orientation write was misclassified as a teardown failure. STOP now records
  teardown and ledger-release outcomes separately, preserving clean
  same-process stop and restart without lengthening the timeout.
- Made release metadata preparation deterministic and package-owned, including
  version and dependency-floor copies, README examples, the retained Summon
  lock, a checked local preparation commit, and fresh state checks before
  remote release actions.
- Raised the core SimpleBroker floor to 5.3.2; set both extension `taut` floors
  and the root Summon development floor to 0.6.1; reconciled the retained
  Summon lock.

## 0.6.0 - 2026-07-13

- Replaced the monolithic CLI switchboard with one versioned command-adapter
  interface for every top-level verb. Core commands register statically;
  separately installed packages register lightweight manifests through the
  `taut.commands` entry-point group.
- Added deterministic installed-command ownership, conflict diagnostics,
  command-local parser configuration, shared root-global policy, and lazy
  command factory loading. Root version/help and command help no longer
  initialize unrelated clients, storage, watchers, providers, PTYs, or driver
  subsystems.
- Made the public `taut` and `taut_summon` package facades lazy while retaining
  their typed import surfaces. Runtime failures now occur at the selected
  subsystem boundary with the original cause preserved.
- Added the typed `SummonController`, frozen request/result/status models, and
  host-interaction terminal lease interface. Rich hosts can compose Summon
  directly without parsing console output or importing private ledger,
  control, driver, or PTY modules.
- Moved `taut summon` and `taut dismiss` to native `taut-summon` entry-point
  adapters shared with the standalone console. Core retains a narrow 0.5.4
  compatibility/install-hint bridge for paired rollout; the 0.6.0 Summon wheel
  wins when installed.
- Expanded the fresh-wheel release gate to verify exact command entry points,
  native Summon lifecycle, the retained 0.5.0 reactor case, 0.5.4 legacy
  command compatibility, and rejection of Summon 0.6.0 with core 0.5.4.
- Made every release pytest precheck select the repository `dev` extra, so an
  activated environment with stale Summon metadata cannot replace the current
  0.6.0 command entry points during release validation.
- Coordinated `taut`, `taut-pg`, and `taut-summon` versions and first-party
  dependency floors at 0.6.0.

## 0.5.4 - 2026-07-12

- Updated names to have a default capitalization rule (humans and agents)
  while preserving --as or explicit names.

## 0.5.3 - 2026-07-11

- Adopted SimpleBroker 5.3.1's atomic `Queue.write()` return value for live
  message ids and closed sender cursor races with a bounded post-write probe.
- Serialized Postgres schema initialization and the cross-table name/alias
  namespace with transaction-scoped advisory locks; corrupt Taut-owned JSON
  now fails with table/field context instead of silently becoming empty state.
- Hardened watcher sink shutdown, Summon control/audit/PTY behavior, reply
  notifications, CLI help, release metadata, and maintained documentation
  checks from the 2026-07-11 multi-factor review.

## 0.5.2 - 2026-07-11

- Coordinated the GitHub-only publication of `taut`, `taut-pg`, and
  `taut-summon` from one tested commit after the extension 0.5.1 tags failed
  before creating GitHub Releases. Core 0.5.2 is runtime-code-equivalent to
  the successfully published core 0.5.1 package; the patch bump gives all
  three packages a fresh, immutable release namespace without rewriting old
  tags.
- Carries the 0.5.1 lifecycle and release-gate corrections across the paired
  core/Summon boundary: generation-safe shutdown, complete Windows process
  fakes, test-owned control cleanup, and the fresh installed-artifact canary.

## 0.5.1 - 2026-07-10

- Rebuilt the core watcher and Summon control owners around generation-fenced
  reactor lifecycles, owner-thread handle replacement, bounded shutdown, and
  fatal owned-thread supervision.
- Added deterministic SQLite/PTY process lanes, dynamic Postgres waiter
  replacement coverage, and a fresh installed-wheel compatibility matrix for
  the paired core/Summon release boundary.
- Removed Taut-owned broker retry policy in favor of the supported
  SimpleBroker ownership/retry contract and raised the paired dependency
  floors accordingly.

## 0.5.0 - 2026-07-08

- Added `taut summon` / `taut dismiss` as thin core delegation verbs that
  hand off to the new **`taut-summon`** extension when installed, or exit 1
  with a one-line install hint otherwise. The verbs carry no summon logic
  and add no core dependency.
- Added the `taut-summon` extension (separate package under
  `extensions/taut_summon/`) that hosts an existing agent harness as an
  ordinary workspace member — no daemon, no bespoke agent protocol. The
  summon driver injects chat into the harness's live session (its ears) and
  the agent speaks through the ordinary `taut` CLI selected by its
  continuity token (its mouth). Ships the `run`/`stop`/`status` verbs, the
  universal PTY adapter for interactive harnesses (`claude`, `codex`,
  `coder`, `grok`, `qwen`, `kimi`, `opencode`, `pi`), the `claude-stream`
  structured adapter, the `scripted` and fake-TUI test seams, a two-table
  session ledger with a single-driver guard and PTY `wired` flag, a
  weft-congruent `sys.*` control plane (STOP/STATUS/PING), a default persona
  template with a rate backstop, a portable, parameterized cross-provider
  conformance suite, local real-harness smoke tests, and a CI-safe
  local-LLM PTY smoke backed by Ollama. See `docs/specs/04-summon.md` and
  `docs/implementation/05-taut-summon-architecture.md`.
- Raised the SimpleBroker floor to 5.1.0. Taut's vendored Weft-style
  `MultiQueueWatcher` now supplies its fan-in activity waiter through
  SimpleBroker's watcher lifecycle hooks instead of cloning the watcher retry
  loop.
- Changed CLI usage errors (unknown flags, unknown subcommands, malformed
  arguments) to exit 1. Compatibility note: these previously exited with
  argparse's 2, colliding with the exit-2 "empty / nothing matched" class
  that shell polling loops key on.
- Added `--` end-of-options handling so option-like message text is
  sendable (`taut say general -- -q` posts the literal text `-q`).
- Made interrupted channel renames resumable: rerunning the same
  `taut rename OLD NEW` finishes the rename from its recovery marker, and
  other commands name that exact command while a rename is incomplete.
- Added anchor-match identity resolution ([IAN-3.3] step 4): an agent whose
  anchor process changed working directory or other mutable claim inputs
  still resolves to its existing member, and the resolver records the
  current claim so later commands resolve by claim hash again.
- Made concurrent first-contact joins retry auto-chosen names (bounded at
  five attempts), re-minting name, member id, and token on each attempt.
  Explicit `--as` names still fail loudly on collision.
- Scoped direct-message mentions to the DM participants; mentioning any
  other member in a DM no longer notifies them.
- Hardened error paths: `init` into an unwritable directory fails fast with
  a one-line diagnostic instead of stalling in lock retries; malformed
  `.taut.toml` diagnostics name the offending file; non-UTF-8 bytes piped
  to `say -` are reported as invalid stdin rather than a raw decode error.
- Fixed the vendored multi-queue watcher to close removed queues'
  connections instead of leaking them.
- Added a documentation reference gate (`tests/test_docs_references.py`)
  that fails the suite when docs cite nonexistent paths or unknown spec
  codes.
- Extended the GitHub-only release helper with SimpleBroker-style positional
  targets, a `summon` release target, `all` batch release planning, release-file
  tracking for the summon lockfile, local summon LLM gate preparation, and a
  `taut_summon/vX.Y.Z` release gate.

## 0.4.7 - 2026-07-06

- Closed the evaluation-review findings: consistent CLI usage exits and `--`
  handling, resumable channel renames, anchor-based identity recovery,
  bounded first-contact collision retries, DM mention scoping, and clean
  diagnostics for malformed config/stdin/database setup.
- Added adversarial CLI probes and the first documentation path/spec-code
  reference gate.

## 0.4.6 - 2026-07-06

- Moved multi-queue activity waiting onto SimpleBroker's public watcher hooks
  and added real watcher lifecycle and wake coverage.

## 0.4.5 - 2026-07-06

- Refreshed the development dependency set used by the release gates.

## 0.4.4 - 2026-07-03

- Updated the SimpleBroker dependency and strengthened spec-promotion,
  traceability, and independent-review guidance used by implementation plans.

## 0.4.3 - 2026-07-02

- Added adversarial acceptance/testing guidance, raised the SimpleBroker
  dependency, and required patch coverage above 50 percent.

## 0.4.2 - 2026-07-01

- Relaxed the Codecov project threshold while retaining patch-level coverage
  enforcement.

## 0.4.1 - 2026-07-01

- Added focused messaging/identity/dev-script coverage and made identity tests
  portable across checkout paths.

## 0.4.0 - 2026-07-01

- Added stable member identity, aliases, direct-message routing by current
  name, consumable mention/DM notifications, `inbox`, `set name`, `rejoin`,
  and channel rename support.
- Reworked `taut.client` into a package facade over concern-specific modules
  while keeping `from taut.client import TautClient, Message, ...` as the
  public import surface.
- Replaced the old `schema.py` helper layer with `taut.state` and a SQL dialect
  hook so sidecar ownership is explicit and tested across SQLite and Postgres.
- Changed `TautWatcher` to depend on a `TautWatchRuntime` protocol. The normal
  public API remains `TautClient.watch()`, and direct `TautWatcher(client, ...)`
  construction is deprecated.
- Updated Taut and `taut-pg` tests for the state adapter, public watcher
  surface, and Postgres-visible behavior. Both the core package and `taut-pg`
  are versioned `0.4.0` for this release.
- Cleaned project hygiene: `.envrc` is local-only, stale generated logo assets
  are out of workflow gates, and private test coupling was reduced where the
  public API gives the same proof.

## 0.3.0 - 2026-07-01

- Introduced the stable member-id, addressing, notification, SQL state-adapter,
  and watcher-runtime refactors later released together as the 0.4 public
  contract.
- Split the client facade into concern-specific modules, retired the schema
  compatibility shim, and refreshed Postgres state-adapter coverage and the
  repository documentation map.

## 0.2.1 - 2026-06-18

- Fixed Postgres project-config and shared backend conformance coverage.
- Documented `read` pagination and tightened bounded `log --limit` behavior.

## 0.2.0 - 2026-06-17

- Added the separate `taut-pg` extension package for Postgres-backed Taut
  projects through `.taut.toml`.
- Added `bin/pytest-pg` and typed shared/PG-only tests against real Docker
  Postgres.
- Relaxed core target resolution for SimpleBroker project-config targets while
  keeping `TAUT_DB`, `--db`, and `db_path=` as filesystem path selectors.
- Added GitHub-only release gates for `taut-pg` using the `taut_pg/vX.Y.Z` tag
  namespace.
- Updated sidecar DDL to use `BIGINT` for 64-bit timestamp/id portability.

## 0.1.1 - 2026-06-12

- Added `psutil` as a bounded runtime dependency for cross-platform process
  metadata capture, while preserving native start-time tokens where available.
- Fixed identity handle quality for fallback `ps args=` output with spaces in
  `argv[0]`.
- Updated human `read`, `log`, `watch`, and `list` rendering to match the
  README transcript shape, including grouped thread headings, local HH:MM
  display, `-t` id columns, and bounded unread counts.
- Completed the remaining [TAUT-11] proof obligations for concurrent writer
  processes, mid-watch joins, idle peek queues, and continuity-token acts-as.
- Added strict mypy coverage for the test suite (`mypy taut tests`).
- Added a GitHub-only `bin/release.py` helper for version sync, local release
  gates, and `vX.Y.Z` tag management while PyPI name clearance is pending.
- Added GitHub Actions test and release workflows that publish GitHub Releases
  without uploading to PyPI.

## 0.1.0 - 2026-06-12

- Added the taut v0.1 core package: config translation, schema, identity,
  envelope, client API, watcher, and CLI.
- Added contract tests for config, envelope tolerance, sidecar schema,
  cursor semantics, client messaging, CLI JSON/exit behavior, and watcher
  membership refresh.
- Added implementation documentation for the v0.1 architecture and release
  checklist context.
