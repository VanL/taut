# Extension Seams, Process-Domain Containment, and Coverage Integrity Plan

Status: active. E1 landed at `d5e3be2`; the E2 local implementation candidate
and independent correction rereview are complete, with hosted exact-commit
proof still pending. The T1 coverage delta remains unpromoted until that
packet is separately authorized.

Class: 5+P. The work changes the public Python embedding contract, the MCP
attachment contract, the Summon child-cleanup lifecycle, installed-wheel
compatibility evidence, and the standing coverage gate. The `+P` modifier is
required because TUI and PostgreSQL coverage become mandatory evidence for
future changes. Hardening is mandatory because the plan changes public and
compatibility contracts and a cross-platform asynchronous process-cleanup
lifecycle.

Plan type: implementation with spec revision.

## Goal

Resolve the three actionable findings from the 2026-08-24 independent review
without adopting its rejected remedies:

1. replace MCP's private core identity and notification-addressing reach-ins
   with narrow public, activity-neutral `TautClient` embedding seams and prove
   that a wheel rebuilt from immutable seam-sensitive MCP 0.9.5 release source
   still runs against candidate core;
2. make every Summon adapter own a bounded platform process domain so terminal
   finalization reaches same-domain descendants with the strongest safe
   guarantee each supported OS exposes, while retaining the distinction
   between lifecycle containment and security sealing; and
3. make TUI and PostgreSQL production code visible to the canonical Coverage.py
   and Codecov patch evidence through real test producers, not merely by adding
   package names to the source list.

The endpoint is reviewed, spec-aligned implementation evidence ready for an
owner-authorized landing. Release publication is outside this plan.

## Finding Register and Decisions

| Finding | Disposition | Planned outcome |
|---------|-------------|-----------------|
| E1 private MCP reach-in | fix the boundary | Add public `peek_identity()` and `notification_activity_queue()` methods; migrate MCP off `_resolve_member`, `_require_member`, and internal queue-name derivation. |
| E1 open core floor | retain ranges, add proof | Keep lower-bounded first-party requirements. Add a wheel built from the immutable `taut-mcp` 0.9.5 release source/current-core installed attach canary because that release contains the private reach-in and its metadata admits future core. Do not add blanket ceilings without a demonstrated incompatibility. |
| E2 direct-child-only stream cleanup | change the contract and implementation | Terminal close owns the provider's platform containment domain. Direct leader exit must not bypass descendant retirement. POSIX uses a new session/process group with a retained, unreaped leader to pin signal identity, but cannot prove group emptiness through a durable group handle; Windows uses a Job Object assigned before the suspended provider is allowed to execute and can require zero active processes. |
| T1 TUI/PG coverage blind spot | fix the evidence topology | Add real TUI and live-PG coverage producers to the canonical Test workflow, require their artifacts in aggregation, and require one behavior-bearing path from each package. |
| E3 10 ms MCP wait | no action | The timeout multiplexes a separate child-control wake. Replacing it with the backstop duration would regress command/cancel latency. |
| E4 process-wide rate bucket | no action | Process-wide loop-damage control and cross-workspace starvation are explicit [MCP-10] behavior. |
| E4 duplicated `taut_meta` DDL | no action | Extension-local SQL ownership is deliberate; exporting raw private DDL would create a worse seam. |
| E4 PostgreSQL exception classes | no action | PostgreSQL mirrors the SQLite provider; any future taxonomy change must be cross-backend. |
| Large TUI/Summon files | no extraction in this plan | File size alone is not a defect. The duplicate TUI Summon-start epilogue and speculative coordinator/view splits do not belong in these contract changes. |

Any evidence that changes one of these dispositions must be recorded in the
Deviation Log before implementation continues.

## Source Documents

Product and process sources consulted for this plan:

- `AGENTS.md`
- `docs/program-theory.md`
- `docs/agent-context/decision-hierarchy.md`
- `docs/agent-context/principles.md`
- `docs/agent-context/engineering-principles.md`
- `docs/agent-context/runbooks/writing-plans.md`
- `docs/agent-context/runbooks/hardening-plans.md`
- `docs/agent-context/runbooks/testing-patterns.md`
- `docs/agent-context/runbooks/adversarial-acceptance-probes.md`
- `docs/agent-context/runbooks/review-loops-and-agent-bootstrap.md`
- `docs/agent-context/runbooks/maintaining-traceability.md`
- `docs/agent-context/lessons.md`
- `docs/lessons.md` (Golden Rules and dated entries after the current
  coalescing watermark)
- `docs/implementation/03-agent-inventory.md`
- `docs/specs/02-taut-core.md` [TAUT-8.3], [TAUT-12.5]
- `docs/specs/03-identity-addressing-notifications.md` [IAN-3.3], [IAN-6.5],
  [IAN-7.4]
