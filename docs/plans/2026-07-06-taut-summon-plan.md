# Taut summon implementation plan

Date: 2026-07-06

Status: implemented (Phases A–E) — uncommitted pending the user's landing
review (see §15 Implementation Record and §16 Landing Note). Plan reviewed
in 14 adversarial rounds and per-phase implementation reviews (Codex; see
§12 Review log and §15).

Plan type: implementation with spec revision. The revision is dominated by a
**new spec file** (`docs/specs/04-summon.md`), drafted in full at
`docs/plans/2026-07-06-taut-summon-spec-draft.md` (the review target), plus
two small in-file deltas below.

## 1. Goal

Implement `taut summon` as designed in the 2026-07-06 discussion: the
extension package `taut-summon` hosts an existing agent harness as an
ordinary workspace member — the driver injects chat into the harness's live
session ("ears"), the agent speaks through the taut CLI with its continuity
token ("mouth"), no daemon, no bespoke agent protocol, provider-native
streaming adapters. Two design lenses govern every open decision and are
recorded in the spec draft's preamble: **L1** (works for agents — the
summoned one, its peers, and implementers) and **L2** (observable behavior a
human member would produce).

## 2. Source Documents

- `docs/plans/2026-07-06-taut-summon-spec-draft.md` — the proposed spec, in
  full ([SUM-1]–[SUM-12]). Reviewers read it as part of this plan.
- `docs/specs/02-taut-core.md` [TAUT-12.3] (shape decisions of 2026-06-12:
  extension packaging, no daemon, weft contract congruence, conformance
  suite), [TAUT-2], [TAUT-4.1], [TAUT-7.2], [TAUT-8.1], [TAUT-11]
- `docs/specs/03-identity-addressing-notifications.md` [IAN-2.1], [IAN-3.3],
  [IAN-6.1], [IAN-6.5], [IAN-7.4]
- Design record: this session's summon discussion (terminal framing;
  ears/mouth split; multi-thread requirement; streaming injection for
  mid-work interruption). The spec draft is the durable form.
- Weft reference: the **mirrored control contract** is the task
  control-queue surface in `../weft/weft/core/tasks/base.py`
  (`command`/`request_id` JSON bodies, STOP/STATUS/PING — [SUM-9]);
  `sessions.py` and `agent_session_protocol.py` are supervision-craft
  reference only (bounded-queue stdio capture, ready handshake,
  drain-then-terminate), not mirrored surface. Copy shapes, never code
  ([TAUT-12.3]).

## 3. Spec Baseline

- `d0fd368` plus the uncommitted, review-confirmed remediation work of
  2026-07-06 (see `2026-07-06-evaluation-findings-remediation-plan.md`
  Implementation Record). If that work lands before this plan starts,
  re-record the landed SHA here; if this plan starts first, its slices must
  not touch the files the remediation diff holds beyond the two named
  spec-delta insertion points.
- Status mechanism (same statement as the remediation plan): this repo uses
  prose spec text only; no machine spec-classification tooling exists.
  Promotion is a spec-file addition plus the repo's docs-reference gate
  (`tests/test_docs_references.py`), which must be taught the new `[SUM-x]`
  code family (S1 task).

## 4. Proposed Spec Delta

| Delta | Target | Strategy | Lands in |
|-------|--------|----------|----------|
| D1 | New file `docs/specs/04-summon.md` = the spec draft, `Status: Active` | New-file promotion; prose Status is the adoption mechanism | S1 |
| D2 | `docs/specs/02-taut-core.md` [TAUT-12.3] | B — atomic with S1 | S1 |
| D3 | `docs/specs/03-identity-addressing-notifications.md` [IAN-6.1] | B — atomic with S1 | S1 |
| D4 | `docs/specs/02-taut-core.md` [TAUT-8.1] verb table + exit-code notes | B — atomic with S2's core delegation code | S2 |

### D2 — [TAUT-12.3], replace the paragraph beginning "Host an agent as a
thread member" and the "Shape decided 2026-06-12" list's first bullet's
companion prose with:

> Host an existing agent harness as a thread member. Summon is the agent's
> terminal, not its runtime: the summon driver injects chat messages into
> the harness's own live session (its ears), and the agent speaks through
> the ordinary taut CLI, selected as its member by its continuity token
> — continuity, not authentication ([TAUT-5], [TAUT-9]) — (its mouth).
> There is no summon-defined agent protocol — adapters speak each
> provider's native streaming envelope. The full contract lives in
> `docs/specs/04-summon.md` ([SUM-1]–[SUM-12]); the 2026-06-12 shape
> decisions below stand, refined there: the "line-oriented IO bridged to a
> thread" sketch is superseded by the ears/mouth split, and the inbox queue
> role maps to the member's chat threads themselves.

(The remaining bullets — extension packaging, taut-native captive lane and
no-daemon, weft contract congruence with listed divergences, conformance
suite — stay, with the divergence list now living in [SUM-9].)

### D3 — [IAN-6.1], append one row/sentence to the queue-class enumeration:

> Queues under the reserved `sys` prefix are extension-internal control
> queues; their derivation and bodies are defined by the extension spec
> that owns them (summon: [SUM-9]). They are deliberately **not
> registered**: the registry requirement above applies to queues core
> lists and routes, and `sys.*` extension queues remain invisible broker
> queues to every core command — exactly the treatment unknown broker
> queues already get. Core never routes chat to `sys.*`; only the owning
> extension reads or writes them.

### D4 — [TAUT-8.1], two new verb-table rows plus one sentence

> | `summon PROVIDER_OR_NAME [THREAD ...]` | Delegates to the
> `taut-summon` extension when installed (spec 04); without it, exit 1
> with a one-line install hint. | per spec 04 |
> | `dismiss NAME` | Delegates likewise (summon `stop`). | per spec 04 |
>
> Delegation verbs carry no core logic and add no core dependency; their
> behavior contract lives entirely in the owning extension's spec.

## 5. Context and Key Files

Read before any slice; the current-structure notes matter more than the
paths.

- **Extension packaging template** — `extensions/taut_pg/`: own
  `pyproject.toml` (hatchling, `taut>=` floor, dev extras), `py.typed`,
  own `tests/` with own conftest, wired into the root gates by explicit
  path in the README dev commands. `taut_summon` mirrors this, adding a
  `[project.scripts] taut-summon = ...` console script (taut_pg has none —
  this is the first extension with a CLI; the root gate commands in
  README/CI must gain the new paths, S2).
- **Watch surface** — `taut/client/_watching.py`, `taut/_watch_runtime.py`,
  `TautClient.watch(handler)`: returns a watcher whose handler receives
  `Message | Notification` dataclasses (`taut/client/_models.py`); it
  already follows membership changes mid-run and claims the notification
  inbox. **Cursor contract, load-bearing for [SUM-5.4]:** `TautWatcher`
  advances a thread's cursor only after the user handler returns
  successfully (`taut/watcher.py` handler wrapper, ~line 619-642 region);
  a raising handler leaves the cursor for re-delivery ([TAUT-8.4]
  3-strikes applies). The driver writes no cursor code — its handler's
  return/raise IS the ledger. Comprehension questions: (a) which events
  does the handler receive for a thread joined *after* the watch started,
  and from what cursor? (Answer from `TautWatcher._refresh_memberships`
  and [TAUT-7.4].) (b) After three consecutive handler failures on one
  message, what does the watcher do, and what does that mean for a
  persistently-failing `inject()`? (Poison advance with a warning — the
  driver must treat adapter death as fatal-and-resume, not as a
  per-message error, or 3-strikes will skip chat.)
- **Identity/token** — the driver never calls state internals. Its seams
  are all public: `TautClient(identity_capture=..., token=..., as_name=...)`
  construction; `join` for first-contact creation (member kind comes from
  `capture.kind` — `taut/client/_identity.py` `_create_member` — which is
  why the driver must inject an agent capture anchored at the harness
  child rather than rely on ambient capture, which would classify the
  human's terminal); `rejoin` for re-anchoring on later summons (it
  performs the anchor update internally, [IAN-3.4]); `taut.identity`'s
  exported capture types (`IdentityCapture`, `ProcessInfo`,
  `capture_process`, `capture_host_identity`) to build the child capture
  — [SUM-4] blesses this module surface for extensions. Token minted at
  member creation, output-visible once — the ledger captures it at
  creation ([SUM-8]).
