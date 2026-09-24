# 2026-09-23 deep-dive review (source artifact)

This is the evidence record for the eight `2026-09-24-*` remediation plans in
`docs/plans/`. It is a review artifact, not a contract: every claim here is a
finding that its owning plan re-verifies with a failing test before code
changes. Reviewer scratch artifacts referenced below lived in a session
scratchpad and are not retained; the reproduction commands are inline.

Reviewed at `c0a4616` plus the uncommitted enhanced-keyboard-detach worktree. Lead: Claude (Fable 5.1). Nine facet reviewers on Opus, coordinated through a taut workspace (`#findings`, 48 posts, zero lost). Every P1 below was reproduced by the lead independently of the reviewer that found it; P2s were verified by the reviewer with commands and by lead code reading where noted.

## Overall grade: B-

The plumbing is honest and the fundamentals hold under measurement: no traceback in ~250 hostile CLI invocations, zero lost or duplicated messages across 3 watchers + 2 writers for 20 s (2,579 messages), exact dump/load round trip, 25 ms median wake latency, wheels clean, release guarantees real. The tests are mostly real-behavior (0/40 sampled false in core; 14/14 planted mutations caught).

The grade is held down because each headline promise has one verified P1 behind it: automatic identity (two), the agent polling recipe, `taut read` under a broken pipe, Ctrl-C on `taut watch`, MCP write errors, TUI live following, and Summon's local test lane. Nine distinct P1s across ~45k product lines is not a crisis, but the P1s cluster exactly where the README leads.

| Element | Grade | One-line basis |
|---|---|---|
| Core code (client, state, identity, commands, persistence, search) | B | Spec-traceable and disciplined; two P1s in the identity heuristic; library raises on empty |
| Core tests | B+ | Real SQLite/subprocess proofs; harness forces UTF-8 and hides a real defect; one env-dependent gate |
| Watcher / reactor / SimpleBroker coupling | B- code, B tests | Measured well; SIGINT override of SimpleBroker's safe handler causes exit 1; spec names a knob taut ignores |
| Summon | B- (code B, detach diff B, tests C+) | Ears/mouth/ledger/dismiss work live; PTY never becomes controlling tty; default live lane spends quota and cannot pass |
| MCP | B (code B, tool design B-, tests B) | Both wire eras work; `say` to a missing channel is a success; two spec-required gates missing |
| TUI | C+ (code B-, UX C, tests B-) | Boundaries clean; tail un-pins after own send; raw 19-digit ids in the time column; false rapid-resize test |
| CLI robustness | B+ | No tracebacks; exit codes mostly truthful; storage discovery misreports unusable files |
| Agent-facing docs (kernel/README recipes) | C+ | Polling recipe advances the bookmark silently; session-start recipe spams; suffix guidance rests on a false premise |
| Release / CI / packaging | B- (helper B, workflows B-, packaging A, tests C+) | Guarantees verified; 5× duplicated gate workflow; PyPI postflight fails falsely; 16/22 workflow tests are YAML change detectors |
| Docs / program theory / process | B (theory B+, specs B+, plans+review B, lessons+coalescing C+, gates B-) | A-records demonstrably stop re-litigation in plans; reviewers never receive them; plan-tier coalescing cannot converge |

## Method

- Ran all five suites on the current tree: core (1,462 tests) green except one environment-caused failure I created; Summon (478, live Kimi lane included), MCP (183), TUI (277) green. PG not run (Docker available; out of time budget).
- Used taut as the coordination bus for the review (see §6). All reviewer access to the shared workspace was through `taut --as <Facet>`; the only SimpleBroker CLI use (six `broker list` calls) was against a reviewer's own scratch database, so no consuming `broker read` touched shared history. `taut read` peeks; only `inbox` consumes.
- Nine Opus reviewers, each with the same brief: verify by execution, check theory/plan rationale before calling anything a defect, propose supported alternatives, grade.
- Lead re-ran: identity PATH and nested-agent repros; `read` under cp1252 and broken pipe; `read -q` loop; repeated join notices; id low-bit layout; code-span mention; MCP exception hierarchy; TUI dead-code test and tail-pin trace; Summon spawn path; spec/launch/regex line checks.

## 1. Verified P1 defects (9)

Each entry: claim → evidence → theory/plan check → better design.

