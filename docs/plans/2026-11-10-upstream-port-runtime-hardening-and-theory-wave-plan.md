# Upstream Port, Runtime Hardening, Python 3.12–3.15 Rotation, and Theory/Coalescing Wave Plan

- **Date:** 2026-11-10
- **Status:** promoted
- **Class:** 5+P (Class 5 spec-changing across specs `01`, `02`, `03`, `04`, `07`, and `08` + Class 4 hardening triggers for load-bearing `simplebroker`/`simplebroker-pg` floor raises, Python support-window rotation from `3.11–3.14` to `3.12–3.15`, vendored Weft `MultiQueueWatcher` concurrency/signal synchronization, OS process-liveness/zombie classification across identity and Summon single-driver claims, and operator-owned dump file permissions + `+P` process-changing modifier for `agent-theory @ e6ac579` guidance/gate propagation, dynamic Ruff `0.17.4` rule-inventory enforcement, and authorized `[DOM-14]` lessons coalescing)
- **Plan type:** implementation with spec revision, upstream porting, runtime bug remediation, agent-theory propagation, and authorized lessons coalescing
- **Owner:** Taut engineering

## Goal

Reconcile Taut's five workspace distributions (`taut-chat`, `taut-pg`, `taut-summon`, `taut-mcp`, `taut-tui`), vendored reactor base, runtime safety boundaries, developer/CI gates, program theory, and lessons memory with the upstream changes in `simplebroker` (`v8.8.1` / `simplebroker_pg v4.8.1`), `weft` (`v0.9.124`), and `agent-theory` (`e6ac579`), while rotating supported Python versions to `3.12`–`3.15` (dropping `3.11`).

Concretely, this plan delivers six dependency-ordered outcomes:

