# Numeric Start-Time Token Plan

Status: active — revised 2026-09-15 after independent review and owner
disposition; scoped revision verification passed. Spec promotion has not begun.
Class: 5 (spec-changing). [DOM-5] risky
trigger fires: identity anchoring is a public contract and the token is
persisted, so the hardening-plans checklist applies. Plan type:
implementation with spec revision. Promotion strategy: A (spec text lands
first, code follows).

Owner: implementing engineer. The repository owner decided on 2026-09-15:
one stable per-platform source for a process's start time, normalized by
Python into digits, with no text token and no `ps` subprocess anywhere; and
no backward compatibility for tokens stored by earlier releases, because
the tool is still internal.
There is no live migration and no legacy state to preserve.

## Goal

Make the process start-time token that anchors agent identity a number on
every platform, produced by one function from the one kernel-stored value
that never changes for a live process: `/proc/<pid>/stat` ticks on Linux,
the unadjusted kernel creation time via psutil on macOS and Windows.
Delete the `ps` capture path. Existing stored tokens are not migrated.

## Source documents

Surfaces consulted: `AGENTS.md`; `docs/program-theory.md` [THEORY-3]
(identity claim is "deterministic and inspectable, never authenticated");
`docs/agent-context/decision-hierarchy.md`;
`docs/agent-context/principles.md`;
`docs/agent-context/engineering-principles.md`;
`docs/agent-context/runbooks/testing-patterns.md`;
`docs/agent-context/runbooks/review-loops-and-agent-bootstrap.md`;
`docs/agent-context/runbooks/writing-plans.md` §4b–§4d;
`docs/agent-context/runbooks/hardening-plans.md`; `docs/lessons.md` Golden
Rules 1, 2, 6, 13; `docs/specs/03-identity-addressing-notifications.md`
[IAN-3.2], [IAN-3.3]; `docs/implementation/04-taut-architecture.md`
"Process capture" bullet; psutil 7.2.2 source (`_pslinux.py`,
`_psosx.py`, `_pswindows.py`, `__init__.py`); the 0.9.7 review finding
that `LC_ALL=C` changed the stored token for macOS users on de, fr, ja,
and en_GB locales. Revision evidence: the 2026-09-15 Codex review in this
task, its independent slice/consumer subagent review, and the owner
dispositions accepting the unadjusted macOS source, combined implementation
slice, corrected tests, and no-live-migration boundary.

## Evidence

Why the token must not be text: 0.9.6 stored macOS `ps -o lstart=` output
under the user's locale (`Di. 15 Sep. 09:43:43 2026`), 0.9.7 forced
`LC_ALL=C` (`Tue Sep 15 09:43:43 2026`), and `match_anchor`,
`member_presence`, and the claim hash all compare that string exactly. Any
text rendering has a second observer somewhere.

Why not `psutil.Process.create_time()` on every platform (psutil 7.2.2):

- Linux `_pslinux.py` computes `starttime_ticks / CLOCK_TICKS +
  boot_time()`, and `boot_time()` re-reads `btime` from `/proc/stat` on
  every call. `btime` moves by a second under NTP slew or a clock step, so
  two `taut` invocations can render one pid as two floats. psutil's own
  comment says the raw ticks "never change and are unaffected by system
  clock updates". The stable form is `create_time(monotonic=True)`, which
  exists only on the private per-platform object.
- macOS public `Process.create_time()` applies `_psosx.py`'s
  `adjust_proc_create_time`, relative to the boot time observed at psutil
  import. Repeated calls without a clock change do not prove stability.
  The review reproduced a 2,000,000-microsecond token change for one real
  live PID by varying only psutil's boot-time observation by two seconds;
  the raw kernel start time stayed equal and the system clock was untouched.
  `proc._proc.create_time(monotonic=True)` bypasses that adjustment and
  returns the stored `kinfo_proc` creation time. On macOS the parameter
  does not convert it to elapsed time. Psutil itself uses this private
  path for stable process identity in `Process._get_ident`.
- Windows `_pswindows.py` returns the `GetProcessTimes` creation time,
  stored at creation. Stable.

Python's `int()` and f-string formatting ignore `LC_NUMERIC`, so a token
rendered by Taut as digits is locale-independent by construction.