- `docs/specs/04-summon.md` [SUM-2], [SUM-7.1], [SUM-7.4], [SUM-12]
- `docs/specs/05-taut-mcp.md` [MCP-4], [MCP-8], [MCP-12]
- `docs/specs/10-taut-tui.md` [TUI-13.3]
- `docs/implementation/04-taut-architecture.md`
- `docs/implementation/05-taut-summon-architecture.md`
- `docs/implementation/07-taut-mcp-architecture.md`
- `docs/implementation/12-taut-tui.md`
- `docs/plans/2026-07-28-summon-terminal-retirement-plan.md`
- `docs/plans/2026-08-13-ranged-dependency-policy-plan.md`
- `docs/plans/2026-08-14-review-findings-remediation-plan.md`
- Microsoft Learn:
  [Process Creation Flags](https://learn.microsoft.com/en-us/windows/win32/procthread/process-creation-flags),
  [Nested Jobs](https://learn.microsoft.com/en-us/windows/win32/procthread/nested-jobs),
  [CreateJobObjectW](https://learn.microsoft.com/en-us/windows/win32/api/jobapi2/nf-jobapi2-createjobobjectw),
  [SetInformationJobObject](https://learn.microsoft.com/en-us/windows/win32/api/jobapi2/nf-jobapi2-setinformationjobobject),
  [JOBOBJECT_EXTENDED_LIMIT_INFORMATION](https://learn.microsoft.com/en-us/windows/win32/api/winnt/ns-winnt-jobobject_extended_limit_information),
  [AssignProcessToJobObject](https://learn.microsoft.com/en-us/windows/win32/api/jobapi2/nf-jobapi2-assignprocesstojobobject),
  [Job Objects](https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects),
  [QueryInformationJobObject](https://learn.microsoft.com/en-us/windows/win32/api/jobapi2/nf-jobapi2-queryinformationjobobject),
  [JOBOBJECT_BASIC_ACCOUNTING_INFORMATION](https://learn.microsoft.com/en-us/windows/win32/api/winnt/ns-winnt-jobobject_basic_accounting_information),
  [TerminateJobObject](https://learn.microsoft.com/en-us/windows/win32/api/jobapi2/nf-jobapi2-terminatejobobject),
  [CreateToolhelp32Snapshot](https://learn.microsoft.com/en-us/windows/win32/api/tlhelp32/nf-tlhelp32-createtoolhelp32snapshot),
  [Thread32First](https://learn.microsoft.com/en-us/windows/win32/api/tlhelp32/nf-tlhelp32-thread32first),
  [Thread32Next](https://learn.microsoft.com/en-us/windows/win32/api/tlhelp32/nf-tlhelp32-thread32next),
  [THREADENTRY32](https://learn.microsoft.com/en-us/windows/win32/api/tlhelp32/ns-tlhelp32-threadentry32),
  [OpenProcess](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-openprocess),
  [OpenThread](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-openthread),
  [ResumeThread](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-resumethread),
  [CloseHandle](https://learn.microsoft.com/en-us/windows/win32/api/handleapi/nf-handleapi-closehandle),
  and [PeekNamedPipe](https://learn.microsoft.com/en-us/windows/win32/api/namedpipeapi/nf-namedpipeapi-peeknamedpipe)
  (the Windows containment mechanism and outer-job constraints)
- The Open Group
  [`waitid()`](https://pubs.opengroup.org/onlinepubs/9799919799/functions/waitid.html)
  contract and Python's
  [`os.waitid()`](https://docs.python.org/3/library/os.html#os.waitid)
  availability note (Python only exposes it on macOS starting in 3.13)

The 2026-08-24 external feedback is a claim source, not governing authority.
The exact dispositions above come from source inspection, focused tests, a
real MCP no-touch attachment probe, and a real `ScriptedHandle` descendant
survival probe.

## Spec Baseline

- `0eacc00adf33c0ab8feef46d35b7909c33f8c40e` is the committed code and active-
  spec baseline for this plan.
- Plan type: implementation with spec revision.
- Promotion strategy: **A, in-file text before implementation-link claims**.
  The spec-promotion slice applies the exact delta below to the then-current
  active files without overwriting unrelated intervening edits. Code does not
  cite the new text until its implementation and reciprocal mappings land.
- Packeted promotion rule: owner authorization on 2026-08-25 covers E1 and,
  after E1 landed, E2. The [TAUT-12.5] T1 coverage replacement remains in this
  proposed delta until separately authorized. This prevents active specs from
  overstating behavior that the current implementation packet will not ship.
- E1 promotion baseline: `cd7e34724f34d8cc9a2e0cc3fdd251955d76914c`
  plus pre-promotion working-tree blobs `7c50af427331b0e4b865ee827d7669d733e18343`
  (spec 02), `1ac6b72b2493798083dbc2b9a9fc18dfe37641b2` (spec 03), and
  `12a6977fe1f87786b19a1703965357cabe1a41fa` (spec 05). These blobs include
  the already-reviewed SimpleBroker 7.4.2 dependency-floor edits. The exact E1
  promoted diff is the addition under [IAN-3.3], [TAUT-8.3], and [TAUT-12.5],
  the replacement paragraph under [MCP-4], and one Related Plans backlink in
  each file. The [TAUT-12.5] addition landed after the first real checker proof;
  the timing correction is recorded in the Deviation Log.
- E2 promotion baseline: pre-promotion HEAD
  `3441fdac21eaf5708e1027ca372ac3ddb6c95c69` and
  `docs/specs/04-summon.md` blob
  `8bf55f5f31bdca82b5b731368b6e3044f8ce2b4a`. The exact promoted diff is the
  proposed [SUM-2], [SUM-7.1], [SUM-7.4], and [SUM-12] text plus the Related
  Plans backlink below. T1 remains proposed.

## Proposed Spec Delta

| Spec file | Strategy | Sections touched |
|-----------|----------|------------------|
| `docs/specs/03-identity-addressing-notifications.md` | A | [IAN-3.3], Related Plans |
| `docs/specs/02-taut-core.md` | A | [TAUT-8.3], [TAUT-12.5], Related Plans |
| `docs/specs/05-taut-mcp.md` | A | [MCP-4], [MCP-12], Related Plans |
| `docs/specs/04-summon.md` | A | [SUM-2], [SUM-7.1], [SUM-7.4], [SUM-12], Related Plans |

### [IAN-3.3] Read-only selected-member resolution

Insert after the paragraph ending `No resolution path silently changes a
member name`:

> A read-only selected-member resolution uses the same precedence above but
> suppresses every state effect. It may select an existing explicit-name,
> continuity-token, claim-hash, anchor, or human-fallback member, but it never
> creates a member, creates or refreshes a claim, heals an anchor match, updates
> activity, changes anchor or fingerprint evidence, or mutates membership or
> cursor state. Invalid deterministic selectors remain errors and never fall
> back. This is selection, not authentication or token verification.

### [TAUT-8.3] Public no-touch identity and notification-activity seams

Insert after the `set_persona()` paragraph:

> `TautClient.peek_identity() -> Member` returns the client's selected existing
> member through [IAN-3.3]'s read-only resolution. It raises the ordinary
> identity or token error when no selected member resolves. It does not create,
> heal, claim, touch activity, update anchor or fingerprint evidence, inspect
> unread state, or mutate membership or cursor state. The effect-bearing
> `whoami()` contract remains unchanged. Success or failure preserves the
> client's existing `last_created_member` and `last_candidates` diagnostic
> objects exactly. The name is intentionally identity-oriented: continuity
> tokens are selectors, not credentials.
>
> `TautClient.notification_activity_queue() -> simplebroker.Queue` resolves the
> same selected member read-only and returns that member's core-derived
> notification queue as a persistent handle owned by the client. Selection runs
> on every call. Calls that resolve the same member reuse the client-owned
> handle; a changed valid selector may return a different cached or new handle,
> and `TautClient.close()` releases all of them. The method
> neither reads, claims, decodes, nor writes a notification. Its public purpose
> is broker activity-waiter integration by long-lived embedders; semantic reads
> continue through `peek_inbox()` or `inbox()`, so extensions do not derive
> `notify.*` names or decode queue bodies.

Insert in [TAUT-12.5] after the current core/current-extension installed-wheel
matrix paragraph:

> Candidate-core compatibility evidence also installs a wheel built from the
> immutable `taut_mcp/v0.9.5` release source, pinned to commit
> `b4ca0fda9767736bfd81eb08c2dfc1e1d2b03998`, with the candidate core wheel
> through normal dependency resolution in a checkout-free environment. That
> historical release-source wheel is the first retained canary whose open `taut-chat`
> requirement and private selected-member reach-in make future-core
> compatibility observable. The probe creates a real SQLite workspace and
> member through the installed candidate core, launches the installed MCP stdio
> entry point, performs attach/list/detach with the member's continuity token,
> and requires clean shutdown. It never uses `--no-deps`, imports from the
> checkout, patches private core methods, or treats import success as runtime
> proof. If a future candidate cannot preserve this admitted combination, the
> release must stop for an explicit compatibility decision and corresponding
> metadata/spec change; the checker must not silently waive or replace the
> canary.

Replace [TAUT-12.5]'s canonical coverage-producer paragraph beginning `The
representative Ubuntu root/unit cell` through the sentence ending `does not
become a second coverage owner` with:

> The canonical Test workflow owns one combined coverage report. The
> representative Ubuntu root/unit cell, deterministic Summon process cell,
> prepared local-LLM job, independent non-PostgreSQL MCP job, package-locked TUI
> job, and live PostgreSQL job collect and upload named raw shards while running
> existing contract selectors. A final aggregation job requires all six
> producers, downloads and validates every shard, combines them, enforces
> behavior-bearing required paths from core, Summon, MCP, TUI, and PG, and
> uploads one Codecov report; it runs no tests. Root coverage configuration
> names `taut`, `taut_summon`, `taut_mcp`, `taut_tui`, and `taut_pg` as source.
>
> The TUI producer runs the complete package-local suite against the retained
> TUI lock on one representative Ubuntu/Python cell. The live PG producer runs
> `bin/pytest-pg --fast` through the root coverage launcher with subprocess
> coverage enabled, so both the shared PostgreSQL contract suite and
> `taut_pg`'s provider suite contribute real-backend lines. Their dedicated
> compatibility workflows remain the multi-version/platform owners and do not
> become second Codecov upload owners. Placeholder, skipped, import-only, or
> mocked-backend execution is not coverage evidence for either package.

### [MCP-4] Public attachment validation boundary

Replace the paragraph beginning `After the validation grant` through `The
master never validates through or uses that client` with:

> After the validation grant, the same candidate child constructs and validates
> the workspace reactor, `TautClient`, backend, token, member, and initial
> notification snapshot on its owner thread. It obtains the selected member
> through public `TautClient.peek_identity()` and obtains the broker activity
> source through public `TautClient.notification_activity_queue()`. Both use
> [IAN-3.3]'s read-only selection: attachment does not create or heal identity,
> record a claim, update member activity, change anchor or fingerprint evidence,
> claim a notification, or move a cursor. MCP does not call a private client
> resolver, import internal queue-name derivation, decode raw notification
> bodies, or move either operation to the master thread. The master never
> validates through or uses that client.

Add to [MCP-12]'s attachment proof requirements:

> Attachment proof fails if production MCP imports core-internal addressing or
> calls a private selected-member method. Real SQLite and PostgreSQL attachment
> tests observe the selected member and stable activity, claim, anchor,
> fingerprint, cursor, and notification-count state through public core
> operations. The installed historical-wheel canary in [TAUT-12.5] remains a
> separate checkout-free compatibility proof.

### [SUM-2] Lifecycle containment is not sealing

Insert after the paragraph ending `the same driver supervises a sealed
instance`:

> Lifecycle captivity includes the provider leader and every descendant that
> remains in the platform containment domain created for that provider
> generation. Terminal finalization applies the platform's bounded retirement
> guarantee even when the provider leader exits first. On Windows the retained
> Job Object is a durable kernel capability and finalization requires zero
> active job processes. Portable POSIX process groups expose only a numeric
> identifier: Taut pins that identity by keeping the group leader unreaped
> through group signaling, but cannot atomically prove group emptiness after
> reaping and therefore does not claim that stronger guarantee. This is
> resource ownership, not a sandbox or security boundary: Taut does not inspect
> arbitrary system ancestry, prevent a process from deliberately escaping the
> domain where the operating system permits it, or reclaim processes launched
> through an external supervisor. Work intended to survive `dismiss` must use
> such an explicit external lifetime rather than relying on accidental
> orphaning.

### [SUM-7.1] Adapter process-domain lifecycle

Change the `close()` comment in the `AdapterHandle` example to:

> `def close(self) -> None  # bounded domain finalize/reap/release`

Insert after the first adapter contract paragraph:

> Every spawn creates one owned process domain before the provider is allowed to
> execute. On POSIX the provider is the leader of a new session/process group,
> and the domain owner is the only code allowed to reap it. Natural exit is
> observed without reaping so the leader continues to pin the numeric process-
> group identity until terminal signaling finishes. On Windows the provider is
> created suspended, assigned to a Job Object configured to terminate its
> members when the job is closed, and resumed only after the assignment
> succeeds. A setup or assignment failure terminates and reaps the suspended
> child and releases every native handle before returning `AdapterError`; there
> is no direct-child-only fallback. If an outer Windows Job Object prevents a
> valid nested assignment, spawn fails rather than requesting breakaway from
> the host job. The adapter retains the provider PID as [SUM-4] identity
> evidence while the domain owner retains the separate cleanup capability.

In the paragraph that begins with `emits_session_events`, retain its first two
sentences through `adapters that declare false never pay that wait`. Replace
from the old ``interrupt()` is a reusable` sentence through the old `close()`
paragraph with:

> `interrupt()` remains reusable, nonterminal cancellation. It preserves the
> existing provider-specific signal or PTY Ctrl-C behavior, aborts adapter
> writes in flight, and leaves a surviving handle and process domain open. It
> does not perform terminal domain escalation.
>
> `request_close()` is the nonblocking terminal-retirement operation. Under the
> handle's reentrant lifecycle lock it atomically changes `open` to
> `close_requested`, permanently rejects or cancels injection, and owns the
> retirement's one graceful provider signal or PTY Ctrl-C. It does not wait,
> escalate, reap, join, release streams, or close the process domain. After
> `close_requested` is visible, `interrupt()` and repeated `request_close()`
> calls are no-ops and cannot deliver another graceful signal.
>
> `close()` is the blocking terminal finalizer. A direct close first performs
> the same terminal request when the handle is open. Exactly one closer changes
> `close_requested` to `closing`; concurrent closers wait for and observe its
> result. The closer allows the existing bounded graceful interval. On POSIX it
> observes leader exit without reaping, sends the bounded SIGTERM/SIGKILL ladder
> to the process group while the unreaped leader still pins the group identity,
> and only then reaps the leader. It never signals the numeric process-group ID
> after leader reap and does not claim an atomic group-empty proof. On Windows
> it terminates the owned Job Object, waits boundedly for zero active processes,
> and reaps the leader. Direct provider exit does not bypass either platform's
> descendant-retirement step. Finalization then releases streams, fds, and
> native domain handles in adapter-specific order. A POSIX no-signalable-target
> result is successful completion of that ladder stage: `ESRCH`, or
> Darwin `EPERM` only after non-reaping observation has already established
> that the leader is terminal. Any other failed group signal, leader reap, Job
> Object operation, or Windows zero-active-process check is terminal
> `AdapterError`; under an existing primary failure it is attached as a cleanup
> note rather than replacing the primary. No cleanup path scans unrelated
> process ancestry or signals a process outside the still-retained platform
> capability. `interrupt()` and `request_close()` may re-enter from a Python
> signal handler at any point in close and must not wait on a non-reentrant
> lock owned by the interrupted frame.

### [SUM-7.4] PTY domain ownership

Replace the `Spawn` sentence that prescribes `subprocess.Popen` with:

> The adapter uses `pty.openpty()` and the shared [SUM-7.1] POSIX process-domain
> spawn owner to launch `argv` with the slave as stdin/stdout/stderr in a new
> session/process group; the parent closes the slave immediately and owns the
> master. The shared owner, not a second PTY-only escalation implementation,
> retains the process-group identity.

Replace the first two sentences of `Master fd ownership` with:

> `request_close()` publishes retirement and attempts the one graceful Ctrl-C;
> `close()` drains write-side operations and delegates bounded process-domain
> finalization to [SUM-7.1] before resolving master-fd ownership. It does not
> return early when the provider leader has exited: the shared owner retains the
> unreaped leader through the safe process-group signal ladder. `close()` closes
> the master iff no reader has started. If a reader has started, the reader
> closes the master on EOF/EIO.

### [SUM-12] Process-domain firing proof

Insert after the terminal-retirement conformance paragraph:

> Process-domain conformance uses real provider and descendant processes, not
> `Popen` doubles or signal-call counts. It proves, on every supported platform,
> that terminal close delivers retirement to a same-domain descendant when the
> provider remains alive, when the provider exits first, and when the descendant
> inherits stdout and would otherwise delay EOF. Normal descendant processes
> must be absent after close in those firing probes. POSIX proof covers non-
> reaping natural-exit observation, safe group identity through graceful exit,
> SIGTERM, and SIGKILL stages for both stream and PTY handles, and the rule that
> no group signal occurs after leader reap; it is evidence for the bounded
> retirement algorithm, not an atomic proof that a numeric process group is
> empty. Windows proof covers suspended spawn, pre-execution Job Object
> assignment, resume, job termination, zero active processes, outer-job
> assignment failure, and cleanup. Existing tests continue to prove that reusable
> `interrupt()` does not retire the handle and that exactly one graceful close
> signal is sent. A POSIX-only boundary probe may show that a child which
> deliberately creates a new session is outside the owned domain, but the test
> must retain creation identity and clean it explicitly. Every descendant probe
> has bounded failure cleanup that refuses to signal a reused PID.

### Related-plan backlink

Add to spec 04's `## Related Plans` section for the E2 packet:

> - `docs/plans/2026-08-24-extension-seams-process-containment-coverage-plan.md`
>   — defines cross-platform Summon process-domain ownership and bounded
>   descendant finalization without treating lifecycle containment as a
>   sandbox.

## Context and Key Files

| Area | Current owner and boundary | Files expected to change or verify |
|------|----------------------------|------------------------------------|
| Core read-only identity | `IdentityMixin._resolve_member()` already has the required no-touch behavior, but only private callers can receive the selected `Member`. `peek_inbox()` owns no-touch notification decoding. `_ClientBase.queue()` owns target/config resolution and persistent queue caching. | `taut/client/_identity.py`, `taut/client/_notifications.py`, `taut/client/_base.py`, `taut/client/__init__.py`, `tests/test_client.py`, `tests/test_shared_contract.py`, public-API/type tests |
| MCP attachment | `_WorkspaceReactor._validate()` currently calls `_resolve_member`, `_require_member`, `addressing.notification_queue_name`, and `client.queue` before constructing the activity waiter and peeking the inbox. The child owner thread must retain all client/queue/waiter use. | `extensions/taut_mcp/taut_mcp/_workspace_reactor.py`, its imports, `extensions/taut_mcp/tests/test_resource.py`, `extensions/taut_mcp/tests/test_process_reactor.py`, `extensions/taut_mcp/tests/test_pg_conformance.py`, `extensions/taut_mcp/tests/test_tools.py` |
| Historical MCP/current-core canary | The core/Summon matrix already owns checkout-free wheel installation, immutable tag resolution, subprocess-group cleanup, sanitized environments, and failure diagnostics. Do not clone that machinery casually into a divergent runner. | `bin/check-core-summon-wheel-matrix.py`, `bin/build-and-check-release-wheels.py`, a narrowly named `bin/check-core-mcp-wheel-matrix.py` only if extension rather than reuse keeps the existing checker cohesive, `tests/test_core_summon_wheel_matrix.py`, optional new `tests/test_core_mcp_wheel_matrix.py`, `tests/test_release_script.py`, `.github/workflows/test.yml` |
| Shared Summon process domain | Stream adapters spawn independently in `_claude.py` and `_scripted.py`; `_stream.py` signals/kills and reaps only the direct child. `_pty.py` starts a new session and has a PTY-local group ladder that exits when the leader exits. `_driver.py` already owns generation teardown and must not gain a second child-reaper path. | new `extensions/taut_summon/taut_summon/_process_domain.py` and Darwin-only `_darwin_wait.py`; a separate Windows-private helper keeps Win32 ctypes out of POSIX imports; `extensions/taut_summon/taut_summon/_claude.py`, `_scripted.py`, `_stream.py`, `_pty.py`, `_adapter.py`; `extensions/taut_summon/tests/test_scripted_adapter.py`, `extensions/taut_summon/tests/test_pty_adapter.py`, `extensions/taut_summon/tests/test_conformance.py`, `extensions/taut_summon/tests/test_driver.py` |
| Real descendant probe | `scripted_provider.py` is the shipped anti-mocking provider. Its JSON scenario language already supports real subprocess and terminal-retirement cases. Extend that one seam rather than adding a test-only fake handle. | `extensions/taut_summon/taut_summon/scripted_provider.py`, `extensions/taut_summon/tests/conftest.py`, `test_scripted_adapter.py`, `test_pty_adapter.py` |
| Coverage configuration | Root Coverage.py source currently names only core, Summon, and MCP. `test.yml` aggregates four producer roles. TUI and PG compatibility workflows run real tests but emit no coverage shard. | `pyproject.toml`, `.github/workflows/test.yml`, `bin/check-required-coverage-paths.py`, `tests/test_github_workflows.py`, `tests/test_required_coverage_paths.py`, `bin/combine-coverage.py` |
| TUI coverage producer | The dedicated workflow owns the retained five-cell OS/Python matrix. Canonical coverage should add one separate representative job rather than mutate that compatibility ownership. | `.github/workflows/test-tui-extension.yml` (verify unchanged ownership), `extensions/taut_tui/pyproject.toml`, `extensions/taut_tui/uv.lock`, `extensions/taut_tui/tests`, `.github/workflows/test.yml` |
| PG coverage producer | `bin/pytest-pg --fast` owns temporary Docker setup and the shared plus extension test split. Running that helper under root Coverage.py with subprocess patching preserves its real-backend ownership. | `.github/workflows/test-pg-extension.yml` (verify unchanged ownership), `taut/_scripts.py`, `bin/pytest-pg`, PG tests, `.github/workflows/test.yml` |
| Durable rationale | Implementation docs must explain why selectors are not credentials, why process-domain containment is not sandboxing, why direct-leader exit is insufficient, and why coverage source declaration without producers is false evidence. | `docs/implementation/04-taut-architecture.md`, `05-taut-summon-architecture.md`, `07-taut-mcp-architecture.md`, `12-taut-tui.md`, `README.md`, `CHANGELOG.md` |

No public CLI command, wire schema, database table, persistence format, or
TUI behavior changes in this plan.

## Required Reading and Comprehension Gates

Before the first implementation edit, the implementer records answers in the
Implementation Log. A missing or incorrect answer blocks editing until the
cited owners are reread.

1. **Why is `verify_token()` the wrong E1 seam?** Expected answer: continuity
   tokens select a member inside one trust domain; they are not authentication
   credentials. MCP needs the selected `Member`, and attach must not touch
   activity or claims. `peek_identity()` names that effect accurately.
2. **Why are both public methods needed?** Expected answer: `peek_identity()`
   replaces private selected-member resolution, while
   `notification_activity_queue()` keeps `notify.<member_id>` derivation and
   persistent queue ownership in core. `peek_inbox()` alone cannot provide the
   queue needed by SimpleBroker's native activity waiter.
3. **Which thread owns MCP validation resources?** Expected answer: the
   candidate/workspace child owner thread constructs and uses the client,
   queue, waiter, and initial snapshot. The master only coordinates immutable
   events and never touches those handles.
4. **What does the historical MCP canary prove?** Expected answer: normal
   resolution and one real attach/list/detach lifecycle for a wheel built from
   immutable seam-sensitive 0.9.5 release source against candidate core. It
   does not prove the byte-identical PyPI artifact, every historical extension,
   or authorize `--no-deps` compatibility fiction.
5. **Why is E2 containment not full captivity?** Expected answer: Taut owns
   cleanup of processes that remain in the OS domain it created. It does not
   sandbox meaning, inspect arbitrary ancestry, or promise control of a process
   that deliberately escapes or uses an external supervisor.
6. **Why can leader exit not end `close()`?** Expected answer: a descendant can
   keep running or hold inherited stdout after the provider exits. On POSIX the
   owner must observe that exit without reaping, apply the group ladder while
   the leader pins the PGID, then reap; on Windows it must retire the Job Object
   to zero active processes, then reap.
7. **Which operations signal the whole domain?** Expected answer: only terminal
   escalation in `close()`. Reusable `interrupt()` and nonblocking
   `request_close()` retain their existing provider-specific graceful behavior
   and exactly-once retirement semantics.
8. **Why must Windows assignment happen before provider execution?** Expected
   answer: assigning an already-running process leaves a race in which it can
   spawn an uncontained descendant. Suspended create, Job Object assignment,
   then resume closes that race. Assignment failure is fatal and cleans the
   suspended child; there is no weakened fallback.
9. **Why is adding `taut_tui` and `taut_pg` to `coverage.source` insufficient?**
   Expected answer: files would appear as zero or absent unless real tests run
   under Coverage.py and their raw shards reach the canonical aggregate. Patch
   evidence needs producers, artifact requirements, and behavior-path gates.
10. **What remains the compatibility-workflow boundary?** Expected answer: the
    dedicated TUI and PG workflows retain their OS/Python and live-provider
    matrices. The canonical Test workflow adds one coverage-producing cell for
    each and remains the sole combined Codecov owner.

## Invariants and Constraints

### Core and MCP

- `whoami()` keeps its existing activity and claim side effects.
- `peek_identity()` and `notification_activity_queue()` are additive methods;
  no CLI command or JSON output is added.
- Read-only selected-member resolution never creates/heals identity, records a
  claim, updates activity, changes anchor/fingerprint evidence, or moves a
  cursor. Invalid explicit selectors never fall back.
- Core continues to own notification queue naming and body decoding. MCP may
  use the returned queue only as the public input to
  `create_activity_waiter_for_queues`; notification snapshots still come from
  `peek_inbox()`.
- The workspace owner thread retains client, queue, waiter, and database
  ownership. No live Queue or waiter crosses to the master asyncio thread.
- Existing MCP attach error text, deadline, cancellation, capacity, degraded
  state, snapshot cap, and token-redaction behavior do not change.
- The private resolver remains available for core internals and the admitted
  historical MCP canary. This plan removes new extension use; it does not
  authorize immediate private-method deletion.
- First-party manifest requirements remain lower-bounded. A known future
  incompatibility may justify a reviewed ceiling, but this plan invents none.

### Summon process lifecycle

- One shared process-domain abstraction owns platform spawn containment,
  domain signaling, non-reaping POSIX leader observation, leader reap
  coordination, Windows job-emptiness observation, and native handle release.
  PTY and stream retain their distinct I/O and graceful-signal state machines.
- POSIX stream and PTY children start in a new session/process group. Windows
  stream children are created suspended, assigned to a kill-on-close Job
  Object, then resumed. No new runtime dependency is authorized; use bounded
  stdlib/`ctypes` Win32 bindings in an isolated private module.
- On POSIX the domain owner replaces every lifecycle `Popen.poll()`/`wait()`
  with non-consuming POSIX `waitid(P_PID, ..., WEXITED | WNOHANG |
  WNOWAIT)` observation until terminal finalization. It uses public
  `os.waitid()` where available. On supported macOS Python 3.11/3.12, where
  Python does not expose that system call, one isolated Darwin-only `ctypes`
  binding uses the public libc `waitid` ABI and the exact `siginfo_t` layout
  from the Darwin SDK headers. The unreaped leader pins its PID/PGID through the
  group ladder; the owner reaps exactly once afterward and never calls
  `killpg()` on that numeric ID again. Linux plus macOS 3.11 and current-Python
  firing tests are required.
- The Darwin binding is a narrow compatibility shim, not a generic libc layer.
  It declares argument/result types, reads named `siginfo_t` fields rather than
  raw offsets, retries `EINTR`, treats `si_pid == 0` as no change, maps only
  `CLD_EXITED`, `CLD_KILLED`, and `CLD_DUMPED` to terminal return codes, and is
  tested against real normal and signal exits before use by an adapter. Any ABI
  mismatch or missing symbol is a supported-platform blocker, not permission to
  reap early.
- The process-domain lock serializes exit observation and the final reap.
  Terminal status is cached so the event iterator can yield the exact
  `ExitEvent` while the leader remains waitable; `close()` consumes that same
  status only after the pinned group ladder. No other thread calls a wait or
  poll primitive on the provider.
- If a safe pre-execution Job Object assignment cannot be implemented without
  private CPython state, an undocumented API, or a new dependency, stop and
  revise the plan/spec. Do not ship post-start assignment or direct-child-only
  fallback under the stronger contract.
- `interrupt()` remains reusable. `request_close()` remains nonblocking,
  terminal, idempotent, and exactly one graceful request. It does not wait for
  or terminate the domain.
- `close()` remains bounded, exactly one closer owns escalation, concurrent
  callers share the result, and active/queued writes are retired before I/O
  resources can be reused.
- Graceful exit is tried before force. POSIX then applies SIGTERM and SIGKILL
  to the pinned group with bounded waits before leader reap. Windows terminates
  the Job Object after its graceful interval and requires zero active processes.
  Direct leader exit never skips the remaining platform retirement step.
- POSIX process groups are a best-effort bounded retirement capability, not a
  durable kernel handle. While the leader pins group identity, finalization
  attempts SIGTERM, gives a successful delivery one bounded grace interval,
  attempts SIGKILL regardless of leader status or the prior stage's accepted
  no-signalable-target result, then observes leader termination within the kill
  bound and makes the one reap attempt. It does not use `killpg(..., 0)` as a
  group-empty oracle. Unexpected signal-stage errors are aggregated while the
  ladder and the one reap continue whenever terminal leader status is known.
  Success does not claim an atomic group-empty observation.
  Windows Job Object success has the stronger zero-active-process postcondition.
- A process outside the retained domain is outside the guarantee. Production
  code does not walk arbitrary descendants with `ps`, `psutil`, `/proc`, WMI,
  or `taskkill /T` as its ownership mechanism.
- Failure to establish containment is a spawn failure. POSIX `ESRCH`, or Darwin
  `EPERM` after the leader is already observed terminal without reaping, is an
  expected no-signalable-target group-signal result. Any other POSIX group-
  signal or leader-reap failure, or failure to confirm zero active Windows job
  processes after forced termination, is a terminal cleanup failure. Cleanup
  failure attaches to an active primary exception instead of replacing it.
- The driver still anchors member presence to the provider leader PID and
  retains generation fencing, pump-drain order, checked joins, ledger release,
  and primary-error precedence. `_driver.py` does not become a second domain
  owner.
- A background service intended to survive dismissal must be launched under an
  explicit external lifetime. Accidental inheritance is not a persistence API.

### Coverage and process evidence

- Coverage source-list widening and both real producers land in the same
  reviewable packet; no intermediate completion claim may count zero-filled
  packages as proof.
- TUI coverage runs the complete retained-lock suite, not an import smoke.
- PG coverage runs a real temporary PostgreSQL backend through
  `bin/pytest-pg --fast`; a mocked provider or SQLite substitution is invalid.
- The canonical aggregate requires every raw shard, validates it through the
  existing public Coverage.py path, requires one behavior-bearing TUI line and
  one behavior-bearing PG line, and uploads one report.
- Dedicated TUI and PG workflows retain their existing compatibility roles and
  release-gate names. Do not create competing Codecov uploads from them.
- Required markers are stable, unique production statements exercised only by
  the intended package suite. Import lines, class definitions, and module
  constants do not qualify.
- Tests use real processes for E2, real SQLite/PostgreSQL for E1 where backend
  parity matters, real installed wheels for compatibility, real Textual tests
  for TUI coverage, and a real PostgreSQL container for PG coverage. Mocks may
  cover clocks, deterministic Win32 error injection, and subprocess command
  assembly only; they cannot be the primary contract proof.

### Scope and review

- No database migration, queue-name change, wire-protocol change, new daemon,
  process-tree security claim, or package ceiling is authorized.
- No MCP wait-loop, rate-limit, Summon DDL, search exception, TUI coordinator,
  transcript view, control-channel, watchdog, or broad file split is
  authorized.
- Each meaningful packet receives independent completed-work review. The E2
  packet also requires hosted Windows evidence before it can be called ready.
- Every behavior change is red-green TDD. If an OS-only failure cannot be made
  red locally, the pre-change production descendant probe and a hosted failing
  Windows job are the substitute proof and must be recorded before green.

## Rollout, Compatibility, and Rollback

There is no persistent-data one-way door. The behavioral one-way risk is
operational: after E2 ships, `dismiss` may terminate same-domain background
work that previously survived accidentally. The release changelog and Summon
implementation note must state that boundary. Do not hide it as an internal
cleanup refactor.

Rollout order:

Shared-owner serialization: this plan's E1 public-API/spec slice is first.
Before `2026-08-24-command-runtime-findings-remediation-plan.md` edits
[TAUT-8.3], `TautClient`, `_base.py`, shared-contract tests, or Related Plans,
it must record E1's immutable identifier, rebase its exact delta, and rerun
plan review. If this plan later revises an E1 shared owner after that handoff,
it must first rebase over the runtime plan's recorded baseline. Neither plan
may overwrite the other's public methods, tests, spec paragraphs, or backlink.

1. review this plan and exact delta;
2. promote the spec delta and record the promotion baseline;
3. land the additive core methods before or atomically with current MCP's use;
4. make the historical MCP/current-core canary blocking before any future
   private resolver removal;
5. land POSIX and Windows process-domain support as one product-contract
   packet after both platform proofs exist;
6. land coverage source widening, producers, artifact requirements, markers,
   and workflow tests atomically; and
7. complete traceability, independent review, hosted signals, and owner-
   authorized landing.

Rollback:

- E1 is additive. Current MCP can revert to the old private calls only together
  with the promoted MCP/core spec text; do not remove the new core methods while
  a released current MCP imports them. The immutable old-wheel canary can be
  reverted only with an explicit change to the open-range compatibility policy.
- E2 reverts as one packet: shared domain module, stream/PTY spawn integration,
  tests, Summon spec text, architecture note, and changelog. The old direct-
  child behavior remains mechanically recoverable, but rollback must explicitly
  reopen the documented orphan risk. No data repair is required.
- T1 reverts atomically: source list, both producers, aggregate dependencies,
  required markers, workflow tests, and coverage spec text. Reverting only a
  producer while leaving its source package or marker required is invalid.
- If hosted Windows Job Object proof fails, stop the E2 packet before landing.
  Do not ship POSIX-only semantics under a cross-platform contract. A revised
  platform limitation requires a new spec delta and review.

Post-landing success signals:

- current MCP attach uses no private core/addressing symbol, and the immutable
  MCP 0.9.5 wheel completes real attach/list/detach against candidate core;
- a descendant intentionally left alive by the provider is absent after
  terminal close in the Ubuntu, macOS, and Windows firing probes, with no pump/
  join timeout; Windows additionally reports zero active job processes;
- Codecov's combined report contains measured `taut_tui` and `taut_pg`
  production files and the required-path checker observes the selected markers;
- the existing dedicated TUI/PG workflow matrices and all release-gate workflow
  names remain green.

## Dependency-Ordered Tasks

### 1. Review and promote the contract

- [x] Run the independent plan/delta review defined below; resolve every point
  in the Review Log.
- [x] Apply the exact E1 Proposed Spec Delta to specs 02, 03, and 05 using
  strategy A. Preserve unrelated then-current spec edits. Spec 04 and the T1
  coverage paragraph remain proposed until their implementation packets.
- [x] Add the E1 Related Plans backlinks without implementation mapping claims.
- [x] Run documentation path, plan-index, DOM fixture, and relevant spec tests.
- [x] Record the E1 promotion baseline identifier in this plan.
- [x] Apply the exact E2 Proposed Spec Delta to spec 04 after separate owner
  authorization. Preserve the landed SimpleBroker 7.4.2 text and keep T1
  proposed.
- [x] Add the E2 Related Plans backlink, run the documentation gates, and
  record the exact pre-promotion HEAD and spec blob.
- **Stop gate:** if review rejects the public method shape, Windows pre-
  execution containment, historical-wheel obligation, or coverage topology,
  revise the delta and rerun review before any code edit.
- **Done signal:** promoted text passes docs gates, the baseline is recorded,
  and no production code cites unimplemented sections.

### 2. Add the public read-only core seams red-first

- [x] Add failing core tests for exact signatures, `Member` result, invalid
  explicit/token errors, and non-mutation of activity, token/process claims,
  anchor, fingerprint, memberships, cursors, and pending notifications.
- [x] Add backend-shared firing coverage so SQLite and PostgreSQL both exercise
  no-touch selection. Use real `TautClient` instances and real state; do not
  monkeypatch `_resolve_member` as the proof.
- [x] Add a failing persistent-lifecycle test proving repeated
  `notification_activity_queue()` returns the same client-owned queue and
  `TautClient.close()` releases it.
- [x] Implement `peek_identity()` in `taut/client/_identity.py` by reusing the
  existing no-touch resolution and public `Member` conversion. Do not duplicate
  selector precedence.
- [x] Implement `notification_activity_queue()` in
  `taut/client/_notifications.py` by reusing read-only selection, core-owned
  `notification_queue_name`, and `_ClientBase.queue(..., persistent=True)`.
- [x] Update public typing/docs without adding a root-level `Queue` export or a
  CLI command.
- **Stop gate:** if implementation needs a second resolver, exposes raw queue
  names, changes `whoami()`, or cannot make client ownership of the queue
  unambiguous, stop and revise the API/spec.
- **Done signal:** focused core and shared PostgreSQL tests pass; tests show all
  named state remains unchanged and queue cleanup is client-owned.

### 3. Move MCP attachment entirely onto the public boundary

- [x] Add a failing MCP test that makes any call to `_resolve_member` or
  `_require_member` fatal while a real attachment still must succeed through
  public methods.
- [x] Add a source-boundary test that rejects production notification queue-name
  derivation and private selected-member calls from `taut_mcp`. Existing
  actor-aware DM selector parsing in `_commands.py` remains outside E1; a
  package-wide `taut.addressing` import ban would conflate that separate public-
  operation adapter with notification queue ownership.
- [x] Replace `_WorkspaceReactor._validate()`'s private identity and queue-name
  path with `peek_identity()` and `notification_activity_queue()` on the child
  owner thread. Retain the current activity-waiter fallback and `peek_inbox(101)`
  snapshot behavior.
- [x] Run real SQLite and PostgreSQL attach probes and assert stable activity,
  claims, anchor/fingerprint, cursors, and notification count.
- [x] Update the MCP implementation note and exact source mappings.
- **Stop gate:** if the migration changes attach error text, token clearing,
  snapshot order/cap, waiter ownership, fallback pacing, or master/child
  division, restore those behaviors before continuing.
- **Done signal:** no production MCP private reach-in remains; focused MCP
  SQLite/PG suites pass and the no-touch assertions fire.

### 4. Add the immutable MCP 0.9.5/current-core wheel canary

- [x] Write failing checker tests for immutable tag/commit validation, ordinary
  dependency installation, checkout isolation, tracebacks, timeouts, token
  redaction, and every attach/list/detach stage.
- [x] Reuse the current wheel-matrix utilities where ownership stays coherent.
  If a separate `check-core-mcp-wheel-matrix.py` is clearer, share only neutral
  artifact/environment/process helpers; do not fork tag validation or process-
  group cleanup semantics.
- [x] Build a wheel from the historical MCP release source at the pinned tag in
  an isolated archive, install it with the candidate core wheel in a fresh
  environment through normal resolver behavior, and drive its installed stdio
  entry point against a real temporary SQLite workspace created by installed
  candidate core. Do not describe this rebuilt artifact as the byte-identical
  wheel published to PyPI; the pinned source and metadata are the canary.
- [x] Wire the canary into `build-and-check-release-wheels.py`, the applicable
  core/all release preparation path, canonical Test release-wheel evidence,
  and dry-run/test command assertions.
- [x] Preserve the current core/Summon matrix and distribution-rename historical
  proof; this is an additional seam-sensitive canary, not a replacement.
- **Stop gate:** if the canary needs the checkout on `PYTHONPATH`, `--no-deps`, a
  private MCP import, network access beyond the existing pinned-origin fetch,
  or an unpinned artifact, stop and redesign it.
- **Done signal:** checker self-tests pass, dry-run shows the canary, and a real
  candidate-core/historical-MCP attach completes checkout-free.

### 5. Characterize E2 with real red process-domain tests

- [x] Extend the shipped scripted-provider scenario language with one bounded
  descendant-spawn step. It must support: same-domain child, inherited stdout,
  ignored graceful/TERM signals, leader-exits-first, and a PID publication file.
- [x] Make tests capture PID plus creation identity immediately. Every failure
  path cleans the descendant only if identity still matches, so tests cannot
  signal a reused PID.
- [x] Add red stream tests proving current `close()` leaves a same-domain
  descendant alive after graceful leader exit and after forced leader kill.
- [x] Add the corresponding red PTY leader-exits-first test, demonstrating the
  current `_reap_child()` early-return gap.
- [x] Add a red inherited-stdout test proving the descendant can delay EOF/pump
  completion under direct-child cleanup.
- [x] Preserve existing tests for reusable interrupt, one graceful retirement
  signal, blocked writes, concurrent close, and primary-error notes.
- **Stop gate:** if a test passes by timing luck, inspects only mock calls, or
  cannot clean its child deterministically after failure, it is not acceptable
  red evidence.
- **Done signal:** the pre-change probes reproduce the orphan/EOF capability on
  POSIX and fail for the intended reason with bounded cleanup.

### 6. Implement the shared POSIX process domain and migrate stream plus PTY

- [x] Add `_process_domain.py` with one narrow owner for POSIX spawn flags,
  saved process-group identity, public non-reaping leader-exit observation,
  SIGTERM/SIGKILL group escalation while identity remains pinned, single leader
  reap, and terminal diagnostics.
- [x] Centralize spawn through a function/class that accepts adapter-specific
  `Popen` stdio/text/env arguments while forcing `start_new_session=True` on
  POSIX. Do not put pipe, PTY-master, or protocol parsing in the domain module.
- [x] Change Claude and scripted spawns to publish the process plus its domain
  atomically to `StreamJsonHandle`.
- [x] Change stream `close()` to preserve graceful request/close concurrency and
  delegate forced domain finalization before pipe release.
- [x] Change PTY spawn and final reap to use the same domain owner; remove the
  PTY-local early-return/group ladder only after equivalent tests pass.
- [x] Replace natural event-stream and lifecycle `Popen.poll()`/`wait()` calls
  with the domain owner's non-consuming `waitid(..., WNOWAIT)` observation until
  terminal close. Use public `os.waitid()` where available and add a private
  Darwin-only `ctypes` binding for Python 3.11/3.12. Preserve the exact normal
  or negative-signal return code in `ExitEvent`, ensure only finalization reaps,
  and prohibit any group signal after reap.
- [x] Test the Darwin binding directly with real children that exit normally and
  by signal; prove repeated observation leaves each waitable until the one
  `Popen.wait()` reap. Add a hosted macOS Python 3.11 process cell (remove only
  that exclusion from the existing Summon process matrix, or add an equally
  narrow blocking cell) so the fallback executes on the exact commit. Python
  3.13+ macOS tests separately exercise the public `os.waitid()` path.
- [x] Add a regression test that makes a post-reap `killpg()` fatal and proves
  natural provider exit still runs the pinned group ladder before the one reap.
- [x] Add a POSIX-only explicit-escape boundary test whose child calls
  `setsid()`, survives domain close by contract, and is then identity-checked
  and cleaned by the test.
- **Stop gate:** stop if the shared module begins owning adapter I/O, if
  `_driver.py` gains a second reaper, if any code scans arbitrary ancestry, or
  if leader exit can still bypass the pinned group ladder. Also stop if any
  production path can reap the leader before group signaling or signal its PGID
  afterward. A missing Darwin `waitid` symbol, ABI/layout mismatch, or skipped
  macOS 3.11 fallback test also blocks the packet.
- **Done signal:** all real stream and PTY descendant tests pass on Linux and
  macOS; existing lifecycle suites retain their signal counts, order, and error
  primacy. The evidence is bounded best-effort POSIX group retirement, not an
  atomic group-empty claim.

### 7. Implement pre-execution Windows Job Object containment

- [x] Isolate minimal typed Win32 `ctypes` declarations behind a platform-
  private module imported only on Windows. Define exact handle ownership and
  `CloseHandle` cleanup for job, process, thread snapshot, and opened-thread
  handles.
- [x] Spawn stream providers with `CREATE_SUSPENDED` and the existing compatible
  creation flags; create/configure a kill-on-close Job Object; reopen the child
  by PID with the documented process rights; assign the suspended provider;
  enumerate and require exactly one thread owned by that still-suspended PID;
  open it with `THREAD_SUSPEND_RESUME`; require the expected `ResumeThread`
  result; then publish the handle/domain. Define documented `CREATE_SUSPENDED`
  locally because `subprocess` does not export it.
- [x] Avoid private `Popen._handle`, undocumented NT APIs, `taskkill /T`, and a
  post-start assignment race. Do not request `CREATE_BREAKAWAY_FROM_JOB`. Use
  documented Win32 process/thread snapshot, job, assignment, resume,
  accounting, and termination APIs.
- [x] On any setup failure, terminate and reap the suspended child, close all
  acquired handles once, close stdio, and raise one `AdapterError` without
  publishing a live handle.
- [x] During terminal close, allow the current graceful provider termination,
  then terminate the Job Object if active processes remain, wait boundedly for
  zero active processes, reap the leader, and release the job handle.
- [x] Add deterministic unit tests for each Win32 setup failure and one hosted
  Windows real-process test for leader-exits-first plus surviving grandchild.
  The real Job Object test is the primary proof and must successfully assign,
  resume, retire the descendant, and observe zero active job processes. Test
  outer-job rejection separately and prove fail-closed cleanup with no resumed
  or surviving child. If the ordinary hosted runner forbids a valid nested job,
  provision another supported hosted Windows environment or keep E2 blocked;
  rejection evidence cannot substitute for successful containment.
- **Stop gate:** if documented APIs cannot provide suspended assignment and
  resume without a new dependency or private runtime state, stop and propose a
  reviewed platform contract change. Do not weaken the implementation locally.
- **Done signal:** at least one Windows hosted test proves successful suspended
  assignment/resume, no pre-assignment spawn race, no surviving same-job
  descendant, zero active job processes, bounded close, and complete handle
  cleanup. A separate rejection path proves fail-closed cleanup.

### 7A. Reconcile the Windows spawn Ruff inventory through judged refactoring

This post-E2 correction remains inside the plan's Class 5+P unit. It changes no
Summon product contract. If a suppression remains after judgment, the
human-owned [DOM-10.2.1] registry and its global inventory must be reconciled as
part of the already-active process-gate scope; a count-only sentinel bump is not
an acceptable substitute for the required design review.

- [x] Preserve the red baseline from clean `50eeb94`: the real raw-inventory
  sentinel reports `BLE001=148` and `C901=39` against stale `144` and `38`.
  The five additions are exactly `spawn_windows_process`'s C901 finding and
  its four setup-failure `BaseException` catches.
- [x] Attempt a concrete C901 refactor at a real ownership seam. The candidate
  must keep suspended create/assign/resume order visible and may not pass a bag
  of partial native-handle locals to an unrelated helper merely to lower the
  score.
- [x] Attempt a concrete refactor of all four BLE001 sites. It must retain
  cleanup after `BaseException`, primary-error precedence, every cleanup note,
  one reap attempt after kill-on-close fallback, stdio closure, and exactly-once
  release of every acquired native handle. Narrowing to ordinary `Exception`
  is a behavior change and is not permitted as lint evasion.
- [x] Before changing the owner, add one baseline characterization per broad
  cleanup boundary using a control-flow `BaseException` (`KeyboardInterrupt`
  or `SystemExit`): initial retire/reap, stream close, native-handle close, and
  fallback reap. Each case must prove the original primary survives, the
  injected failure becomes a note, every later cleanup phase still runs, and
  each acquired stream/handle closes once. These cases pass on the original
  implementation because the refactor is behavior-preserving; the named Rule 5
  substitute proof is the already-red policy sentinel plus pre/post
  characterization of the behavior that must not move. A narrowed
  `except Exception` candidate is rejected if any control-flow probe escapes.
- [x] Give the original and runnable candidate diff to one independent judge.
  The judge must decide each candidate `net positive` or `net negative` using
  understandability, compactness, legibility, grouping of similar concerns,
  and overall maintainability. A retained suppression needs the rejected
  candidate and reason recorded in the Review Log; an accepted candidate lands
  only after its closest behavior proof passes.
- [x] Reconcile all surviving source directives, human registry cardinalities,
  generated locations, the global raw inventory, and the policy-test sentinel.
  Remove obsolete directives and registry memberships rather than blessing
  findings that the accepted refactor eliminated.
- **Invariants:** no provider executes before Job Object assignment; every
  setup failure remains fail-closed; no handle, process, or stream ownership is
  duplicated or leaked; programming/control-flow primaries remain primary;
  public signatures and error text remain stable; POSIX process-domain code is
  untouched.
- **Red/green proof:** use the already-failing
  `tests/test_ruff_policy.py::test_raw_active_rule_inventory_and_registry_are_exact`
  as the red test, then run the complete deterministic Win32 Job Object suite,
  raw C901/BLE001 inspection, normal Ruff, the suppression-index checker,
  Summon mypy, and the documentation/status/diff gates.
- **Done signal:** all five additions have an attempted before/after design and
  an independent verdict; accepted refactors pass their real behavior tests;
  every retained finding has exact reviewed policy evidence; normal and raw
  Ruff inventories reconcile from the current tree.

The judge fills every row independently. Rows may point to one shared
transaction-owner candidate, but no row inherits another row's verdict:

| Finding | Original | Attempted replacement | Verdict | Criteria-based rationale |
|---------|----------|-----------------------|---------|--------------------------|
| `C901` — `spawn_windows_process` | One 23-point setup/rollback/error-normalization owner | `_WindowsSpawnAttempt` owns partial resources, rollback, and publication while the public setup order stays linear | `net positive` | More source lines, but lower cognitive size, visible create/assign/resume order, and named transaction boundaries improve understanding, legibility, grouping, and maintenance. |
| `BLE001` — initial retire/reap cleanup | Inline broad catch preserves the setup primary | Transaction-local `_attempt_cleanup(_retire_and_reap, ...)` | `net positive` | The assigned-job versus unassigned-child choice stays together and the explicit boolean still owns fallback; centralized aggregation is shorter and easier to audit. |
| `BLE001` — per-stream close cleanup | Inline broad catch aggregates each stream failure | Ordered stream loop through transaction-local `_attempt_cleanup` | `net positive` | Every stream remains independently attempted in place; repeated scaffolding disappears without moving ownership or hiding continuation. |
| `BLE001` — per-native-handle close cleanup | Inline broad catch aggregates each handle failure | Ordered handle loop through transaction-local `_attempt_cleanup` | `net positive` | Reverse dependency order remains visible and `_OwnedHandle.close()` still clears ownership before the native call; one aggregation seam improves compactness and exact-once auditability. |
| `BLE001` — fallback reap cleanup | Inline broad catch retains failure after kill-on-close fallback | Named `_reap` attempted only after failed initial retirement and handle closure | `net positive` | The condition and ordering remain explicit while the named operation makes kill-on-close fallback easier to read and maintain. |

### 8. Add canonical TUI and PostgreSQL coverage producers red-first

- [ ] Update `tests/test_github_workflows.py` first so it expects exact source
  order `taut`, `taut_summon`, `taut_mcp`, `taut_tui`, `taut_pg`; named
  `tui-coverage` and `pg-coverage` producers; exact selectors; fail-closed raw
  artifact uploads; aggregate `needs`; and no tests in the aggregator.
- [ ] Add marker-checker mutation tests requiring one unique behavior-bearing
  TUI statement and one unique behavior-bearing PG statement. Select marker
  lines only after local coverage proves the intended full suite executes them.
- [ ] Add `taut_tui` and `taut_pg` to root coverage source in the same packet as
  both producers.
- [ ] Add a representative Ubuntu/Python TUI job to canonical `test.yml`. Use
  the TUI retained lock and complete package suite under root Coverage.py,
  run `coverage erase` against a job-private base before tests, upload
  `.coverage.tui.*`, and do not alter the dedicated TUI matrix.
- [ ] Add a representative Ubuntu/Python live PG job to canonical `test.yml`.
  Run `bin/pytest-pg --fast` under root Coverage.py with `COVERAGE_PROCESS_START`
  and an absolute `COVERAGE_FILE`, so its child pytest processes contribute to
  `.coverage.pg.*`. Erase only that job-private base before the run. Reuse the
  helper's bounded Docker lifecycle; do not add a second PostgreSQL bootstrap
  implementation.
- [ ] Require both new artifacts in the aggregate, validate them through
  `bin/combine-coverage.py`, and install the exact local source set before
  required-path/report generation with:

  ```bash
  uv pip install --system -e ".[dev]" \
    -e "./extensions/taut_summon" -e "./extensions/taut_mcp" \
    -e "./extensions/taut_tui" -e "./extensions/taut_pg"
  ```

  Enforce all required paths and emit one Codecov XML/upload.
- [ ] Add a local empirical coverage test or probe showing both package paths
  appear in combined `CoverageData`; test collection counts alone are not the
  proof.
- **Stop gate:** stop if the design creates cross-workflow artifact lookup,
  duplicate Codecov upload owners, an import-only PG shard, a mocked PG shard,
  or a source-list-only change.
- **Done signal:** workflow contract tests pass; local combined data contains
  executed TUI and PG markers; hosted aggregation downloads all six producer
  roles and Codecov reports changed lines in both packages.

### 9. Reconcile durable documentation and traceability

- [x] Update core architecture with the public read-only selection and client-
  owned notification-activity queue boundary.
- [x] Update MCP architecture to remove the documented private resolver and
  internal addressing dependency while preserving child-thread ownership.
- [ ] Update Summon architecture with the shared process-domain abstraction,
  POSIX/Windows split, terminal order, deliberate-escape boundary, and why this
  is not sealing.
- [ ] Update TUI/core coverage documentation with the canonical producer versus
  dedicated compatibility-workflow ownership split.
- [ ] Add a concise README/CHANGELOG note that `dismiss` now terminates
  same-domain descendants and that persistent services require an explicit
  external lifetime.
- [x] Add implementation mappings and reciprocal plan/code/test links only now,
  when implementation exists. Re-run the repository path/reference gates.
- [x] Evaluate whether the work exposed a durable lesson or a missing step in
  the planning/testing runbooks. Record a lesson only if the correction is
  reusable beyond this plan.
- **Stop gate:** do not describe process domains as security containment, tokens
  as authentication, coverage as proof of firing by itself, or old-wheel
  canaries as universal compatibility.
- **Done signal:** the minimum spec-plan-implementation-code/test chain is
  current and all doc/path gates pass.

### 10. Final verification, review, and owner handoff

- [ ] Run every focused and full gate below from current state; record commands,
  results, and any platform-limited evidence in the Verification Log.
- [ ] Run independent completed-work reviews after E1, E2, and T1 packets and a
  final whole-diff review. A different agent family is preferred for the final
  `+P` pre-landing review.
- [ ] Reconcile every planned task against executable evidence. A checked box,
  skipped suite, or test that exists but did not execute is not proof.
- [ ] Update the status-index row to `completed` only after implementation,
  hosted evidence, final review, and owner-authorized landing actually exist.
- [ ] If work remains uncommitted for owner review, report that state and exact
  changed files; do not call the plan complete.
- **Done signal:** no open deviation, review, platform, coverage, traceability,
  or landing gate remains.

## Testing Plan

### E1 core and MCP behavior

- Core SQLite tests use real clients and inspect member, claim, membership,
  cursor, notification, anchor, and fingerprint state before and after both new
  calls.
- Shared-contract PostgreSQL tests repeat the no-touch proof on a real backend.
- MCP tests attach through the real process/workspace reactor and use public
  API postconditions. Private-method monkeypatching is allowed only as a tripwire
  proving MCP does not call it, not as the semantic proof.
- The historical-wheel canary installs real built wheels and drives real stdio
  JSON-RPC. Imports from the checkout, editable installation, and `--no-deps`
  are forbidden.

Representative focused commands after implementation:

```bash
uv run --no-sync pytest -q -n 0 tests/test_client.py tests/test_shared_contract.py
uv run --project extensions/taut_mcp --extra dev --locked pytest -q -n 0 \
  extensions/taut_mcp/tests/test_resource.py \
  extensions/taut_mcp/tests/test_process_reactor.py \
  extensions/taut_mcp/tests/test_tools.py
uv run ./bin/pytest-pg --fast -n 0 \
  extensions/taut_mcp/tests/test_pg_conformance.py \
  extensions/taut_pg/tests/test_pg_search_provider.py
uv run --no-sync pytest -q -n 0 \
  tests/test_core_summon_wheel_matrix.py \
  tests/test_core_mcp_wheel_matrix.py \
  tests/test_release_script.py
```

If the final checker test file retains a different reviewed name, update the
commands and plan before execution rather than leaving a nonexistent path.

### E2 real process lifecycle

- The primary proof uses real Python provider and descendant processes. Test
  doubles may exercise deterministic error ordering but cannot prove domain
  signal delivery, inherited-pipe EOF, Job Object membership/emptiness, pinned
  POSIX group identity, or leader reap.
- Every process test has a bounded deadline, captures creation identity, and
  performs identity-safe cleanup in `finally` if production cleanup fails.
- Existing stream and PTY retirement suites remain regression gates for write
  epochs, signal-handler reentry, exactly-once graceful signal, concurrent
  close, error notes, fd ownership, and pump ordering.
- Hosted Windows proof must execute a real Job Object descendant case. A skipped
  test is a blocker, not portable evidence.

Representative commands:

```bash
uv run --project extensions/taut_summon --extra dev --locked pytest -q -n 0 \
  extensions/taut_summon/tests/test_scripted_adapter.py \
  extensions/taut_summon/tests/test_pty_adapter.py \
  extensions/taut_summon/tests/test_conformance.py \
  extensions/taut_summon/tests/test_driver.py
uv run --extra dev pytest extensions/taut_summon/tests -v --tb=short \
  -m "xdist_group and not requires_live_harness and not requires_local_llm" \
  -n 2 --dist load
```

### T1 coverage evidence

- Workflow parser tests prove exact producer topology and fail-closed artifact
  ownership.
- Required-marker tests mutate/remove each TUI/PG marker and prove the checker
  fails.
- A local representative TUI coverage run uses the retained project lock and
  full suite.
- A local representative PG coverage run uses real Docker PostgreSQL and the
  existing helper under subprocess coverage.
- Combined data is inspected through Coverage.py's public API for the exact
  package paths before XML generation.

Representative commands:

```bash
uv run --no-sync pytest -q -n 0 \
  tests/test_github_workflows.py tests/test_required_coverage_paths.py
COVERAGE_FILE=.coverage.tui \
  uv run --project extensions/taut_tui --extra dev --locked \
  python -m coverage run --rcfile=pyproject.toml --parallel-mode \
  -m pytest extensions/taut_tui/tests -n 0
COVERAGE_PROCESS_START="$PWD/pyproject.toml" COVERAGE_FILE="$PWD/.coverage.pg" \
  uv run --extra dev python -m coverage run --parallel-mode \
  ./bin/pytest-pg --fast -n 0
```

The implementer must use collision-safe temporary coverage paths when executing
locally and must not delete or overwrite unrelated existing `.coverage*` data.

## Verification and Gates

### Per-packet static and focused gates

```bash
uv run --no-sync bin/check-plan-status-index
uv run --no-sync bin/check-doc-paths
uv run --no-sync bin/check-dom15-fixtures
uv run --no-sync bin/coalesce-check
uv run --extra dev ruff check taut tests bin \
  extensions/taut_pg/taut_pg extensions/taut_pg/tests \
  extensions/taut_summon/taut_summon extensions/taut_summon/tests \
  extensions/taut_mcp/taut_mcp extensions/taut_mcp/tests
uv run --extra dev ruff format --check taut tests bin \
  extensions/taut_pg/taut_pg extensions/taut_pg/tests \
  extensions/taut_summon/taut_summon extensions/taut_summon/tests \
  extensions/taut_mcp/taut_mcp extensions/taut_mcp/tests
uv run --project extensions/taut_tui --extra dev --locked \
  ruff check extensions/taut_tui/taut_tui extensions/taut_tui/tests
uv run --project extensions/taut_tui --extra dev --locked \
  ruff format --check extensions/taut_tui/taut_tui extensions/taut_tui/tests
uv run --extra dev mypy taut tests bin/release.py \
  extensions/taut_pg/taut_pg extensions/taut_pg/tests \
  --config-file pyproject.toml
uv run --extra dev mypy taut tests \
  extensions/taut_summon/taut_summon extensions/taut_summon/tests \
  --config-file pyproject.toml
uv run --project extensions/taut_mcp --extra dev --locked \
  mypy extensions/taut_mcp/taut_mcp extensions/taut_mcp/tests \
  --config-file extensions/taut_mcp/pyproject.toml
uv run --project extensions/taut_tui --extra dev --locked \
  mypy extensions/taut_tui/taut_tui extensions/taut_tui/tests \
  --config-file extensions/taut_tui/pyproject.toml
```

### Final local gates

```bash
uv run --extra dev pytest -v --tb=short -m "not slow and not installed_wheel"
uv run --extra dev pytest extensions/taut_summon/tests -v --tb=short \
  -m "not requires_live_harness and not requires_local_llm"
uv run --project extensions/taut_mcp --extra dev --locked \
  pytest extensions/taut_mcp/tests -v --tb=short -m "not pg_only" -n 0
uv run --project extensions/taut_tui --extra dev --locked \
  pytest extensions/taut_tui/tests -v --tb=short -n 2 --dist loadfile
uv run ./bin/pytest-pg --fast
uv run --no-sync python bin/build-and-check-release-wheels.py
git diff --check
```

### Hosted and post-change gates

- canonical Test workflow: all source cells, deterministic Summon process,
  local LLM, MCP coverage, TUI coverage, PG coverage, aggregation, packaging,
  lint, and release-wheel evidence green on the exact commit;
- dedicated TUI and PG workflows green under their retained matrices;
- Windows real Job Object descendant test successfully assigns, resumes,
  reaches zero active processes, and passes, not skips; assignment-rejection
  coverage is separate and cannot satisfy this gate;
- macOS Python 3.11 Darwin-`waitid` fallback and current-Python POSIX process-
  group descendant tests execute and pass;
- aggregate Coverage XML contains measured `taut_tui` and `taut_pg` files and
  Codecov evaluates their changed lines;
- immutable MCP 0.9.5/current-core canary attaches and shuts down cleanly.

## Independent Review Loop

### Plan and delta review before promotion

Use a fresh agent with no conversation context, preferably a different agent
family. Give it this plan, all four touched specs, the current source owners,
the ranged-dependency policy plan, and the terminal-retirement plan. Prompt:

> Read the plan and its exact Proposed Spec Delta. Verify every named file,
> function, platform mechanism, test seam, command, and promotion step against
> the repository. Challenge whether `peek_identity()` and
> `notification_activity_queue()` are the narrowest useful public seams;
> whether the immutable MCP 0.9.5 canary is the honest consequence of open
> metadata; whether POSIX groups and pre-execution Windows Job Objects can meet
> their distinct claimed contracts without private runtime APIs, including the
> POSIX non-reaping/PGID boundary and Windows zero-active-process proof; and
> whether the TUI/PG coverage topology supplies real combined patch evidence. Look for
> hidden lifecycle races, behavior that contradicts program theory, missing
> rollback, weak or mocked proof, nonexistent commands, and performative
> abstraction. Could a zero-context engineer implement this correctly after
> promotion? Return blocking findings first and say which proposed text should
> change.

Every point is appended to the Review Log with `accepted`, `modified`, or
`rejected` plus evidence. A reviewer who cannot implement confidently blocks
spec promotion.

### Reader test

A second fresh-context pass must answer these questions from the plan alone:

1. Which findings are implemented, and which are explicit non-goals?
2. What exact state effects do the new public core methods forbid?
3. Why is the old MCP wheel tested, and what does that test not prove?
4. What process does Summon own after this change?
5. What happens when the provider leader exits before its grandchild on POSIX,
   and what stronger postcondition exists on Windows?
6. How is Windows containment established before provider execution?
7. What is outside the process-domain guarantee?
8. Why are TUI/PG workflow tests alone not coverage evidence?
9. Which workflow owns the combined Codecov report?
10. What evidence blocks completion on Windows?

Any wrong or ambiguous answer causes a plan edit and another reader pass.

### Implementation review

- after E1: review the public API effects, MCP owner-thread boundary, and
  checkout-free historical-wheel canary;
- after E2: review spawn publication, every signal/reap/handle edge, real
  descendant proof, and POSIX/Windows parity;
- after T1: review workflow topology, raw artifact integrity, marker execution,
  and Codecov visibility; and
- before landing: review the complete diff against every plan task and exact
  promoted spec paragraph. A different-family review is preferred and required
  when available for the `+P` process-gate change.

## Out of Scope

- upper-bounding all first-party dependencies without a known incompatibility;
- deleting or renaming core private identity machinery immediately;
- authenticating continuity tokens or changing Taut's one-trust-domain model;
- changing MCP activity-wait pacing, rate limits, schemas, tool count, resource
  representation, or workspace concurrency;
- security sandboxing, cgroups, containers, privilege reduction, arbitrary
  ancestry scanning, or guaranteed reclamation after deliberate `setsid`/
  external-supervisor escape;
- a user-facing keep-background-processes option. Persistent work uses an
  explicit external lifetime; a future opt-out requires separate semantics;
- DDL deduplication, PostgreSQL-only exception changes, search redesign, or
  extension schema ownership changes;
- TUI Summon coordinator/transcript extraction, Summon driver control/watchdog
  extraction, or file-size refactors;
- changing overall coverage percentage thresholds solely because the measured
  source set grows. Observe the truthful new baseline first; any threshold
  policy change is separate `+P` work;
- publishing a release or committing on the owner's behalf.

## Deviation Log

| Spec ref | Planned behavior | Actual behavior | Rationale | Spec proposal |
|----------|------------------|-----------------|-----------|---------------|
| [TAUT-12.5] | Promote the E1 historical MCP/current-core canary contract before implementing its checker. | The first promotion pass mistakenly grouped the canary paragraph with [TAUT-12.5]'s unapproved T1 coverage replacement. The canary paragraph was promoted after the first real checker proof and before E1 review or closure. | Two planned changes share [TAUT-12.5], but only the coverage replacement belongs to T1. Traceability reconciliation exposed the packet-boundary error. | Correct the active spec now; retain the T1 coverage replacement as proposed. No runtime contract changed. |

## Implementation Log

| Date | Slice | Baseline/evidence | Result | Next gate |
|------|-------|-------------------|--------|-----------|
| 2026-08-25 | E1 spec promotion | HEAD `cd7e347`; pre-promotion spec blobs recorded under Spec Baseline | Promoted only the authorized E1 identity/core/MCP text and backlinks; E2/T1 remain proposed. | Documentation gates, then first red core tracer. |
| 2026-08-25 | E1 public core seams | Red-first exact-signature, selector, no-touch, reselection, queue-reuse, and close tests in `tests/test_client.py`, `tests/test_public_api.py`, and `tests/test_shared_contract.py` | Added `peek_identity()` through the existing resolver's no-touch controls and `notification_activity_queue()` through the client-owned persistent queue cache. No root queue export or CLI surface was added. | Migrate MCP and prove both backends. |
| 2026-08-25 | E1 MCP public-boundary migration | Real SQLite owner-thread attachment tripwire plus live PostgreSQL conformance | `_WorkspaceReactor` now calls only the two public core seams for attachment identity and waiter setup; notification semantics remain on `peek_inbox(limit=101)`. SQLite and PostgreSQL state snapshots stayed unchanged. | Historical installed-wheel compatibility gate. |
| 2026-08-25 | E1 historical-wheel canary | `uv run --no-sync python bin/build-and-check-release-wheels.py`; historical MCP wheel SHA-256 `e68fb51fd7a8ba2119b74a2a28fd5cc030d28082d10f0eb3f5e6ab835f36b608` | PASS: immutable `taut_mcp/v0.9.5` source, ordinary candidate-core dependency resolution, checkout-free imports, real SQLite attach/list/detach, and clean stdio shutdown. | Reconcile implementation docs, run PostgreSQL and focused suites, then independent review. |
| 2026-08-25 | SimpleBroker 7.4.2 typing reconciliation found during E1 gates | Full MCP, Summon, and TUI mypy gates | Removed redundant test-only casts now made obsolete by the public typed queue iterator/read contracts. No runtime behavior changed. | Rerun affected tests and static gates. |
| 2026-08-25 | E2 spec promotion | HEAD `3441fda`; pre-promotion spec 04 blob recorded under Spec Baseline | Promoted only the authorized Summon process-domain lifecycle and firing-proof text plus backlink; T1 remains proposed. | Documentation gates, then the first real descendant red tracer. |
| 2026-08-25 | E2 real POSIX characterization | Pre-change stream leader-first, inherited-stdout, forced-signal, and PTY leader-first probes with PID plus process-creation identity and bounded self-expiry | RED for the intended reasons: natural stream and PTY cleanup left the exact same-domain descendant alive; inherited stdout held the structured pump open; forced close killed only the leader. Each probe identity-checked and removed its descendant afterward. | Implement one non-reaping domain owner before changing adapter I/O. |
| 2026-08-25 | E2 POSIX domain and adapter migration | Real macOS Python 3.11 libc-`waitid` normal/signal exits; real stream and PTY leader-first, inherited-stdout, TERM, SIGKILL, and explicit-`setsid` probes; post-reap `killpg` tripwire | Shared spawn now publishes capability-minimal `ProcessIO` plus one domain; raw `Popen` lifecycle stays private. POSIX leader status remains waitable through the group ladder and is reaped once afterward. Stream raw readers no longer require descendant-held EOF. | Complete Windows implementation and hosted platform proof. |
| 2026-08-25 | E2 POSIX finalization review correction | Red-first zero-signal-oracle and terminal-TERM-error regressions, followed by deterministic signal/reap error firing tests | Replaced group-emptiness polling with ordered bounded TERM grace, unconditional KILL attempt, bounded non-reaping leader observation, and one reap attempt. Signal errors aggregate without stranding a known-terminal leader; a successful mismatched reap is marked final before its cached-status diagnostic; repeat finalization rethrows the stored terminal error without signaling or waiting again. | Rerun the focused process-domain suite and static/documentation gates; retain the hosted Linux natural-exit row as blocking evidence. |
| 2026-08-25 | E2 busy inherited-output correction | Red-first continuous stream writer, incomplete non-EOF frame, and deterministic always-readable PTY probes | POSIX raw stream work is capped at 16 reads and 1 MiB per turn; the terminal-observed final drain has the same bound and accepts only complete newline-delimited frames unless true EOF is present. PTY observes leader status after every readable turn. Real stream and PTY descendants remain alive through `ExitEvent` and are retired by `close()`. | Rerun full local Summon behavior and independent correction review. |
| 2026-08-25 | E2 Windows collection isolation | Red workflow contract for a missing Windows-specific process step | The Windows row selects only process-domain, structured-adapter, and Job Object test files, so pytest never imports the POSIX-only PTY module before marker filtering. POSIX rows retain broad process-marker collection. | Hosted Windows must execute both real Job Object proofs on the exact commit. |
| 2026-08-25 | E2 Windows implementation and proof wiring | 31 deterministic Job Object tests, 12 pipe/readiness tests, real leader/descendant and incompatible-outer-job hosted tests, and a blocking Windows Python 3.11 process-matrix row | Suspended assign-before-resume, temporary/native handle ownership, kill-on-close fallback, zero-active finalization, single leader reap, inherited-stdout readiness, and fail-closed nesting rejection are implemented without private CPython state. Local deterministic gates pass; the real Windows tests are present but cannot execute on the macOS workstation. | Hosted Windows success remains the Task 7 stop gate, then independent E2 review. |
| 2026-08-28 | E2 Ruff-inventory correction | Red raw inventory `BLE001=148`/`C901=39`; four pre/post control-flow cleanup characterizations; independently judged runnable diff | Added one `_WindowsSpawnAttempt` owner that keeps create/assign/resume linear, transfers the job only after result construction, and consolidates four broad cleanup sites into one explicit boundary. The spawn C901 and three net BLE001 findings were removed; surviving raw inventory is `BLE001=145`/`C901=38`. | Run the complete Task 7A static, policy, documentation, and neighboring behavior gates. |

## Review Log

| Date | Reviewer/scope | Finding | Disposition and evidence |
|------|----------------|---------|--------------------------|
| 2026-08-25 | E2 promotion exactness review | The first pass found lost signal-handler reentry text, an E2 backlink that claimed unpromoted T1, ambiguous Darwin `EPERM` semantics, and two proposed/live replacement-boundary mismatches. | **accepted, final re-review passed**: restored reentry; made the backlink E2-only; defined `ESRCH` and terminal-leader Darwin `EPERM` as no-signalable-target outcomes without claiming group emptiness; preserved PTY master ownership text; and narrowed the paragraph replacement instruction. The reviewer found no SimpleBroker 7.4.2 or landed-E1 conflict. |
| 2026-08-24 | Fresh-context independent plan/delta review | Portable POSIX process groups cannot support the draft's atomic domain-empty claim once the numeric PGID can be reused after leader reap. | **accepted, plan revised**: POSIX now has one non-reaping owner, signals only while the leader pins the PGID, never signals after reap, and claims bounded best-effort group retirement. Windows alone retains the durable Job Object zero-active-process postcondition. |
| 2026-08-24 | Fresh-context independent plan/delta review | Focused MCP and Summon `uv --project` commands used nonexistent root-relative `tests/...` paths. | **accepted, corrected** to full `extensions/.../tests/...` paths; `uv --project` selects an environment and does not change cwd. |
| 2026-08-24 | Fresh-context independent plan/delta review | The canary text called a freshly built pinned-source wheel the published wheel. | **accepted, corrected**: the proof is consistently a wheel built from immutable 0.9.5 release source, not a byte-identical PyPI artifact. |
| 2026-08-24 | Fresh-context independent plan/delta review | Repeated notification-queue calls, Windows suspended-process handle recovery, outer-job nesting failure, coverage initialization, and aggregate installation needed sharper implementation rules. | **accepted, clarified**: selection runs per queue call; Windows uses documented reopen/snapshot/resume APIs with exactly-one-thread and fail-closed outer-job gates; each producer erases only its private base and the aggregate install command is exact. |
| 2026-08-24 | Fresh-context reader test | All ten questions were answered, but the first targeted reread found that Python 3.11/3.12 on macOS does not expose `os.waitid`, and that Windows rejection evidence could substitute for successful containment in Task 7. | **accepted, revised, final reread passed**: add the narrow Darwin libc `waitid` shim plus macOS 3.11 hosted proof; require a separate successful Windows Job Object hosted proof and keep rejection as a distinct failure test. The reviewer found no remaining blocker. |
| 2026-08-25 | Independent E1 completed-work review | `peek_identity()` leaked the shared resolver's reset of `last_created_member` and `last_candidates`; canary timeout/traceback/token/stage obligations were only source-string assertions; the MCP AST boundary missed direct import aliases. | **accepted and fixed**: both public seams restore the exact diagnostic objects in `finally` on success and failure; the production canary now uses an executable stdio driver with scripted subprocess failure proofs; the AST gate rejects forbidden imports and aliased calls with a mutation fixture. |
| 2026-08-25 | Independent E1 correction rereview | Rechecked only the three E1 findings against current code and firing tests. | **PASS**: all three findings resolved; no remaining blocker or new E1 contradiction. |
| 2026-08-25 | Independent E2 completed-work review, POSIX F1/F3 | Linux can keep `killpg(pgid, 0)` successful while the unreaped zombie leader pins the PGID, so zero-signal absence cannot terminate the ladder. An unexpected group-signal error returned before reaping a known-terminal leader, and a successful `Popen.wait()` status mismatch raised before recording that the child was already reaped. | **accepted and fixed**: POSIX finalization now uses explicit bounded stages without a zero-signal oracle, aggregates signal failures while continuing cleanup, marks a successful reap before comparing status, and stores terminal finalization errors for stable rethrow. Deterministic firing tests cover TERM/KILL aggregation, `ESRCH`, conditional Darwin `EPERM`, observation timeout, reap exceptions, mismatch, and the no-post-reap-signal tripwire; a real Linux zombie-leader regression is selected only on Linux. |
| 2026-08-25 | Independent E2 completed-work review, output F2 | A continuously writing inherited stdout could keep the POSIX raw drain loop or PTY readable path busy forever, preventing leader observation; the prior real tests held inherited output open silently. | **accepted and fixed**: stream reads have strict per-turn read/byte bounds, incomplete non-EOF fragments are not promoted to frames, and PTY checks after every readable turn. Deterministic RED probes plus real continuously writing descendants cover both adapters and exact descendant retirement. |
| 2026-08-25 | Independent E2 correction rereview | Rechecked the full E2 diff and F1/F2/F3 corrections against [SUM-7.1], [SUM-7.4], [SUM-12], both platform owners, stream/PTY fairness, Windows collection isolation, and documentation. | **PASS**: no actionable blocker remains. The reviewer independently reran process-domain, scripted, Win32, full PTY, static, workflow, and documentation gates. Hosted exact-commit Windows and Linux execution remain evidence gates, not local code defects. |
| 2026-08-28 | Task 7A scoped plan review and round 2 | Initial review blocked on missing control-flow `BaseException` firing proof and a candidate-level rather than five-finding decision record. | **accepted; round-2 PASS**: Task 7A now requires four per-boundary characterization cases, names the red policy sentinel plus pre/post characterization as the Rule 5 substitute, and carries five independent decision rows. |
| 2026-08-28 | Task 7A runnable-candidate judgment | Compared clean `50eeb94` with the actual `_WindowsSpawnAttempt` diff and independently ran focused Win32, Ruff, and mypy proof. | **no blocker; five `net positive` verdicts**: the judge found the transaction owner improved understanding, legibility, concern grouping, and maintenance despite adding physical lines; every cleanup order, primary/cause/note behavior, assignment barrier, and ownership transfer remained exact. |
| 2026-08-28 | Task 7A final reconciliation review | Rechecked the accepted code/tests, `RUFF-SUP-035` owner move, new `RUFF-SUP-091` graph, global/test inventories, five verdict rows, and current verification evidence. | **PASS**: no defect; direct raw derivation is `BLE001=145`/`C901=38`, both groups reconcile one directive/location/raw diagnostic, and every focused static, behavior, policy, and documentation rerun passed. |

## Verification Log

| Date | Scope | Command or hosted signal | Result |
|------|-------|--------------------------|--------|
| 2026-08-24 | Plan structure and repository consistency | `check-plan-status-index`; `check-doc-paths`; `check-dom15-fixtures`; `coalesce-check`; plan-scoped `git diff --check` | PASS after the final revision. Path checker inspected 63 sources and 1,348 claims; coalescing reported only the five already-known foreign claims and all cues resolved. |
| 2026-08-24 | Darwin Python 3.11 non-reaping feasibility | Locked Summon Python 3.11 inline typed-`ctypes` calls to libc `waitid` with `WNOWAIT`, followed by `Popen.wait()` | PASS: 104-byte typed `siginfo_t`; normal exit observed as `CLD_EXITED/status 7` then reaped as `7`; SIGTERM observed as `CLD_KILLED/status 15` then reaped as `-15`. No child was left alive. |
| 2026-08-24 | Independent plan/delta and fresh-reader review | Zero-context full review, two targeted rereads after corrections | PASS: three original blockers and two targeted portability/proof blockers were incorporated; final reviewer reported no blocking issue. |
| 2026-08-25 | E1 installed historical MCP/current-core canary | `uv run --no-sync python bin/build-and-check-release-wheels.py` | PASS: all four installed-wheel cases passed; the historical MCP lifecycle canary used normal resolution and cleanly shut down. Historical MCP wheel SHA-256: `e68fb51fd7a8ba2119b74a2a28fd5cc030d28082d10f0eb3f5e6ab835f36b608`. |
| 2026-08-25 | E1 focused core and wheel-checker contracts | `uv run --extra dev pytest -q -n 0 tests/test_client.py tests/test_shared_contract.py tests/test_public_api.py tests/test_core_summon_wheel_matrix.py` | PASS: 408 tests; exact public shape, durable and client-diagnostic neutrality, queue lifecycle, cross-backend contract source, immutable-ref/commit enforcement, and executable checker failure modes fired. |
| 2026-08-25 | E1 MCP SQLite and PostgreSQL behavior | Package-local non-PG suite; `uv run ./bin/pytest-pg --fast -n 0 extensions/taut_mcp/tests/test_pg_conformance.py` | PASS: the full non-PG MCP suite completed; all 7 live PostgreSQL tests passed. |
| 2026-08-25 | Root regression | `uv run --extra dev pytest -q -m 'not slow and not installed_wheel'` | PASS on the final standalone rerun with one expected Windows-only filename-contract skip on macOS. A preceding run concurrent with Docker PG had one unrelated mocked-readiness timing-fixture failure; that exact test passed immediately in isolation before the clean broad rerun. |
| 2026-08-25 | Static, typing, and documentation integrity | Root/PG/Summon/MCP/TUI Ruff and mypy gates; `check-plan-status-index`; `check-doc-paths`; `check-dom15-fixtures`; docs-reference tests; `coalesce-check`; `git diff --check` | PASS. Path checker inspected 63 sources and 1,372 claims; coalescing resolved all local cues and reported only the five known foreign claims. |
| 2026-08-25 | E2 local POSIX behavior | `uv run pytest -q -n 0 extensions/taut_summon/tests/test_process_domain.py extensions/taut_summon/tests/test_scripted_adapter.py extensions/taut_summon/tests/test_claude_adapter.py`; full `test_pty_adapter.py` plus focused forced-stage rerun | PASS on macOS Python 3.11: Darwin fallback, exact natural/signal status, leader-first stream/PTY retirement, inherited stdout, TERM/SIGKILL, explicit escape, and retained lifecycle concurrency contracts. |
| 2026-08-25 | E2 POSIX finalization correction | Full `test_process_domain.py`; seven focused real stream/PTY descendant cases; scoped Ruff and mypy; plan status, doc-path, docs-reference, and diff checks | PASS locally: 13 process-domain cases passed with the one real Linux zombie-group regression selected only on Linux; all seven neighboring real-process cases and every static/documentation gate passed. Hosted Linux remains required to execute the nonportable regression on the exact commit. |
| 2026-08-25 | E2 Linux zombie-group reproduction | Read-only repository mount in local `python:3.12-bookworm`; natural leader exit observed with `WNOWAIT`, followed by 20 ms TERM/KILL bounds and final reap | PASS after correction: `observed 0 raw_returncode None` then `result 0`, with no manual reap. The same probe failed before correction with `provider process domain survived SIGKILL` and required a manual reap. Hosted Linux remains the exact-commit release gate. |
| 2026-08-25 | E2 corrected local regression | `uv run pytest -q extensions/taut_summon/tests -m 'not requires_live_harness and not requires_local_llm'`; full workflow contracts; focused continuous-writer and finalization cases; scoped Ruff/mypy; all documentation gates | PASS on macOS: the full local Summon suite completed with exactly the expected Linux semantic skip and two real-Windows skips; workflow selection collected both named Windows proofs without importing PTY; static and documentation gates passed. |
| 2026-08-25 | E2 Windows deterministic boundary | `uv run pytest -q -n 0 extensions/taut_summon/tests/test_win32_job.py extensions/taut_summon/tests/test_win32_pipe.py extensions/taut_summon/tests/test_process_domain.py` | PASS locally with the expected real-Windows outer-job skip: typed ABI, every setup failure, assign-before-resume, exact handle closure, zero-before-reap ordering, pipe readiness/EOF/error mapping, and shared factory publication fired. |
| 2026-08-25 | E2 hosted platform proof | `summon-process` matrix rows added for macOS Python 3.11 and Windows Python 3.11; Windows uses a POSIX-import-free file list | **PENDING**: workflow structure and a local Debian container reproduction are green, but this workstation cannot supply the required real Windows Job Object execution. E2 is not ready until the hosted Windows, Linux, and macOS rows pass on the exact commit. |
| 2026-08-28 | Task 7A judged Ruff correction | Red policy sentinel; 37 policy/index tests; deterministic Win32 Job Object, pipe, and process-domain set; full non-live Summon suite; 48-file Summon mypy; repository Ruff/index; formatter, plan/status/path/DOM/coalescing/docs-reference/diff gates | PASS. The red reproduced `BLE001=148`/`C901=39`; accepted refactoring and registry regeneration reconcile at `BLE001=145`/`C901=38`. Four control-flow cleanup cells pass, the focused platform set has only its two expected host skips, the broad Summon suite reached 100% with three expected platform skips, and every static/documentation gate is green. Independent judge: five `net positive` verdicts, no blocker. |

## Fresh-Eyes Completion Checklist

- [ ] Every named path, method, command, marker, and workflow job exists in the
  implemented tree or the plan was updated before execution.
- [x] The promotion baseline is recorded. E1 text preceded dependent code
  except the corrected [TAUT-12.5] timing miss recorded in the Deviation Log;
  that paragraph landed before E1 review or closure.
- [x] No public method calls a second selector implementation or changes
  `whoami()` effects.
- [x] No production MCP private identity/addressing reach-in remains.
- [x] The old-wheel canary is checkout-free and uses normal resolution.
- [ ] Leader exit cannot bypass same-domain cleanup on stream or PTY.
- [ ] POSIX natural exit is observed without reap until the safe group ladder
  finishes; no signal targets the numeric PGID after reap, and no atomic empty-
  group claim remains.
- [ ] Windows assigns the suspended provider to the Job Object before resume
  without private CPython or undocumented NT APIs.
- [ ] Every real process probe is bounded and identity-safe on cleanup.
- [ ] Coverage has both source declarations and real raw-shard producers.
- [ ] The aggregate requires and validates TUI/PG shards and executed markers.
- [ ] Error primacy, owner-thread boundaries, write epochs, pump order, and
  dedicated compatibility workflows remain intact.
- [ ] All deviations and review findings are closed explicitly.
- [ ] Final evidence comes from current state and includes hosted Windows,
  macOS, PostgreSQL, installed-wheel, and Codecov signals.
- [ ] Plan, spec, implementation docs, code, tests, changelog, and status index
  agree before any completion claim.