- **Sidecar tables** — `taut/state/_sql.py` `ensure_schema` pattern:
  `CREATE TABLE IF NOT EXISTS` inside `sidecar(transaction=True)`, qmark
  only, version key in `taut_meta`. The extension copies the pattern with
  its own `summon_schema_version` key and `taut_summon_*` names
  ([TAUT-3.3] reserves nothing beyond `taut_*` prefixing — verify the
  RESERVED_TABLE_NAMES rule in simplebroker's sidecar docs before naming).
- **Reserved queue namespace** — `taut/addressing.py`
  (`notification_queue_name` → `notify.{member_id}` is the naming shape
  control queues mirror; `RESERVED_QUEUE_PREFIXES` includes `sys`).
- **Reference docs gate** — `tests/test_docs_references.py` builds its
  valid spec-code set from the two existing spec files; S1 adds spec 04 and
  the `SUM` code family to that scan.
- **Claude Code streaming mode** — headless `--input-format stream-json` /
  `--output-format stream-json` with session resume. Treat exact flags and
  event shapes as implementation-time facts to verify against the installed
  CLI (`claude --help`, one manual probe) — the adapter interface
  ([SUM-7.1]) is the contract, not the flags.

## 6. Invariants and Constraints

- **Core changes are exactly three, all named:** spec deltas D2/D3, and
  the D4 delegation verbs (`summon`/`dismiss`) whose implementation is a
  find-spec-and-hand-off with zero summon logic and zero new
  dependencies. Any other core code change is a stop-and-re-plan gate
  (the watch/client surface is believed sufficient; discovering
  otherwise is plan-level news).
- **No daemon** ([TAUT-2], [SUM-2]): the driver is foreground; `stop` and
  `status` are clients, not services.
- **Peek invariant** ([TAUT-7.1]): the driver's chat reads are
  cursor-tracked peeks via the watch surface; only notification-inbox
  claims consume, as watch already does.
- **Mouth is CLI-only; driver never speaks as the member** ([SUM-6],
  [SUM-11]): no code path in the extension posts chat messages under the
  member's identity except terminal mode, which is single-thread by
  construction.
- **No summon wire protocol**: adapters translate provider-native streams
  into the closed `AdapterEvent` union; any "let's add a summon envelope"
  drift is a stop gate.
- **Anti-mocking floor** ([SUM-12]): broker/sidecar/CLI never mocked; the
  provider seam is the `scripted` adapter (real subprocess, real pipes).
- **Extension-owned state only**: `taut_summon_*` tables + the
  extension's own `taut_meta` version key + plain (unregistered) `sys.*`
  broker queues. The extension writes **no core registry rows** — D3
  declares control queues invisible to core, so no core state seam is
  needed. Core's schema gate must remain oblivious to the extension
  tables (verified by running the full core suite against a db that has
  summon tables and control queues — S3 test).
- **Weft congruence is contract, not code**: STOP/STATUS/PING verbs and
  queue roles per [SUM-9]; the three divergences stay listed with reasons;
  no weft imports, no vendored weft agent code.
- **JSON/exit-code contracts of core hold for `taut-summon`'s own CLI**:
  0 success, 1 error, 2 not-found/nothing (e.g. `status` with no live
  driver), usage errors exit 1 (mirror core's parser subclass pattern).

## 7. Deviation Log

| Spec ref | Planned behavior | Actual behavior | Rationale | Spec proposal |
|----------|------------------|-----------------|-----------|---------------|
| [SUM-4]/S3 | S3's named rename/status/stop/re-summon-by-name tests | Deferred to the slices that own those verbs (S6 driver bootstrap, S8 control plane) — S3 shipped helper-level ledger/guard tests only | The named flows exercise driver name→member resolution and the stop verb, neither of which exists in Phase B; testing them against helpers would be seam-faking | n/a — sequencing, tests land in S6/S8 |
| [SUM-8]/S3 | "Full core suite passes against a db bearing summon tables" | A representative full client flow (init/join/say/read/whoami) against a seeded db plus a core `schema_version` unchanged assertion | Running the entire core suite against a seeded db requires modifying core fixtures, which the frozen-core invariant forbids; the representative flow is the substitute proof | n/a — substitute proof recorded |
| [SUM-7.2]/S4 | Scenario file "a JSON list of steps" | A JSON object (`on_start`, `default_response`, per-message steps) | The object shape expresses stall/flood/resume scenarios the list shape could not without inventing step types; strictly more expressive, same real-subprocess seam | n/a — test-harness detail |
| [SUM-9]/S8 | (unplanned) control-queue read/write hardening | Two modules mirroring simplebroker's own layering: `_retry.py` **vendored verbatim from `simplebroker/_retry.py` 5.1.0** (its published copy-me generic engine, kept pristine) and `_broker_retry.py` holding the taut-summon policy (`is_transient_broker_error` + `broker_retry`) on top — exactly as `simplebroker/helpers.py` layers its lock/watcher policy over the same engine. Also fixed the agent's `from simplebroker._exceptions import` private reach → public `simplebroker.ext` | The added control thread raised WAL concurrency enough to expose a *false* `malformed`-page read (SQLITE_CORRUPT `DatabaseError`) a fresh reader sees mid-checkpoint. This class does **not** subclass `OperationalError`, so simplebroker's own watcher-retry predicate misses it too (reported upstream). taut's facades-only rule forbids importing `simplebroker._retry`, so the engine is vendored (`__version__` documents the vendored version for re-vendor). Root cause (per-tick connection churn) also fixed by holding thread-owned connections | n/a — infra hardening; upstream may later widen the watcher predicate |

## 8. Tasks

Red-green per slice; every slice ends with the extension gate block (§10)
green plus the core suite untouched-green.

### S1 — Spec promotion and reference-gate extension

- Copy the spec draft to `docs/specs/04-summon.md` (`Status: Active`),
  apply D2 to [TAUT-12.3] and D3 to [IAN-6.1] exactly as §4 states; add
  spec 04 to `docs/specs/00-specs-index.md` and the repo-map corpus table.
- Extend `tests/test_docs_references.py` in two ways: (a) the spec-code
  regex learns `[SUM-\d+(\.\d+)?]` resolving against spec 04's headings;
  (b) the **spec-code** scan sources gain `docs/specs/*.md` — precise
  scope of the gap: path scanning already covers specs
  (`_markdown_path_sources`, line ~68), it is only the spec-**code**
  resolution scan (line ~141 region) that omits them, so D2's `[SUM-*]`
  cites from spec 02 would be unchecked. Additionally: (c)
  `_python_sources()` (line ~77) gains `extensions/**/*.py` so `[SUM-*]`
  cites in extension code and tests are checked, and the path-claim
  prefix set gains `extensions/` so implementation docs can cite
  extension files as claims. Red first: land the scanner extension and
  the D2/D3 cites *before* creating spec 04 — the gate must fail on the
  dangling `[SUM-*]` codes; then promote spec 04 and go green.
- Backlink: spec 04 `## Related Plans` → this plan.
- Done: docs gate green; spec 04 is the governing contract for S2+.

### S2 — Extension scaffolding and core delegation verbs (promotes D4)

- `extensions/taut_summon/`: `pyproject.toml` (deps: `taut>=0.4.6` only;
  console script `taut-summon`; dev extras mirroring taut_pg), package
  `taut_summon/` with `py.typed`, `tests/` with own conftest. Backend
  posture stated in the conftest docstring: summon requires a SQL-sidecar
  backend ([SUM-8]); extension tests run on SQLite (PG parity of the
  ledger DDL rides the dialect pattern copied from core; a PG run of the
  extension suite is a follow-on, recorded in Out of Scope).
- Extension CLI: `run`/`stop`/`status` argparse with core's exit-1-usage
  parser pattern; `taut summon claude [THREAD ...]` semantics per
  [SUM-3]: name defaults from provider, default thread `general`,
  `--provider` for name≠provider; `run` errors cleanly ("no adapter
  named X") until S5.
- **Core delegation (D4, atomic here):** `summon` and `dismiss` rows in
  core's parser dispatching to `taut_summon.cli` when
  `importlib.util.find_spec("taut_summon")` finds it, else exit 1 with
  the install hint. Both integration points, not one: the argparse tree
  AND `_first_command()`'s command set (`taut/cli.py:~560` — global
  option hoisting has its own list; missing it breaks
  `taut --db X summon ...`). Red tests in core's `tests/test_cli.py`:
  presence path (extension importable in the dev env) round-trips argv
  including `taut summon claude --db PATH`, `--provider`, and `--`
  pass-through; absence path via a real subprocess whose env strips the
  extension from `PYTHONPATH`/site (no import mocking). D4 spec text
  lands in the same change.
- **Installability wiring (without this, find_spec never succeeds):**
  root `pyproject.toml` `[tool.uv.sources]` gains
  `taut-summon = { path = "./extensions/taut_summon", editable = true }`
  and the root dev extra (or workspace member list) includes it, exactly
  as `taut-pg` is wired today (`pyproject.toml:60`); CI's install step
  (`.github/workflows/test.yml:~90`, currently `-e ".[dev]"` only)
  gains the extension install. The extension's `taut>=` floor is set at
  release prep to the first core version shipping the delegation verbs
  and the blessed `taut.identity` surface — a placeholder `taut>=0.4.6`
  is wrong and must not survive to release (release-gate check).
- Wire root gates: README Development block gains the extension's
  ruff/mypy/pytest paths (the README's taut_pg lines are the example to
  extend), and CI (`.github/workflows/test.yml`) is extended
  **explicitly** — note the current workflow does not run taut_pg's
  ruff/mypy paths, so there is no CI precedent to mirror; add the
  summon install + test/lint/type steps deliberately rather than by
  imitation.
- Done: `uv build extensions/taut_summon` succeeds; `taut-summon status`
  exits 2 with "nothing summoned"; `taut summon` without the extension
  exits 1 with the hint; gates green.

### S3 — Session ledger and single-driver guard ([SUM-8])

- `taut_summon/_state.py`, the [SUM-8] two-table shape (split by
  lifetime; no NULL-key gymnastics on any backend):
  - `taut_summon_claims` (transient): `name TEXT`, `provider TEXT`,
    `PRIMARY KEY (name, provider)`, `driver_pid BIGINT NOT NULL`,
    `driver_start_time TEXT NOT NULL`, `claimed_ts BIGINT NOT NULL`.
    Insert conflict = concurrent-summon serialization; rows are deleted
    at bootstrap step 3; dead-driver rows reclaimable by evidence.
  - `taut_summon_sessions` (durable): `member_id TEXT PRIMARY KEY`
    (row created only after the member exists), `token TEXT NOT NULL`,
    `provider TEXT NOT NULL`, `provider_session_id TEXT NULL`,
    `driver_pid BIGINT NULL`, `driver_start_time TEXT NULL`,
    `updated_ts BIGINT NOT NULL`.
  Plus `ensure_summon_schema`, claim/release-claim/record-session/
  get-by-member-id/update/release functions, copying core's `_sql.py`
  shapes (single-transaction read-modify-write; the persona lost-update
  lesson applies). **Lookup discipline per [SUM-8]:** names never key
  durable state — stop/status/re-summon resolve the current name via
  core to `member_id`, then read `taut_summon_sessions`. Tests: rename
  the summoned member mid-run (`set name`), then `status`, `stop`, and
  a later re-summon by the *new* name all reach the same session row
  and member; re-summon by the *old* name finds no member and no claim
  → fresh member, never adoption; a claim row from a dead driver is
  reclaimable; claims are gone after successful bootstrap.
- Claim is evidence-based: pid + start_time, live-checked the same way
  presence does; `--takeover` semantics; release on clean exit.
- Tests: schema creates alongside core schema and **core's full suite
  passes against a db bearing summon tables** (the oblivious-core
  invariant); claim/refuse/takeover/release; row survives driver restart.
- Stop gate: needing a second `taut_meta` writer pattern or touching
  core's SCHEMA_VERSION → stop.

### S4 — Adapter interface and the scripted provider ([SUM-7.1], [SUM-7.2])

- `taut_summon/_adapter.py`: `ProviderAdapter` protocol, `AdapterHandle`,
  `AdapterEvent` union exactly per [SUM-7.1]; registry keyed by provider
  name.
- `taut_summon/_scripted.py` + `taut_summon/scripted_provider.py`: the
  test provider — a real child process reading stream-json-shaped lines,
  emitting scripted `assistant_text`/`activity`/`session` events from a
  scenario file (JSON list) given by env var. Deterministic, no timing
  magic beyond bounded waits.
- Tests: spawn/inject/events/interrupt round-trip through real pipes;
  handle close leaves no child (waitpid asserted); event-union parsing
  rejects unknown shapes loudly.

### S5 — Claude adapter ([SUM-7.2], [SUM-7.3])

- `taut_summon/_claude.py`: spawn headless streaming session (verify
  flags against the installed CLI first and record them in the module
  docstring), inject user events, translate output events to the union
  (`assistant_text` from assistant text blocks; `activity` from tool
  events; `session` from init/result metadata), `interrupt()` via the
  harness's graceful path, session id capture for resume.
- Tests: unit-level translation from captured sample event lines (fixture
  file of real recorded stream-json lines — record once, commit; note
  provenance in the fixture header); `requires_claude`-marked live smoke:
  summon echo-persona, one prompt, one reply, resume works. CI skips it.
- Stop gate: if headless streaming or resume is not actually available in
  the installed CLI generation, stop — the adapter contract may need a
  one-shot-resume fallback mode designed on purpose, not improvised.

### S6 — Driver ears ([SUM-5])

- `taut_summon/_driver.py`, in [SUM-4]'s six-step bootstrap (the
  token/env cycle, the concurrent-summon race, and the
  never-touch-a-foreign-member rule make any other order wrong):
  (0) claim (name, provider) in `taut_summon_claims`; (1) first summon
  only — create under a driver-generated collision-proof **temp name**
  with a driver-anchored agent capture (fresh names cannot adopt;
  assert via `last_created_member`), token captured; (2) take the
  target name with `set_name()` — fail-loud rename, `choose_name`
  fallback on collision, foreign members untouched by construction;
  (3) record the member_id-keyed session row, delete the claim;
  (4) spawn the harness via the adapter (session id, env carrying
  `TAUT_TOKEN`/`TAUT_DB`); (5) re-anchor with
  `TautClient(identity_capture=<child capture>, token=<ledger>).rejoin()`
  (token-only; rejoin rejects name+token); then set persona, join
  thread targets, and run the injection loop as a **watch handler**:
  self-filter → format ([SUM-5.2], one shared helper) → `inject()` →
  return. The handler raising = no cursor advance = re-delivery — the
  driver owns zero cursor code ([SUM-5.4]). Adapter death is
  fatal-and-resume ([SUM-11]), never swallowed per-message (or
  [TAUT-8.4] 3-strikes would advance past chat). The driver also owns
  the **event pump**: a dedicated thread draining `events()` for the
  life of the child — ledger session-id updates, `activity` → member
  activity, diagnostics → log, `exit` → resume path — required by
  [SUM-7.1] to prevent child-stdout deadlock, and part of shutdown
  ordering. Rate-backstop counting is NOT in the watch handler
  ([TAUT-7.4]: the member's own sends never arrive there); **S8**
  implements the audit pass. Event-pump tests: scripted provider floods
  diagnostics while injection is idle → no deadlock, log receives them;
  session-id update lands in the ledger; `exit` triggers resume.
- Tests (scripted adapter, real db, real second-CLI writer processes):
  arrival-order injection across two threads + a DM; format golden
  tests; member is kind `agent` anchored at the scripted child, `who`
  shows `here` then `gone` after exit; re-summon rejoins the same
  member_id with a fresh anchor; **concurrent-summon race test** (two
  real `taut summon claude` processes, barrier-synchronized like the
  identity concurrency test): two distinct members or one clean
  fallback, never one shared member; self-messages never injected;
  **at-least-once**: (a) scripted provider rejects one inject → handler
  raises → same message re-injects next cycle, cursor intact; (b)
  restart replay — stop the driver, write more chat, restart, assert
  exactly the post-cursor tail injects; mid-run join injects the new
  thread from its join cursor; backpressure: scripted provider stalls
  stdin, unread grows (`taut list` from a second process), driver
  buffers nothing beyond the write in flight (injected-count
  accounting, not rss).

### S7 — Persona template, mouth wiring, terminal mode ([SUM-6], [SUM-10])

- `taut_summon/_persona.py`: the default template with the five mandatory
  elements of [SUM-10]; parameterization; `--system-prompt-file`
  override; `TAUT_TOKEN`/`TAUT_DB` env assembly.
- Rate-backstop enforcement is deliberately **not** in this slice: its
  audit pass rides the control thread and reports on ctrl_out, both of
  which S8 creates — it lands there (S7 only assembles the persona
  language that references the backstop's existence).
- Terminal mode: `--terminal` valid only with exactly one positional
  thread; adapter `assistant_text` → `client.say(thread, ...)`.
- Tests: template contains the five elements (golden with parameters);
  env carries token (scripted provider echoes env back as an event —
  proves the mouth credential path end-to-end without a real harness);
  terminal-mode routing; multi-thread + unrouted text → log only, chat
  clean. (The backstop flood test lives in S8 with the enforcement.)
- The end-to-end mouth proof: scripted provider scenario that *actually
  runs* `taut say` as a subprocess using the injected env — the reply
  appears in the thread with the member's id. This is the closest test to
  the real thing and must exist (L1 proof).

### S8 — Control plane ([SUM-9])

- `taut_summon/_control.py`: queue names (`sys.ctl_`/`sys.rsp_` +
  member id, derivation helper beside addressing's shapes) —
  **unregistered** plain broker queues per D3/[SUM-9], no registry rows
  anywhere; JSON bodies keyed `command`/`request_id` (weft's
  task-control keys — [SUM-9] subset); the driver consumes control
  commands with its **own consumer** over the public `simplebroker`
  Queue surface — concretely **`read_one`** (at-most-once command
  consumption: a command lost to a driver crash is acceptable because
  STOP on a dead driver is moot and STATUS/PING requesters retry on
  timeout; `move_one`-based crash-safe handoff is deliberately not
  needed) via a `QueueWatcher` or bounded-interval loop —
  `TautClient.watch` is chat-only and stays that way;
  `taut-summon stop|status` client commands; SIGINT
  path shares the STOP ordering: stop injection → adapter.interrupt() →
  bounded wait → ledger release → exit 0.
- The control consumer runs on a **dedicated thread**; the STOP path
  closes the adapter handle, which the adapter contract requires to
  unblock a blocked `inject()` ([SUM-7.1]/[SUM-9]).
- **Rate backstop lands here** (moved from S7 — it needs this thread):
  per [SUM-10], a driver-local audit cursor per thread; on the control
  cadence, log-semantics peeks after it counting `from_id == self`
  messages ([TAUT-7.4] means the watch stream never delivers own sends
  — `tests/test_client.py:80` pins that). Breach → inject a system
  nudge + log; hard breach → interrupt harness and report on ctrl_out
  (never chat). Test: scripted provider scenario runs `taut say` in a
  loop via the injected env → breaker trips at threshold, nudge
  injected, hard breach interrupts.
- Tests: stop from a second process mid-scripted-turn (control while busy
  — conformance item); **stop while `inject()` is blocked on a stalled
  scripted harness** completes shutdown within its bound (the
  stuck-harness kill proof); status fields; ping; unknown verbs answered
  with an error reply, never crash; clean-shutdown leaves no child,
  releases claim, cursors intact (re-summon resumes cleanly).

### S9 — Conformance suite ([SUM-12]) and hardening pass

- `extensions/taut_summon/tests/test_conformance.py`: the named items,
  written against (adapter, driver) parameterized fixtures with the
  scripted provider — control idle/busy, restart-with-scope (resume and
  fresh+replay), backpressure, clean shutdown/no double-speak,
  single-driver guard, injection-format stability. A short module
  docstring states the portability contract for weft (what a runner must
  provide).
- Adversarial probes for the new CLI per the probe-floor runbook:
  `taut-summon run` with no db, unknown provider, dead ledger claim,
  garbage scenario file — exit classes, one-line stderr, no tracebacks.

### S10 — Docs and closeout

- Implementation doc: new `docs/implementation/05-summon.md` (why-focused:
  terminal framing, ears/mouth, ledger lifecycle, weft divergences) +
  repo-map row + agent-inventory untouched.
- README: move summon from Roadmap to a short usage section mirroring the
  Postgres extension's placement (install, one `taut-summon run` example,
  pointer to spec 04).
- CHANGELOG (extension's own + root Unreleased note), spec backlinks
  verified by the docs gate, Deviation Log reconciled (no `pending`),
  Implementation Record appended here, full gates, uncommitted-state
  report per the commit-gate carve-out.

## 9. Testing Plan

- Harness: pytest; extension tests in `extensions/taut_summon/tests`, run
  explicitly (root `testpaths` stays `tests`); driver/e2e tests use real
  `.taut.db` files, real subprocesses for both the scripted provider and
  peer CLI writers.
- Never mocked: broker, sidecar, taut CLI, the pipes to the provider
  child. Allowed double: the scripted provider (real process, fake
  model) — the seam [SUM-12] blesses; plus recorded stream-json fixture
  lines for claude-adapter unit translation.
- Red-green default; where a race can't be deterministically red (none
  currently foreseen — S6's crash-window is deterministic via kill
  points), name the substitute proof in the slice before implementing.
- Contract focus: injection format, cursor/replay semantics, mouth
  credential path, control verbs, exit codes — the things another agent
  (or weft) will program against.

## 10. Verification and Gates

Per-slice: `uv run pytest extensions/taut_summon/tests -q` plus
`uv run pytest -q` (core untouched-green), then:

```bash
uv run ruff check taut tests bin extensions/taut_pg/taut_pg extensions/taut_pg/tests extensions/taut_summon/taut_summon extensions/taut_summon/tests
uv run ruff format --check <same paths>
uv run --extra dev mypy taut tests bin/release.py extensions/taut_pg/taut_pg extensions/taut_pg/tests extensions/taut_summon/taut_summon extensions/taut_summon/tests --config-file pyproject.toml
uv build && uv build extensions/taut_pg && uv build extensions/taut_summon
```

Final: all of the above + `uv run ./bin/pytest-pg --fast` (summon state
must not break PG runs of the shared suite) + the `requires_claude` smoke
run locally once, result recorded in the slice record.

Observable success after landing: `taut summon reviewer --provider
claude dev` in this repo, a human `taut say dev "@reviewer ..."` from
another terminal, and a routed reply arriving in `#dev` — the dogfood
loop this plan exists for.

## 11. Rollout and Rollback

- Additive throughout: core untouched (two spec-text deltas aside), new
  package, new tables under extension-owned names. Rollback = don't
  install the extension; a db that has summon tables remains fully valid
  for core (S3's oblivious-core test is the proof).
- One-way doors: none. The ledger schema is v1 under its own version key;
  the injection format ([SUM-5.2]) is the stickiest contract — treat any
  post-S6 change to it as a spec revision, not a tweak.
- Sequencing: S1 strictly first (governing spec), S2→S3→S4 in order,
  S5 and S6 may interleave after S4 (S6 tests need only the scripted
  adapter), S7→S8→S9→S10. The `codex` adapter is explicitly a follow-on
  plan.

## 12. Independent Review Loop

- Reviewer: Codex (different agent family), adversarial stance, iterating
  to a clean verdict per repo convention.
- Reads: this plan, the spec draft in full, [TAUT-12.3], [IAN-6.1], the
  watch/client surfaces named in §5, and weft's
  `weft/core/tasks/base.py` for the mirrored control contract
  ([SUM-9]; `sessions.py`/`agent_session_protocol.py` only for the
  supervision-craft provenance claims).
- Prompt (verbatim):

  > Read the plan at docs/plans/2026-07-06-taut-summon-plan.md and its
  > full Proposed Spec Delta, including the linked spec draft
  > docs/plans/2026-07-06-taut-summon-spec-draft.md and the named
  > promotion strategy. Carefully examine the plan, the proposed spec
  > text, and the associated code. Look for errors, bad ideas, and latent
  > ambiguities. Don't do any implementation, but answer carefully: If
  > asked, could you implement this plan confidently and correctly as
  > written?

- Feedback handling: every point addressed by plan/spec-draft edit,
  reasoned rebuttal in the review log below, or explicit out-of-scope
  entry; blocker condition is the reviewer's negative answer.

### Review log

**Round 1 — Codex (codex-cli 0.135.0, adversarial consult, 2026-07-06).**
Verdict: "No — revision needed around watcher cursor ownership, control
queue integration, agent identity creation, private state access, token
semantics, and Weft congruence." All 10 findings addressed, plus three
owner refinements folded into the same revision:

1. [P1] The plan described driver-managed cursor advancement, but
   `TautWatcher` advances cursors on handler return — **fixed**:
   [SUM-5.4] and S6 rewritten onto the handler-return contract (the
   driver owns zero cursor code); crash-window tests replaced with the
   two deterministic public-surface proofs (inject-raise re-delivery,
   restart replay); a comprehension question added for the [TAUT-8.4]
   3-strikes interaction (adapter death must be fatal-and-resume).
2. [P1] Control queues cannot ride `TautClient.watch` — **fixed**:
   [SUM-9]/S8 now specify a dedicated consumer over the public
   simplebroker Queue surface; watch stays chat-only.
3. [P1] `join --as` would classify a human-launched summon as a human
   member — **fixed**: [SUM-4]/S6 use the public
   `TautClient(identity_capture=...)` seam with an agent capture built
   from the harness child pid.
4. [P1] `update_member_anchor` is not public — **fixed**: re-anchoring
   now goes through public `rejoin` (which owns the anchor update);
   first-contact anchoring rides member creation under the injected
   capture. No private state calls remain.
5. [P1] "Authenticated by token" contradicted [TAUT-5] — **fixed**:
   continuity-not-authentication language with [TAUT-9] cite in [SUM-6].
6. [P1] Weft congruence pointed at the wrong weft surface — **fixed**:
   [SUM-9] now names the task control-queue contract
   (`weft/core/tasks/base.py`) as the mirrored surface, adopts its
   `command`/`request_id` keys verbatim, and demotes
   `agent_session_protocol.py` to supervision-craft reference only.
7. [P2] Docs gate doesn't scan specs for spec codes — **fixed**: S1
   expands scan sources to `docs/specs/*.md` with a red-first ordering.
8. [P2] Backend-agnostic claim vs SQL ledger — **fixed**: [SUM-8]
   states the SQL-sidecar requirement; S2 states the SQLite test
   posture; PG run of the extension suite added to Out of Scope.
9. [P2] Rate backstop could be filtered inert — **fixed**: [SUM-10]
   orders count-before-self-filter with the rationale.
10. [P2] `sys.*` registry-row question — **fixed**: D3 and [SUM-9]
    register control queues (class `system`, hidden by default).
    *(Superseded in round 4: registration was removed entirely —
    control queues are deliberately unregistered.)*

Owner refinements in the same revision: (a) core `taut summon` /
`taut dismiss` delegation verbs (new delta D4, S2) replacing the
standalone-only script surface; (b) default thread `general`, name
defaulting from provider; (c) [SUM-2] "captive process, free agent"
paragraph making explicit that the harness child is fully supervised
while its meaning is not captive.

**Round 2 — Codex (codex-cli 0.135.0, adversarial consult, 2026-07-06).**
Verdict: "No — the identity/rejoin path and injection/control guarantees
need tightening." All 8 points addressed:

1. [P1] `rejoin(NAME)` with a token is rejected by core — **fixed**:
   token-only `rejoin()` in [SUM-4]/S6.
2. [P1] First-summon creation without `as_name` would auto-name from the
   child basename — **fixed**: [SUM-4] adds explicit name resolution
   (ledger → rejoin; free → `as_name` creation; taken → driver-side
   [IAN-9] pool fallback, never implicit adoption of an existing
   member); S6 mirrors it.
3. [P1] "Authenticated by token" survived in D2 and [SUM-1]/[SUM-2] —
   **fixed**: all occurrences now read selected-by/continuity with
   [TAUT-5]/[TAUT-9] cites (grep-verified zero remaining).
4. [P1] At-least-once was overclaimed past the process boundary —
   **fixed**: [SUM-5.4] now guarantees delivery to the harness process
   boundary (flushed write, synchronous failure), names the
   harness-crash residual window explicitly, ties recovery to durable
   chat history, and invites (not requires) protocol-level acks.
5. [P1] Blocked `inject()` vs control responsiveness — **fixed**:
   dedicated control thread; adapter contract requires thread-safe
   `interrupt()`/close that unblocks in-flight `inject()`
   ([SUM-7.1]/[SUM-9]); S8 gains the stalled-harness STOP test.
6. [P2] "Mirrored exactly" overstated weft congruence — **fixed**:
   [SUM-9] now claims the `command`/`request_id` JSON subset, notes
   weft's raw-string and extra-field behaviors, and requires consumers
   to ignore unknown reply fields.
7. [P2] Out-of-scope contradicted D4 — **fixed**: the item now defers
   only *generic* external-subcommand dispatch.
8. [P2] Handler-ordering texts disagreed — **fixed**: both now read
   count → self-filter → format → inject. (Superseded in round 3: the
   count step left the handler entirely.)

**Round 3 — Codex (codex-cli 0.135.0, adversarial consult, 2026-07-06).**
Verdict: "No — the rate-backstop and event-drain gaps would force design
decisions during implementation." All 6 points addressed:

1. [P1] The watch stream never delivers the member's own sends
   ([TAUT-7.4] advances the sender cursor at write time), so
   count-in-handler was mechanically inert — **fixed**: [SUM-10]/S7 now
   specify a driver-local audit cursor with log-semantics peeks on the
   control-thread cadence; the count step is removed from the watch
   handler in both documents.
2. [P1] No slice owned the continuous adapter-event drain — **fixed**:
   [SUM-7.1] now requires a dedicated event-pump thread (session-id
   updates, activity, diagnostics, exit; deadlock rationale; shutdown
   ordering) and S6 owns it with tests.
3. [P1] Delegation installability was unwired (uv sources/CI install
   only cover taut-pg; find_spec would fail; stale `taut>=0.4.6`
   floor) — **fixed**: S2 gains explicit root `[tool.uv.sources]` + CI
   install wiring and a release-gate rule for the real version floor.
4. [P2] "Extension-owned state only" conflicted with core-owned
   `sys.*` registry rows — **fixed**: invariant rewritten to name the
   two core touchpoints (registry rows of kind `system`, public state
   surface). *(Superseded in round 4: registry rows were removed
   entirely; the invariant reverted to extension-owned state only.)*
5. [P2] S1 overstated the docs-gate delta (paths already scan specs;
   only spec-code resolution omits them) — **fixed**: precise scope and
   a concrete red-first ordering.
6. [P2] Delegation had to touch `_first_command()`'s hoisting set too —
   **fixed**: S2 names both integration points and adds
   `--db`/`--provider`/`--` pass-through tests.

**Round 4 — Codex (codex-cli 0.135.0, adversarial consult, 2026-07-06).**
Verdict: "No — three P1s would force implementation-time contract
decisions." All 4 points addressed:

1. [P1] `sys.*` registry rows had no public writer — **resolved by
   removing the requirement**: D3 and [SUM-9] now declare control queues
   deliberately unregistered (invisible broker queues, the same
   treatment as foreign queues), which needs no core seam at all and
   restores the extension-owned-state-only invariant. Discoverability
   for debugging stays via `broker -f .taut.db list` ([TAUT-3.4]).
2. [P1] Ledger DDL omitted the token column the design depends on —
   **fixed**: S3 now carries the explicit column list including `token`
   and `member_name`, with the (member_name, provider) lookup constraint
   and the [TAUT-9] rationale for storing the token.
3. [P1] S7's backstop depended on S8's control thread — **fixed**:
   enforcement moved to S8; S7 keeps only the persona language.
4. [P2] The [IAN-9] pool fallback had no blessed implementation —
   **fixed**: [SUM-4] blesses `taut.identity.choose_name()` for
   extensions, seeded from public `who()`.

**Round 12 — Codex (codex-cli 0.135.0, adversarial consult, 2026-07-06).**
Verdict: "No — the name-collision contract is still contradictory."
Both points addressed:

1. [P1] [SUM-3]'s pool fallback contradicted [SUM-4]'s loud refusal for
   colliding names — **fixed with one rule stated in [SUM-4] and
   summarized in [SUM-3]**: an *implied* name (convenience form,
   positional == provider) falls back through the pool with a console
   note — the user asked for *a* claude; a *chosen* name (`--provider`
   given) refuses loudly — renaming a deliberate choice would surprise
   people and scripts. The same rule governs `set_name` collisions in
   bootstrap step 2.
2. [P2] The round-3 log entry still described the superseded
   registry-row invariant — **fixed**: supersession note added.

**Round 13 — Codex (codex-cli 0.135.0, adversarial consult, 2026-07-06).**
Verdict: "No — the explicit-name collision branch still requires an
implementation-time choice." The single residual addressed:

1. [P1] Bootstrap step 2's unconditional fallback contradicted the
   chosen-name refusal rule — **fixed**: [SUM-4] now scopes chosen-name
   refusal to resolution time (before anything exists); a collision
   appearing inside the bootstrap window falls back for implied and
   chosen names alike, with a louder note for chosen names — refusal
   mid-bootstrap would strand the temp-named member, while fallback is
   recoverable (`taut set name`) and leaves no debris.

**Round 14 — Codex (codex-cli 0.135.0, adversarial consult, 2026-07-06).**
Verdict: **"Yes — no P1s found; if asked, could implement this plan
confidently and correctly as written."** One advisory applied after the
affirmative verdict, strictly tightening the reviewed text:

1. [P2] Step-0 claim collisions applied fallback uniformly, though for
   chosen names nothing exists yet and refusal is clean — **fixed**:
   step 0 now applies the [SUM-4] collision rule (implied → fallback;
   chosen → loud refusal), with the concurrent chosen-name test
   expectation (one `reviewer`, one clean refusal).

**Status: plan review-clean.** The independent-review loop's blocker
condition is cleared as of round 14.

**Round 5 — Codex (codex-cli 0.135.0, adversarial consult, 2026-07-06).**
Verdict: "No — the first-summon token/bootstrap ordering and stale S8
registry instruction must be fixed first." All 4 points addressed:

1. [P1] Token/env cycle: the child env needs `TAUT_TOKEN`, the token is
   minted at creation, and creation was specified as child-anchored —
   **fixed**: [SUM-4]/S6 now specify the three-step bootstrap
   (create-with-driver-anchor → spawn-with-token-env → token-only
   `rejoin()` re-anchors to the child), which also unifies first and
   later summons into one shape.
2. [P1] S8's task text still instructed registry rows after round 4
   removed the requirement — **fixed**: S8 now says unregistered plain
   broker queues, matching D3/[SUM-9]/the invariant.
3. [P2] Stale S6/S7 backstop ownership references — **fixed**: both now
   point at S8 as the sole owner (S7's flood test line removed).
4. [P2] The docs gate would not scan extension code for `[SUM-*]` cites
   — **fixed**: S1 extends `_python_sources()` with `extensions/**/*.py`
   and the path-claim prefix set with `extensions/`.

**Round 6 — Codex (codex-cli 0.135.0, adversarial consult, 2026-07-06).**
Verdict: "No — first-summon creation needs a race-safe seam the plan
forbade adding." All 4 points addressed:

1. [P1] Concurrent first summons of the same name could silently adopt
   one shared member (explicit-`as_name` resolution adopts an existing
   row before insert) — **fixed without a core seam**: bootstrap step 0
   claims the (member_name, provider) ledger row transactionally
   (UNIQUE; loser retries with fallback), serializing summon-vs-summon
   through extension-owned state; and after `join` the driver verifies
   creation via the public `last_created_member` signal, aborting loudly
   if a non-summon actor created the name in the window. [SUM-4] blesses
   that signal as extension-visible surface. *(Detection-then-abort
   superseded in round 9 by temp-name creation, which makes adoption
   impossible rather than detected; the claim step and the blessed
   signal survive.)*
2. [P2] Race test required — **fixed**: S6 gains a two-process
   barrier-synchronized concurrent-summon test (two members or clean
   fallback, never shared).
3. [P2] "Claim/read semantics" named no real primitive — **fixed**: S8
   pins `read_one` with the at-most-once rationale (STOP on a dead
   driver is moot; STATUS/PING requesters retry).
4. [P2] "Arrival order" overstated the watcher guarantee — **fixed**:
   [SUM-5.1] now says watcher delivery order, per-thread chronological,
   no global cross-thread guarantee.

**Round 7 — Codex (codex-cli 0.135.0, adversarial consult, 2026-07-06).**
Verdict: "No — the ledger bootstrap schema must be fixed first." All 3
points addressed:

1. [P1] Claim-before-create contradicted `member_id TEXT PRIMARY KEY`
   (NULL PK is illegal on Postgres) — **fixed**: the ledger PK is now
   `(member_name, provider)` (the claim constraint itself), with
   `member_id NULL-then-UNIQUE` and `token NULL-then-set` at creation;
   [SUM-8] states the constraint explicitly; abandoned claims (NULL
   member_id + dead driver evidence) are reclaimable. *(Single-table
   shape superseded in round 9 by the transient-claims + durable
   member_id-PK sessions split.)*
2. [P2] [SUM-4]'s opening still implied capture-after-spawn — **fixed**:
   "ultimately the harness child" with the temporary driver anchor named
   and a do-not-spawn-first warning.
3. [P2] "Mirror taut_pg in CI" had no CI precedent to mirror —
   **fixed**: S2 now instructs extending CI explicitly and names the
   README as the only existing extension-gate example.

**Round 8 — Codex (codex-cli 0.135.0, adversarial consult, 2026-07-06).**
Verdict: "No — the mutable-name versus name-keyed ledger issue needs one
more revision." All 3 points addressed:

1. [P1] Post-creation ledger lookups by name break under `set name`
   (names are mutable, [IAN-2.2]) — **fixed**: [SUM-8] and S3 now pin
   the lookup discipline (name PK serializes pre-create claims only;
   stop/status/re-summon resolve the current name via core to member_id
   and read by the UNIQUE member_id column *(schema superseded in round
   9: transient claims table + member_id-PK sessions table)*) with
   rename-during-run
   tests for status, stop, and re-summon by new and old names.
2. [P2] Thread syntax inconsistency (`[THREAD ...]` vs `--thread`) —
   **fixed**: positional threads are canonical at both entry points;
   terminal mode takes exactly one positional thread; the dogfood
   command updated.
3. [P2] Stale weft reading pointers in §2/§12 — **fixed**: both now
   name `weft/core/tasks/base.py` as the mirrored contract and demote
   the session files to supervision-craft provenance.

**Round 9 — Codex (codex-cli 0.135.0, adversarial consult, 2026-07-06).**
Verdict: "No — the two P1s require a plan/spec revision." Resolved by
restructuring the bootstrap rather than patching it again:

1. [P1] The (name, provider) PK permanently occupied renamed-away
   names — **fixed structurally**: [SUM-8] now splits the ledger into a
   *transient* `taut_summon_claims` table (deleted after bootstrap;
   dead-driver rows reclaimable) and a *durable* member_id-keyed
   `taut_summon_sessions` table. Old names free up the moment their
   claim row is deleted.
2. [P1] The `last_created_member` verification ran after explicit-name
   resolution had already mutated a foreign member (activity, persona,
   membership, join notice) — **fixed structurally**: creation now
   happens under a driver-generated collision-proof temp name (fresh
   names cannot adopt anything), followed by core's transactional
   fail-loud `set_name()` to take the target name. Foreign members are
   untouched by construction; the only cost is one cosmetic temp-name
   join notice.
3. [P2] Event-pump activity had no public seam and invited a private
   `_state` reach — **fixed**: [SUM-7.1] names the seam (rate-limited
   token-selected `whoami()` resolution, which updates
   `last_active_ts` per [IAN-3.3] step 2).

**Round 10 — Codex (codex-cli 0.135.0, adversarial consult, 2026-07-06).**
Verdict: "No — fix the two [P1] bootstrap/spec contradictions first;
**after that, yes**." All 3 points addressed:

1. [P1] [SUM-4]'s name-resolution paragraph still carried the
   pre-round-9 name-keyed session lookup — **fixed**: it now reads
   current-name → member_id → session row, refuses loudly for existing
   non-summoned members, and routes first summons through
   claim-then-temp-name.
2. [P1] The `set_name` collision fallback could leave the final name
   uncovered by a claim — **fixed**: on rename collision the driver
   releases the stale claim and restarts at step 0 with the fallback
   target (temp-named member reused; steps 0 and 2 rerun), so the race
   guarantee never lapses.
3. [P2] `taut-summon run` name/provider resolution was ambiguous —
   **fixed**: [SUM-3] pins one contract shared verbatim by both entry
   points (positional = member name; provider = `--provider`, else the
   name when it matches a registered adapter, else an error naming the
   adapters). *(Extended in round 11 with the session-row step.)*

**Round 11 — Codex (codex-cli 0.135.0, adversarial consult, 2026-07-06).**
Verdict: "No — the re-summon name/provider contradiction is a [P1]."
Both points addressed:

1. [P1] The round-10 provider rule broke re-summon by name alone
   (`taut summon reviewer` would error because `reviewer` is not an
   adapter, despite the session row knowing the provider) — **fixed**:
   [SUM-3]'s resolution order is now `--provider` (conflict with a
   session row's stored provider is a loud error — no implicit harness
   switching) → session row's provider (re-summon by name just works)
   → name-as-adapter (first-summon convenience) → error naming
   adapters.
2. [P2] Three earlier review-log entries described since-superseded
   designs without saying so — **fixed**: supersession parentheticals
   added (rounds 2, 6, 7, 8 entries), keeping the log honest as a
   record without letting stale prose mislead an implementer.

## 13. Out of Scope

- **Codex adapter** — named in [SUM-7.2] so the interface is shaped for
  two providers, shipped by a follow-on plan.
- **Sandboxed/sealed execution** — a pipe-command wrapper concern; no
  architecture here ([SUM-1]).
- **Generic git-style external-subcommand dispatch in core** (any
  `taut X` → `taut-X` on PATH) — deferred. D4 adds exactly the two
  named delegation verbs, nothing generic.
- **Presence "typing" indicators beyond activity timestamps** — the
  `activity` event feeds `last_active_ts`; richer signals are future
  polish.
- **Hook recipe for interactive (non-summoned) sessions** — documentation
  deliverable, valuable, separate small plan; it needs no summon code.
- **Weft actually running the conformance suite** — the suite ships
  portable; wiring it into weft's CI is weft-side work.
- **Postgres run of the extension test suite** — the ledger DDL rides
  core's dialect pattern; a PG execution lane for
  `extensions/taut_summon/tests` is follow-on wiring.
- **Redis backend interactions** — summon state is SQL-sidecar-only until
  [TAUT-12.2] designs the Redis state mapping.

## 14. Fresh-Eyes Check (author, pre-review)

Checked against writing-plans + hardening checklists: invariants before
tasks; new-persistence lifecycle (ledger) has creation/claim/release/
restart semantics and an oblivious-core proof; the async lane
(injection) has explicit at-least-once semantics, a backpressure story,
and deterministic crash-window tests; stop gates on the three drift
directions that would sink this design (core changes, a summon wire
protocol, mock creep at the provider seam); rollback trivial and stated;
comprehension question on the watch surface where cold-reading would hurt
most. Known soft spots for the reviewer: the claude streaming flags are
deliberately implementation-time facts, and [SUM-5.2]'s injection format
is asserted stable before any real-world dogfood has stressed it.

## 15. Implementation Record

**Phase A (S1 + S2), 2026-07-06/07.** Implemented by subagents, verified
by gates, adversarially reviewed by Codex per phase.

- S1: spec 04 promoted (`Status: Active`), D2/D3/D4 applied, reference
  gate extended to `[SUM-*]` codes, spec-code scanning of
  `docs/specs/*.md`, and `extensions/**/*.py` sources. Red-run caught
  the staged dangling codes as designed.
- S2: extension package + console script + delegation verbs +
  CI/uv wiring; absence path proven via a site-processing-disabled
  subprocess.
- **Codex implementation review round 1: No.** [P1] the delegated tail
  was hoisted before splitting, so core-global lookalikes (`--as`,
  `--json`, `-q`) never reached the extension, breaking [SUM-3]'s
  verbatim contract; [P2] the `--db` propagation tests asserted only a
  generic error a dropped flag would also produce; [P2] the docs gate
  soft-skipped a missing registered spec file. All three fixed
  (fix agent stalled; fixes applied and verified by the supervising
  agent directly): `main()` now splits on raw argv at the delegated verb
  and hoists only the pre-verb head; the S2 skeleton echoes its parsed
  db (`(db: PATH)`) and five new/upgraded core tests assert the echo and
  extension-usage-errors naming tail tokens; `_valid_spec_codes` hard-
  fails on a missing registered spec. Gates: 297 core + 15 extension
  tests, ruff/format/mypy clean.

**Phase B (S3 + S4), 2026-07-07.** Ledger + guard (`_state.py`, 21
tests) and adapter interface + scripted provider (`_adapter.py`,
`_scripted.py`, `scripted_provider.py`, 12 tests), CLI registry wiring.
**Codex implementation review round 1: No.** [P1] `release_driver` (and
`release_claim`) cleared by key alone, so a replaced driver's cleanup
could erase its successor's live claim — fixed with ownership-checked
release (read-then-conditional-write in one transaction, returns bool;
stale release is a no-op) plus two red tests. [P2] inject/lifecycle
serialization — fixed with a dedicated injector lock (deliberately not
the lifecycle lock, preserving interrupt-unblocks-inject) and a
concurrent-injectors protocol-integrity test. [P2×3] undocumented
deferrals/drift — recorded as the three §7 Deviation Log rows (S3 named
tests deferred to S6/S8; representative-flow substitute proof;
scenario-object shape). Fixes applied and verified by the supervising
agent directly. Gates after fixes: 50 extension + 297 core tests,
ruff/format/mypy clean. **Confirmation round: Yes** — all five items
CONFIRMED; its one advisory (release SQL relied on `BEGIN IMMEDIATE`
semantics that `simplebroker-pg` maps to plain read-committed `BEGIN`)
was hardened immediately: evidence predicates on the release
UPDATE/DELETE plus an in-transaction confirm re-read make the ownership
check portable to read-committed backends.

**Phase C (S5 + S6), 2026-07-07.** Claude adapter (+ shared
`_stream.py` handle mechanics), full driver (bootstrap, ears, event
pump, resume, shutdown), 30 new tests incl. a live `requires_claude`
smoke; claude CLI flag realities recorded in `_claude.py` (`--verbose`
required; no init event until the first user turn). Supervisor
verification found and fixed three test-suite defects the subagent's
green run masked: a missing dev-queue wait plus a missing
bootstrap-completion barrier (the driver spawns the child before
joining threads per [SUM-4], so provider-start precedes joins and a
pre-join `say` is correctly invisible under [TAUT-7.4] — two
pool-fallback tests opt out of the name-keyed barrier with their own),
and a vacuous `assert ... or True`. Serial-by-design pinned in the
extension pyproject (driver tests are three-process pipelines);
`_DEADLINE` 30→90s for CI headroom; stability: 4× serial suite runs
clean. **Codex implementation review: "[P1] None … sound enough to
build Phase D on."** Five P2s dispositioned: centralized `_release()`
on all fatal paths, `_halt_and_raise` ack-timeout hardening + test,
terminal-mode anti-loop assertion, and the claude-docstring
recorded-vs-synthetic split are Phase D carry-in tasks; the
`time.sleep(0.5)` race-test settle is replaced by S9's conformance
stress probe (Codex accepted that placement).

**Phase D (S7 + S8), 2026-07-07.** Persona template (`_persona.py`),
rate backstop + control plane (`_control.py`: STOP/STATUS/PING mirroring
weft's command/request_id subset, ControlLoop on its own thread/
connection, ControlClient), real `stop`/`status` verbs, and the four
Phase-C carry-ins (centralized release, hardened `_halt_and_raise`,
terminal anti-loop, `_claude.py` docstring honesty — all verified by the
review). Retry vendoring done to the user's spec: `_retry.py` vendored
byte-identical from simplebroker 5.1.0, `_broker_retry.py` the taut-
summon policy on top (mirroring `helpers.py` over `_retry.py`); the
drift-guard test was dropped and an incidental `simplebroker._exceptions`
private import fixed to public `simplebroker.ext`. **Codex review round
1: No** — two P1 blockers + three P2s, all fixed by the supervising
agent directly:
- [P1] STOP ack was not gated on ledger release (`_release` swallowed
  failures; `run()` acked unconditionally) — **fixed**: `_release`
  records confirmation; the control loop acks only on confirmed release,
  else replies `error`. (The CLI `stop` already independently polled the
  ledger, so exit codes were already correct; now the [SUM-9] reply is
  honest too.)
- [P1] the retry could mask genuine corruption (predicate retried the
  whole `OperationalError`/`DatabaseError` classes; `_tick` swallowed the
  post-budget reraise as debug) — **fixed**: predicate narrowed to the
  two specific transients by message marker (lock/busy + malformed),
  honoring the `retryable` attribute; `_tick` now marks control unhealthy
  and STATUS reports `control_health: degraded` instead of dying silent.
- [P2] `_retry.py` was not pristine (my provenance paragraph) — **fixed**:
  restored byte-identical; provenance moved to `_broker_retry.py`.
- [P2] concurrent control clients consumed each other's replies on the
  shared rsp queue — **fixed**: per-request reply queues
  (`sys.rsp_<member>_<request_id>`, an additive `reply_to` wire field);
  new concurrent-clients test.
- [P2] rate backstop was static/one-shot — **partly fixed**: the breaker
  re-arm (the load-bearing circuit-breaker fix) landed with a unit test.
  The dynamic-thread-coverage half was **attempted then reverted**: a
  per-tick `list_threads()` re-records the member's continuity-token
  claim and races the watcher on the `claim_hash` UNIQUE constraint
  (surfaced as an `IntegrityError` that destabilized both audit and
  injection — it was, in fact, the true cause of the intermittent
  `test_arrival_order` failure). Closing the late-joined-thread gap
  correctly needs idempotent claim recording in core (frozen) or an
  in-memory watcher→control membership channel; deferred as an accepted,
  documented limitation ([SUM-10] static startup coverage). This is the
  clearest case in the whole effort for why adversarial review plus real
  stress matters: the "fix" was worse than the gap.
Gates after fixes: ruff/format/mypy (14 files) clean; new tests for
predicate-narrowing, breaker re-arm, degraded-STATUS, concurrent clients.
Three test flakes surfaced during post-fix stabilization, each fixed at
the source (not masked):
1. The concurrent-implied race test's `time.sleep(0.5)` (the deferred S9
   item) became a deterministic barrier keyed on each driver's
   `driver_pid` in its session row — and that surfaced the actual bug: the
   barrier's `_session_row` helper read the `taut_summon_sessions` table
   *before* either racing driver had run `ensure_summon_schema` (via the
   peer `van` member in `who()`), raising `no such table`. Fixed: the test
   helper treats a not-yet-created summon table as "no row yet." 0/20
   fails after.
2. The status client's 10s timeout → 30s (matching stop): a control
   round-trip against a loaded/mid-turn driver can take a cadence or two,
   so 10s reported a false "did not respond."
3. `test_arrival_order` flaked because it exposed a **real product bug**:
   `_bootstrap` joined only `threads[0]`; the remaining summon threads
   were joined later in `_supervise`, *after* `record_session` signals
   readiness. So `taut summon claude general dev` would silently drop
   anything said in `dev` in the window between "ready" and that deferred
   join ([TAUT-7.4]: joining starts you at now). Fixed: bootstrap joins
   **all** threads before recording the session row, so readiness implies
   full membership. 0/15 after — this was the dominant flake, and finding
   it is exactly why the stress loop was worth running.
4. Residual: two control-plane integration tests
   (`test_rate_backstop_*`, `test_stop_from_another_terminal`) show a
   low-rate (~1/8–1/23) timeout under machine load — real multi-process
   timing variance, not a logic defect (each passes 15–20× in isolation;
   the STOP path's ack-gating/release/routing all verified across the
   many passes). A single CI-representative run tolerates it; back-to-back
   batches self-inflict the saturation. Documented, not masked.

**Phase E (S9 + S10), 2026-07-07.** Conformance suite + docs closeout.

- S9: `extensions/taut_summon/tests/test_conformance.py` — the [SUM-12]
  named items expressed as tests written against a small, provider-agnostic
  `ConformanceHarness` interface and **parameterized over a harness
  factory** (`scripted` runs; `claude` is a `requires_claude`-gated
  portability placeholder — skipped when the CLI is absent, and a
  deliberate skip-with-reason when present so the heavy serial suite does
  not spin up N live model sessions; the single live claude proof stays
  `test_claude_adapter.py::test_live_claude_smoke`). To satisfy the
  anti-duplication mandate, the real-process driver harness (`DriverProcess`
  + peer-writer/ledger/control helpers + the `summon_db`/`driver_factory`
  fixtures) was **moved from `test_driver.py` into `conftest.py`**, so the
  deep proofs and the portable suite drive one identical harness — never a
  divergent copy. The module docstring carries the [SUM-12] coverage map
  (each named item → its conformance test → the existing deep proof it
  complements) and the "what Weft supplies" portability contract. The
  adversarial CLI probe floor (no-db, unknown provider, garbage scenario
  file) asserts the shape the exit-class tests did not: one-line stderr, no
  traceback. The Phase-C-deferred `time.sleep(0.5)` race item was already
  fixed deterministically in Phase D (the `driver_pid`-keyed barrier); this
  suite adds no sleep-based synchronization and no `xdist`, honoring the
  serial-by-design posture. Three mypy tidy-ups rode along (the relocated
  `peek_many` union guard in `conftest.py`; a `retryable`-attr `type: ignore`
  in `test_control.py`; the harness-factory fixture annotation) so the full
  README gate — which type-checks the tests — stays green, not just the
  package-only gate.
- S10: new `docs/implementation/05-taut-summon-architecture.md`
  (why-focused: ears/mouth, captive-process/free-agent, the three-thread
  driver, the ledger split, the `sys.*` control queues, the vendored retry,
  the SimpleBroker facade boundary) + its rows in
  `docs/implementation/00-implementation-index.md` and
  `docs/implementation/02-repository-map.md`; root `CHANGELOG.md` Unreleased
  note (delegation verbs + the extension); README Roadmap bullet updated to
  "shipped" plus a new "Summon Extension" usage section mirroring the
  Postgres extension's placement; the spec `## Related Plans` backlink
  verified present ([SUM-12] docs gate green). §7 Deviation Log carries no
  `pending` rows.
- Gates (2026-07-07): full extension suite green (7 `claude` conformance
  placeholders skipped); core suite green; `tests/test_docs_references.py`
  green; ruff check + `ruff format --check` clean over
  `taut tests extensions/taut_summon/...`; mypy clean (package 14 files;
  full package+tests 23 files); `uv build extensions/taut_summon` succeeds.

**Closing summary.** All ten slices (S1–S10) are implemented, gate-green,
and Codex-reviewed through Phase D; Phase E adds the portable [SUM-12]
conformance suite and the documentation closeout. The extension is
functional end to end (`taut summon`/`dismiss` delegation, `run`/`stop`/
`status`, scripted + claude adapters, driver, control plane, persona, rate
backstop) with zero changes to frozen core beyond the two spec-text deltas
and the two zero-logic delegation verbs. The work is intentionally left
**uncommitted** for the user's pre-landing review (see the Landing Note).

Supervisor robustness fix during Phase E verification: STATUS's
`_cursor_lag` caught only `TautError`, so a transient broker error or a
claim-hash race with the watcher during its `list_threads` resolution
degraded the *entire* STATUS reply to "status unavailable." Widened to
`(TautError, BrokerError)` → the lag summary degrades to empty while
STATUS still reports provider/session/thread_count — exactly the
concurrent condition ([SUM-9] mid-turn) STATUS exists to answer. (The
one conformance flake that surfaced it, `test_control_responsive_mid_turn`,
is otherwise saturation-only: 0/8 isolated.)

Post-review lifecycle fix (control-message reaping). A design-question
review found that control messages relied entirely on simplebroker's
auto-vacuum, which reclaims only *claimed* rows — so two paths that leave
*unclaimed* rows would accumulate slowly in the member's durable `sys.*`
namespace: the rate-backstop's requester-less ctrl_out report (no consumer)
and orphaned per-request replies on client timeout. Fixed at the source:
(1) the hard-breach is now surfaced through STATUS (`rate_limited`,
`rate_breaches`) + the log instead of an unconsumed ctrl_out message
([SUM-10] refined); (2) `ControlClient.request` hard-`delete()`s its
single-use reply queue in `finally` (explicit, no vacuum reliance);
(3) the driver reaps `ctl_in` and the shared rsp queue on shutdown. New
test `test_dismiss_leaves_no_unclaimed_control_rows` asserts no pending
control rows survive a dismiss; the rate test now asserts STATUS state and
an empty ctrl_out. Command/reply happy paths were already consumed
(claimed) via `read_one`; this closes the unclaimed-accumulation tail.

## 16. Landing Note

The whole implementation is uncommitted so the user reviews before landing.

**Two overlapping bodies of uncommitted work in this tree.** Summon's spec
baseline (§3) is `d0fd368` *plus* the uncommitted evaluation-findings
remediation work (`2026-07-06-evaluation-findings-remediation-plan.md`).
Several files carry **both**: `taut/cli.py` (remediation's usage-exit-code
parser + `--` handling, then summon's delegation verbs on top), `tests/
test_cli.py`, `tests/test_docs_references.py`, `docs/specs/02-taut-core.md`
and `docs/specs/03-identity-addressing-notifications.md` (remediation deltas
+ summon's D2/D3). If landing separately, land the remediation plan first;
if landing together, that is fine — the summon work was built and verified
on top of it. Full surface for whoever commits:

**Untracked (new):**

- `extensions/taut_summon/` — the entire extension tree (package, tests,
  `pyproject.toml`, `README.md`, `LICENSE`, `py.typed`, fixtures). Do **not**
  commit generated artifacts under it: `dist/`, `__pycache__/`,
  `.pytest_cache/`, `.venv/` (cleaned during closeout; gitignore or omit).
- `docs/specs/04-summon.md` — the promoted spec ([SUM-1]–[SUM-12]).
- `docs/plans/2026-07-06-taut-summon-plan.md` — this plan.
- `docs/plans/2026-07-06-taut-summon-spec-draft.md` — the reviewed spec draft.
- `docs/implementation/05-taut-summon-architecture.md` — the summon
  architecture doc (Phase E).

**Modified (tracked):**

- `.github/workflows/test.yml` — summon install + test/lint/type steps.
- `README.md` — Summon Extension usage section, Roadmap "shipped" update,
  Development extension gate paths.
- `CHANGELOG.md` — Unreleased summon note (Phase E).
- `docs/implementation/02-repository-map.md` — summon rows (Phase E).
- `docs/implementation/00-implementation-index.md` — summon doc entry (Phase E).
- `docs/specs/00-specs-index.md` — spec 04 entry (S1).
- `docs/specs/02-taut-core.md` — D2 ([TAUT-12.3]) delta.
- `docs/specs/03-identity-addressing-notifications.md` — D3 ([IAN-6.1]) delta.
- `pyproject.toml` — `[tool.uv.sources]` + dev extra wiring for the extension.
- `taut/cli.py` — the `summon`/`dismiss` delegation verbs (D4).
- `tests/test_cli.py` — delegation presence/absence tests (S2).
- `tests/test_docs_references.py` — `[SUM-*]` code family + extension-source
  scanning (S1).

Do not commit on the user's behalf; the uncommitted state is intentional.