## Context and key files

`taut/identity.py` today:

- `capture_process(pid)` tries `_capture_psutil_process`, then on Linux
  `_capture_linux_process`, then `_capture_ps_process`.
- `_capture_psutil_process` sets `start_time = _native_start_time(pid) or
  _psutil_start_time(proc)`. `_native_start_time` reads `/proc` ticks on
  Linux and calls `_read_ps_lstart` elsewhere; `_psutil_start_time` returns
  `f"psutil:{proc.create_time():.6f}"`. On Windows, `ps` does not exist, so
  the psutil form is what Windows stores today.
- `_capture_linux_process` reads `fields[19]` of `/proc/<pid>/stat`
  directly (bare digits) when psutil fails.
- `_capture_ps_process`, `_ps_output`, `_reconstruct_ps_argv`, and
  `_read_ps_lstart` are the `ps` path. `_ps_output` is the only place
  `LC_ALL` is set. `_capture_cwd_with_lsof` is used only by the `ps` path.
- `select_anchor` routes a chain entry with `start_time is None` to human
  fallback. `match_anchor` and `member_presence` compare `start_time`
  strings exactly. `claim_for_capture` hashes `anchor_start_time`;
  `fingerprint_for_process` records it. `rejoin` rewrites it through
  `update_member_anchor`.
- `ProcessInfo.start_time: str | None`.

Consumers of the token outside core identity:

- `taut/state/_sql.py` column `anchor_start_time TEXT` and the
  `update_member_anchor` write; `taut/client/_identity.py` `rejoin`.
- `extensions/taut_summon/taut_summon/_state.py` stores
  `driver_start_time TEXT` from `capture_process` and compares it exactly
  for driver liveness (`_evidence_liveness` and `claim_driver`);
  `extensions/taut_summon/taut_summon/_driver.py` calls `capture_process`
  for the same purpose. Both keep working unchanged because they compare
  tokens captured by the same function on the same host.

Tests: `tests/test_identity.py` covers the `ps` path
(`test_ps_output_returns_stripped_stdout_or_none`,
`test_native_start_time_uses_platform_specific_reader`,
`test_ps_lstart_token_is_locale_independent`, the `_capture_ps_process`
tests around lines 937–944 and 1268–1284, `_reconstruct_ps_argv` at 1252),
the Linux reader (`test_read_linux_start_time_parses_proc_stat` and the
two malformed cases), and `_psutil_start_time` (line ~1066). Other tests
use fixture strings like `"start"` for `start_time`, which stay valid
because the field type is unchanged.

Docs: spec 03 [IAN-3.2] evidence table row `agent_process` says "anchor
start token"; [IAN-3.3] step 4 names the triple; implementation doc 04's
"Process capture" bullet explains `ps` and `LC_ALL=C`; spec 02 declares
the column.

## Invariants and constraints

1. A token is produced by exactly one function, `start_time_token`, and is
   either `None` or matches `^(proc|psutil):[0-9]+$`. Production capture
   constructors only pass through this helper's result; they never derive
   a token independently. Synthetic test fixtures may use literal tokens.
2. Same live process, same host, any two captures, any locale, any
   capturing-process lifetime: equal tokens. This is the invariant the
   locale bug broke and the reason Linux does not use wall-clock arithmetic.
3. No subprocess is spawned to obtain a start time on any platform.
4. `select_anchor` still routes `start_time is None` to human fallback;
   `match_anchor`, `member_presence`, `claim_for_capture`,
   `fingerprint_for_process`, and `rejoin` are unchanged.
5. The `anchor_start_time` and `driver_start_time` columns stay `TEXT`;
   no schema version bump.
6. `capture_process` on Linux keeps the `/proc` fallback when psutil
   cannot read a process; on macOS and Windows a psutil failure yields
   `None` for that pid and the chain walk stops there.
7. No compatibility reader, migration, or mixed-version driver protection
   is added. There is no live migration and no legacy state to preserve.

Hidden couplings:

- Summon driver and bootstrap liveness compare tokens exactly through
  `_evidence_liveness`. Current producers and consumers must agree;
  mixed-version operation is outside the owner-defined scope.