**1. A nested agent is captured by its ancestor's identity** (`taut/identity.py:354-371` `match_anchor`; `taut/client/_identity.py:250-300`).
- Lead repro: from a `Claude` shell, a child process named `codex` runs `taut join general` → "Claude joined". `join --new` creates `Codex`, but the next `whoami` from that same child still says `Claude`; `who` shows `Codex … gone`. [IAN-3.3] step 4 matches stored anchors against *every* process in the chain, so the first selector-free command a child runs binds its claim to the parent.
- Theory check: [IAN-3.3]'s step-4 rationale covers the *same* anchor changing cwd/tty/pgid, not ancestors. No test covers a match above the selected anchor. [TAUT-10]'s "two members in one ancestor chain" becomes unreachable on first contact.
- Better: heal only when the stored triple equals `capture.anchor` itself. An ancestor-only match selects the parent for the current op *without recording a claim*, and `whoami --explain` names the rule ("ancestor anchor match"). Tools launched by an agent still speak as the agent; a nested agent can `join --new`/`rejoin` its own member. Cost: one extra `list_members` scan on a claim miss, which already happens.

**2. macOS host id depends on ambient PATH** (`taut/identity.py:132-164`).
- Lead repro: `taut whoami` → `Claude`; `env PATH=/usr/bin:/bin taut whoami` → "unrecognized caller … reclaim with 'taut rejoin Claude'". Bare `ioreg` (lives in `/usr/sbin`) fails silently → `hostname:` fallback → different claim hash. A cron job or a launchd agent would create a duplicate member.
- Theory check: THEORY-2 says the claim is "deterministic"; [TAUT-10] says host_id is opaque because hostnames drift. The fallback is tested as intended (`test_capture_host_identity_falls_back_to_hostname`) but specified nowhere.
- Better: absolute `/usr/sbin/ioreg`, or read the platform UUID without a subprocess; never switch namespaces silently.