1. **Spec promotion first (Strategy A):** Promote exact normative updates in specs `01`, `02`, `03`, `04`, `07`, and `08` before code slices execute, using machine-verified `Replacement` blocks.
2. **Program theory, `agent-theory @ e6ac579` guidance/gates, agent inventory, and `[DOM-14]` lessons coalescing:** Update `docs/program-theory.md` with the four-measure `Verification` header, `Kind:` classifications on `[THEORY-5.A1]`–`[THEORY-5.A6]`, a `[THEORY-5.A4]` bare-citation fix, and `[REV-THEORY-004]`; propagate `agent-theory @ e6ac579` across `AGENTS.md`, runbooks, `skills/crystallize-program-theory/SKILL.md`, `bin/check-plan-status-index`, and `bin/check-doc-paths` (adapted to Taut's 4-column `## Plan Status Index`); port batched git checks to `bin/coalesce-check`; refresh `docs/implementation/03-agent-inventory.md`; and execute an authorized `[DOM-14]` coalescing sweep over `docs/lessons.md` (`26` post-watermark entries past `2026-08-18`) plus durable new lessons from this wave.
3. **Vendored `MultiQueueWatcher` re-pin (`9fc913c1` → Weft `0.9.124` / `62a4504b`):** Port upstream `_ensure_multi_activity_waiter` candidate cleanup, `replace_activity_waiter` installation, and `_topology_sigint_critical` protection (`4a8884cb`, plus removing the early `return` in `_ensure_wait_strategy_started`), evidence-gated `_has_pending_observation()` reads at wait entry, hint validation, and deadline-expiry returns (`956acab1` / `14d84f29`), and dynamic `_update_active_queues` `_queue_counts_as_wait_activity` eviction (`62a4504b`), preserving only `[TAUT-12.3]`'s two documented Taut divergence seams (`yield_strategy != "round_robin"` and `_TopologyStopping` at the three stop-rejection sites) and updating the AST/SHA-256 sync ledger in `docs/implementation/04-taut-architecture.md`.
4. **Runtime bug fixes across Core, Summon, Persistence, and MCP:**
   - Reject zombie and exited-but-open OS process handles in `taut/identity.py` (`_capture_psutil_process`, `start_time_token`, and `_capture_linux_process`) while preserving `ProcessInfo(..., start_time=None)` (`"indeterminate"`) when a live process's creation time cannot be read, so `capture_process()`, `member_presence()`, and `SummonState.claim_driver()` (`extensions/taut_summon/taut_summon/_state.py`) classify exited/zombie processes as dead without weakening unknown-token takeover protection (`weft` `a1c20ef3`, `57ba1724`).
   - Remove process-global `warnings.catch_warnings(record=True)` mutation from `taut/_config.py::load_config()` so concurrent `taut-mcp` workspace threads cannot lose or cross-contaminate Python warning filters.
   - Replace `tempfile.mkstemp` + `os.chmod(..., 0o600)` in `taut/persistence/_operations.py::dump_workspace()` with exclusive `0o666` same-directory staging (`os.open(..., O_WRONLY | O_CREAT | O_EXCL, 0o666)`) over the existing `"wb"` binary serialization/digest pipeline, governed by operator `umask` and parent-directory ACLs (`weft` `805e0dc1`, `[THEORY-2]`).
   - Remove the obsolete Python `3.11` leading-`--` parser workaround in `taut/commands/_protocol.py::CommandArgumentParser.parse_command_args()`.
   - Align `extensions/taut_mcp` imports on `from simplebroker.ext import PollingStrategy` and bring `extensions/taut_mcp/taut_mcp` + `_WorkspaceReactor` into `tests/test_architecture_boundaries.py`.
5. **Packaging (`simplebroker>=8.8.1`, `simplebroker-pg>=4.8.1`, Python `3.12`–`3.15`), Ruff `0.17.4` dynamic rule policy, dev scripts, and CI workflows:** Drop Python `3.11` and add Python `3.15` across all 5 `pyproject.toml` files, 4 retained `uv.lock` files, `bin/check-core-summon-wheel-matrix.py`, READMEs, and all 11 `.github/workflows/*.yml` files; replace static `tests/fixtures/ruff-enabled-rules.txt` with dynamic `ruff check --isolated --show-settings` rule derivation (`simplebroker` `6923276`); add Windows `PermissionError` retry to `bin/ruff_suppression_index.py` (`weft` `8085962a`); harden `taut/_scripts.py` Postgres readiness via TCP `psql -h 127.0.0.1` + failure container log capture + `docker rm -f -v` (`weft` `540707a3`, `b4afe36e`, `simplebroker` `4304873`); and isolate Windows runner temp paths onto `$env:RUNNER_TEMP` (`weft` `3ce155fc`).
6. **Final verification, theory-versus-code/spec audit refresh, and completed-work cross-family review.**

## Source Documents

### Repository Authority

- `docs/program-theory.md` — `[THEORY-1]` through `[THEORY-8]`, especially `[THEORY-2]` (operator-owned storage/permission boundary), `[THEORY-3]` (live watcher wake ownership), `[THEORY-5.A1]`–`[THEORY-5.A6]`, and `[REV-THEORY-001]`–`[REV-THEORY-003]`
- `docs/specs/product-section-registry.md` — canonical spec vs README ownership map
- `docs/specs/01-development-documentation-operating-model.md` — `[DOM-2]`, `[DOM-3]`, `[DOM-5]`, `[DOM-6]`, `[DOM-10.2]`, `[DOM-10.2.1]`, `[DOM-11]`, `[DOM-13]`, `[DOM-14]`, `[DOM-15]`
- `docs/specs/02-taut-core.md` — `[TAUT-3.4]`, `[TAUT-8.1]`, `[TAUT-8.3]`, `[TAUT-8.4]`, `[TAUT-8.5]`, `[TAUT-8.6]`, `[TAUT-9]`, `[TAUT-12.3]`, `[TAUT-12.5]`
- `docs/specs/03-identity-addressing-notifications.md` — `[IAN-3.2]`, `[IAN-3.3]`, `[IAN-8.2]`, `[IAN-10]`
- `docs/specs/04-summon.md` — `[SUM-4]`, `[SUM-5.4]`, `[SUM-8]`
- `docs/specs/05-taut-mcp.md` — `[MCP-3]`, `[MCP-9]`, `[MCP-10]`
- `docs/specs/07-agent-theory-and-program-theory.md` — `[AT-REF-1]` through `[AT-REF-5]`
- `docs/specs/08-persistence-io.md` — `[PIO-6.2]`, `[PIO-11]`
- `docs/implementation/02-repository-map.md`, `03-agent-inventory.md`, `04-taut-architecture.md`, `05-taut-summon-architecture.md`, `07-taut-mcp-architecture.md`
- `docs/coalescing.md` and `docs/lessons.md`
- `docs/agent-context/runbooks/writing-plans.md`, `hardening-plans.md`, `review-loops-and-agent-bootstrap.md`, `testing-patterns.md`, `adversarial-acceptance-probes.md`
- `skills/call-agent/SKILL.md`, `skills/coalescing/SKILL.md`, `skills/crystallize-program-theory/SKILL.md`

### Upstream Provenance Pins

- **`simplebroker @ 93d2aec`** (`v8.8.1` / `simplebroker_pg/v4.8.1`):
  - `8.5.1`–`8.6.2`: Waiter stop-event preservation (`QueueWatcher` / `QueueMoveWatcher`), `BrokerRunner.setup()` partial-init leak fix, `SQLRunner` fork-safety PID invalidation, SQLite/PG high-water & vacuum correctness.
  - `8.7.0` / `simplebroker-pg 4.7.0`: Pipelined `psycopg` batch ID allocation (`generate_timestamps`), `LISTEN` waiter data-connection release before sleeping, 30–60s jittered safety recheck (`PG_WAITER_SAFETY_RECHECK_SECONDS = (30.0, 60.0)`), Python `>=3.12` floor, Python `3.15` CI lane.
  - `8.8.0`–`8.8.1` / `simplebroker-pg 4.8.0`–`4.8.1`: Per-queue Postgres `LISTEN`/`NOTIFY` channels (`create_activity_waiter_for_queues` subscribes only to listed queues plus control channels), coalescing `QueueActivityWaiter` on `LISTEN` reconnect/poll, Ruff `0.17.4` dynamic rule derivation (`6923276`), batched `bin/coalesce-check` (`178822b`), `docker rm -f -v` anonymous volume cleanup (`4304873`).
- **`weft @ 0.9.124`**:
  - `62a4504b` (`weft/core/tasks/multiqueue_watcher.py`, incorporating `4a8884cb`, `956acab1`, `14d84f29` atop `9fc913c1`): `MultiQueueWatcher` `_ensure_multi_activity_waiter` `_topology_sigint_critical` / candidate-cleanup / `replace_activity_waiter` installation, evidence-gated `_has_pending_observation()` reads across `_wait_for_activity` / `_activity_hint_action` / `_readiness_action` (including deadline-expiry return), and `_update_active_queues` `_queue_counts_as_wait_activity` eviction.
  - `a1c20ef3` & `57ba1724`: `pid_is_live` zombie (`STATUS_ZOMBIE`) and Windows open-handle (`not proc.is_running()`) rejection.
  - `805e0dc1`: Operator-owned file permissions on `weft system dump` (`docs/plans/2026-10-15-operator-owned-permissions.md`).
  - `3ce155fc`: Windows CI `$env:RUNNER_TEMP` NVMe temp isolation.
  - `540707a3` & `b4afe36e`: Postgres test container TCP `psql -h 127.0.0.1` readiness check + container log dump on test failure.
  - `8085962a`: `bin/ruff_suppression_index.py` bounded `PermissionError` retry around `os.replace`.
  - `b7eed9f9`: `docs/program-theory.md` alignment with `agent-theory @ e6ac579`.
- **`agent-theory @ e6ac579`** (`4d791fd` README link follow-up is hub-only):
  - Four-part balance of written program theory, theory-versus-code/spec audit table, three directional rules (`theory is the ideal`, `specs describe what is currently in the code`, `plans morph code and specs closer to the ideal`), human-decided `MODULE-THEORY.md` boundary, Round-2 external review cap, `"promoted"` plan status, and `bin/check-doc-paths` `Replacement` block sync verification.

## Spec Baseline

- **Baseline commit:** `5b8e439` (`call-agent: add the verified agy (Antigravity) reviewer row`)
- **Promotion strategy:** **Strategy A — In-file edit before code** (`docs/agent-context/runbooks/writing-plans.md` §4c). Slice 0 applies every `Replacement` block below to its target spec file and updates `Promotion baseline:` below to the resulting Slice 0 commit SHA (or sets `spec promoted` in `docs/plans/README.md`) before Slice 1 begins.
- **Promotion baseline:** Slice 0 spec-promotion applied atop `5b8e439` (spec promoted)
- **Touched spec sections:**
  - `docs/specs/01-development-documentation-operating-model.md`: `[DOM-2]`, `[DOM-3]`, `[DOM-10.2]`, `[DOM-11]`, `[DOM-14]`, `## Related Plans`
  - `docs/specs/02-taut-core.md`: `[TAUT-3.4]`, `[TAUT-8.1]`, `[TAUT-8.3]`, `[TAUT-8.6]`, `[TAUT-9]`, `## Related Plans`
  - `docs/specs/03-identity-addressing-notifications.md`: `[IAN-3.2]`, `[IAN-8.2]`, `## Related Plans`
  - `docs/specs/04-summon.md`: `[SUM-8]`, `## Related Plans`
  - `docs/specs/07-agent-theory-and-program-theory.md`: `[AT-REF-2]`, `[AT-REF-3]`, `## Related Plans`
  - `docs/specs/08-persistence-io.md`: `[PIO-6.2]`, `## Related Plans`

## Proposed Spec Delta

Every `Replacement` block below is exact post-promotion text for its backticked target file, verified mechanically by `bin/check-doc-paths` once Slice 0 promotes the spec delta.

### 1. `docs/specs/01-development-documentation-operating-model.md`

#### 1a. `[DOM-2]` and `[DOM-3]` — directional rules and human-decided `MODULE-THEORY.md` (`L36–80`)

Replacement (`docs/specs/01-development-documentation-operating-model.md`):
```markdown
- `docs/program-theory.md`: the conceptual identity of **this product** — the
  written account of what kind of system Taut is, why it has its shape, what it
  deliberately refuses to do, and what evidence would show that account is
  wrong. Program theory **frames** interpretation, placement, and the direction
  in which plans move specs and code (`[AT-REF-3]`); it is not a behavioral
  contract (do not silently break active spec clauses mid-edit, and do not
  treat a spec or plan that pulls away from the theory as final).
```

Replacement (`docs/specs/01-development-documentation-operating-model.md`):
```markdown
**Module theory** (conventional path `MODULE-THEORY.md` next to owning code) is
a human-decided scoped extension of the product program theory for a module that
is weakly coupled to the rest of the program and has theory-level invariants
applying only to that module (`[AT-REF-2]`). It is not a separate taxonomy tier
and is loaded only on entry to that module, not at every session start.

## 3. Agent Startup Context [DOM-3]

Program theory loads first among conceptual surfaces (see [DOM-2]). Three
directional rules govern how theory, specs, and plans interact (`[AT-REF-3]`):
the program theory is the ideal, specs describe what is currently in the code,
and plans morph code and specs closer to the ideal. When the active contract and
code disagree, the presumption is a code bug; when a spec or plan pulls away
from the theory, surface the drift and revise the spec or theory explicitly.
```

#### 1b. `[DOM-10.2]` and `[DOM-10.2.1]` — dynamic Ruff `0.17.4` rule-inventory derivation across all three `[tool.ruff]` owners and `[RUFF-SUP-078]` (`DTZ006`) retirement (`L346–358`, `L510–511`, `L528`)

Replacement (`docs/specs/01-development-documentation-operating-model.md`):
```markdown
Exact dependency pins are permitted only for a separately documented concrete
need; no current dependency has one. The root, MCP, and TUI Ruff configurations
continue to own the reviewed stable-default rule inventory and suppression
policy.
`pyproject.toml`, `extensions/taut_mcp/pyproject.toml`, and
`extensions/taut_tui/pyproject.toml` own their respective Ruff configuration;
all three enable Ruff's stable defaults and extend them with
`E`, `W`, `F`, `I`, `B`, `C901`, `C4`, and `UP`, use
`mccabe.max-complexity = 10`, ignore only `E501` and `B008`, and keep preview
rules opt-in. All three configurations must resolve the exact effective rule set
derived dynamically from the pinned Ruff binary's isolated default rule set
(`ruff check --isolated --show-settings`) unioned with those reviewed rule
families minus the declared global ignores. A Ruff selection or floor change
must update manifest ranges and retained locks in one reviewed change and re-run
the raw suppression audit before adoption.
```

Replacement (`docs/specs/01-development-documentation-operating-model.md`):
```markdown
| `[RUFF-SUP-076]` | `SIM115` | `3` directives; raw: `SIM115=3` | Stderr handles stay open for exactly the subprocess lifetime and close through the existing lifecycle owner | Driver-process and live-harness cleanup tests | Indenting whole process scenarios under `with` blocks or adding an `ExitStack` owner solely for lint | Independent review passed; user-approved exact fields 2026-08-05. |
| `[RUFF-SUP-079]` | `FURB122` | `1` directive; raw: `FURB122=1` | GitHub output records remain an explicit local one-record-per-write loop | Release-publication output tests | A generator passed to `writelines`, which decreases locality without changing ownership or behavior | Independent review passed; user-approved exact fields 2026-08-05. |
```

Replacement (`docs/specs/01-development-documentation-operating-model.md`):
```markdown
Global raw-`noqa` inventory: `BLE001=130`, `C901=34`, `F401=1`, `FLY002=16`, `FURB122=1`, `LOG001=1`, `N999=6`, `PYI041=1`, `SIM102=1`, `SIM115=3`, `SIM117=5`, `TRY004=11`
```

#### 1c. `[DOM-11]` — causal-premise review check, `Replacement` sync gate, and Round-2 external review cap (`L629–645`)

Replacement (`docs/specs/01-development-documentation-operating-model.md`):
```markdown
- the reviewer receives the governing spec, active plan, relevant
  implementation note, and touched files, plus any standing invariants or
  refused alternatives in force for the touched surface
- the review focuses on errors, bad ideas, latent ambiguities, performative
  overengineering — process, abstraction, or ceremony that does not address
  a real risk or improve correctness — whether the plan's causal premise holds
  in the code and its proposed proof is falsifiable, and whether a different
  engineer could implement the plan confidently and correctly; when reviewing a
  plan, analyze the plan as a whole, including all amendments, with two lenses:
  (1) is this what an expert developer would do and think well-crafted or
  elegant? (2) is there a known algorithm or computer science principle that
  should be applied here?
- the authoring agent considers each review point explicitly
- the authoring agent either updates the work or records why the current path
  remains the best choice, and verifies that every `fixed in plan` disposition
  is reflected in the plan's task list and code snippets before closing the
  review loop (backed by `bin/check-doc-paths` verifying that promoted
  `Replacement` fenced blocks appear in their target files); when a review
  returns `PASS` or `no blocker`, the loop closes after the author applies
  dispositions, verifies them locally, and `bin/check-doc-paths` passes — do not
  run follow-up external review rounds merely to re-verify non-blocking edits
  (a second round is warranted only after `BLOCKED` / `blocker: F<ids>` or when
  scope, invariants, or authority change after review)
```

#### 1d. `[DOM-14]` and `## Related Plans` — closed status vocabulary adds `promoted` (`L753–761`, `L967–971`)

Replacement (`docs/specs/01-development-documentation-operating-model.md`):
```markdown
- enumerable coalescing metadata uses an executable gate. In this repository,
  every plan file appears exactly once in a structured status index with an
  allowed lifecycle status and explicit exemplar marker. The closed status
  vocabulary is `draft`, `active`, `promoted`, `status-review`, `completed`,
  `superseded`, and `retired-pending`; `status-review` is a conservative
  maintenance quarantine, not a completion state. The exemplar field is exactly
  `yes` or `no`. Missing rows, duplicate rows, nonexistent-path rows, unknown
  statuses, unknown exemplar values, and malformed status tables fail the gate.
  A sweep repairs gate failures before trusting the affected trigger count
```

Replacement (`docs/specs/01-development-documentation-operating-model.md`):
```markdown
## Related Plans

- `docs/plans/2026-11-10-upstream-port-runtime-hardening-and-theory-wave-plan.md`:
  propagates `agent-theory` @ `e6ac579`, dynamic Ruff `0.17.4` rule-inventory
  verification, `bin/check-doc-paths` `Replacement` sync checking, batched
  `bin/coalesce-check` git probes, and the 2026-11-10 lessons coalescing sweep.
- `docs/plans/2026-10-14-agent-theory-delta-wave-plan.md`: propagates the
  2026-10-14 `agent-theory` hub delta (`0423923..8f41a9d`).
```

### 2. `docs/specs/02-taut-core.md`

#### 2a. `[TAUT-3.4]` — `simplebroker>=8.8.1` and `simplebroker-pg>=4.8.1` floors and mixed-version `taut-pg` rollout note (`L471`, `L502–510`)

Replacement (`docs/specs/02-taut-core.md`):
```markdown
  The `simplebroker>=8.8.1` floor is load-bearing. Version 5.2.0 supplies the
  reference ownership model, 5.2.2 first passed Taut's persistent-owner
```

Replacement (`docs/specs/02-taut-core.md`):
```markdown
  API to v8. Version 8.4.0 adds bounded native waits and coalescing local
  activity notification for the shared reactor. Version 8.8.1 and the matching
  `simplebroker-pg>=4.8.1` PostgreSQL line add waiter stop-event preservation,
  `BrokerRunner.setup()` partial-initialization cleanup, fork-safe SQL runner
  invalidation, pipelined PostgreSQL batch ID generation, quiet `LISTEN` waiter
  data-connection release with a 30–60 second jittered safety recheck,
  reconnect-coalescing `QueueActivityWaiter`, and per-queue PostgreSQL
  `LISTEN`/`NOTIFY` channels scoped to the exact queue set passed to
  `create_activity_waiter_for_queues` (making every reactor's registration of
  `taut.cache_stale` in its subscribed queue set load-bearing on PostgreSQL).
  On shared PostgreSQL targets, upgrade long-lived watchers (`taut watch`,
  Summon drivers, `taut-mcp`, `taut-tui`) before or alongside `taut-pg` 4.8+
  writers: `simplebroker-pg` 4.7.x listeners subscribe only to the schema-wide
  channel and rely on their 30–60 second safety recheck until upgraded. Ordinary
  generated writes remain FIFO-like because their ids are monotonic. Exact
```

#### 2b. `[TAUT-8.1]`, `[TAUT-8.3]`, `[TAUT-8.6]`, `[TAUT-9]`, and `## Related Plans` (`L1254`, `L1562–1566`, `L1942–1947`, `L2062–2079`, `L3133–3138`)

Replacement (`docs/specs/02-taut-core.md`):
```markdown
| `system dump --output FILE` / `system load --input FILE [--dry-run]` | Actor-free full-workspace persistence maintenance under spec 08. Dump writes an unredacted composite logical backup using ordinary OS and operator file-permission policy ([PIO-6.2]); load preflights or restores it into a fresh target. | 0 success; 1 usage/validation/conflict/I/O/backend/apply error; 2 missing input |
```

Replacement (`docs/specs/02-taut-core.md`):
```markdown
Core runtime dependencies: exactly `simplebroker>=8.8.1` and `psutil`. The
optional `taut-pg` extension adds `simplebroker-pg>=4.8.1` and its driver
dependencies in the same environment as Taut. Python ≥ 3.12. The CLI uses
argparse, not a CLI framework.
```

Replacement (`docs/specs/02-taut-core.md`):
```markdown
`REMAINDER` action, which argparse does not support in intermixed mode. The
default remains unchanged for every adapter that does not opt in. A leading
literal `--` still uses ordinary parsing because CPython's intermixed parser
before 3.12.8 and 3.13.1 loses the required positionals in that shape; the
separator and every later option-shaped token remain literal as required by
dispatch.
```

Replacement (`docs/specs/02-taut-core.md`):
```markdown
Verification must include source-tree and installed-wheel invocation, built-in
parity, entry-point install/uninstall, duplicate/broken/incompatible providers,
literal/global grammar on the oldest supported Python (3.12), exit classes,
traceback absence, and isolated `sys.modules` import floors for version, help,
ordinary messaging, watcher, and extension commands.

## 9. Trust Model [TAUT-9]

Taut's trust model is deliberately weak, and the documentation must say so
plainly rather than imply otherwise:

- Everyone who can open the file is root of the chat. `.taut.db` and
  `taut system dump` outputs are created under the operating system's and
  operator's permission policy (`umask` and inherited directory ACLs); Taut
  does not narrow or `chmod` them ([THEORY-2], [PIO-6.2]). Operators exporting
  dumps should write into a restricted directory or set an appropriate `umask`,
  because dumps carry continuity tokens and unredacted chat history. Any process
  that can read/write the database can read all history, post as anyone (`--as`
  requires no proof), move cursors, and edit tables with sqlite3.
```

Replacement (`docs/specs/02-taut-core.md`):
```markdown
## Related Plans

- `docs/plans/2026-11-10-upstream-port-runtime-hardening-and-theory-wave-plan.md`
  — raises the supported broker floors to `simplebroker>=8.8.1` and
  `simplebroker-pg>=4.8.1`, rotates supported Python versions to `3.12`–`3.15`,
  re-pins vendored `MultiQueueWatcher` to Weft `0.9.124` (`62a4504b`), aligns
  dump file permissions with operator-owned policy, and makes `load_config()`
  thread-safe.

- `docs/plans/2026-09-28-simplification-and-hot-path-plan.md` — binds one
```

### 3. `docs/specs/03-identity-addressing-notifications.md`

#### 3a. `[IAN-3.2]`, `[IAN-8.2]`, and `## Related Plans` (`L146–148`, `L844–847`, `L1068–1072`)

Replacement (`docs/specs/03-identity-addressing-notifications.md`):
```markdown
capturing process lifetime. A process whose start time cannot be read
has no token (`start_time` is null) and cannot be an `agent_process` anchor,
while remaining distinguishable from a missing process so [SUM-8] treats live
unreadable evidence as indeterminate. An exited or zombie process
(`psutil.STATUS_ZOMBIE`, `not proc.is_running()`, or Linux `/proc/<pid>/stat`
state `'Z'`) whose unreaped process-table entry or open OS handle still keeps
its PID and creation timestamp readable is not a live process:
`capture_process()` returns `None` so presence, anchor capture, and [SUM-8]
single-driver liveness classify it as gone/dead rather than alive or
indeterminate.
```

Replacement (`docs/specs/03-identity-addressing-notifications.md`):
```markdown
Taut requires `simplebroker>=8.8.1` and `taut-pg` requires
`simplebroker-pg>=4.8.1`, the same floors as the core runtime dependency
contract. This compatible pair preserves the atomic write ids,
```

Replacement (`docs/specs/03-identity-addressing-notifications.md`):
```markdown
## Related Plans

- `docs/plans/2026-11-10-upstream-port-runtime-hardening-and-theory-wave-plan.md`
  — rejects exited and zombie OS process entries in `capture_process()` and
  reconciles the `simplebroker>=8.8.1` / `simplebroker-pg>=4.8.1` floors.
- `docs/plans/2026-09-28-simplification-and-hot-path-plan.md`
```

### 4. `docs/specs/04-summon.md`

#### 4a. `[SUM-8]` and `## Related Plans` (`L1011–1016`, `L1663–1668`)

Replacement (`docs/specs/04-summon.md`):
```markdown
- **Single-driver guard:** `run` refuses when the ledger row shows a
  live driver (pid + start-time still alive on a running, non-zombie process,
  using the same [IAN-3.2] `capture_process()` liveness rule as presence so an
  exited or zombie OS process entry is classified `dead` and never blocks
  re-summon). Two drivers injecting into two harness sessions as one
  member would double-speak (L2: a person is in one place). `--takeover`
  replaces dead or abandoned driver evidence.
```

Replacement (`docs/specs/04-summon.md`):
```markdown
## Related Plans

- `docs/plans/2026-11-10-upstream-port-runtime-hardening-and-theory-wave-plan.md`
  — aligns [SUM-8] driver liveness with [IAN-3.2] zombie/exited-handle rejection
  and re-pins the shared reactor base to Weft `0.9.124` (`62a4504b`).

- `docs/plans/2026-09-24-summon-controlling-terminal-and-live-lane-plan.md`
```

### 5. `docs/specs/07-agent-theory-and-program-theory.md`

#### 5a. `[AT-REF-2]`, `[AT-REF-3]`, and `## Related Plans` — port `agent-theory @ e6ac579` four-way balance, human-decided module theory, and directional rules (`L100–151`, `L197–202`)

Replacement (`docs/specs/07-agent-theory-and-program-theory.md`):
```markdown
A quick self-test: when the system misbehaves, do you feel *betrayed by an
invariant you know*, or *surprised by a system you do not really own*?

### The four-way balance of a written program theory

Writing a good `docs/program-theory.md` is a balancing act because the document
must do four things at the same time:

1. **Stay general enough that changing implementations remain measurable against
   it.** If you replace an internal algorithm, storage layout, or helper module,
   you should still be able to evaluate the new implementation against the same
   program theory without rewriting the theory first. The concrete instrument for
   that measurement is a **theory-versus-code (and theory-versus-spec) audit
   table**—owned by the product owner, recorded in the crystallization or
   Class-5 plan (or `docs/lessons.md`), run at `skills/crystallize-program-theory`
   confirmation when code or specs already exist, and refreshed at each release
   or Class-5 completion alongside the possession check (carrying forward
   unchanged rows by reference while re-auditing touched claims and
   boundaries)—mapping each theory claim and identity invariant against current
   specs and code as aligned, drifted (to be morphed via a plan), or evidence
   that the theory itself needs revision.
2. **Be specific enough to be more than a list of aphorisms.** Generic advice
   (*"keep it simple"*, *"prefer explicit over implicit"*) cannot tell an agent
   or engineer whether a concrete feature proposal belongs in this program or
   violates its shape.
3. **Record invariants that are core to the identity of the product—the choices
   that shape the entire program.** These **identity (theory-level) invariants**
   are the commitments that make the system what it is across rewrites (for
   example, who owns process lifecycles, where trust boundaries sit, or what
   guarantee never bends for convenience): many parts of the codebase quietly
   depend on them, an agent must not casually "simplify" them away, and if they
   change, the program starts to become something else. They stay distinct from
   the exact wire formats, flags, and state tables in `docs/specs/`.
4. **Record negative knowledge in two parts:**
   - *What the product is not* — category and boundary refusals that stop scope
     creep and overlap with adjacent tools.
   - *What paths were tried and discarded* — empirical dead ends (`[THEORY-5.A*]`),
     so future humans and agents do not spend cycles re-discovering why a
     plausible approach failed.

A useful—though incomplete—analogy is the **Zen of Python** (`PEP 20`). The Zen
of Python came along early enough in Python's development that it guided an
entire generation of developers: it introduced the concept of being *"Pythonic"*
with enough specificity that people could spot non-Pythonic code, while staying
general enough to support a broad ecosystem. Whether a program theory is written
early or after code already exists changes the first work it has to do: written
early (like `PEP 20`), it guides new specs and code as they are built;
crystallized after a codebase has already grown, its immediate job is to audit
existing specs and code against the ideal and surface what needs to be morphed
or cut.

Even so, a product's `docs/program-theory.md` must be **more specific and
fleshed-out than the Zen of Python** for two reasons:

- **A product is narrower and more opinionated than an entire language
   interpreter.** It solves a specific problem with specific boundaries,
   composable operations, and whole-shape commitments.
- **Coding agents have no cultural apprenticeship.** Human Python developers
   learned how to weigh competing aphorisms through years of community review. A
   coding agent starts each session cold; if the tie-breakers, identity
   invariants, and discarded paths are not written down, the agent will use
   generic aphorisms to rationalize whatever local patch it just generated.

### Product theory vs. hub theory

Every repository has one `docs/program-theory.md`, and it always describes
**that repository**:

| Repository | What `docs/program-theory.md` describes |
|------------|-----------------------------------------|
| **A product or library repository** | That product's problem, feel/idiom, composable operations, concepts, ownership boundaries, non-goals, and falsifiers. |
| **The `agent-theory` hub repository** | The guidance system itself (how the process, documents, and gates work). |

When you install the starter kit into a product repository, the installer
writes a short `Status: Stub` file at `docs/program-theory.md`. Replace that
stub with your product's own theory before committing product behavior or
architecture. Never copy the hub's guidance theory into a product repository as
if it were the product's identity.

### Extending the model with module theory

Keep your top-level `docs/program-theory.md` short so every session can read it
in a few minutes. Extending the project theory with a **module theory** file
(typically `<module>/MODULE-THEORY.md` next to that code) is ultimately the
human owner's decision: use one only when a specific module is weakly coupled to
the rest of the program and has theory-level invariants that apply only to that
module—never to excuse a subsystem that diverged from a single whole-program
theory (and never for routine subsystem rules that belong in `docs/specs/` or
`docs/implementation/`). Agents read a module theory only when their task enters
that module, not at every session start.

---

## How program theory differs from other documents [AT-REF-3]

Each document surface in the repository answers a different question:

| Document surface | Question it answers |
|------------------|---------------------|
| **Program theory** (`docs/program-theory.md`, `MODULE-THEORY.md`) | What is the conceptual **ideal** of this system or module? What is its feel/idiom, core composable operations, and **identity invariants** (the choices that shape the entire program)? Why do these concepts, boundaries, non-goals, and discarded paths exist? |
| **Process and operating model** (`[DOM-*]`, `docs/agent-context/`, `skills/`) | How do humans and agents classify tasks, write plans, run reviews, verify changes, and maintain docs? |
| **Product contracts** (`docs/specs/`, authoritative README sections) | What exact behavior, flags, schemas, and **contract invariants** are in the code **right now**? |
| **Implementation docs** (`docs/implementation/`) | Why is the current code structured this way, and where are the key edit points? |
| **Code, tests, and gates** | How does the system run, and what automated checks prove it works? |
| **Plans and decision records** (`docs/plans/`, `[THEORY-5.A*]` / `[REV-*]`) | How are we morphing the code and specs closer to the program theory, and which alternatives were rejected or revised? |

Three directional rules govern how program theory, specs, and plans interact:

- **The program theory is the ideal** — what the software is aiming to be.
- **Specs describe what is currently in the code** — the concrete behavioral
  contract for the current implementation (not an unbuilt wishlist; a spec leads
  the code only across an active plan's spec-promotion slice or when a bug
  violates the contract).
- **Plans morph the code (and the specs) closer to the ideal.**

Note:
1. If the specification or code is pulling away from the theory, the presumption
   is that the specs or code are not properly moored in the theory. If the code
   and the spec disagree, then the presumption is that the code has a bug.
2. Never mistake a current spec or plan for "what has been decided" and try to
   justify it when it falls short of the theory. Everything—including the theory
   itself (`[REV-*]`)—can be revised as implementation and experience teach us
   more. When a spec clause itself is stale or when experience building and
   operating the code suggests a better path, then use a plan to fix the spec
   itself.

This file lives in `docs/specs/` as a **reference primer** alongside the
operating-model spec (`01-development-documentation-operating-model.md`). It is
not a behavioral specification for a product.
```

Replacement (`docs/specs/07-agent-theory-and-program-theory.md`):
```markdown
## Related Plans

- `docs/plans/2026-11-10-upstream-port-runtime-hardening-and-theory-wave-plan.md`
  — propagates the four-way balance of written program theory, theory-versus-code
  audit table, human-decided module-theory boundary, and three directional rules
  from `agent-theory` @ `e6ac579`
- `docs/plans/2026-10-14-agent-theory-delta-wave-plan.md` — propagates the
```

### 6. `docs/specs/08-persistence-io.md`

#### 6a. `[PIO-6.2]` and `## Related Plans` — operator-owned staging and output permissions (`L489–497`, `L845–849`)

Replacement (`docs/specs/08-persistence-io.md`):
```markdown
### [PIO-6.2] File lifecycle and permissions

Core creates a fresh, exclusive staging file in the destination directory with
`open(candidate, "xb")`: `O_CREAT | O_EXCL` with ordinary `0666` open mode, so
the operating system applies the caller's `umask` and any inherited parent
directory ACLs, without calling `chmod` or forcing `0600` ([THEORY-2]). The
staging file is binary on every platform (`O_BINARY` on Windows), so no newline
translation alters the digested bytes. Core
flushes and fsyncs the staging file where supported, verifies its own final
digest, then atomically replaces the named output via `os.replace`, publishing a
new inode with that freshly created mode rather than copying a previous inode's
manual `chmod`. Failure before replacement leaves any older output untouched and
removes only a staging file that this attempt created; an unexpected `O_EXCL`
collision fails closed without unlinking the colliding path. No partially
written dump appears at the final path.
```

Replacement (`docs/specs/08-persistence-io.md`):
```markdown
## Related Plans

- `docs/plans/2026-11-10-upstream-port-runtime-hardening-and-theory-wave-plan.md`:
  replaces forced `0600` dump permissions with operator-owned `umask`/ACL staging
  under [PIO-6.2] and [THEORY-2].
- `docs/plans/2026-09-28-simplification-and-hot-path-plan.md`
```

---

## Theory-Versus-Code and Theory-Versus-Spec Audit Table

Per `[AT-REF-2]` (`agent-theory @ e6ac579`), this table audits Taut's `[THEORY-1]`–`[THEORY-7]` commitments and identity invariants against specs and code at baseline `5b8e439` and records the verified post-implementation alignment across Slices 0–5:

| Theory section / invariant | Spec surface | Code surface | Baseline status | Action in this plan | Post-implementation status |
|---|---|---|---|---|---|
| `[THEORY-1]` Installable with `pipx`, deletable with `rm`; record CLI `--json`, native rich/protocol transports | `[TAUT-2]`, `[TAUT-8]`, `[MCP-3]`, `[TUI-1]` | `taut/cli.py`, `extensions/taut_mcp`, `extensions/taut_tui` | Aligned | Preserve; drop Python `3.11` shim in `taut/commands/_protocol.py:73-78` as supported floor advances to `3.12`–`3.15` | **Aligned** (verified on Python `3.12` and `3.14`) |
| `[THEORY-2]` Workspace is storage; **storage/permission boundary is chosen by the operator, never managed by Taut** | `[TAUT-8.1]`, `[TAUT-9]`, `[PIO-6.2]` | `taut/persistence/_operations.py:345-360` (`dump_workspace`) | **Drifted** (`[PIO-6.2]` and `[TAUT-9]` mandated forced `0600` on `taut system dump`, breaking group-readable backup directories and ACL inheritance, same defect fixed in Weft `805e0dc1`) | **Morph spec + code** in Slice 0 & Slice 3 to exclusive `0o666` open over the `"wb"` binary serialization/digest pipeline, governed by operator `umask`/ACLs; record `[REV-THEORY-004]` | **Aligned** (`os.open(..., O_WRONLY \| O_CREAT \| O_EXCL, 0o666)` verified under `umask` `0027` and `0077`) |
| `[THEORY-2]` Queue is history (peek + sidecar cursor); notification inboxes are consumable pointers (`[THEORY-5.A1]`) | `[TAUT-7.2]`–`[TAUT-7.6]`, `[IAN-7]` | `taut/client/_messages.py`, `taut/client/_notifications.py` | Aligned | Preserve | **Aligned** |
| `[THEORY-2]` / `[THEORY-3]` Identity is opaque `member_id`; process evidence identifies and drives presence/driver liveness without authenticating (`[THEORY-5.A3]`) | `[IAN-3.2]`, `[SUM-8]` | `taut/identity.py`, `extensions/taut_summon/taut_summon/_state.py` | **Drifted in code & underspecified on zombies** (`_capture_psutil_process`, `start_time_token`, and `_capture_linux_process` accept zombie/exited processes whose PID/creation time remain readable, reporting dead agents `"here"` and blocking re-summon without `--takeover`) | **Morph spec + code** in Slice 0 & Slice 3 to reject `STATUS_ZOMBIE`, `not proc.is_running()`, and `/proc/<pid>/stat` state `'Z'` (`None` -> `"dead"`) while keeping unreadable live `start_time=None` as `"indeterminate"` | **Aligned** (verified with real unreaped POSIX zombie child across `taut who` and `claim_driver`) |
| `[THEORY-3]` Live chat watcher has one foreground wake path (`LISTEN`/`NOTIFY` on PG, `PollingStrategy` on SQLite, latch for OS/PTY, deadline for clock) | `[TAUT-8.4]`, `[TAUT-8.5]`, `[TAUT-12.3]` | `taut/watcher.py`, `extensions/taut_summon/taut_summon/_reactor.py`, `extensions/taut_mcp/taut_mcp/_workspace_reactor.py` | **Drifted behind upstream base** (pinned to Weft `9fc913c1`, missing `4a8884cb` `_ensure_multi_activity_waiter` `_topology_sigint_critical` / candidate cleanup / `replace_activity_waiter`, `956acab1`/`14d84f29` evidence-gated `_has_pending_observation()` reads at entry, hint validation, and deadline return, `62a4504b` `_queue_counts_as_wait_activity` eviction, and `simplebroker-pg` `4.8.1` per-queue `LISTEN`) | **Morph spec + code** in Slice 0, Slice 2, & Slice 4: re-pin `taut/watcher.py` to Weft `0.9.124` (`62a4504b:weft/core/tasks/multiqueue_watcher.py`), bump `simplebroker>=8.8.1` / `simplebroker-pg>=4.8.1`, preserve `taut.cache_stale` subscription | **Aligned** (AST & SHA-256 parity script green; SQLite + PG suites green) |
| `[THEORY-4]` Extensions widen one model (`taut-pg`, `taut-summon`, `taut-mcp`, `taut-tui`) over public seams | `[TAUT-12]`, `[MCP-9]` | `taut/_config.py`, `extensions/taut_mcp/taut_mcp/_workspace_reactor.py`, `_process_reactor.py` | **Minor code drift** (`load_config()` mutates process-global `warnings.filters` across `taut-mcp`'s 8 threads; `taut_mcp` imports `PollingStrategy` from `simplebroker.watcher` instead of `simplebroker.ext` and is absent from `tests/test_architecture_boundaries.py`) | **Fix code + boundary gate** in Slice 3 | **Aligned** (`tests/test_constants.py` & `tests/test_architecture_boundaries.py` green) |
| `[THEORY-5.A2]`, `[THEORY-5.A4]`, `[THEORY-5.A5]`, `[THEORY-5.A6]` Native search analyzers; no required daemon (fix bare `(see A4)` citation at `docs/program-theory.md:147`); cursor-after-insert; destructive-op preconditions | `[SRCH-2.3]`, `[TAUT-2]`, `[TAUT-7.4]`, `[PIO-7]` | `taut/search/`, `taut/client/`, `taut/persistence/` | Aligned (one bare `A4` citation in `docs/program-theory.md:147`) | Preserve behavior; add `Kind:` tags and fix `(see [THEORY-5.A4])` in Slice 1 | **Aligned** |
| `[THEORY-7]` Product-section registry (`docs/specs/product-section-registry.md`) + `README.md` promises | `docs/specs/product-section-registry.md`, `README.md` | `README.md` | Needs floor sync when Python/`simplebroker` floors move | Update `README.md` Python `3.12`–`3.15` and `simplebroker>=8.8.1` lines in Slice 4 | **Aligned** |

---

## Context and Key Files

| Area | Files | Current structure & edit point |
|---|---|---|
| Normative specs | `docs/specs/01-development-documentation-operating-model.md`, `02-taut-core.md`, `03-identity-addressing-notifications.md`, `04-summon.md`, `07-agent-theory-and-program-theory.md`, `08-persistence-io.md` | Promoted in Slice 0 using the exact `Replacement` blocks above |
| Program theory & guidance | `docs/program-theory.md`, `AGENTS.md`, `docs/agent-context/README.md`, `docs/agent-context/runbooks/review-loops-and-agent-bootstrap.md`, `docs/agent-context/runbooks/writing-plans.md`, `skills/crystallize-program-theory/SKILL.md` | `agent-theory @ e6ac579` propagation, four-measure `Verification` header, `Kind:` labels on `[THEORY-5.A1]`–`[THEORY-5.A6]`, `[REV-THEORY-004]` |
| Doc/plan/coalescing gates & memory | `bin/check-plan-status-index`, `bin/check-doc-paths`, `bin/coalesce-check`, `docs/coalescing.md`, `docs/lessons.md`, `docs/implementation/03-agent-inventory.md`, `tests/test_plan_status_index.py`, `tests/test_docs_references.py`, `tests/test_coalesce_check.py` | Add `"promoted"` status; add `_plan_replacement_sync_failures()` adapted to Taut's 4-column `## Plan Status Index`; batch `coalesce-check` git object/path and reachability checks (`batch_object_info`, `reachable_commits`); refresh reviewer inventory; fold eligible post-`2026-08-18` lessons and advance watermark to `2026-09-25` |
| Vendored reactor & sync ledger | `taut/watcher.py`, `docs/implementation/04-taut-architecture.md`, `bin/ruff_suppression_index.py`, `tests/test_watcher.py`, `tests/helpers/base_reactor_sigint_probe.py` | Re-pin `MultiQueueWatcher` (`taut/watcher.py:105-1614`) from Weft `9fc913c1` to `62a4504b` (`weft/core/tasks/multiqueue_watcher.py`, `0.9.124`), keep `[TAUT-12.3]`'s two Taut divergence seams, refresh SHA-256 digests and AST check in `04-taut-architecture.md:768-815` |
| Core, Summon, Persistence, & MCP bug fixes | `taut/identity.py`, `extensions/taut_summon/taut_summon/_state.py`, `taut/_config.py`, `taut/persistence/_operations.py`, `taut/commands/_protocol.py`, `extensions/taut_mcp/taut_mcp/_workspace_reactor.py`, `extensions/taut_mcp/taut_mcp/_process_reactor.py`, `tests/test_identity.py`, `extensions/taut_summon/tests/test_state.py`, `tests/test_constants.py`, `tests/test_persistence_io.py`, `tests/test_command_registry.py`, `tests/test_command_syntax.py`, `tests/test_architecture_boundaries.py` | Zombie/exited process rejection (preserving `start_time=None` indeterminate classification); thread-safe `load_config()`; `0o666` exclusive `"wb"` dump staging in `dump_workspace()`; Python `3.11` `--` shim removal; `simplebroker.ext` import + `taut_mcp` architecture-boundary assertions |
| Packaging, Ruff `0.17.4`, dev scripts, & CI | `pyproject.toml`, `extensions/*/pyproject.toml` (4), `uv.lock`, `extensions/{taut_summon,taut_mcp,taut_tui}/uv.lock`, `tests/test_ruff_policy.py`, `tests/fixtures/ruff-enabled-rules.txt` (delete), `bin/ruff_suppression_index.py`, `bin/check-core-summon-wheel-matrix.py`, `bin/release.py`, `taut/_scripts.py`, `README.md`, `extensions/{taut_pg,taut_summon}/README.md`, `tests/fixtures/taut_command_plugin/pyproject.toml`, `.github/workflows/*.yml` (11), `tests/test_core_summon_wheel_matrix.py`, `tests/test_dev_scripts.py`, `tests/test_github_workflows.py`, `docs/implementation/{02-repository-map,04-taut-architecture,05-taut-summon-architecture,07-taut-mcp-architecture}.md` | Python `3.12`–`3.15` rotation, `simplebroker>=8.8.1` / `simplebroker-pg>=4.8.1`, dynamic Ruff `0.17.4` rule check, `ruff_suppression_index.py` `PermissionError` retry, TCP `psql` readiness + failure log dump + `docker rm -f -v`, Windows `$env:RUNNER_TEMP` isolation, SHA-pinned GitHub Actions refresh |

### Comprehension Check (Zero-Context Readiness)

1. **Why must `CACHE_STALE_QUEUE_NAME` (`taut.cache_stale`) stay in `queue_configs` on `TautWatcher` and `taut_mcp._WorkspaceReactor` even after porting Weft `62a4504b`?**
   - *Expected answer:* In `simplebroker-pg>=4.8.0`, `BackendPlugin.create_activity_waiter_for_queues(queues)` issues PostgreSQL `LISTEN` per subscribed queue channel rather than a single noisy schema-wide data channel. Removing `taut.cache_stale` from `queue_configs` would silently stop PostgreSQL watchers from waking on membership/topology invalidation hints.
2. **Why do we keep `SummonReactor._fetch_next_message()`'s `if not self._queue_counts_as_wait_activity(config): return None` guard (`extensions/taut_summon/taut_summon/_reactor.py:106-111`) after porting Weft `62a4504b`'s `_update_active_queues()` `_queue_counts_as_wait_activity` eviction?**
   - *Expected answer:* Upstream `_update_active_queues()` refreshes `_active_queues` via `self._queue_counts_as_wait_activity(self._queues[name])` between drain passes, whereas `SummonReactor` flips the boolean `self._delivery_pending = True` mid-pass inside its message callback; the `_fetch_next_message()` guard prevents an already-active non-control PEEK lane from claiming a second message later in that *same* dispatch pass while still allowing `config.name == self.control_queue_name` through.
3. **Why must `bin/check-doc-paths` NOT copy `agent-theory`'s `## Status Index` heading or `\bpromoted\b` regex verbatim?**
   - *Expected answer:* Taut's `docs/plans/README.md` uses `## Plan Status Index` with 4 columns (`Plan | Status | Exemplar | Note`), closed statuses `status-review` and `retired-pending`, and historical notes containing phrases like `"E2 process containment is promoted for implementation"`. Taut's parser must match `## Plan Status Index`, skip `{"draft", "completed", "superseded", "status-review", "retired-pending"}`, and match `\b(?:spec promoted|spec-promotion slice applied)\b` in the `Note` column (alongside `status_word == "promoted"` and `Promotion baseline:`).

---

## Invariants, Hidden Couplings, and Difference Register

### Standing Invariants That Must Not Move

1. **Operator-owned storage and permission boundary (`[THEORY-2]`, `[THEORY-5.A3]`):** Taut never `chmod`s `.taut.db` or `taut system dump` outputs and adds no authentication layer.
2. **Single foreground reactor wake path (`[THEORY-3]`, `[TAUT-8.5]`):** One arbiter owns queue wakes, OS/PTY latches, and clock deadlines; no background polling thread or second freshness timer is introduced.
3. **Two-divergence-seam budget on vendored `MultiQueueWatcher` (`[TAUT-12.3]`):** `taut/watcher.py`'s vendored `MultiQueueWatcher` class diverges from Weft `0.9.124` (`62a4504b:weft/core/tasks/multiqueue_watcher.py`) at **only two** documented seams across three methods: (a) rejecting `yield_strategy != "round_robin"` in `__init__`, and (b) raising `_TopologyStopping("watcher topology is stopping")` instead of `RuntimeError("watcher topology is stopping")` at the three synchronous stop-rejection sites. All copied class bodies must otherwise match `62a4504b` verbatim, proven by `docs/implementation/04-taut-architecture.md`'s AST comparison script and upstream SHA-256 pins (`713060f2880b401220505e82f9fad11916740a8355cad026f869ac61dfdbf086` for the full file; `792d34b26dd83d4b86b695e79d5e27130df510f39049fc6f6fac6b6b297ebd76` for `QueueMode`..EOF).
4. **Lockless `taut-pg` package (`[TAUT-12.5]`):** `extensions/taut_pg` intentionally has **no** tracked `uv.lock` (`tests/test_release_script.py`); never commit `extensions/taut_pg/uv.lock` and delete any untracked `extensions/taut_pg/uv.lock` created as a tool side effect.
5. **Preservation of concurrent active plans and untouched modules:** Do not alter `taut-tui` Summon modal/selection code or `taut/search` projection logic owned by `docs/plans/2026-10-15-deep-review-remediation-plan.md`, and do not invent local workarounds for the SimpleBroker strict-discovery seam deferred in `docs/plans/2026-09-24-cli-read-delivery-and-agent-recipes-plan.md`. When `taut/_scripts.py`, `pyproject.toml`, `tests/test_dev_scripts.py`, or `docs/plans/README.md` already carry adjacent edits, read the live file immediately before editing and merge cleanly without reverting sibling lines.

### Upstream-to-Taut Difference Register (Explicit Non-Ports)

| Upstream surface | Why it does not port to Taut | Governing authority |
|---|---|---|
| Weft manager / heartbeat / `TaskMonitor` / detached service lifecycle | Taut has no resident daemon or manager process | `[THEORY-5.A4]` |
| SimpleBroker CLI flags (`broker move`, `--json` command layer) | Taut embeds `simplebroker` / `simplebroker.ext`, never `simplebroker.commands` | `[TAUT-3.4]`, `[IAN-8.2]` |
| `agent-theory @ 4d791fd` root `README.md` adopter list | Hub-only repository index | `[AT-REF-5]` |
| `MODULE-THEORY.md` creation in Taut extensions | Extensions widen one whole-program model rather than defining weakly coupled local theories; `MODULE-THEORY.md` is owner-initiated only | `[THEORY-2]`, `[DOM-2]`, `[AT-REF-2]` |

---

## Rollout Sequencing, One-Way Doors, and Rollback

1. **Slice order is load-bearing:**
   - **Slice 0 (Spec promotion)** lands first so specs lead implementation only across the active plan's promotion boundary (`[AT-REF-3]`, `writing-plans.md` §4c).
   - **Slice 1 (Theory, `agent-theory @ e6ac579` gates, inventory, lessons coalescing)** lands second so `bin/check-plan-status-index` (`promoted`), `bin/check-doc-paths` (`Replacement` sync check), and `bin/coalesce-check` enforce invariants on every subsequent slice.
   - **Slice 2 (`MultiQueueWatcher` `62a4504b` re-pin)** and **Slice 3 (Core/Summon/Persistence/MCP runtime fixes)** land before dependency/Python floor rotation so behavioral regressions are isolated from lockfile/interpreter changes.
   - **Slice 4 (Python `3.12`–`3.15`, `simplebroker>=8.8.1`, `simplebroker-pg>=4.8.1`, Ruff `0.17.4`, dev scripts, CI workflows)** updates all manifests, locks, wheel-matrix bounds, and workflows together in one atomic compatibility wave.
   - **Slice 5 (Full verification, theory-vs-code audit confirmation, and Tier-1 completed-work review)** closes the plan.
2. **One-way doors and compatibility notes:**
   - **Dropping Python `3.11` (`requires-python = ">=3.12"`):** Published wheels after the next release will not install on Python `3.11` (PyPI retains prior `0.9.x` wheels for `3.11` users). Pre-release rollback is a clean `git revert` of Slice 4 + Slice 0's `3.12` lines.
   - **PostgreSQL per-queue `LISTEN`/`NOTIFY` (`simplebroker-pg>=4.8.1`):** Wire-compatible at the SQL schema level (still SimpleBroker schema 6 / backend API v8; zero DDL migration). On shared PostgreSQL deployments, `4.8.x` writers notify per-queue channels whereas `4.7.x` watchers listen only on the schema channel (falling back to their 30–60s safety recheck); `[TAUT-3.4]` and `extensions/taut_pg/README.md` document upgrading watchers before or with writers.
   - **Dump file permissions (`[PIO-6.2]`):** Wire format of `taut system dump` JSON is unchanged. Operators who previously relied on Taut forcing `0600` inside a world-readable directory (`/tmp` with `umask 0022`) now receive `0644` unless they set `umask 0077` or use a `0700`/`0750` backup directory, matching `.taut.db` and Weft `0.9.124`.
   - **Coalescing deletions in `docs/lessons.md`:** Reversible via git archive at `source 5b8e439` (`[DOM-14]`), gated by `bin/coalesce-check` verifying every cue SHA exists and is an ancestor of `main`.

## Deviation Log

| Slice | Deviation from plan | Reason | Scope / invariant impact |
|---|---|---|---|
| Slice 0 | Stop-gate runs `bin/check-dom15-fixtures` directly instead of `pytest tests/test_dom15_fixtures.py` | Taut's executable `[DOM-15]` fixture gate lives at `bin/check-dom15-fixtures` (`check-dom15-fixtures: ... OK`) rather than a `tests/test_dom15_fixtures.py` file | Stronger/exact repository gate; zero contract change |
| Slice 1 | Lessons fold cues pin `source f4275a6` (`origin/main` tip) rather than local-only `5b8e439` | `git diff f4275a6..5b8e439 -- docs/lessons.md` is empty, and `f4275a6` is published on `origin/main`, satisfying `skills/coalescing/SKILL.md` §3 cue portability without adding a `local-only pin` warning in `bin/coalesce-check` | Strictly stronger archive portability; identical pre-fold `docs/lessons.md` blob |

---

## Tasks

### Slice 0: Spec Promotion (`01`, `02`, `03`, `04`, `07`, `08`)

- **Objective:** Apply all normative spec updates in `## Proposed Spec Delta` before touching runtime or gate code (Strategy A).
- **Files:**
  - `docs/specs/01-development-documentation-operating-model.md`
  - `docs/specs/02-taut-core.md`
  - `docs/specs/03-identity-addressing-notifications.md`
  - `docs/specs/04-summon.md`
  - `docs/specs/07-agent-theory-and-program-theory.md`
  - `docs/specs/08-persistence-io.md`
  - `docs/plans/2026-11-10-upstream-port-runtime-hardening-and-theory-wave-plan.md` (`Promotion baseline:` field)
  - `docs/plans/README.md` (`Status` -> `promoted` or `Note` -> includes `spec promoted`)
- **Read first:** The exact target ranges in each of the six spec files above plus `docs/specs/product-section-registry.md`.
- **Steps:**
  1. Apply each `Replacement` block in `## Proposed Spec Delta` verbatim to its target file (`01`, `02`, `03`, `04`, `07`, `08`).
  2. Verify `docs/specs/product-section-registry.md` needs no ownership-row change (all six specs already own the edited sections; `README.md` floor promises are updated in Slice 4).
  3. Update `docs/plans/README.md` row note (or status once Slice 1 adds `promoted` to `bin/check-plan-status-index` — keep `Status: active` during Slice 0 until Slice 1 lands `"promoted"` in `ALLOWED_STATUSES`, and record `spec promoted` in `Note` + the Slice 0 commit SHA in `Promotion baseline:` once committed).
- **Stop-gate / verification:**
  - `uv run --no-sync pytest tests/test_docs_references.py && uv run --no-sync bin/check-dom15-fixtures`
  - `uv run --no-sync bin/check-plan-status-index`
  - `git diff --check -- docs/specs/ docs/plans/`
- **Done signal:** All six spec files contain the exact `Replacement` blocks, and documentation reference/citation tests pass.
- **Explicit staging list (when committing):** `git add docs/specs/01-development-documentation-operating-model.md docs/specs/02-taut-core.md docs/specs/03-identity-addressing-notifications.md docs/specs/04-summon.md docs/specs/07-agent-theory-and-program-theory.md docs/specs/08-persistence-io.md docs/plans/2026-11-10-upstream-port-runtime-hardening-and-theory-wave-plan.md docs/plans/README.md`

---

### Slice 1: Program Theory, `agent-theory @ e6ac579` Propagation, Gate Upgrades, Agent Inventory, and Lessons Coalescing

- **Objective:** Align `docs/program-theory.md`, shared agent-context docs/skills, `bin/check-plan-status-index`, `bin/check-doc-paths`, `bin/coalesce-check`, `docs/implementation/03-agent-inventory.md`, `docs/lessons.md`, and `docs/coalescing.md` with `agent-theory @ e6ac579` and `simplebroker @ 178822b`.
- **Files:**
  - `docs/program-theory.md`
  - `AGENTS.md`
  - `docs/agent-context/README.md`
  - `docs/agent-context/runbooks/review-loops-and-agent-bootstrap.md`
  - `docs/agent-context/runbooks/writing-plans.md`
  - `skills/crystallize-program-theory/SKILL.md`
  - `bin/check-plan-status-index` and `tests/test_plan_status_index.py`
  - `bin/check-doc-paths` and `tests/test_docs_references.py`
  - `bin/coalesce-check` and `tests/test_coalesce_check.py`
  - `docs/implementation/03-agent-inventory.md`
  - `docs/lessons.md` and `docs/coalescing.md`
- **Read first:**
  - `../agent-theory` commit `e6ac579` (`git -C ../agent-theory show e6ac579`)
  - `../weft` commit `b7eed9f9` (`git -C ../weft show b7eed9f9`)
  - `../simplebroker` commit `178822b` (`git -C ../simplebroker show 178822b`)
  - `docs/program-theory.md`, `docs/coalescing.md`, `docs/lessons.md`, `skills/coalescing/SKILL.md`
- **Existing helpers to reuse:** `tests/test_docs_references.py` (`_prose_lines`, `LINK_PATH_RE`, `BACKTICK_PATH_RE`), `bin/check-doc-paths::self_test()`.
- **Steps (RED -> GREEN):**
  1. **RED (`bin/check-plan-status-index`, `bin/check-doc-paths`, `bin/coalesce-check`):**
     - Add failing test in `tests/test_plan_status_index.py` asserting `"promoted"` is accepted in `ALLOWED_STATUSES` while an unknown status still fails.
     - Add failing probes in `bin/check-doc-paths::self_test()` and `tests/test_docs_references.py` for `_plan_replacement_sync_failures()`:
       - active plan with `Status: promoted` (or `Note` matching `\b(?:spec promoted|spec-promotion slice applied)\b` or `Promotion baseline: <sha>`) whose `Replacement (\`docs/specs/01-sample.md\`):` block matches target -> exit `0`;
       - same promoted plan whose `Replacement` snippet diverges from target -> exit `1`;
       - active *unpromoted* plan (`Promotion baseline: pending`, `Status: active`, `Note` without `spec promoted` — including a note saying `"slice E2 is promoted for implementation"`) -> skipped (`0`);
       - `completed`, `draft`, `superseded`, `status-review`, and `retired-pending` plans in Taut's 4-column `## Plan Status Index` -> skipped (`0`);
       - path traversal `Replacement (\`../outside.md\`):` or missing backticked path -> exit `1`.
     - Add failing unit tests in `tests/test_coalesce_check.py` proving batched git verification (`batch_object_info(expressions)` batching both `<sha>^{commit}` and `<sha>:<path>` expressions through one `git cat-file --batch-check=%(objectname) %(objecttype)` process + `reachable_commits(remote_ref)` through one `git rev-list <remote_ref>` process) catches missing SHAs, missing `<sha>:<path>` blobs, non-commit tags/blobs, and local-only/unreachable SHAs while accepting reachable history.
     - Run pytest on those three test files and observe RED failures.
  2. **GREEN (gates):**
     - Update `ALLOWED_STATUSES` in `bin/check-plan-status-index` to include `"promoted"`.
     - Implement `_load_plan_index_statuses`, `_is_plan_promoted`, and `_plan_replacement_sync_failures` in `bin/check-doc-paths`, keeping helper decomposition clean so every function stays within `C901 <= 10` (`bin/ruff_suppression_index.py` zero new suppressions) and matching `stripped == "## Plan Status Index"` + 4-column rows (`| Plan | Status | Exemplar | Note |`).
     - Port `batch_object_info(expressions)` and `reachable_commits(remote_ref)` from `simplebroker @ 178822b` (`bin/coalesce-check`) into Taut's `bin/coalesce-check`, retaining batching of both commit and `<sha>:<path>` object expressions.
     - Run `uv run --no-sync bin/check-doc-paths --self-test` and `uv run --no-sync bin/check-doc-paths` against the live repo to prove every `Replacement` block promoted in Slice 0 matches its live spec file!
  3. **Program theory & `agent-theory @ e6ac579` guidance updates:**
     - Update `docs/program-theory.md`:
       - Expand `Verification:` in the header (`L18–20`) to name the four verification instruments from `e6ac579` / Weft `b7eed9f9`: (1) owner endorsement, (2) cold-start transfer/comprehension probe, (3) `[THEORY-8]` revision/transfer log, and (4) the theory-versus-code and theory-versus-spec audit table refreshed at Class-5/release boundaries; add `Governing process: docs/specs/07-agent-theory-and-program-theory.md [AT-REF-1]–[AT-REF-5]`.
       - Fix bare `(see A4)` at `docs/program-theory.md:146-147` to `(see [THEORY-5.A4])`.
       - Add explicit `Kind:` lines (`Kind: boundary refusal`, `Kind: discarded path`, or `Kind: sequencing invariant`) to `[THEORY-5.A1]` through `[THEORY-5.A6]` so negative knowledge distinguishes category refusals from empirical dead ends (`[AT-REF-2]` item 4).
       - Append `### [REV-THEORY-004] Theory-versus-spec audit aligns dump file permissions with operator-owned boundary and classifies negative-knowledge kinds (2026-11-10)` under `[THEORY-8]`, recording how auditing `[PIO-6.2]`/`[TAUT-9]` against `[THEORY-2]` ("the boundary is chosen by the operator, never managed by Taut") surfaced the forced-`0600` dump permission drift alongside Weft `805e0dc1`.
     - Port the `agent-theory @ e6ac579` prose deltas into `AGENTS.md`, `docs/agent-context/README.md`, `docs/agent-context/runbooks/review-loops-and-agent-bootstrap.md` (Round-2 external review cap + causal-premise check), `docs/agent-context/runbooks/writing-plans.md` (`Replacement (\`<path>\`):` convention + `"promoted"` status), and `skills/crystallize-program-theory/SKILL.md` (four-part balance, taste-up-front anchors, theory-vs-code/spec audit table, human-decided `MODULE-THEORY.md`), preserving all Taut-local rules (`[DOM-11]` Tier-1 `skills/call-agent`, no-self-attribution, subagent scope).
  4. **Agent inventory refresh (`docs/implementation/03-agent-inventory.md`):**
     - Update `Last checked` from `2026-09-25` to `2026-11-10`; record observed live versions (`codex-cli 0.161.0` verified in enclosing-parent read-only review on 2026-11-10, `claude 2.1.293`, `grok 1.0.77` / `review-read-only-macos` OrbStack profile from `6b0f800`, and `Agy (Antigravity)` `1.5.5` / `gemini-4-argon-medium` from `5b8e439`), and mark standalone `Gemini` CLI retired/deprecated per `skills/call-agent/SKILL.md`.
  5. **Authorized `[DOM-14]` lessons coalescing sweep (`docs/lessons.md` + `docs/coalescing.md`):**
     - Pre-sweep check: run `uv run --no-sync bin/coalesce-check` and `uv run --no-sync bin/check-plan-status-index`; verify `source_sha` `5b8e439` is reachable from `main` (`git merge-base --is-ancestor 5b8e439 main`).
     - Audit all `26` dated entries past `2026-08-18` (`2026-08-25..2026-09-25`):
       - Fold entries whose distinct triggers, exceptions, and required actions are already owned in `docs/specs/*`, `docs/implementation/*`, or `docs/agent-context/runbooks/*` into compact distilled cluster lines carrying `(distilled from N entries, YYYY-MM-DD..YYYY-MM-DD, source 5b8e439)` after verifying **text fidelity**, **symbol liveness**, and **behavioral parity** (`[DOM-14]`).
       - Retain verbatim any recent/unowned post-`2026-09-15` entries whose concrete testing or concurrency heuristic has no fuller home yet, without lossy compression.
       - Append concise `2026-11-10` durable lessons uncovered in this wave:
         1. OS process liveness vs creation-token readability: exited/zombie processes (`psutil.STATUS_ZOMBIE`, `not proc.is_running()`, Linux `/proc/<pid>/stat` `'Z'`) retain readable PID + `create_time` in OS tables/handles; liveness probes must check running + non-zombie status alongside start-time equality.
         2. Atomic file replacement and `tempfile.mkstemp`: `mkstemp` hardcodes `0600` and `os.replace` publishes that temp inode's mode over the destination; use exclusive same-directory `os.open(..., O_CREAT | O_EXCL | O_WRONLY, 0o666)` when operator `umask` and directory ACLs own permissions.
         3. Containerized Postgres readiness: `pg_isready` over the default Unix domain socket inside `postgres:alpine` succeeds during initdb's temporary local-only server restart before TCP `5432` accepts host clients; probe `psql -h 127.0.0.1 ... -c "SELECT 1"` instead.
     - Update `docs/coalescing.md`: advance `Lessons` watermark to `2026-09-25` (with `2026-11-10` entries remaining fresh post-watermark), update `Deferral State`, and append one spot-checkable `Run Log` row.
- **Stop-gate / verification:**
  - `uv run --no-sync bin/check-doc-paths --self-test && uv run --no-sync bin/check-doc-paths`
  - `uv run --no-sync bin/check-plan-status-index`
  - `uv run --no-sync bin/coalesce-check`
  - `uv run --no-sync bin/check-dom15-fixtures`
  - `uv run --no-sync pytest tests/test_plan_status_index.py tests/test_docs_references.py tests/test_coalesce_check.py tests/test_ruff_suppression_index.py`
- **Done signal:** All doc, plan-status, `Replacement` sync, DOM-15 fixture, suppression-index, and coalescing checks pass with `0` errors.

---

### Slice 2: Re-Pin Vendored `MultiQueueWatcher` to Weft `0.9.124` (`62a4504b`)

- **Objective:** Advance `taut/watcher.py`'s vendored `MultiQueueWatcher` from Weft `9fc913c1` to Weft `0.9.124` (`62a4504b:weft/core/tasks/multiqueue_watcher.py`), porting the exact `9fc913c1..62a4504b` upstream improvements while preserving `[TAUT-12.3]`'s two-divergence-seam budget, existing deferred-SIGINT regression proofs (`tests/test_watcher.py:1537`), and `CACHE_STALE_QUEUE_NAME` PostgreSQL `LISTEN` subscription.
- **Files:**
  - `taut/watcher.py`
  - `docs/implementation/04-taut-architecture.md`
  - `bin/ruff_suppression_index.py` and `docs/specs/01-development-documentation-operating-model.md` (`[DOM-10.2.1]` line numbers only if `taut/watcher.py` line offsets shift existing `[RUFF-SUP-*]` entries, regenerated via `--write`)
  - `tests/test_watcher.py`
- **Read first:**
  - `../weft/weft/core/tasks/multiqueue_watcher.py` at `62a4504b` (`git -C ../weft log -p 9fc913c1..62a4504b -- weft/core/tasks/multiqueue_watcher.py`)
  - `taut/watcher.py` (`L1–1650`) and `tests/test_watcher.py` (`L1530–1620`, existing deferred-SIGINT critical-section tests)
  - `docs/implementation/04-taut-architecture.md` (`L765–820`, class-body AST comparison & SHA-256 verification recipe)
  - `extensions/taut_summon/taut_summon/_reactor.py` (`SummonReactor`), `extensions/taut_summon/taut_summon/_driver.py`, and `extensions/taut_mcp/taut_mcp/_workspace_reactor.py` (`_WorkspaceReactor`)
- **Existing helpers to reuse:** `tests/helpers/base_reactor_sigint_probe.py` (retained unchanged for regression), `tests/test_watcher.py` fake broker / waiter / strategy fixtures.
- **Steps (RED -> GREEN):**
  1. **RED (`tests/test_watcher.py`):**
     - Write three firing unit tests targeting the exact `9fc913c1..62a4504b` delta before editing `taut/watcher.py`:
       1. **`_ensure_multi_activity_waiter` stop/BaseException candidate cleanup & strategy replacement (`4a8884cb`):** Prove that if `self._stop_event` becomes set (or `BaseException` is raised) after `create_activity_waiter_for_queues` constructs a candidate waiter before installation under `_topology_lock`, the uninstalled candidate waiter is closed once via `_close_candidate_resource_once(candidate)` and `self._multi_activity_waiter` is not overwritten; and when `_strategy_started` is `True` on a live installation, `self._strategy.replace_activity_waiter(candidate)` is invoked and any displaced waiter distinct from `previous` and `candidate` is closed once (plus `_ensure_wait_strategy_started()` installs the multi-activity waiter on the initial `_start_strategy()` call rather than returning early).
       2. **Evidence-gated `_has_pending_observation()` at wait entry, hint validation, and deadline return (`956acab1` / `14d84f29`):** Subclass `MultiQueueWatcher` overriding `_has_pending_observation(self) -> bool` (whose base implementation returns `False`) and prove: (a) `_wait_for_activity` checks `_has_pending_observation()` once immediately after `_ensure_wait_strategy_started()` ("register before reading") and returns immediately when `True`; (b) a quiet persistent SQLite strategy return before deadline with no `local_hint`, `native_hint`, or `data_version_hint` (`can_carry_evidence == False`) skips `_has_pending_observation()`; and (c) when the deadline is reached on either the loop-head `remaining <= 0` return (`_activity_hint_action(deadline=deadline)`) or inside `_readiness_action(deadline_reached and not evidence_read)`, `_has_pending_observation()` IS called once before returning turn control to the owner.
       3. **`_update_active_queues` `_queue_counts_as_wait_activity` eviction (`62a4504b`):** Subclass `MultiQueueWatcher` overriding `_queue_counts_as_wait_activity(self, config)` so a queue already present in `self._active_queues` with pending messages flips from `True` to `False`; assert `_update_active_queues()` evicts that queue name from `self._active_queues` even while `_queue_has_pending(config.queue)` remains `True`.
     - Run `uv run --no-sync pytest tests/test_watcher.py -k "multi_activity_waiter or pending_observation or active_queues"` and observe RED failures on all three tests.
  2. **GREEN (`taut/watcher.py` + sync ledger):**
     - Update `taut/watcher.py`'s provenance header and copied `MultiQueueWatcher` body (`9fc913c1` -> `62a4504b`, Weft `0.9.124`), keeping **only** the two `[TAUT-12.3]` divergence seams (`yield_strategy != "round_robin"` validation in `__init__` and `raise _TopologyStopping("watcher topology is stopping")` at the 3 synchronous stop-rejection sites across 3 methods).
     - Verify `TautWatcher`, `SummonReactor` (`extensions/taut_summon/taut_summon/_reactor.py`), and `taut_mcp._WorkspaceReactor` continue to include `CACHE_STALE_QUEUE_NAME` (`taut.cache_stale`) in `queue_configs`, and keep `SummonReactor._fetch_next_message()`'s intra-pass `if not self._queue_counts_as_wait_activity(config): return None` guard (including its `control_queue_name` exception) intact.
     - Update `docs/implementation/04-taut-architecture.md` (`L768–811`): advance `9fc913c1` -> `62a4504b` (`weft/core/tasks/multiqueue_watcher.py`), update the full-file SHA-256 to `713060f2880b401220505e82f9fad11916740a8355cad026f869ac61dfdbf086` and `QueueMode`-through-EOF SHA-256 to `792d34b26dd83d4b86b695e79d5e27130df510f39049fc6f6fac6b6b297ebd76`, and verify the embedded AST comparison snippet exits `0` (`"Copied classes match; only yield validation and three stop types differ."`).
     - If line shifts in `taut/watcher.py` moved any existing `# noqa` lines registered in `bin/ruff_suppression_index.py`, run `uv run --no-sync python bin/ruff_suppression_index.py --write` to synchronize `[DOM-10.2.1]` line anchors without adding new suppressions.
- **Stop-gate / verification:**
  - `uv run --no-sync pytest tests/test_watcher.py extensions/taut_summon/tests/test_driver.py`
  - `uv run --project extensions/taut_mcp pytest extensions/taut_mcp/tests/test_workspace_reactor.py`
  - `uv run --no-sync pytest tests/test_ruff_suppression_index.py`
  - Mutation check (`[DOM-11]` P1 floor): temporarily revert `_close_candidate_resource_once(candidate)` in `taut/watcher.py::_ensure_multi_activity_waiter`, confirm the new candidate-cleanup test fails, and restore.
- **Done signal:** All three new watcher tests plus existing deferred-SIGINT regression tests (`tests/test_watcher.py:1537`) pass, `SummonReactor` and `_WorkspaceReactor` suites pass, and the AST comparison against `62a4504b:weft/core/tasks/multiqueue_watcher.py` confirms only the two `[TAUT-12.3]` divergence seams differ.

---

### Slice 3: Core, Summon, Persistence, CLI Parser, and MCP Runtime Bug Fixes

- **Objective:** Remediate the five uncovered runtime/boundary bugs across `taut/identity.py`, `extensions/taut_summon/taut_summon/_state.py`, `taut/_config.py`, `taut/persistence/_operations.py`, `taut/commands/_protocol.py`, and `extensions/taut_mcp`.
- **Files:**
  - `taut/identity.py` and `tests/test_identity.py`
  - `extensions/taut_summon/taut_summon/_state.py` and `extensions/taut_summon/tests/test_state.py`
  - `taut/_config.py` and `tests/test_constants.py`
  - `taut/persistence/_operations.py` and `tests/test_persistence_io.py`
  - `taut/commands/_protocol.py`, `tests/test_cli.py`, `tests/test_command_registry.py`, and `tests/test_command_syntax.py`
  - `extensions/taut_mcp/taut_mcp/_workspace_reactor.py`, `extensions/taut_mcp/taut_mcp/_process_reactor.py`, and `tests/test_architecture_boundaries.py`
- **Read first:**
  - `taut/identity.py` (`L535–635`), `../weft/weft/helpers/__init__.py` (`L384–415`, `pid_is_live`)
  - `extensions/taut_summon/taut_summon/_state.py` (`L625–665`, `_evidence_liveness`, `claim_driver`)
  - `taut/_config.py` (`L1–47`)
  - `taut/persistence/_operations.py` (`L340–485`, `dump_workspace`), `../weft/weft/commands/dump.py`, `tests/test_persistence_io.py` (`L235–275`)
  - `taut/commands/_protocol.py` (`L60–85`), `tests/test_command_registry.py`, `tests/test_command_syntax.py`
  - `extensions/taut_mcp/taut_mcp/_workspace_reactor.py` (`L1–40`), `_process_reactor.py` (`L1–35`), `tests/test_architecture_boundaries.py`
- **Steps (RED -> GREEN):**
  1. **Zombie & exited-handle liveness (`taut/identity.py` + `taut_summon/_state.py`):**
     - **RED:**
       - In `tests/test_identity.py`, add:
         - (a) a real POSIX subprocess zombie test (`pytest.mark.skipif(os.name == "nt", ...)`) spawning `proc = subprocess.Popen([sys.executable, "-c", "import os; os._exit(0)"])`, waiting with a bounded `eventually` helper until `psutil.Process(proc.pid).status() == psutil.STATUS_ZOMBIE` without reaping (`finally: proc.wait()`), and asserting `capture_process(proc.pid)` is `None` and `member_presence(...)` is `"gone"`;
         - (b) deterministic unit tests on `_capture_psutil_process` and `start_time_token` for: `proc.is_running() == False` -> `None` (Windows open-handle-after-exit shape); `proc.status() == psutil.STATUS_ZOMBIE` -> `None`; `psutil.ZombieProcess` or `psutil.NoSuchProcess` raised inside `status()` or `start_time_token()` (`create_time()`) -> `None` (proven death); `psutil.AccessDenied` raised from `status()` when `is_running()` is `True` and `create_time()` succeeds -> returns `ProcessInfo` with valid `start_time`; and `psutil.AccessDenied` raised from `create_time()` on a live non-zombie process -> returns `ProcessInfo(..., start_time=None)` so Summon `_evidence_liveness()` continues to classify live unreadable evidence as `"indeterminate"` (requiring `--takeover`);
         - (c) deterministic unit test on `_capture_linux_process` feeding a real-shaped `/proc/<pid>/stat` line `1234 (python (worker)) Z 1 ...` and asserting `None`.
       - In `extensions/taut_summon/tests/test_state.py`, add a real POSIX zombie test proving `SummonState.claim_driver()` succeeds **without** `takeover=True` when the stored `(driver_pid, driver_start_time)` belongs to an exited, unreaped zombie child (`finally: proc.wait()`), while keeping an unreadable live `start_time=None` row classified `"indeterminate"`.
       - Observe RED failures (`capture_process(proc.pid)` currently returns a `ProcessInfo` for the zombie and `claim_driver` raises active-driver conflict).
     - **GREEN:**
       - Update `start_time_token(pid, proc)` in `taut/identity.py` (`L550–558`) to re-raise `(psutil.NoSuchProcess, psutil.ZombieProcess)` before `except psutil.Error: return None` so proven process death propagates to `_capture_psutil_process` while permission/unreadable errors still return `None` (`start_time=None`).
       - Update `_capture_psutil_process(pid)` in `taut/identity.py` (`L596–624`) to check `if not proc.is_running(): return None` and inspect `proc.status()` inside `proc.oneshot()` via `try: status = proc.status() except (psutil.NoSuchProcess, psutil.ZombieProcess): return None except psutil.AccessDenied: status = None` (`if status == psutil.STATUS_ZOMBIE: return None`), catching `psutil.Error` around `oneshot()` -> `None`.
       - Update `_capture_linux_process(pid)` in `taut/identity.py` (`L561–594`) so `if fields[0] == "Z": return None` immediately after splitting `tail`.
       - Confirm `extensions/taut_summon/taut_summon/_state.py::_evidence_liveness()` (`L646–660`) continues to map `proc is None` -> `"dead"`, `proc.start_time is None` -> `"indeterminate"`, and `proc.start_time == start_time` -> `"live"`.
  2. **Thread-safe `load_config()` (`taut/_config.py`):**
     - **RED:** Add a deterministic unit test in `tests/test_constants.py` wrapping `resolve_config` (or observing `warnings.filters` and `warnings.showwarning` inside a custom warning/resolver spy) during `load_config()` and asserting `load_config()` never mutates `warnings.filters` or `warnings.showwarning` while still emitting config warnings from `resolve_config()`. Observe RED (`catch_warnings(record=True)` currently replaces `warnings.filters` and `warnings.showwarning`).
     - **GREEN:** Simplify `taut/_config.py::load_config()` (`L34–47`) to `return resolve_config("TAUT", defaults=TAUT_CONFIG_DEFAULTS, env=os.environ, override=overrides)` and remove the unused `import warnings`.
  3. **Operator-owned dump file permissions (`taut/persistence/_operations.py::dump_workspace`):**
     - **RED:** Update `tests/test_persistence_io.py` (`L249–250`) and add subprocess tests on POSIX running `dump_workspace()` / `taut system dump --output ...` under `os.umask(0o027)` (expecting `0o640`), `os.umask(0o077)` (expecting `0o600`), overwriting a pre-existing `0o600` output file under `os.umask(0o027)` (expecting the replaced inode to take `0o640`), and an `O_EXCL` collision test (monkeypatching `secrets.token_hex` to collide with a pre-existing file and proving `dump_workspace()` raises `TautError` without unlinking the colliding file). Observe RED (`0o600` forced under `0o027`).
     - **GREEN:** In `taut/persistence/_operations.py::dump_workspace()` (`L345–360`, `L474–480`), initialize `temp_path: Path | None = None` before staging creation, construct `candidate_path = output_path.parent / f".{output_path.name}.{secrets.token_hex(8)}.tmp"`, open with `fd = os.open(candidate_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o666)`, assign `temp_path = candidate_path` **only after** `os.open` succeeds, and keep `with os.fdopen(fd, "wb") as stream, open_broker(target, config=config) as broker:` plus the entire binary `_write`/`_component`/`final_hasher`/`os.fsync`/`validate_dump`/`os.replace(temp_path, output_path)` pipeline unchanged — deleting `tempfile.mkstemp` and `os.chmod(temp_path, 0o600)`.
  4. **Python 3.11 parser shim & `taut_mcp` architecture boundaries:**
     - **RED:** Add architecture-boundary assertions in `tests/test_architecture_boundaries.py` scanning `extensions/taut_mcp/taut_mcp` (forbidding `from simplebroker.watcher import` in favor of `simplebroker.ext` and verifying `_WorkspaceReactor` subclasses `MultiQueueWatcher`). Observe RED on `extensions/taut_mcp/taut_mcp/_workspace_reactor.py:22` and `_process_reactor.py:17`.
     - **GREEN:** Update both `taut_mcp` reactor imports to `from simplebroker.ext import PollingStrategy`; simplify `taut/commands/_protocol.py::CommandArgumentParser.parse_command_args()` to `if self._taut_intermixed_args: return self.parse_intermixed_args(args)` / `return self.parse_args(args)`, keeping `tests/test_cli.py`, `tests/test_command_registry.py`, and `tests/test_command_syntax.py` green on Python 3.12+.
- **Stop-gate / verification:**
  - `uv run --no-sync pytest tests/test_identity.py tests/test_constants.py tests/test_persistence_io.py tests/test_cli.py tests/test_command_registry.py tests/test_command_syntax.py tests/test_architecture_boundaries.py extensions/taut_summon/tests/test_state.py`
  - `uv run --project extensions/taut_mcp pytest extensions/taut_mcp/tests`
  - Mutation check (`[DOM-11]` P1 floor): temporarily disable the `STATUS_ZOMBIE` check in `taut/identity.py`, confirm both the identity zombie test and `SummonState.claim_driver` zombie test fail, and restore.
- **Done signal:** All runtime bug-fix tests, MCP extension tests, and mutation proofs pass.

---

### Slice 4: Python `3.12`–`3.15` Rotation, `simplebroker>=8.8.1` / `simplebroker-pg>=4.8.1`, Ruff `0.17.4` Policy, Dev Tooling, and CI Workflows

- **Objective:** Advance all five workspace packages, lockfiles, Ruff policy gates, wheel-matrix bounds, dev scripts, READMEs, implementation docs, and all 11 GitHub Actions workflows to Python `3.12`–`3.15`, `simplebroker>=8.8.1`, `simplebroker-pg>=4.8.1`, and `ruff>=0.17.4`.
- **Files:**
  - Manifests & locks: `pyproject.toml`, `extensions/taut_pg/pyproject.toml`, `extensions/taut_summon/pyproject.toml`, `extensions/taut_mcp/pyproject.toml`, `extensions/taut_tui/pyproject.toml`, `tests/fixtures/taut_command_plugin/pyproject.toml`, `uv.lock`, `extensions/taut_summon/uv.lock`, `extensions/taut_mcp/uv.lock`, `extensions/taut_tui/uv.lock`
  - Ruff & tooling: `tests/test_ruff_policy.py`, `tests/fixtures/ruff-enabled-rules.txt` (delete), `bin/ruff_suppression_index.py`, `tests/test_ruff_suppression_index.py`, `bin/check-core-summon-wheel-matrix.py`, `tests/test_core_summon_wheel_matrix.py`, `bin/release.py`, `taut/_scripts.py`, `tests/test_dev_scripts.py`
  - Workflows & workflow gate: `.github/workflows/test.yml`, `test-mcp-extension.yml`, `test-pg-extension.yml`, `test-tui-extension.yml`, `release.yml`, `release-finalize.yml`, `release-gate.yml`, `release-gate-mcp.yml`, `release-gate-pg.yml`, `release-gate-summon.yml`, `release-gate-tui.yml`, `tests/test_github_workflows.py`
  - Docs: `README.md`, `extensions/taut_pg/README.md`, `extensions/taut_summon/README.md`, `docs/implementation/02-repository-map.md`, `04-taut-architecture.md`, `05-taut-summon-architecture.md`, `07-taut-mcp-architecture.md`
- **Read first:**
  - `../simplebroker` commit `6923276` (`tests/test_ruff_policy.py` dynamic Ruff rule derivation) and `4304873` (`docker rm -f -v`)
  - `../weft` commits `8085962a` (`bin/ruff_suppression_index.py` `PermissionError` retry), `540707a3` & `b4afe36e` (`_scripts.py` TCP `psql` readiness + failure logs), and `3ce155fc` (`RUNNER_TEMP` Windows NVMe temp)
  - Live `pyproject.toml`, `taut/_scripts.py`, `tests/test_dev_scripts.py`, `tests/test_github_workflows.py`, and `tests/test_core_summon_wheel_matrix.py` (read immediately before editing to preserve all existing lines cleanly)
- **Steps (RED -> GREEN):**
  1. **Manifests & lockfiles (`>=3.12`, `3.12`–`3.15`, `simplebroker>=8.8.1`, `simplebroker-pg>=4.8.1`, `ruff>=0.17.4`):**
     - Update all 5 `pyproject.toml` files + `tests/fixtures/taut_command_plugin/pyproject.toml`:
       - `requires-python = ">=3.12"`
       - PyPI classifiers: remove `3.11`, ensure `3.12`, `3.13`, `3.14`, `3.15`
       - `[tool.mypy] python_version = "3.12"` (where declared) and `[tool.ruff] target-version = "py312"` (in root, `taut_mcp`, and `taut_tui`)
       - `simplebroker>=8.8.1` in root `pyproject.toml` and `extensions/taut_mcp/pyproject.toml`
       - `simplebroker-pg>=4.8.1` in `extensions/taut_pg/pyproject.toml` and root `pyproject.toml` `dev` extra
       - `ruff>=0.17.4` in all `dev` dependency lists
     - Re-lock all 4 locked projects (`uv lock --upgrade-package simplebroker --upgrade-package simplebroker-pg --upgrade-package ruff` at root, `extensions/taut_summon`, `extensions/taut_mcp`, `extensions/taut_tui`), sync the root dev environment (`uv sync --extra dev`), and verify `extensions/taut_pg/uv.lock` does **not** exist (`tests/test_release_script.py`).
  2. **Dynamic Ruff `0.17.4` policy & `ruff_suppression_index.py` `PermissionError` retry:**
     - **RED:** Add a unit test in `tests/test_ruff_suppression_index.py` simulating transient Windows `PermissionError` on the first two `os.replace` attempts in `_atomic_replace` before succeeding on the third (plus exhausting all 10 attempts raising `ToolFailure` whose `__cause__` is the underlying `PermissionError` / `OSError`, cleaning up the temporary file). Rewrite `tests/test_ruff_policy.py` (`L124–149`) to derive Ruff's isolated default rule set via `ruff check --isolated --show-settings` + `REVIEWED_FAMILIES - GLOBAL_IGNORES` across root, `taut_mcp`, and `taut_tui`, and delete `tests/fixtures/ruff-enabled-rules.txt`.
     - **GREEN:** Implement the 10 × 10 ms `PermissionError` retry loop around `os.replace(temporary, path)` inside `bin/ruff_suppression_index.py::_atomic_replace` (`L722–748`); run `uv run --no-sync ruff check .` across the entire repository under Ruff `0.17.4` and fix any newly surfaced findings cleanly without unapproved suppressions.
  3. **Wheel matrix Python `3.12`–`3.15` bounds (`bin/check-core-summon-wheel-matrix.py`):**
     - **RED:** Update `tests/test_core_summon_wheel_matrix.py` (`L108–135`, `L992`, `L1177`) to expect `MATRIX_PYTHON_MIN_MINOR = 12`, candidate scan `python3.15`..`python3.12`, rejection of `python3.11`, and error message `>= 3.12`. Observe RED.
     - **GREEN:** Update `MATRIX_PYTHON_MIN_MINOR = 12` and `range(15, MATRIX_PYTHON_MIN_MINOR - 1, -1)` in `bin/check-core-summon-wheel-matrix.py:32,384`.
  4. **Postgres test harness & Docker volume hygiene (`taut/_scripts.py` + `bin/release.py`):**
     - **RED:** In `tests/test_dev_scripts.py`, add/update tests asserting:
       - `_wait_for_postgres` probes TCP readiness via `docker exec <container> psql -h 127.0.0.1 -U postgres -d taut_test -c "SELECT 1"` (not Unix-socket `pg_isready`, which succeeds prematurely before post-initdb TCP restart);
       - `test_pg` captures and prints `docker logs <container>` when `pytest` exits non-zero before tearing down the container;
       - `docker rm -f -v` is used on container teardown in `taut/_scripts.py` and `bin/release.py:1378,1386`.
       Observe RED.
     - **GREEN:** Update `taut/_scripts.py` and `bin/release.py` to satisfy all three contracts while preserving existing `test_pg` options and behavior.
  5. **GitHub Actions workflows (`3.12`–`3.15`, Windows `$env:RUNNER_TEMP`, SHA-pinned action refresh):**
     - **RED:** Update `tests/test_github_workflows.py` first to assert:
       - Python matrices across `test.yml`, `test-mcp-extension.yml`, `test-pg-extension.yml`, and `test-tui-extension.yml` cover `("3.12", "3.13", "3.14", "3.15")` (with `3.11` absent everywhere, Windows 4-way shards paired across `3.12`–`3.15`, Windows `summon-process` on `3.12`, and `packaging`/release workflows using `3.12` rather than `3.11`);
       - Windows test jobs in `test.yml`, `test-mcp-extension.yml`, and `test-tui-extension.yml` create `$env:RUNNER_TEMP\taut-test-temp` and export `TEMP`/`TMP` to `GITHUB_ENV`;
       - Unified SHA pins across all 11 workflows match sibling verified commits:
         - `UV_VERSION: "0.13.6"`
         - `actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1`
         - `actions/setup-python@6d4fd22b20465ccc0f7354476588e8df7c9ca0e0 # v7.1.0`
         - `astral-sh/setup-uv@68559e99cc807c1eb7e9238fd43a15bba460eec2 # v10.3.3`
         - `actions/upload-artifact@cf430e030ddbb5b0abf93d22962f4752f3646cd9 # v7.0.2`
         - `actions/download-artifact@9000827ccba6bdab643e8b6fd33ac0654aef8333 # v8.0.2` (HTTP 429 retry fix)
         - `codecov/codecov-action@303a32d7a59b442fa8d48b6a1cc6825c09c847a5 # v7.1.1`
         - `pypa/gh-action-pypi-publish@7245906fb61fa33a13554f9d5fb856fe61758086 # v1.14.3`
         - `softprops/action-gh-release@8a0cd651e5b2365bd640854a3fa5dfc70e4875f3 # v3.0.4`
       Observe RED in `tests/test_github_workflows.py`.
     - **GREEN:** Update all 11 `.github/workflows/*.yml` files (ensuring Python `3.15` setup steps pass `allow-prereleases: true` where `actions/setup-python` requires it, matching `simplebroker` / `weft`).
  6. **README & implementation documentation alignment:**
     - Update `README.md` (badge `3.12 | 3.13 | 3.14 | 3.15`, `Python 3.12+`, `simplebroker>=8.8.1`, trust-model dump permission note), `extensions/taut_pg/README.md` (`Python 3.12+`, `simplebroker-pg>=4.8.1`, mixed-version watcher rollout note), `extensions/taut_summon/README.md` (if floor-cited), and `docs/implementation/{02-repository-map,04-taut-architecture,05-taut-summon-architecture,07-taut-mcp-architecture}.md` (`simplebroker>=8.8.1`, `simplebroker-pg>=4.8.1`, deleted `ruff-enabled-rules.txt` reference if any, zombie liveness note, operator-owned dump mode note; note that `extensions/taut_summon/taut_summon/_darwin_wait.py` remains load-bearing on macOS **Python 3.12** because `os.waitid` landed in macOS Python `3.13`!).
- **Stop-gate / verification:**
  - `uv run --no-sync ruff check .`
  - `uv run --no-sync mypy taut tests extensions/taut_pg/taut_pg extensions/taut_summon/taut_summon extensions/taut_tui/taut_tui`
  - `uv run --project extensions/taut_mcp mypy extensions/taut_mcp/taut_mcp extensions/taut_mcp/tests`
  - `uv run --no-sync pytest tests/test_ruff_policy.py tests/test_ruff_suppression_index.py tests/test_core_summon_wheel_matrix.py tests/test_dev_scripts.py tests/test_github_workflows.py tests/test_release_script.py`
- **Done signal:** All lint, typecheck, Ruff policy, wheel-matrix, dev-script, release-script, and workflow-contract tests pass on the upgraded lockfiles.

---

### Slice 5: Full Verification Floor, Adversarial Probes, Theory-Versus-Code Audit Confirmation, and Completed-Work Review

- **Objective:** Prove end-to-end behavioral parity across SQLite, PostgreSQL (when Docker is running locally), Summon, MCP, TUI, and installed wheel matrices; refresh the theory-versus-code/spec audit table; and complete the `[DOM-11]` Tier-1 cross-family completed-work review.
- **Steps:**
  1. Run the full test, lint, type, doc-path, plan-index, DOM-15, suppression-index, and coalescing suites listed in `## Verification and Gates`.
  2. Apply the CLI/persistence/process floors from `docs/agent-context/runbooks/adversarial-acceptance-probes.md`:
     - CLI leading `--` with option-shaped positionals (`taut say -- general --not-a-flag`) under Python `3.12` (`uv run --isolated --python 3.12`) and Python `3.14`;
     - `taut system dump` into restricted (`0700`) and group-shared (`0750`, `umask 0027`) directories, plus `O_EXCL` staging collision refusal;
     - unreaped zombie child PID reuse / liveness probe across `taut who` and `taut summon`.
  3. Confirm every row in `## Theory-Versus-Code and Theory-Versus-Spec Audit Table` is now **Aligned** and record observed verification outputs in `## Execution Log`.
  4. Dispatch an independent Tier-1 cross-family review (`skills/call-agent/SKILL.md`) over the completed diff, reproduce and disposition every finding in `## Review Log`, and re-run all affected gates.

---

## Testing Plan

### What Must Stay Real (Anti-Mocking Rules)

- **OS process & zombie liveness (`tests/test_identity.py`, `extensions/taut_summon/tests/test_state.py`):** Must spawn a real exited-but-unreaped child via `subprocess.Popen([sys.executable, "-c", "import os; os._exit(0)"])` on POSIX and exercise real `psutil.Process` + real SQLite `SummonState.claim_driver()` (`finally: proc.wait()`). Targeted unit fakes are allowed **only** for Windows-specific `is_running() == False` open-handle shapes, `AccessDenied` fallback, and Linux `/proc/<pid>/stat` parsing on non-Linux hosts.
- **Dump file permissions (`tests/test_persistence_io.py`):** Must run real `dump_workspace()` / CLI `taut system dump` inside real child processes with controlled `os.umask(...)` values on real filesystem directories — never mock `os.open`, `os.replace`, or `os.chmod`.
- **Ruff dynamic rule policy (`tests/test_ruff_policy.py`):** Must invoke the real pinned `ruff` binary (`ruff check --isolated --show-settings` and `ruff check --show-settings`) against the real `pyproject.toml`, `extensions/taut_mcp/pyproject.toml`, and `extensions/taut_tui/pyproject.toml` files.
- **Doc & coalescing gates (`bin/check-doc-paths`, `bin/coalesce-check`):** Must execute against real temporary git repositories (`git init`, real commits/tags/branches) and the live repository tree.
- **MultiQueueWatcher (`tests/test_watcher.py`):** Must exercise real `TautWatcher`, `SummonReactor`, and `_WorkspaceReactor` instances over real SimpleBroker `8.8.1` SQLite (and PostgreSQL `4.8.1` in `test-pg`) targets.

---

## Verification and Gates

### Per-Slice & Final Local Gate Commands

```bash
# 1. Documentation, citation, plan-index, DOM-15, suppression, and coalescing gates
uv run --no-sync bin/check-doc-paths --self-test
uv run --no-sync bin/check-doc-paths
uv run --no-sync bin/check-plan-status-index
uv run --no-sync bin/check-dom15-fixtures
uv run --no-sync bin/coalesce-check
uv run --no-sync python bin/ruff_suppression_index.py --check

# 2. Repository-wide Ruff 0.17.4 lint, format check, and strict mypy across all 5 packages
uv run --no-sync ruff check .
uv run --no-sync ruff format --check taut tests bin extensions
uv run --no-sync mypy taut tests extensions/taut_pg/taut_pg extensions/taut_summon/taut_summon extensions/taut_tui/taut_tui
uv run --project extensions/taut_mcp mypy extensions/taut_mcp/taut_mcp extensions/taut_mcp/tests

# 3. Core, Summon, TUI, MCP, and PostgreSQL test suites
uv run --no-sync pytest
uv run --project extensions/taut_summon pytest extensions/taut_summon/tests -m "not live_llm"
uv run --project extensions/taut_mcp pytest extensions/taut_mcp/tests
uv run --project extensions/taut_tui pytest extensions/taut_tui/tests
uv run --extra dev test-pg

# 4. Oldest-supported Python 3.12 smoke check & git whitespace gate
uv run --isolated --python 3.12 --with pytest --with psutil --with "simplebroker>=8.8.1" pytest tests/test_cli.py tests/test_identity.py tests/test_persistence_io.py
git diff --check
```

### Post-Merge / Hosted CI Success Signals

- All 11 GitHub Actions workflows parse cleanly and `Test`, `Test MCP Extension`, `Test PG Extension`, and `Test TUI Extension` pass across Ubuntu, macOS, and Windows on Python `3.12`, `3.13`, `3.14`, and `3.15` (with zero Windows `RUNNER_TEMP` SQLite contention timeouts and zero `download-artifact` HTTP 429 failures).
- `bin/check-core-summon-wheel-matrix.py` passes in the `packaging` CI job under Python `3.12+` with `simplebroker>=8.8.1`.

---

## Independent Review Loop

1. **Plan review (before Slice 0 execution):** Invoke a Tier-1 cross-family reviewer (`codex`, `claude`, or `grok` — cross-family relative to the authoring `agy` / Gemini session) via `skills/call-agent/SKILL.md`, supplying this plan, governing spec sections, `[THEORY-5.A1]`–`[THEORY-5.A6]` under `Rejected alternatives in force`, and the two design/CS lenses (`[DOM-11]`).
2. **Round-cap discipline (`agent-theory @ e6ac579`):** If Round 1 returns `PASS` / `no blocker`, apply all accepted dispositions to both `## Tasks` and `## Proposed Spec Delta`, verify locally with `bin/check-doc-paths` and `bin/check-plan-status-index`, and close the plan review loop without a ceremonial Round 2. Run Round 2 **only** if Round 1 returns `BLOCKED` or if scope, invariants, or authority change.
3. **Completed-work review (Slice 5):** Run a Tier-1 cross-family review over the implemented diff before declaring the plan complete.

---

## Out of Scope

- **Active sibling remediation slices in `docs/plans/2026-10-15-deep-review-remediation-plan.md`:** `taut-tui` Summon modal cancellation/failure containment, transcript selection memoization, `taut/search` tombstone projection bumps, and `_DetachChordMatcher` deadline tests remain owned by that plan.
- **SimpleBroker strict-discovery invalid-target CLI read seam:** Remains owned by `docs/plans/2026-09-24-cli-read-delivery-and-agent-recipes-plan.md`.
- **Retiring `extensions/taut_summon/taut_summon/_darwin_wait.py`:** `os.waitid` is still absent on macOS Python `3.12` (it arrived on macOS in Python `3.13`), so `_darwin_wait.py` remains required until Python `3.12` leaves the support window; update its comments/docs from `"Python 3.11/3.12"` to `"Python 3.12"` rather than deleting it.
- **Daemon/manager processes (`[THEORY-5.A4]`), in-band authentication (`[THEORY-5.A3]`), or `MODULE-THEORY.md` files (`[DOM-2]`).**

---

## Fresh-Eyes Review

Performed author fresh-eyes pass prior to external Tier-1 dispatch:

1. **Checked macOS `_darwin_wait.py` trap:** Caught a potential bad deletion — dropping Python `3.11` does *not* make `extensions/taut_summon/taut_summon/_darwin_wait.py` dead code because macOS Python `3.12` still lacks `os.waitid`. Recorded explicitly in Slice 4 Step 6 and `## Out of Scope`.
2. **Checked `bin/check-doc-paths` Taut index-format mismatch:** Verified `docs/plans/README.md` uses `## Plan Status Index` (4 columns, including `status-review`, `retired-pending`, and historical slice notes mentioning `"is promoted for implementation"`). Explicitly specified Taut's heading, status skip-set, and `\b(?:spec promoted|spec-promotion slice applied)\b` note regex in Slice 1 so `_plan_replacement_sync_failures()` cannot false-fire.
3. **Checked `psutil.AccessDenied` on `proc.status()`:** Verified in Slice 3 Step 1 that when `proc.is_running()` is `True` and `create_time()` is readable, `psutil.AccessDenied` from `proc.status()` on hardened OSes must fall through as non-zombie rather than falsely treating a live peer process as dead (matching Weft `pid_is_live`).
4. **Checked every `Replacement` block against live files (`01`, `02`, `03`, `04`, `07`, `08`):** Verified exact context lines and backticked target headers (`Replacement (\`<path>\`):`) so Slice 0 applies cleanly and Slice 1's `bin/check-doc-paths` sync gate passes immediately after promotion.

## Review Log

### Plan Review — Round 1 (`codex-cli 0.161.0`, Tier-1 cross-family read-only sandbox, 2026-11-10)

- **Reviewer:** `codex` (`codex exec -s read-only --skip-git-repo-check -C /Users/van/Developer -c 'model_reasoning_effort="high"'`)
- **Reviewed baseline:** `5b8e439`
- **Verdict:** `BLOCKED` (5 actionable precision findings; 0 out-of-scope observations; 0 reconsideration requests)
- **Findings & Dispositions:**
  1. **`[P1]` Rebuild Slice 2's proofs and paths around the actual `9fc913c1..62a4504b` diff:**
     - *Reproduction:* Verified `git -C ../weft diff 9fc913c1..62a4504b -- weft/core/tasks/multiqueue_watcher.py`. `8bcf294b` (`_topology_sigint_critical` deferred SIGINT) was already present in `9fc913c1` and tested at `tests/test_watcher.py:1537`; at `62a4504b`, `_has_pending_observation()` returns `False` by default and is called on evidence-carrying returns + deadline returns (`956acab1`/`14d84f29`), `_update_active_queues()` filters via `_queue_counts_as_wait_activity(self._queues[name])` (`62a4504b`), `_ensure_multi_activity_waiter()` adds `_topology_sigint_critical` + `_close_candidate_resource_once` + `replace_activity_waiter` (`4a8884cb`), and Taut's two divergence seams span three methods.
     - *Disposition:* **Fixed in plan** — Updated `## Goal`, `## Source Documents`, `## Theory-Versus-Code and Theory-Versus-Spec Audit Table`, `## Invariants`, and `Slice 2` with exact path `weft/core/tasks/multiqueue_watcher.py`, exact SHA-256 digests (`713060f...` / `792d34b...`), two-divergence-seam wording, and three RED tests matching `4a8884cb`, `956acab1`/`14d84f29`, and `62a4504b`.
  2. **`[P1]` Preserve binary `"wb"` dump serialization in `dump_workspace()`:**
     - *Reproduction:* Verified `taut/persistence/_operations.py:345-480`. `dump_workspace()` opens `os.fdopen(fd, "wb")` and writes/hashes UTF-8 `bytes`.
     - *Disposition:* **Fixed in plan** — Updated `## Goal`, `## Audit Table`, `## Context`, and `Slice 3` Step 3 to target `dump_workspace()` and preserve `os.fdopen(fd, "wb")`, changing only exclusive `os.open(..., O_WRONLY | O_CREAT | O_EXCL, 0o666)` creation and post-open `temp_path` cleanup ownership.
  3. **`[P2]` Preserve `"indeterminate"` (`start_time=None`) vs `"dead"` (`capture_process() -> None`) in `[IAN-3.2]` and `taut/identity.py`:**
     - *Reproduction:* Verified `taut/identity.py:535-624` and `extensions/taut_summon/taut_summon/_state.py:646-660`. `start_time_token()` catches `psutil.Error` (swallowing `ZombieProcess`), while `_evidence_liveness()` maps `proc.start_time is None` to `"indeterminate"` (requiring `--takeover`).
     - *Disposition:* **Fixed in plan** — Updated `Replacement` 3a (`[IAN-3.2]`) and `Slice 3` Step 1 so live unreadable `start_time` still yields `ProcessInfo(..., start_time=None)` (`"indeterminate"`), while `start_time_token()` re-raises `(psutil.NoSuchProcess, psutil.ZombieProcess)` and `_capture_psutil_process` / `_capture_linux_process` return `None` (`"dead"`) on proven exit or zombie state.
  4. **`[P2]` Repair spec `Replacement` boundaries in `[DOM-14]` and `[AT-REF-2]`:**
     - *Reproduction:* Verified `01-development-documentation-operating-model.md:753-761` (`unknown` vs `unknown statuses,`) and `07-agent-theory-and-program-theory.md:100-151` (`L100` start of self-test).
     - *Disposition:* **Fixed in plan** — Extended `Replacement` 1d through the full paragraph (`L753–761`) and corrected heading 5a's anchor note to `L100–151`.
  5. **`[P2]` Correct executable anchors, flags, and helper signatures:**
     - *Reproduction:* Verified `tests/test_command_registry.py` + `tests/test_command_syntax.py`, `.github/workflows/release-gate.yml`, `bin/ruff_suppression_index.py --write` & `_atomic_replace` (`ToolFailure` with `OSError` cause), `resolve_config("TAUT", defaults=TAUT_CONFIG_DEFAULTS, env=os.environ, override=overrides)` (plus deterministic warning-filter non-mutation test), and `simplebroker @ 178822b`'s `batch_object_info` / `reachable_commits`.
     - *Disposition:* **Fixed in plan** — Updated `Slice 1`, `Slice 2`, `Slice 3`, and `Slice 4` with all exact live names, signatures, and flags.

### Plan Review — Round 2 (`codex-cli 0.161.0`, Tier-1 cross-family read-only sandbox, 2026-11-10)

- **Reviewer:** `codex` (`codex exec -s read-only --skip-git-repo-check -C /Users/van/Developer -c 'model_reasoning_effort="high"'`)
- **Reviewed baseline:** `5b8e439`
- **Verdict:** **`PASS`** (all five Round-1 findings `F1`–`F5` verified resolved; 1 non-blocking precision note; 0 out-of-scope observations; 0 reconsideration requests)
- **Findings & Dispositions:**
  1. **`[P2]` Non-blocking prose precision on `SummonReactor._fetch_next_message` and `_reactor.py` path (`R2-F1`):**
     - *Reproduction:* Verified `extensions/taut_summon/taut_summon/_reactor.py:101-111`. `SummonReactor` is defined in `_reactor.py` (imported by `_driver.py`), `self._delivery_pending` is a boolean attribute, and `_fetch_next_message` guards intra-pass PEEK lanes with `if not self._queue_counts_as_wait_activity(config): return None` (preserving the `control_queue_name` exception).
     - *Disposition:* **Fixed in plan** — Updated `## Audit Table`, `## Comprehension Check` item 2, and `Slice 2` (`Read first` and `Step 2`) to cite `_reactor.py` and the exact `if not self._queue_counts_as_wait_activity(config): return None` guard. Per `[DOM-11]` / `agent-theory @ e6ac579`, review loop closes after local gate verification without a Round 3.

### Completed-Work Review — Round 1 (`codex-cli 0.161.0`, Tier-1 cross-family read-only sandbox, 2026-11-10)

- **Reviewer:** `codex` (`codex exec -s read-only --skip-git-repo-check -C /Users/van/Developer -c 'model_reasoning_effort="high"'`, thread `01a1c75e-d725-7cb0-8af9-6735b87185bb`)
- **Verdict:** `blocker: F1` (`0` production-runtime defects; `1` `[DOM-14]` lesson-fold fidelity/citation defect `F1`; `1` non-blocking test-clock reliability note `F2`; `1` pre-existing out-of-scope observation; `0` reconsideration requests)
- **Findings & Dispositions:**
  1. **`F1` (`[P2]`, accepted blocker — `docs/lessons.md:126`):**
     - *Reproduction:* Verified against `git show f4275a6:docs/lessons.md:107-115` and `docs/specs/03-identity-addressing-notifications.md`. Folding the 2026-09-24 harvested message-react lesson into the 2026-09-24 distilled pointer dropped its durable process rule (*promote a spec only against a published upstream primitive whose target-selection semantics were runtime-probed against Taut's own state lifecycle; block and add missing capabilities upstream rather than compensating locally*) and cited a nonexistent `[IAN-7.7]` section code.
     - *Disposition:* **Fixed in code/docs** — Restored the 2026-09-24 harvested message-react lesson verbatim in `docs/lessons.md`, narrowed the 2026-09-24 distilled pointer to the 2 truly owned entries (`distilled from 2 entries`), and reconciled the derived counts (`5` folded / `21` kept verbatim / `108` total dated entries) in `docs/coalescing.md` and `## Execution Log`. Verified via `bin/coalesce-check` and `tests/test_docs_references.py`.
  2. **`F2` (`[P3]`, accepted non-blocking — `tests/test_watcher.py:4416`):**
     - *Reproduction:* Verified `tests/test_watcher.py:4396-4419`. `threading.Event().wait(0.01)` inside `quiet_pass` plus `assert quiet_waits >= 3` within `timeout=0.08` coupled sub-case `(b)` to OS scheduler wakeup latency when one delayed sleep could reach `0.08s` after a single pass.
     - *Disposition:* **Fixed in test** — Replaced `threading.Event().wait(0.01)` in sub-case `(b)` with the deterministic module-local `SimpleNamespace(monotonic=...)` clock (`now_b += 0.03` per pass, asserting exact `quiet_waits == 3` and `watcher.observation_calls == 2`). Verified via `pytest tests/test_watcher.py`.
- **Out-of-scope observation recorded:** Pre-existing `_start_postgres_container()` readiness error cleanup ownership in `taut/_scripts.py` (predates `5b8e439`; unchanged by this wave).

### Completed-Work Review — Round 2 (`codex-cli 0.161.0`, Tier-1 cross-family read-only sandbox, 2026-11-10)

- **Reviewer:** `codex` (`codex exec resume 01a1c75e-d725-7cb0-8af9-6735b87185bb --skip-git-repo-check -c 'sandbox_mode="read-only"' -c 'model_reasoning_effort="high"'`)
- **Verdict:** **`no blocker`** (`F1` verbatim lesson restoration, citation cleanup, and `5` folded / `21` kept / `108` total / `3` post-watermark counts independently re-derived and verified; `F2` deterministic module-local clock verified to execute `3` waits and `2` observation reads; `0` new defects; `0` reconsideration requests). Review loop closed.

### Completed-Work Review — Post-Review Fixes Round 1 (`codex-cli 0.161.0`, Tier-1 cross-family read-only sandbox, 2026-11-10)

- **Reviewer:** `codex` (`codex exec -s read-only --skip-git-repo-check -C /Users/van/Developer/taut -c 'model_reasoning_effort="high"' --json`, thread `01a1c785-a024-7d13-9e0f-4deed3a84e0c`)
- **Unit:** Deviation Log items 8–11 only (binary dump staging, restored leading-`--` guard, `pytest-pg` readiness-failure cleanup, interpreter-pinned Ruff in the suppression index).
- **Verdict:** **`no blocker`** (`1` nit; parser, readiness, and Ruff tests confirmed to fail against in-memory pre-fix controls; `Replacement` blocks confirmed to match their specs; no permission-policy, exclusive-creation, collision-cleanup, or literal-grammar regression).
- **Findings & Dispositions:**
  1. **`F1` (nit — `taut/_scripts.py::_launch_postgres_container` docstring):** claimed an interrupt during the readiness wait reaches log capture; `KeyboardInterrupt` gets removal only. *Disposition:* **Fixed** — docstring narrowed.
- **Observation recorded:** the reviewer could not independently verify the Windows `os.fdopen` text-mode premise or the CPython argparse version cutoffs from repository files; the author verified both against CPython sources (`tempfile._bin_openflags`; `parse_known_intermixed_args` text at `v3.11.15`, `v3.12.0`, `v3.12.7`, `v3.12.8`, `v3.13.0`, `v3.13.1`) and a local `3.11.15` run. Fix 1's RED remains Windows-CI-only, as declared in Deviation Log item 8.

### Release Pre-Tag CI Correction Review (`agy 1.5.5`, Gemini Tier-1 read-only plan sandbox, 2026-11-10)

- **Reviewer:** `agy` (`agy --mode plan --sandbox --model gemini-4-argon-medium --output-format json --print-timeout 900s`, conversation `271c6ed2-d76b-4aa9-a933-fbae7f12839a`)
- **Unit:** Deviation Log items 12–13 only: the exited-child Summon rejoin correction, its RED test, and the watcher test's event-based synchronization.
- **Verdict:** **`no blocker`** (`0` in-scope findings; `2` non-actionable observations; `0` reconsideration requests). The reviewer traced `_accept_spawn` → `_rejoin` → `_harness_dead` → owner teardown/backoff, verified that live-but-indeterminate identity evidence still raises, confirmed the RED test's falsifiability, and verified the watcher event's happens-before edge.
- **Observations recorded:** A direct `_accept_spawn` unit test would be optional because the changed glue is three lines and the concurrent process suite exercises it. The pre-existing possibility of an `unknown` final exit code when an adapter has no early pump was not worsened by this change. Neither observation requires expansion of this release correction.

### Release Watcher-Correction Review (`agy 1.5.5`, Gemini Tier-1 read-only plan sandbox, 2026-11-10)

- **Round 1 reviewer:** `agy`, conversation `96f9874c-fd41-4e7b-8b56-804bd08057c8`.
- **Unit:** Deviation Log items 13–14 after exact-SHA run `42949404845`: synchronous waiter setup plus event-based membership refresh/close observation.
- **Verdict:** **`blocker: F1`** (`1` P2 blocker, `1` accepted nit). `F1` found that the first refresh pre-set removal events for all not-yet-added churn names, making later removal waits tautological. `F2` found the global `Queue.close` spy was installed after the background owner started.
- **Dispositions:** **Accepted F1** — removal events now require the corresponding add event before a completed refresh may publish absence. **Accepted F2** — all close instrumentation is installed before readiness registration and thread start. The corrected pair passed 30 consecutive concurrent `-n 2 --dist load` runs.
- **Round 2 reviewer:** `agy`, conversation `93a3a80d-0ef1-4ee0-b529-5ba621375920`.
- **Round 2 verdict:** **`no blocker`**. Both accepted fixes were verified in the live test; no new defect was introduced.

## Revision Log

- `2026-11-10`: Initial Class 5+P hardened plan drafted against baseline `5b8e439`.
- `2026-11-10`: Applied all five Round-1 `codex` Tier-1 review fixes (`F1`–`F5`) across `## Proposed Spec Delta`, `## Audit Table`, `## Invariants`, and `Slices 1–4`.
- `2026-11-10`: Round-2 `codex` Tier-1 review returned `PASS`; applied `R2-F1` (`SummonReactor` `_reactor.py` path and `_queue_counts_as_wait_activity` guard prose) and closed the plan review loop.

## Deviation Log

1. **`docs/coalescing.md` provenance pin (`Slice 1`):** Pinned `docs/coalescing.md`'s `Last coalesced commit` to published `origin/main` commit `f4275a6` (`2026-09-25` watermark) so `bin/coalesce-check` verifies the provenance SHA in published history without adding a local-only SHA warning.
2. **`extensions/taut_mcp` test filename (`Slice 3`):** Updated `extensions/taut_mcp/tests/test_reactor_restoration.py` (alongside `test_pg_conformance.py` and `test_process_reactor.py`), which is the live test file corresponding to the plan's `test_workspace_reactor.py` shorthand.
3. **`load_config()` native `UserWarning` propagation (`Slice 3`):** Removing `warnings.catch_warnings(record=True)` from `taut/_config.py::load_config()` lets `simplebroker.ext.resolve_config()` emit its native `UserWarning` directly under Python's active warning filters rather than capturing and re-emitting through `logging.getLogger(__name__)`; aligned `tests/test_constants.py` and `tests/test_cli.py` accordingly.
4. **Ruff `0.17.4` PEP 695 (`UP040`/`UP046`/`UP047`/`UP049`) modernization and `[RUFF-SUP-078]` (`DTZ006`) retirement (`Slice 4`):** Raising `target-version = "py312"` and upgrading Ruff to `0.17.4` surfaced 15 PEP 695 type-parameter/type-alias findings across first-party modules and tests plus one `RUF100` stale-noqa finding on `taut/terminal.py` (`[RUFF-SUP-078]`, `DTZ006`, removed from Ruff `0.17` stable defaults). Modernized all 15 PEP 695 sites, retired `[RUFF-SUP-078]` in `taut/terminal.py` and `[DOM-10.2.1]` (`docs/specs/01-development-documentation-operating-model.md`, mirrored in `## Proposed Spec Delta` `1b`), and regenerated the derived suppression index via `bin/ruff_suppression_index.py --write`.
5. **`uv 0.13.6` duplicate wheel `entry_points.txt` key validation (`Slice 4`):** `uv 0.13+` rejects `.whl` archives containing duplicate INI keys inside `entry_points.txt` during `uv pip install`. Updated `tests/test_core_summon_wheel_matrix.py::test_installed_duplicate_official_claims_do_not_run_legacy_fallback` to install a valid wheel first and append the duplicate `summon = ...` key directly to the installed `.dist-info/entry_points.txt` before exercising `taut`'s runtime `importlib.metadata` duplicate-claim refusal.
6. **Implementation-note alignment for `08-complexity-and-suppression-policy.md` and `10-persistence-io.md` (`Slice 4`):** Updated `docs/implementation/08-complexity-and-suppression-policy.md` (removing its stale reference to the deleted `tests/fixtures/ruff-enabled-rules.txt` snapshot and documenting the `_atomic_replace` Windows `PermissionError` retry) and `docs/implementation/10-persistence-io.md` (documenting `0o666` + `O_EXCL` operator-owned dump staging) alongside `02`, `04`, `05`, and `07`.
7. **Python `3.15` setup in `.github/workflows/*.yml` (`Slice 4`):** `actions/setup-python@v7.1.0` resolves released Python `3.15` directly with `python-version: "3.15"` (matching `simplebroker` and `weft` workflows), so `allow-prereleases: true` was not needed.
8. **Binary dump staging on Windows (post-review fix, `Slice 3`):** Bare `os.open(..., O_WRONLY | O_CREAT | O_EXCL, 0o666)` omits `O_BINARY`, so the Windows fd is CRT text mode and `os.fdopen(fd, "wb")` cannot change it (CPython `FileIO` adds `O_BINARY` only when it opens a path; `tempfile` adds it explicitly, which is why the old `mkstemp` path was binary). Every LF was written as CRLF after hashing, so dump failed its own `validate_dump` digest check. `dump_workspace()` now stages with `candidate_path.open("xb")` (`O_CREAT | O_EXCL`, mode `0o666`, binary everywhere), matching Weft's `write_file_atomically` (`temp_file.open("xb")`). Updated `Replacement` 6a and `[PIO-6.2]`, `docs/implementation/10-persistence-io.md`, and the 2026-11-10 lesson. TDD exception (`testing-patterns.md` rule 5): RED is observable only on the Windows CI lanes because POSIX fds have no text mode; `tests/test_persistence_io.py::test_dump_staging_writes_exact_lf_bytes_on_every_platform` is the firing test there, and the local substitute proof is the CPython mechanism above.
9. **Leading `--` guard restored (post-review fix, `Slice 3`):** The removed shim was not 3.11-only. `parse_known_intermixed_args` in CPython `3.12.0`–`3.12.7` and `3.13.0` is textually identical to `3.11.15`'s, which fails `["--", "general", "--not-a-flag"]` with `the following arguments are required: text`; the rewrite first ships in `3.12.8` and `3.13.1`. `requires-python >=3.12` admits the old releases (for example Ubuntu 24.04's system `3.12.3`). Slice 5 probe (1) used `taut say`, which does not opt into intermixed parsing, and the isolated `3.12` smoke ran `3.12.13`, so neither exercised the affected path. Restored the guard in `CommandArgumentParser.parse_command_args()`, inverted `tests/test_command_registry.py::test_command_parser_leading_double_dash_bypasses_intermixed_parser` (RED observed before the fix), and updated `Replacement` 2b and `[TAUT-8.3]`. Summon's `_parse_run_args` already splits at `--` before intermixed parsing and is unaffected.
10. **`pytest-pg` readiness-failure cleanup (Round-1 out-of-scope observation, now fixed, `Slice 4`):** `_start_postgres_container()` raised from its readiness wait before returning the container name, so `pytest_pg_main()` printed no container logs and never removed the detached container (also on `KeyboardInterrupt` during the wait). Split it into `_launch_postgres_container()` and `_postgres_test_dsn()` so the cleanup owner holds the name before waiting, and print container logs on unexpected failures as well as test failures. `tests/test_dev_scripts.py::test_pytest_pg_main_logs_and_removes_container_that_never_became_ready` (RED observed before the fix).
11. **Suppression index runs the pinned Ruff (`Slice 4`):** `bin/ruff_suppression_index.py::_run_ruff` ran bare `ruff` from `PATH`, while `tests/test_ruff_policy.py` derives rules with `sys.executable -m ruff`. A stale global Ruff `0.16.6` first on `PATH` still flags `DTZ006` and failed `test_spec_owned_ruff_inventory_and_registry_are_current` with a false mismatch. The tool now runs `sys.executable -m ruff`; `tests/test_ruff_suppression_index.py::test_ruff_runs_from_the_running_interpreter_not_path` (RED observed before the fix).
12. **Pre-tag CI exposed an exited-child rejoin race (`Slice 3`):** The zombie-aware `capture_process()` contract correctly returns `None` for a child that has already exited, but `SummonDriver._rejoin()` still treated that normal harness lifecycle state as an identity-integrity failure. Short-lived scripted harnesses therefore terminated the driver instead of entering the existing restart policy. `_rejoin()` now distinguishes a definitely exited child (`False`) from a live child with unreadable start-time evidence (still a `DriverError`), and `_accept_spawn()` publishes `_harness_dead` for the former. `test_rejoin_reports_child_that_exited_before_identity_capture` was RED before the fix; the two CI failure paths and the new regression passed 10 consecutive focused runs, and the full concurrent Summon process suite passed with `-n auto`.
13. **Background-waiter test setup ownership (`Slice 2`):** `test_base_reactor_background_owner_closes_current_waiter` made the background owner perform waiter installation before the behavior under test, then used a three-second observation guard for that unrelated setup. Exact-SHA run `42949404845` proved that replacing the polled predicate with a waiter-entry event did not remove the setup dependency. The test now installs the current waiter synchronously, verifies native ownership, starts the background owner, and synchronizes on its existing `_running_event` before requesting stop. The assertion remains that background-owner cleanup closes the exact current waiter once; no behavior timeout or xdist concurrency was weakened.
14. **Membership-churn test uses transaction events (`Slice 2`):** `test_taut_watcher_membership_churn_closes_removed_queues` began after only observing `thread.is_alive()`, then polled foreign-thread queue and close lists for every join/leave. Windows Python `3.15` completed `churn0` but could spend the next three-second guard in filesystem/scheduler overhead before publishing `churn1`. The test now registers `notify_ready_after_initial_drain()` before start and instruments the real `_refresh_memberships()` and `Queue.close()` calls with test-owned events. Each of the ten cycles waits for its actual add, remove, and close transactions, then retains the exact queue-state and owner-thread assertions. Deadlock guards use the already accepted Windows process/filesystem factor (`10s` Windows, `3s` elsewhere); cycle count, close ownership, post-churn delivery, and xdist concurrency are unchanged.
15. **PTY terminal-state sentinel excludes input echo (`Slice 4`):** The local release gate caught `test_scripted_root_cli_detach_control_plane_and_fresh_attach[legacy]` matching `STTY-DONE` in the echoed shell command before `stty -a` executed; the captured tokens contained only `stty`, `-a`, `printf`, and the format literal. The command now constructs the sentinel at runtime with `printf '\nSTTY-%s\n' DONE`, so terminal input cannot satisfy the output wait. The exact `icanon` / `echo` / `isig` assertions remain unchanged; the focused test passed 20 consecutive runs.

## Execution Log

- **Slices 0–4 completed and verified (2026-11-10):** Applied all spec `Replacement` blocks (`Slice 0`), upgraded `bin/{check-plan-status-index,check-doc-paths,coalesce-check}` + program theory + coalescing sweep (`Slice 1`), re-pinned `taut/watcher.py` to Weft `0.9.124` / `62a4504b` (`Slice 2`), landed zombie-aware liveness, thread-safe `load_config()`, `0o666` `O_EXCL` dump staging, Python `3.11` `--` shim removal, and `taut_mcp` `simplebroker.ext.PollingStrategy` (`Slice 3`), and rotated manifests, lockfiles, Ruff `0.17.4` dynamic policy, wheel matrix `3.12`–`3.15`, `pytest-pg` TCP readiness + container failure logs + `-v` volume cleanup, and all 11 GitHub Actions workflows (`Slice 4`).
- **Slice 5 full verification floor and adversarial probes (2026-11-10):**
  - `uv run --no-sync bin/check-doc-paths --self-test` & `bin/check-doc-paths`: `OK` (`65 source(s), 1604 path claim(s)` + promoted `Replacement` block sync).
  - `uv run --no-sync bin/check-plan-status-index`: `OK`.
  - `uv run --no-sync bin/check-dom15-fixtures`: `OK`.
  - `uv run --no-sync bin/coalesce-check`: `OK` (`108 total, 3 past the 2026-09-25 watermark`, `all cues resolve`).
  - `uv run --no-sync bin/check-cli-claims`: `OK` (`65 source(s), 299 command claim(s)`).
  - `uv run --no-sync python bin/ruff_suppression_index.py --check`: `OK` (exit `0`).
  - `uv run --no-sync ruff check .` & `ruff format --check taut tests bin extensions`: `All checks passed!`, `311 files already formatted`.
  - `mypy` across root (`191` files), `taut_mcp` (`22` files), `taut_tui` (`56` files), `taut_summon` (`55` files), and `taut_pg` (`11` files): `Success: no issues found`.
  - `uv run --no-sync pytest`: `2445 passed, 5 skipped in 41.30s`.
  - `taut_summon` suite (`not requires_live_harness and not requires_local_llm`, with `SIGHUP` restored to `SIG_DFL` when invoked under a harness that sets `SIG_IGN`): `718 passed, 11 skipped` (`717 passed` + `test_pty_posix.py` `20 passed, 3 skipped`).
  - `taut_mcp` suite: `333 passed, 10 skipped in 10.29s`.
  - `taut_tui` suite: `765 passed, 3 skipped in 277.23s`.
  - `TAUT_PG_UV_NO_SYNC=1 uv run --no-sync ./bin/pytest-pg --fast` (Docker `postgres:18` over TCP `127.0.0.1` with `simplebroker 8.8.1` + `simplebroker-pg 4.8.1`): `288 passed in 31.60s` (`shared and not slow`) + `49 passed in 10.00s` (`pg_only`).
  - Python `3.12.13` isolated smoke (`tests/test_cli.py`, `tests/test_identity.py`, `tests/test_persistence_io.py`): `329 passed, 5 skipped in 9.00s`.
  - Adversarial acceptance probes (`docs/agent-context/runbooks/adversarial-acceptance-probes.md`): (1) `taut say --as Probe -- general --not-a-flag` / `--also-not-a-flag` verified on Python `3.14` and isolated Python `3.12`; (2) `taut system dump` under `umask 0027` produced `0o640` in `0700` and `0750` directories and refused a pre-seeded `O_EXCL` staging collision without unlinking the sentinel; (3) compiled real native `claude` child process transitioned to unreaped POSIX `STATUS_ZOMBIE`, verified `capture_process(pid) is None`, `taut who --json` `presence == "gone"`, `driver_liveness == "dead"`, and `claim_driver(..., takeover=False)` succeeded immediately.
  - `git diff --check`: `OK` (exit `0`).
- **Post-review fixes, Deviation Log items 8–11 (2026-11-10):** RED observed before each fix for items 9, 10, and 11 (item 8 is Windows-CI-only, as declared). After the fixes: `bin/check-doc-paths` (+ `--self-test`), `bin/check-plan-status-index`, `bin/check-dom15-fixtures`, `bin/coalesce-check`, `bin/check-cli-claims`, and `bin/ruff_suppression_index.py --check`: `OK`; `ruff check .` and `ruff format --check .`: clean; `mypy` (CI root and `taut_summon` targets): `Success: no issues found in 146 / 55 source files`; root `pytest`: `2453 passed, 5 skipped`; `taut_summon` suite (`not requires_live_harness and not requires_local_llm`): exit `0`; `test_spec_owned_ruff_inventory_and_registry_are_current` now passes with a stale global Ruff `0.16.6` first on `PATH`; `git diff --check`: `OK`. Not run: `taut_mcp`, `taut_tui`, `pytest-pg`, and Windows lanes.
- **Release pre-tag CI correction (2026-11-10):** Exact-SHA run `42944695052` blocked publication before tags. Seven concurrent Summon process lanes exposed the exited-child rejoin race from Deviation 12; Ubuntu Python `3.15` exposed the unsynchronized watcher assertion from Deviation 13. No failed job was ignored or retried. The deterministic RED and focused repeated proofs are recorded above; the full concurrent Summon process suite passed after the fix. Publication remains gated on a fresh exact-SHA run of all required workflows.
- **Release pre-tag CI correction, second exact-SHA run (2026-11-10):** Run `42949404845` independently verified the Summon correction across completed process lanes, but Ubuntu Python `3.15` disproved Deviation 13's first event design because it still coupled the assertion to background setup. Windows Python `3.15` exposed the missing initial-drain readiness barrier in Deviation 14. Both corrected watcher tests passed 30 consecutive concurrent `-n 2` runs locally. Publication again remained blocked before tags; no failed job was retried or ignored.
- **Local release rerun correction (2026-11-10):** The full release gate passed core and PostgreSQL, then exposed Deviation 15's PTY input-echo sentinel race in the concurrent Summon unit lane. The release stopped before push/tagging. After the one-line sentinel correction, the exact focused case passed 20 consecutive runs; the complete release floor is rerun from the clean committed tree rather than resuming after the failed assertion.