- `_capture_cwd_with_lsof` has no caller once the `ps` path is deleted;
  it goes with it, and so do its tests.
- `test_capture_process_prefers_psutil_then_platform_fallbacks` owns
  backend routing; rewrite its off-Linux outcome instead of replacing it
  with another successful-psutil assertion.
- `test_capture_psutil_process_reads_best_effort_fields` owns field
  plumbing; replace its `_native_start_time` patch with a known helper
  result and update the expected token in the same edit.
- `test_capture_linux_process_reads_procfs_fields` is a synthetic parser
  test that also runs off Linux. Explicitly select the Linux branch there
  and expect `proc:98765`; native Linux proof remains separate.
- The macOS branch uses a private psutil API. Keep that dependency inside
  `start_time_token`, document why it is needed, and let native macOS
  contract tests expose dependency drift. Never fall back to the adjusted
  public API when the private interface changes.

## Decisions

### One function, one branch, digits only

```python
def start_time_token(pid: int, proc: psutil.Process | None) -> str | None
```

- Linux: read `/proc/<pid>/stat`, take field 22 (`fields[19]` after the
  `) ` split already used in `_capture_linux_process`), return
  `f"proc:{ticks}"`. This is the value psutil itself calls unaffected by
  clock updates. `proc` is ignored on Linux.
- macOS: `proc._proc.create_time(monotonic=True)` from the existing psutil
  process object, bypassing the boot-time adjustment.
- Windows: public `proc.create_time()` from the existing psutil object.
- Both use `f"psutil:{round(seconds * 1_000_000)}"`: integer microseconds,
  no decimal point, no float `repr` dependence. Windows' 100 ns creation
  time is exposed as a float by psutil and deterministically rounded;
  the token is an identity discriminator, not a lossless timestamp export.
- Any read failure returns `None`, which is human fallback, never a
  guessed token.

Rejected: appending the Linux boot id. Repeating the same PID and start
tick across boots can collide; no numerical probability is claimed.
This plan retains that existing raw-tick collision surface rather than
adding a second source that some containers cannot read.

Rejected: rounding `create_time()` to whole seconds. Rounding does not
resolve a boundary straddle, and the Linux drift is the problem it would
have to solve.

Rejected for this change: a native `libproc.proc_pidinfo(PROC_PIDTBSDINFO)`
binding. Its integer seconds/microseconds fields avoid private psutil APIs
and floating-point conversion, but require a maintained native structure
binding and ABI tests. The owner accepted the smaller private-psutil path;
its dependency-upgrade risk is explicit above.

### The `ps` path is deleted, not kept as fallback

`_capture_ps_process`, `_ps_output`, `_reconstruct_ps_argv`,
`_read_ps_lstart`, `_native_start_time`, `_read_linux_start_time`,
`_psutil_start_time`, and `_capture_cwd_with_lsof` are removed. On Windows
the path was already inert (`ps` absent). A native macOS review probe read
all six processes in the reviewer's ancestry without psutil errors. That
is host evidence, not proof that every psutil failure means process exit.
Preserve the native ancestry qualification and stop gate in Slice 2.

### No migration

There is no live migration and no legacy state to preserve. Implement the
new token directly. Do not add compatibility handling, legacy fixtures,
migration tests, mixed-version driver guards, or stop-before-upgrade work.
The earlier review finding about live old drivers is withdrawn under this
owner-supplied operating boundary.

## Spec baseline

- `c24cec07e426227454d6aff949e8752835a87965` —
  `docs/specs/03-identity-addressing-notifications.md`,
  `docs/specs/02-taut-core.md` at plan authoring time.
- Promotion baseline identifier: `dd6eac4` — the spec-promotion slice.

## Proposed spec delta

| Spec file | Strategy | Sections touched |
|-----------|----------|------------------|
| `docs/specs/03-identity-addressing-notifications.md` | A | [IAN-3.2] new paragraph after the claim-kind table; [IAN-3.3] step 4 one sentence |

### [IAN-3.2] — insert after the "Supported claim kinds" table