**3. Ctrl-C on a busy `taut watch` exits 1 with tracebacks** (`taut/watcher.py:1820-1828`; `taut/commands/watch.py:72-76`; SimpleBroker `_broker_session.py:278`).
- Found independently by CoreTests and Reactor. Reproduced 6/60 and 3/60 under a writer thread; 0/80 idle. `_sigint_handler` raises `KeyboardInterrupt` wherever the main thread is; when that is inside SimpleBroker's operation bookkeeping the session keeps an open operation; `watch.py` returns 0 but its `finally: watcher.stop()` raises `_ActiveOperationCloseError` → rendered error, exit 1, four `.taut.db` handles still open. This is the "flaky" `test_cli_watch_json_flushes_records_while_live`.
- Theory check: [TAUT-8.5] keeps an "immediate `KeyboardInterrupt` outside waiter replacement". The restoration plan's reviewer (finding P2-1, line ~1806) traced it as safe because "unwind reaches `stop()`" — it does, but `stop()` cannot close. SimpleBroker's own `BaseWatcher._sigint_handler` and Summon's `_on_signal` only set a flag, precisely to avoid this.
- Better: flag + `strategy.notify_activity()`, break at the loop boundary, raise after cleanup (Reactor's scratch patch: 180/180 clean vs 9/120 failures). Second Ctrl-C raises immediately. Two tests pinning the immediate raise need rewriting. Also declare the interrupted-watch exit code in [TAUT-8.1] (today it is 0, 1, or 130 by timing).

**4. `taut read` advances the cursor before the output is written** (`taut/commands/read.py:31-32`).
- Lead repro: `PYTHONIOENCODING=cp1252 taut --as bob read general --json` on a message with 🙂 → exit 1, nothing on stdout; next `read` → "nothing unread". Same with `read --json | head -c 0` (BrokenPipe): the reader's bookmark has advanced past the messages; they remain in history (`log`) but a `read`-driven agent never sees them. Windows pipes default to the ANSI code page, so agents reading taut through pipes on Windows hit this without doing anything wrong. The CLI harness forces `PYTHONIOENCODING=utf-8` on every subprocess test (`tests/conftest.py:448`), which is exactly testing-patterns Pattern 7.
- Theory check: [TAUT-7.2] says `read` advances "as they display"; `watch` already refuses to advance on a broken pipe; `read` has no equivalent.
- Better: advance only through records actually written (matches the watch rule), or reconfigure stdout UTF-8 with `errors="backslashreplace"` at the CLI entry; add a companion test without the forced encoding.

**5. The kernel's polling recipe advances the bookmark past messages unseen** (`docs/agent-kernel.md:23`, `README.md:597`, `02-taut-core.md:1251`).
- Lead repro: `taut -q read` → exit 0, prints nothing; `taut read` → "nothing unread". The documented `taut read -q && process_inbox` loop marks everything read before `process_inbox` runs.
- Better: `taut list -q` already has the wanted semantics (exit 0 iff unread, cursor untouched; lead verified). Doc-only fix in three places. This is the highest-leverage fix in the report.

**6. MCP `say` to a missing channel/`@name` returns `isError:false, {"records":[]}`** (`extensions/taut_mcp/taut_mcp/_workspace_reactor.py:357`).
- Lead code check: `NotFoundError(EmptyResultError)`; `_commands.py:66-69` re-raises for non-DM targets; the reactor's `except EmptyResultError: pass` swallows it. Spec [MCP-5]/[MCP-6] say only an exact `dm.d_*` miss is content-free. `test_say_normalizes_only_exact_stable_dm_not_found` is a false test: it checks the command layer with a spy and never reaches the reactor that undoes it.
- Better: catch `NotFoundError` before `EmptyResultError` in `_execute_command` for mutating tools and map to `command_error`; extend the same to `reply`/`leave`/`channel_rename` (P2), keeping content-free empties only for privacy-bearing lookups.

**7. Summon's default local live lane spends real model quota and cannot pass** (`extensions/taut_summon/tests/test_live_harness.py:70-77, 242`; `_driver.py:1223-1226`).
- Each run makes a fresh unwired DB; the driver marks `awaiting_onboarding` and still injects the orientation prompt (a real model turn in every installed CLI — seven here); the test then skips on `awaiting_onboarding`. Lead's full-suite run launched a live `kimi` session. README documents "local runs attempt by default" but not that it costs a turn and can only skip or time out.
- Better: make local default opt-in like CI, keep strict mode as the smoke test; or skip before spawning when the DB is unwired.

**8. TUI transcript stops following after your own send, and after one resize** (`extensions/taut_tui/taut_tui/app.py:543, 3251`).
- Lead ran the reviewer's trace: after send, the watcher's duplicate delivery calls `_capture_scroll_anchor` while `scroll_end` is pending; `scroll_y=176 max=178` → `tail_pinned=False`. Reproduced 6/7 (send) and 5/5 (resize). [TUI-9.2] says a tail-pinned view stays pinned. The 2026-08-18 lesson says capture on *leaving*, never on arrival.
- Better: make tail-pin sticky, cleared only by user scroll intent (`_on_transcript_user_viewport_intent` exists); extract a named `TranscriptViewport` state machine with contract tests (engineering-principles §14 floor 2; same extraction the doc already endorses for `MultiQueueWatcher`).

**9. The TUI rapid-resize test is dead code** (`extensions/taut_tui/tests/test_tui_resize.py:231`; `layout.py:206`).
- Lead grep: `plan_latest_resize` has no production caller; `layout_passes` is a constant default of 1. The 2026-08-12 plan (lines 683–690) required an app-level burst test and is marked completed.
- Better: delete both; add a real `run_test` burst (119→79→49→80 cols) during a live delivery, asserting one final render and tail still pinned.

## 2. Notable P2s (verified)

- **Summon PTY is never the child's controlling terminal** (`_pty_posix.py:44-62`, `_process_domain_posix.py:76`; no `TIOCSCTTY`/`login_tty` anywhere, lead grep). `kill -9` on the driver leaves the provider alive with PPID 1 and `status` says "nothing summoned"; a resummon needs no `--takeover`, so two processes can hold one `TAUT_TOKEN`. Reviewer verified an exec-trampoline with `TIOCSCTTY` fixes it. [SUM-11] is silent on provider survival — spec gap.
- **Leaked fixture process** on this machine: PID 70100, `fake_tui.py`, running since Sep 16 11:53 (`PYTEST_CURRENT_TEST=tests/test_pty_adapter.py::test_interrupt_unblocks_full_pty_input_queue`). Cause: `_spawn_fake` has no finalizer, the test closes only on the happy path, and without a controlling tty nothing sends SIGHUP. Not killed; owner's call.
- **Re-joining writes a new "X joined" notice every time** (lead repro: four consecutive notices). The kernel's session-start recipe therefore spams every channel and trips every other agent's unread. Fix: joining a channel you are in is a silent success.
- **Reply suffix entropy is 625, not 10,000**: message ids are multiples of 4096 (SimpleBroker's 12 counter bits; lead verified `ts % 4096 == 0` on five consecutive ids), so a 4-digit suffix has 625 values; ~80% ambiguous in a 1,000-message window; a stale suffix can silently resolve to the wrong recent message (reviewer repro). README "the last few digits vary" is false. Fix: human `reply` echoes the resolved parent; recommend 7+ digits; correct README and kernel.
- **Mentions fire from inert text**: `` `@bob` `` in a code span sends a real mention (lead repro). [IAN-5.2] states no rule; this is the runbook's own grammar-mimicry floor with no probe.
- **Unusable `.taut.db` reported as missing**: `chmod 444` or a foreign SQLite file → "No taut database found. Run 'taut init'" → `init` says `exists:`. Agents loop. SimpleBroker's `is_valid_database` collapses the precise error to `False`.
- **taut installs its schema into any existing SQLite file** even on a read-only command (`taut --db app.db log general`). One `sqlite_master` probe would refuse files with neither broker nor taut tables.
- **`taut tui` exits 0 after a fatal Textual crash** (`_launch.py:47`, lead confirmed `return 0`); `test_tui_launch.py:403-405` pins `result == 0` while `app.return_code == 1`.
- **Spec names a knob taut ignores**: [TAUT-8.5] line 1728 says `BROKER_MAX_INTERVAL` is the tuning knob; taut reads the `TAUT` prefix (`_config.py:39`). Measured: no effect. Even `TAUT_MAX_INTERVAL` barely helps because SimpleBroker rechecks `data_version` every 20 ms chunk. Idle SQLite watcher ≈ 1% CPU, 63 queries/s; no doc sets an idle budget.
- **MCP**: no firing test for "workspace directory identity unavailable" ([MCP-12]); no oversized-frame probe ([MCP-10] claims one); `--claude-channel` wakes the agent on its own `inbox` consumption.
- **CLI harness** forces `PYTHONIOENCODING=utf-8` (Pattern 7) and `run_cli` strips stdout/stderr, hiding whitespace contracts.
- **Exit-class contradictions**: short/malformed reply suffix exits 2 (spec [TAUT-8.1] says malformed → 1, "never 2"), pinned by `test_cli_reply_too_short_suffix…`; `message react` with no audience exits 2 silently (only blank `say` is specified silent). `channel rename` exit 2 has no firing test.
- **Release**: `test_pg_lockfile_is_not_retained_and_is_ignored` asserts an *ignored* file is absent from disk; any `uv run` in `extensions/taut_pg` (including mine) fails a release gate. Rationale (v0.5.2 plan) is "not committed"; assert `git ls-files` instead. PyPI postflight (80 s budget) failed falsely on 0.9.8 and 0.9.0; the 0.9.8 recurrence is unrecorded. Five gate workflows are byte-identical except four literals (~740 duplicated lines).
- **Docs gates**: `CITATION_RE` (`tests/test_docs_references.py:66`, lead confirmed) accepts only `N` or `N.N`, so `[DOM-10.2.1]` on 210 noqa lines is unchecked; the retired-plan ledger SHAs are ungated (a `deadbee` SHA passes); DOM-15 fixture negative-trigger check is a substring match.

## 3. Design defects with supported alternatives

These are not bugs in the code so much as places the design or the process produced the wrong shape. Each has a supported alternative.

**A. Selector-free identity heals too eagerly.** Three verbs that should be read-only (`whoami`, `who`, `list`) write claims (claim count 1→4 across nested reads; [IAN-10] says `whoami --explain` captures "without silently associating", and a test asserts the opposite). Combined with P1-1 this makes the "identity trick" non-idempotent. Alternative: name the resolution modes (read-only / non-healing / full) as a small policy object replacing the seven-flag `_resolve_member` (complexity 43, `[RUFF-SUP-047]`), give every read verb the read-only mode, and record a claim only on `join`/`say`/`rejoin`. Cost: one refactor inside one function; the suppression registry's own "rejected alternative" clause already names this design.

**B. The CLI `read` adapter commits the bookmark before rendering.** Correction after the lead re-checked the read model: `read` advancing the *reader's own* per-member bookmark is [TAUT-7.2] working as specified; no reviewer's `read` affected any other member (lead evidence: after all nine reviewers read `#findings`, `Claude` still showed 54 unread, `Probe` 12, `TUI` 10, and `log` returned all 80 records). What is defective is narrower: `taut/commands/read.py` calls `read_unread` (which commits the cursor) before `emit_messages`, so a broken pipe or an encoding failure loses messages for that reader (P1-4), and the documented `read -q` poll advances the bookmark while printing nothing (P1-5). `inbox` claiming pointers is A1 and deliberate; the `inbox | head` trap is the same commit-before-render ordering. Alternative: render-then-advance in `read` (already the `watch` rule), and document `list -q` as the poll. A1 and the single-directory model are untouched.

**C. MCP normalizes not-found into empty success for mutating tools.** [MCP-6]'s general rule and [MCP-5]'s `say` exception pull in opposite directions; the code follows neither. Alternative: content-free empties only for privacy-bearing lookups (DM handles, exact ids, read/log); mutating tools surface core's `NotFoundError` text as `isError`. Fits THEORY-4.1 and the agent-interface runbook's "every error carries its action".

**D. Immediate `KeyboardInterrupt` in the reactor.** SimpleBroker, Weft's copy, and Summon all flag-and-drain; taut alone raises in place. The restoration plan kept it "may remain" with no stated reason and its reviewer's safety trace was wrong. Alternative in P1-3; the plan-review process should have caught this and did not, which is a process finding (see §4).

**E. Reply-suffix addressing over a counter-padded id space.** The README's mental model ("last few digits vary") is false for SimpleBroker's hybrid timestamps. Alternative: derive the shortest-unique suffix at render time (the inbox already prints one), document 7+ digits, and echo the resolved parent on `reply`.

**F. Summon's process domain without a controlling tty.** `start_new_session=True` + a pre-opened slave gives a session with no controlling terminal, so the OS never delivers SIGHUP. Alternative: `os.login_tty` / `TIOCSCTTY` in an exec trampoline (thread-safe, unlike `preexec_fn`); `escape_domain` providers unaffected. [SUM-11] should state whether driver death must kill the provider.

**G. TUI scroll-anchor as an unnamed state machine** — P1-8/9; alternative given there. This one already produced a regression (`620fbe3` → `d7fc067`) and the current P1, which is the §14 floor-2 failure mode the repo's own doc predicts.

**H. Release machinery proportion.** ~10k lines of tooling + ~14k lines of tests of tooling for a 5-package project. The guarantees (exact tested bytes, single build, immutable release, exact-SHA evidence) are real and worth keeping. Lighter shape with the same guarantees: one tag-triggered gate workflow mapping tag prefix → package (upload stays top-level, satisfying the plan's rationale); drop version-metadata reconciliation in favor of `importlib.metadata`; widen the PyPI postflight to ~5 min. Loss: per-package Actions run lists; one-time re-registration of four Trusted Publishers.

## 4. Does the project theory do its job?

The owner's premise — heavyweight docs whose friction stops locally-optimal but globally-wrong changes — was tested empirically by the Theory reviewer and mostly holds:

- **The A-records work inside plans.** A6 is cited *proactively* in five later plans before anyone re-proposes census/quiescence hardening; A1/A3 disposed an external "tokens are secrets" finding in one table row (command-runtime plan line 31). The mechanism does exactly what it was built for.
- **They don't reach reviewers.** All six A-records were written after a *human* caught the re-proposal, twice after an independent reviewer had pushed the rejected design through (A2: reviewer F1 accepted, promoted, owner-reversed same day; 08-24 R2). Neither `skills/call-agent` nor the review-loops runbook mentions program theory (grep: 0 hits). The people most likely to re-litigate are the only ones never handed the records. Fix: a "rejected alternatives in force" bracket in the review-brief template.
- **Review is real, not a rubber stamp**: 26 of 48 first verdicts were non-PASS; 13 plans had a P1; 6/6 spot-checked findings landed. But this review found two cases where a reviewer's reasoning was wrong and accepted (SIGINT safety trace; TUI rapid-resize "completed" with a dead test), and one where the rationale was right and the code broke it anyway (MCP say-miss). Findings-are-claims (engineering-principles §8) applies to the review log itself.
- **Coalescing cannot converge at the plan tier**: eligible backlog 48→58→66→91→103→99 against a threshold of 8; ~9 plans/week in, ~2.5/week retired. Recorded only as "checked-deferred". Alternative: retire at completion (author writes the ledger line at the completion commit). Loss: the later independent harvest audit.
- **Cost**: fixed startup floor ≈ 15.6k tokens; a planning task ≈ 100k tokens before code. Tracked Markdown is 6.5 MB vs ~1.5 MB of product code. Most of it earns its keep (registry, stable codes + citation gate, A-records). Mostly ceremony: the Ruff suppression registry (228 directives, 132 BLE001, approvals batched 32+14 under two strings) and paragraph-length coalescing run-log lines.
- **Where unclarity is a theory failure** (each named by the doc that should answer it): Ctrl-C exit code for `watch` ([TAUT-8.1]); whether `read` may advance before rendering ([TAUT-7.2]); whether tools an agent launches speak as the agent ([IAN-3.3]); host-id derivation and fallback ([IAN-3.2]); mentions inside code ([IAN-5.2]); rejoin-as-no-op ([TAUT-8.1] join row); MCP's list of content-free tools ([MCP-6]); provider survival on driver death ([SUM-11]); `tui` process exit code ([TUI-12.1]); README typo class and dependency-floor class ([DOM-15] fixtures); idle-CPU budget for a follower ([TAUT-8.5]/THEORY-3).

## 5. Test quality across the repo

- **Core (B+)**: 1,462 tests; 0/40 sampled false; 14/14 mutations caught; mocks at OS/network/git/fault seams; no elapsed-time non-occurrence proofs; three enumerable contracts fully fire. Defects: harness Pattern 7 (forced UTF-8), one env-dependent release gate, two tests pinning spec-contradicting exit classes, 244 monkeypatches in `test_release_script.py`. Product vs process split: 75% / 22% / 3% packaging, judged proportionate.
- **Reactor (B)**: 44/111 real-SQLite; 3/3 mutants killed; SIGINT tests never deliver the signal inside broker I/O (where the P1 lives); 128 private-attribute accesses.
- **Summon (C+)**: no mock library; real PTY and real-process driver harness; 7/9 detach-diff mutants killed (survivors: Windows deadline composition, atom-deadline retention); live lane P1; no happy-path-only teardown; 37 process-wide stdlib patch sites; `test_posix_attach_routes_ambiguity_deadline_through_select` patches `os.read/os.write/select.select` globally (the 2026-09-03 lesson's exact hazard).
- **MCP (B)**: all 21 tools schema-validated through real stdio; one false test; two spec-required gates missing; 62 mocks in `test_process_reactor.py` at ordering seams.
- **TUI (B-)**: real Textual/SQLite/PTY; one false test; no real-app tail-pin test; ~80 attempt-counted polling loops (~1 s), the exact pattern the 2026-08-14 lesson rejects and the likely cause of the unresolved Windows S4 blocker (reviewer could not reproduce on macOS at 6× oversubscription; proposes closing S4 on retained instrumentation rather than blocking release indefinitely).
- **Release/CI (C+)**: observer and publication state-machine tests are behavioral; 16/22 workflow tests are YAML substring detectors; tag/push never exercised against a real remote.
- **Uncommitted detach diff**: red at HEAD (26 adapter + 3 Windows tests fail), green on tree, ruff clean; grammar matches [SUM-7.4]; deadline folded into `select()`/chunk wait, no timer thread; fresh matcher per attach. One undocumented behavior change: a lone legacy ESC is now held ≤100 ms and coalesced with the next key (`ESC`,`x` → `b"\x1bx"`, which TUIs read as Alt+x) — needs a documented trade-off or forward-lone-ESC-immediately. One surviving mutant worth a test: first enhanced atom held past 100 ms still detaches on the second.

## 6. Taut as a coordination tool (the live trial)

Ten members (lead + nine reviewers) on one SQLite file for ~35 minutes; 48 findings posts; a 4-minute `taut watch --json` follower; DMs, threads, search, doctor, dump all used. **Zero errors, zero lock contention, zero lost messages.** That is the product's core promise and it held.

What every reviewer independently reported as friction, in frequency order:
1. `read --json` to "check for questions" moved each reviewer's own bookmark, so a second `read` showed nothing and they had to switch to `log` (9/9). That is [TAUT-7.2] working as specified, not a defect; the brief should have said `log`. The real defect nearby is design defect B (commit-before-render).
2. `join` prints the continuity token to the terminal (7/9). Not a secret per A3, but it lands in shared logs; consider `--quiet` suppressing it or printing to stderr only (it already goes to stderr; reviewers were capturing both).
3. `say` succeeds silently (6/9). Scripts like it; humans and agents wanted a message id back. `--json` on `say` returning the record would satisfy both.
4. `inbox`/`read` exit 2 on empty breaks `&&` chains and `set -e` (6/9). Documented; expected once learned.
5. Every reviewer showed `here` because all share one anchor process, and without `--as` they would all have been the same member. Inherent, but no doc names in-process subagents as a case requiring `--as`/tokens. One sentence in the kernel would fix it.
6. Own posts come back as unread in a busy channel ([TAUT-7.4], deliberate) — noisy but harmless.

Summon product trial (scripted provider): summon → injection `[#general] alice: …` → reply via mouth with `TAUT_TOKEN` → `dismiss` clean. Works as specified. MCP trial: both wire eras, 21 tools, manifest 20,514 B, commit→resource-update 2–25 ms, EOF exit 0 in 0.12 s with all DB fds closed.

## 7. Things that looked wrong but are deliberate (and where it says so)

Consumable notification pointers (A1); no auth, token not a secret, tokens in tracebacks (A3, [MCP-10], [TAUT-13.3.1]); dump permits writers while load requires quiescence (A6, [PIO]); cursor advance last and best-effort, own posts can reappear (A5, [TAUT-7.4]); exit 2 merges empty and not-found (README); blank `say` silent exit 2 ([TAUT-6.5]); unknown `.taut.toml` keys ignored ([TAUT-3.2]); escape policy is C0/C1 only, RTL passes ([TAUT-6.4]); channel names lowercase-only ([TAUT-4.1]); `--as` beats token silently ([IAN-3.3]); FTS syntax treated as words ([SRCH]); doctor "healthy" after `messages` dropped ([DOCT-2.5]); whole-class Weft vendoring with stale docstrings ([TAUT-12.3], lead verified digest script matches); MCP rate bucket (plan-required, 15 lines); Summon setup-gate recovery (recorded Kimi incident, behavioral, opt-out); Windows fake-API tests honestly scoped, native qualification recorded as deferred; TUI "retained gate" = retained-lock CI lane, not product code; reusable workflows never publish (plan §5.2); PG extension has no lock (v0.5.2 plan); publish-action pin asserted (lesson 2026-08-11).

## 8. Open questions for the owner

Each of these is unclear in the repo, and each names the doc that should have answered it (§4 last bullet lists the codes).

1. Ctrl-C on `watch`: 0 or 130? And is the immediate-raise rule still wanted?
2. Should `read` ever advance before bytes are written? Should `read -q` exist at all, given `list -q`?
3. Do tools an agent launches speak as the agent (ancestor match) by intent?
4. Should selector-free `whoami`/`who`/`list` persist claims?
5. Mentions inside code spans/fences: parsed or inert?
6. Re-join as silent no-op?
7. MCP: which tools return content-free empties?
8. Must a driver crash kill the provider?
9. Should S4 block release without a reproduction standard or time-box?
10. Should reviewers receive the A-records? If independence from theory is intended, say so.
11. Retire plans at completion, or accept a permanently tripped plan threshold?
12. Idle-CPU budget for an always-on follower?

## Appendix: process leftovers

- PID 70100 (`fake_tui.py`, since Sep 16) is still running; not killed.
- `extensions/taut_pg/uv.lock` created by my `uv run` at 13:53 was removed after the Release reviewer investigated; tree is back to its pre-review state.
- Reviewer scratch artifacts (repro scripts, mutation copies, SVG screenshots, stdio transcripts) are under `<session scratchpad>`.