> The anchor start token is a platform start-time value that the kernel
> stores once at process creation and never recomputes, rendered by Taut
> as digits with a scheme prefix: `proc:<ticks>` from `/proc/<pid>/stat`
> field 22 on Linux, and `psutil:<microseconds>` from the process creation
> time on macOS and Windows, without read-time boot-clock adjustments. It matches `^(proc|psutil):[0-9]+$`. Taut
> never derives it from wall-clock arithmetic and never spawns a
> subprocess to obtain it, so two captures of one live process agree
> regardless of locale, clock adjustments, or capturing process lifetime.
> A process whose start time cannot be read has no token and cannot be an
> `agent_process` anchor.

### [IAN-3.3] step 4 — replace one sentence

Anchor: "resolution may match a stored member anchor by the stable triple
(`host_id`, `anchor_pid`, `anchor_start_time`) against the captured
ancestor chain."

> resolution may match a stored member anchor by the stable triple
> (`host_id`, `anchor_pid`, `anchor_start_time`) against the captured
> ancestor chain, comparing the [IAN-3.2] start token by exact equality.

### Related Plans

Add to spec 03's `## Related Plans` (create the section at the end of the
file if absent):

> - `docs/plans/2026-09-15-numeric-start-time-token-plan.md` — one
>   numeric per-platform start-time token and removal of `ps` capture.

## Deviation Log

| Date | Slice | Deviation | Reason | Spec edit |
|------|-------|-----------|--------|-----------|
| — | — | none yet | — | — |

## Required reading and comprehension check

Before Slice 2 the implementer reads psutil's `_pslinux.py::create_time`
and `boot_time`, `_psosx.py::create_time` and `adjust_proc_create_time`,
`__init__.py::Process._get_ident`, and `taut/identity.py`'s capture helpers
and `select_anchor`. Record answers in the execution handoff before edits;
an incorrect answer requires rereading the owning code before proceeding.

1. Why does Linux not use public `proc.create_time()`? (It adds a boot
   time re-read from `/proc/stat`, which can change with clock adjustments.)
2. Why does macOS use `proc._proc.create_time(monotonic=True)`? (It returns
   the stored kernel creation time without the public API's boot-time
   adjustment. It is private API, confined to one helper.)
3. What happens to an eligible non-wrapper chain entry with no token?
   (`select_anchor` returns human fallback at that entry.)
4. What compatibility work is owed? (None: no live migration or legacy
   state. Current Summon producers and consumers still need verification.)

## Slices

### Slice 0 — independent plan review

Run the review in "Independent review loop". Disposition every finding in
the Review Log before Slice 1.

### Slice 1 — spec-promotion slice

Files: `docs/specs/03-identity-addressing-notifications.md`.

1. Apply the delta verbatim.
2. `uv run pytest tests/test_docs_references.py -q -n 0` and
   `uv run python bin/check-doc-paths`.
3. Commit: `Promote numeric start-time token contract`. Record the SHA as
   the promotion baseline above.

Stop gate: any wording change outside the three delta items goes back
into the delta first.

### Slice 2 — numeric capture and removal of the ps path

Files: `taut/identity.py`, `tests/test_identity.py`.

Token conversion and fallback removal are one implementation slice. Its
final contract gates run after both changes; there is no intermediate
commit retaining a text-token producer.

#### Red tests and preserved coverage

Add or rewrite these tests before implementation. Test names below are
implementation targets, not claims that they already exist. Use
`TOKEN_RE = re.compile(r"^(proc|psutil):[0-9]+$")` with `fullmatch`.

| Test | Boundary and required assertion |
|------|----------------------------------|
| `test_start_time_token_is_digits_with_scheme_on_this_platform` | Real current PID and fresh psutil object; require non-null, full regex match, `proc` on Linux and `psutil` on macOS/Windows. |
| `test_linux_start_time_token_is_proc_stat_field_22` | Native Linux only; independently read field 22 and assert exact `proc:<ticks>` equality. |
| `test_macos_start_time_token_is_integer_microseconds` | Native macOS only; compare the helper result with integer microseconds from the unadjusted private source on a fresh psutil object. |
| `test_windows_start_time_token_is_integer_microseconds` | Native Windows only; compare with integer microseconds from public `create_time()` on a fresh psutil object. |
| `test_macos_start_time_token_ignores_boot_time_adjustments` | Native macOS, real PID and real kernel reads; patch only `_psosx.INIT_BOOT_TIME` and `_psosx.boot_time` to model unchanged, +2-second, and -2-second observations. Fresh psutil object for every capture. Assert the raw value and all non-null tokens stay equal. Also show that the public adjusted source changes under the same observations, so the test demonstrates the original root cause. Never change the host clock. |
| `test_start_time_token_matches_across_observer_processes` | On each native platform, keep the pytest parent alive as the target and launch two fresh Python observers using `sys.executable`. Each imports the production helper and captures the parent's PID. Supply distinct locale environments (`LC_ALL`/`LANG` set to `C` versus `de_DE.UTF-8`/`ja_JP.UTF-8`); observers print only the token. Require successful exits, non-null correctly shaped tokens, and equality. Use bounded subprocess completion and no fixed sleeps. Locale installation is not required: the assertion is that these environment values cannot affect the token. |
| `test_start_time_token_returns_none_when_unreadable` | Controlled source failures: Linux `OSError` reading stat; macOS `psutil.AccessDenied` from the private creation-time path; Windows the same error from the public path. Keep the production helper real; assert `None`. |
| `test_start_time_token_without_psutil_object_off_linux` | Native macOS/Windows; `start_time_token(pid, None)` returns `None`. Linux's real `proc=None` path is covered by the field-22 test. |
| `test_linux_start_time_token_rejects_malformed_stat` | Synthetic Linux parser cases: missing separator with at least 20 fields and a numeric field at index 19 (so length alone cannot reject it), short fields, empty token, non-digit token, and non-ASCII digit token. Require `None`; preserve the existing malformed-reader cases when moving ownership to the new helper. |
| `test_capture_process_never_spawns_a_subprocess` | Real readable current PID, subprocess tripwire active during capture only; require a non-null capture and token. |
| `test_capture_process_psutil_failure_never_spawns_a_subprocess` | Force `_capture_psutil_process` to return `None` while the subprocess tripwire is active. On native Linux require a real `/proc` capture and exact token; off Linux require `None`. |
| `test_capture_without_start_time_uses_human_fallback` | Fail the native start-time source while preserving readable process metadata; call production capture, require a retained process with `start_time is None`, then pass it to real `select_anchor` and require human fallback. The fixture must represent a non-wrapper, non-infrastructure process so classification cannot mask the missing-token branch. |

For the subprocess tripwire, patch `subprocess.run` only in a narrow
`monkeypatch.context()` surrounding production capture. The observer test
runs outside that context: its subprocesses are test infrastructure.
For the macOS clock test, choose a fixed nonzero import-time boot value;
patch module-local psutil observations, not global stdlib clock functions.

Correct these existing tests in the same red-test edit:

- Rewrite `test_capture_process_prefers_psutil_then_platform_fallbacks`
  into explicit routing cases: psutil success; Linux psutil failure with
  `/proc` success; off-Linux psutil failure returning `None`. Controlled
  `sys.platform` and backend patches are allowed here. Do not replace the
  old `_capture_ps_process` patch with another successful psutil branch.
- In `test_capture_psutil_process_reads_best_effort_fields`, replace the
  `_native_start_time` patch with `start_time_token` returning the known
  token `psutil:123456000`, and change the expected `ProcessInfo` token
  to that value. This proves plumbing; the unreadable test above owns
  failure behavior.
- In `test_capture_linux_process_reads_procfs_fields`, explicitly select
  the Linux branch for its synthetic procfs fixture and change the
  expectation from `98765` to `proc:98765`. Retain the production token
  helper. This unit test may run on any host; it is not native-platform
  evidence.
- Move the `_read_linux_start_time` parsing/error assertions to
  `start_time_token` tests before removing their old helper tests. Remove
  obsolete `_native_start_time`, `_read_ps_lstart`, `_psutil_start_time`,
  `_capture_ps_process`, `_ps_output`, `_reconstruct_ps_argv`, and
  `_capture_cwd_with_lsof` tests only after their retained contracts have
  the replacements above. The deleted subprocess implementations do not
  need replacement success tests.

Run the targeted tests and then the full identity module. Record the
observed red failures, distinguishing absent-helper failures from the
macOS public-source clock counterexample and the old off-Linux fallback
behavior. Some existing Linux success tests already pass before the edit;
do not describe them as new regression failures.

```bash
uv run pytest tests/test_identity.py -n 0 -q -k "start_time_token or never_spawns or human_fallback or platform_fallbacks or reads_best_effort_fields or reads_procfs_fields"
```

#### Implementation

Add `start_time_token` and route both production capture constructors
through it. Intended logic:

```python
def start_time_token(pid: int, proc: psutil.Process | None) -> str | None:
    """Return the unadjusted process-start token defined by [IAN-3.2]."""
    if sys.platform.startswith("linux"):
        try:
            stat = (Path("/proc") / str(pid) / "stat").read_text(encoding="utf-8")
            _prefix, separator, tail = stat.rpartition(") ")
            if not separator:
                return None
            ticks = tail.split()[19]
        except (OSError, IndexError):
            return None
        return f"proc:{ticks}" if ticks.isascii() and ticks.isdigit() else None
    if proc is None:
        return None
    try:
        if sys.platform == "darwin":
            # Private psutil API: public create_time applies boot-clock drift.
            seconds = proc._proc.create_time(monotonic=True)
        else:
            seconds = proc.create_time()
    except psutil.Error:
        return None
    return f"psutil:{round(seconds * 1_000_000)}"
```

Keep any type-stub accommodation for `_proc` local to that access, using
an explicit typed protocol/cast if the installed stubs require it; do not
weaken module-wide typing or add a fallback to public macOS `create_time`.
An absent or incompatible private API is dependency drift exposed by the
macOS tests, not an unreadable-process condition to silently swallow.

In `_capture_psutil_process`, replace the old native-or-psutil expression
with `start_time_token(pid, proc)`. In `_capture_linux_process`, replace
the direct field assignment with `start_time_token(pid, None)`.

Change `capture_process` to:

```python
def capture_process(pid: int) -> ProcessInfo | None:
    """Capture one process using psutil, with the /proc fallback on Linux."""
    psutil_process = _capture_psutil_process(pid)
    if psutil_process is not None:
        return psutil_process
    if sys.platform.startswith("linux"):
        return _capture_linux_process(pid)
    return None
```

Delete `_capture_ps_process`, `_ps_output`, `_reconstruct_ps_argv`,
`_read_ps_lstart`, `_native_start_time`, `_read_linux_start_time`,
`_psutil_start_time`, and `_capture_cwd_with_lsof`. Keep the `subprocess`
import: `capture_host_identity` still uses it for `ioreg`, outside this
change's process-capture boundary. Update obsolete module comments.

#### Gates and coherent checkpoint

```bash
uv run pytest tests/test_identity.py -n 0 -q
uv run mypy taut tests --config-file pyproject.toml
uv run ruff check taut tests
uv run ruff format --check taut tests
```

Inspect both capture constructors: every produced token must come from
`start_time_token`. No deleted helper reference or process-capture
subprocess call may remain. Both success and forced-failure tripwires
must pass. Native-platform tests must run on their matching CI platforms;
a local pass is not evidence for the other two operating systems.

On macOS, qualify the real ancestor chain using the psutil path. If it
truncates unexpectedly at a live PID, report the PID and actual exception
and reassess before declaring the slice complete; do not reintroduce `ps`.
Expected controlled unreadable-PID tests do not trigger this stop gate.

Commit: `Anchor identity on numeric tokens and remove ps capture`.

### Slice 3 — summon and CLI surfaces

Files: none expected. Verify only.

Run the Summon unit and process lanes and the installed-wheel lane; both
store and compare the token through `capture_process` and need no edit:

```bash
uv run --extra dev pytest extensions/taut_summon/tests -m "not xdist_group" -n auto --dist load -q
uv run --extra dev pytest extensions/taut_summon/tests -m "xdist_group and not requires_live_harness and not requires_local_llm" -n auto --dist load -q
uv run pytest -m "not slow and installed_wheel" -n 0 -q
```

Stop gate: if any summon test asserts the old `psutil:<float>` or
`lstart` spelling, update the assertion to `TOKEN_RE`; if a summon test
spawns `ps`, stop and report.

### Slice 4 — traceability reconciliation

Files: `docs/implementation/04-taut-architecture.md`, `CHANGELOG.md`,
`docs/plans/README.md`, this plan.

1. Doc 04 "Process capture" bullet: replace the sentences from "Native
   `/proc` or `ps` evidence remains the start-time token" through "agree
   about one start time." with: "The start-time token is produced by
   `start_time_token`: `/proc/<pid>/stat` ticks on Linux, because psutil's
   `create_time()` there adds a boot time that drifts under NTP, and the
   unadjusted kernel creation time via private
   `proc._proc.create_time(monotonic=True)` on macOS and public
   `proc.create_time()` on Windows, rendered as integer microseconds.
   The macOS private dependency is confined to this helper and verified
   by native clock-adjustment tests. No `ps` subprocess or locale-sensitive
   text rendering participates in process capture."
2. CHANGELOG `## Unreleased`: state the numeric scheme-prefixed tokens,
   unadjusted macOS source, and removal of the `ps` process-capture path.
   Do not add legacy recovery or migration instructions.
3. Record the promotion baseline and current review dispositions. After
   Slice 5 passes, mark this plan completed and update its
   `docs/plans/README.md` row; do not claim completion before final review.
4. Final gates below.

Commit: `Reconcile start-time token docs`.

### Slice 5 — independent review of completed work

Same reviewer stance over the full diff; disposition every finding.

## Testing plan

- Native proof: real psutil and kernel reads on Linux, macOS, and Windows
  CI, including fresh observer processes. Native tests select by actual
  `sys.platform`; synthetic tests cannot satisfy another OS's evidence.
- Controlled proof: source exceptions, parser fixtures, platform routing,
  known-token plumbing, and subprocess tripwires may patch their named
  boundaries. Keep the token helper and downstream behavior real wherever
  they are the contract under test. The macOS clock test changes only
  psutil's module-local boot-time observations, retaining real kernel reads.
- The Slice 2 table owns the enumerable test inventory: both token schemes,
  three native platforms, ASCII token grammar, missing/unreadable/malformed
  sources, three routing outcomes, success/failure subprocess absence,
  clock stability, separate observers/locales, and missing-token fallback.
- Error path: ordinary process-source read failures are best-effort and
  yield `None`; eligible anchor selection then uses human fallback.
  Dependency API drift is a failing compatibility gate, never a reason to
  substitute an adjusted token.
- No live-migration, legacy-state, or mixed-version test lane is required.

## Verification and gates

```bash
uv run pytest tests/test_identity.py tests/test_lazy_imports.py tests/test_docs_references.py -n 0 -q
uv run pytest -m "not slow and not installed_wheel" -q
uv run pytest -m "not slow and installed_wheel" -n 0 -q
uv run --extra dev pytest extensions/taut_summon/tests -m "not xdist_group" -n auto --dist load -q
uv run ruff check . && uv run ruff format --check .
uv run mypy taut tests --config-file pyproject.toml
uv run python bin/check-doc-paths
uv run python bin/check-plan-status-index
```

Observable success after release: on a macOS host with `LANG=de_DE.UTF-8`,
`taut join general` followed by `taut whoami --explain` shows a
`psutil:<digits>` start token, and a second `whoami` under `LANG=C`
resolves the same member. On Linux, `whoami --explain` shows
`proc:<digits>` and `ps` never appears in `strace -f -e execve taut whoami`.

## Rollout and rollback

Rollout: one core release (0.9.8) through `bin/release.py core`. Summon
ships no code change. There is no live migration and no legacy state to
preserve; no migration or mixed-version operational sequence is required.

Rollback: revert implementation and reconciliation Slices 2–4 together
with the spec promotion. This is code/spec rollback, not a stored-token
compatibility promise. No legacy recovery machinery belongs to this unit.

One-way door: none in storage. Column types and schema versions stay
unchanged.

## Independent review loop

Initial review: Codex in this task, with an independent repository
subagent checking slice execution, tests, and Summon consumers. The agent
inventory records external Codex CLI failures on 2026-09-15, so do not
assume that invocation is usable from an older status claim.

Revision verification: use a fresh repository subagent, read-only, scoped
to accepted findings F1/F3/F4 and new defects introduced by their fixes.
F2 is withdrawn under the explicit owner boundary and must not be reopened
as a compatibility or operational task. Record the verdict below.

Before spec promotion, the reviewer checks the revised delta, helper,
combined slice, and test inventory against spec 03 [IAN-3.2]/[IAN-3.3],
`taut/identity.py`, `tests/test_identity.py`, and installed psutil's macOS,
Linux, Windows, and public Process implementations. Answer PASS or BLOCKED
on implementability and degradation within the stated operating scope.
Do not mistake host-only native evidence for three-platform qualification.

Slice 5 reviews the completed implementation against this revised plan
and the promoted spec, with every finding dispositioned before completion.

## Out of scope

- Legacy state, live migration, token translation, and mixed-version
  driver protection or rollout machinery.
- The wrapper, shell, and infrastructure basename lists and
  `select_anchor` policy.
- Host identity (`capture_host_identity`).
- Summon's driver liveness schema.
- Schema versions or dump/load format.

## Fresh-eyes notes

The implementation checkpoint is atomic with respect to the token
contract: conversion and `ps` deletion pass one set of gates. Native
source tests and synthetic routing/parser tests have separate proof
boundaries. The private macOS dependency and its failure policy are
explicit. The plan is not an implementation-completion claim.

This 2026-09-15 revision changes only the plan under its existing Class 5
scope. Verification is scoped review plus plan-content, doc-reference,
path, and status-index checks; no production behavior changed. The
planning/testing runbooks already cover these corrections; no durable
process amendment or new skill is required.

## Execution Log

| Date | Slice | Evidence | Result |
|------|-------|----------|--------|
| 2026-09-15 | 1 — spec promotion | `uv run pytest tests/test_docs_references.py -q -n 0`; `uv run python bin/check-doc-paths`; commit `dd6eac4` | 12 passed; 63 sources and 1390 path claims passed. Promotion baseline recorded. |
| 2026-09-15 | 2 — numeric capture and `ps` removal | Failing-first targeted identity run; `uv run pytest tests/test_identity.py -n 0 -q`; `uv run mypy taut tests --config-file pyproject.toml`; Ruff check/format; commit `cca84d1` | Red failures reproduced the absent helper, bare Linux ticks, and macOS `ps` fallback. Green: identity suite passed with 3 native-platform skips; mypy passed 138 files; Ruff passed. |
| 2026-09-15 | 3 — consumers | Both planned Summon lanes and the installed-wheel lane | Summon unit 308 passed; process lane 291 passed with 8 expected native-platform skips; installed-wheel lane 28 passed. No consumer edit required. |
| 2026-09-15 | 4 — reconciliation | Documentation-reference, path, plan-index, and diff checks | Passed before reconciliation commit; final repository gates and completed-work review remain. |

## Review Log

| Review | Reviewer / invocation | Verdict | Findings | Disposition |
|--------|-----------------------|---------|----------|-------------|
| 2026-09-15 initial review F1 | Codex task; installed psutil source and controlled native probe | BLOCKED | Public macOS creation time changes with boot-time observations | Accepted: private unadjusted macOS source, explicit dependency risk, native clock and observer tests. |
| 2026-09-15 initial review F2 | Codex task and independent slice/consumer subagent | withdrawn | Mixed-version Summon driver conflict | Owner clarified no live migration or legacy state; no compatibility, migration, or rollout work is owed. |
| 2026-09-15 initial review F3 | Codex task and independent slice/consumer subagent | BLOCKED | Slice 2 stop gate contradicted retained ps producer | Accepted: conversion and deletion combined in Slice 2. |
| 2026-09-15 initial review F4 | Codex task and independent slice/consumer subagent | BLOCKED | Incorrect fixture edits and missing failure/stability proof | Accepted: explicit test inventory, corrected routing/plumbing/parser expectations, controlled patches with separate native proof. |
| 2026-09-15 revision verification | fresh repository subagent (`verify_plan_revision`) | PASS | F1/F3/F4 fixes; new malformed-stat separator case | Explicit separator rejection and a long malformed fixture added and re-reviewed. Documentation-reference tests: 12 passed; path and status-index gates passed. No implementation has begun; native three-platform qualification remains an execution gate. |
