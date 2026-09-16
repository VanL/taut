# Reactor Worker Cache Compatibility Repair

Class: 4. Lifecycle repair under the existing contract, without spec revision.

Status: completed. Implemented, verified on both broker versions, independently
reviewed, and recorded in the dedicated compatibility-repair commit.

## Goal and sources

Restore reactor worker cache retirement with SimpleBroker 8.3.0 before the
larger BrokerSession migration. The existing `>=8.2.2` requirement admits the
regression today; the lock alone does not protect fresh installations.

Baseline: `c79b448351f0e0df1276ceefb41cb17dc34f7bf0`.
Sources consulted: `docs/specs/02-taut-core.md` [TAUT-3.4], [TAUT-8.5];
`docs/implementation/04-taut-architecture.md`; SimpleBroker tag `v8.3.0`,
commit `d5d5c81d32f325e27566e936b5ae77fd57259bed`, public Queue cleanup and
watcher stop source plus real SQLite probes against 8.2.2 and 8.3.0; AGENTS,
program theory, decision hierarchy, principles, engineering principles,
testing, writing-plans, hardening, review runbooks, required lessons, agent
inventory, and `skills/call-agent/SKILL.md`.

## Design, invariants, and boundaries

Taut's custom loop bypasses upstream `run()`, so inherited stop follows the
idle path. SimpleBroker 8.3 intentionally stopped recycling the caller cache
on that path. Upstream's release documentation does not explain the implication
for custom-loop subclasses. This repair makes Taut's owner cleanup explicit.

In `BaseReactor._close_reactor_resources`, after closing the strategy and before
closing queue leases, call public `self._queue_obj.cleanup_connections()` only
when `self._drive_thread is threading.current_thread()`. Catch and log ordinary
cleanup failures independently, so queue lease closure still runs. Do not touch
private upstream lifecycle slots. Keep the existing stop/turn/once guards.

Same-key queues share one thread cache: one cleanup suffices. A live peer lease
must survive and remain usable. The cleanup runs after the owner's turn unwinds;
foreign and never-driven stop paths must not acquire this new cache-recycle
behavior. SimpleBroker 8.2.2 may also recycle through inherited stop; repetition
is safe. No process registry, session handle, dependency bump, or host changes.

## Tasks and proof

1. Independently review this plan before changing runtime code.
2. Add a real SQLite regression: hold a same-key peer, retire three workers,
   assert the peer's sole caller cache remains after every joined worker, and
   prove peer read/write remains usable. Observe private core counts only in
   tests; do not mock the broker. Run red on 8.3.0 and green on 8.2.2.
3. Apply the owner-only cleanup. Run the regression and watcher suite on both
   versions. Exercise cleanup failure and existing foreign/active-turn stop tests;
   inspect the never-driven guard (`_drive_thread is None`) explicitly.
4. Update implementation rationale and changelog, independently review the
   scoped diff, run document gates, and commit this repair separately.

## Rollout, rollback, and exclusions

This is a prerequisite to the BrokerSession plan, which later replaces this
queue-based cleanup with explicit scope recycling. Publish through the normal
release process separately; a local commit cannot protect users installing an
older published Taut artifact. Success signal: no retired worker cores accumulate
while a peer remains live. Reverting restores the 8.3 leak; a release rollback
must also select SimpleBroker below 8.3 until a corrected Taut build ships.
Client-worker retention and full session ownership remain integration-plan work.

## Review and verification

Preimplementation review: Claude 2.1.207, read-only invocation under the
verified `call-agent` procedure, returned PASS. Findings reproduced below.

| Finding | Disposition |
|---------|-------------|
| Test already exists at baseline | Incorrect baseline inference: the reviewer read the newly added working-tree test while the independent plan review ran. It is absent from `c79b448`; no duplicate test was added. |
| Tolerate unexpected primary-queue cleanup errors | Covered by the planned independent `except Exception` around public cleanup, including attribute access. Real failure test proves remaining lease closure. No optional-queue abstraction needed. |

Red evidence: isolated SimpleBroker 8.3.0 regression failed with 2 cores after
the first worker exit (expected 1); the same test passed on 8.2.2. The cleanup
failure test also failed before implementation because no recycle attempt was
logged. Tests were written while plan review ran; runtime edits began after PASS.

### Preimplementation review, verbatim

Write isn't available in this context, so here is the review directly.

# Preimplementation Review — Reactor Worker Cache Compatibility Repair

**Verdict: PASS.** Scope is decided and the design is hardened enough to implement. Two [P2] findings; no [P1] blockers.

Reviewed at baseline c79b448: the appended plan; `taut/watcher.py` `BaseReactor.stop` / `_close_reactor_resources` / `run`; and the relevant `tests/test_watcher.py` lifecycle tests. Accepted risks taken as given.

## What the design gets right (verified against code)

- **Insertion point is correct.** Normal owner exit already routes through `run_until_stopped`/`run_forever` finally → `stop(join=False)` → `_close_reactor_resources` **on the owner thread** (`watcher.py:1091-1094`, `1109-1117`, `1231-1241`). Placing `self._queue_obj.cleanup_connections()` there, guarded by `self._drive_thread is threading.current_thread()`, recycles the worker-thread core in the shared session while leaving a peer's main-thread core intact.
- **The owner-only guard is genuinely exclusive.** Foreign `stop()` returns early while the owner is alive (`watcher.py:1222-1227`); a never-driven reactor has `_drive_thread is None`, so the guard is False and the recycle is correctly skipped — matching the plan's stated exclusions.
- **Idempotent and correctly ordered.** `_close_reactor_resources` runs at most once behind the `_resources_closed` gate (`watcher.py:1231-1234`). Order strategy-close → cleanup_connections → queue `close()` is sound: cleanup retains leases, `close()` ends them.
- **`_queue_obj` sharing the peer session is a real, tested invariant** (`tests/test_watcher.py:809`), so the chosen handle is valid.

## Findings

**[P2] Task 2's regression test already exists at baseline — don't re-add it.** `tests/test_watcher.py:784 test_base_reactor_retirement_recycles_worker_cache_with_live_peer` already holds a same-key peer, retires three background workers, asserts the sole caller core survives each join (`len(session._cores) == 1`), and proves peer read/write (final `peer.read` == `["seed","0","1","2"]`). It is green on the installed 8.2.2 and would go red on 8.3.0 without the fix — exactly the plan's red/green intent. *Disposition:* reframe Task 2 to "reuse the existing regression"; confine genuinely-new test work to Task 3's two additions (cleanup-failure isolation, foreign/never-driven guard assertions). Removes redundant work.

**[P2] Harden the new block against an absent/already-closed `_queue_obj`.** The existing close loop catches `(BrokerError, OSError, RuntimeError)` (`watcher.py:1186`), and `super().stop(join=False)` runs *before* `_close_reactor_resources` (`watcher.py:1237`). If inherited stop ever ends `_queue_obj`'s lease, the subsequent `cleanup_connections()` could raise outside that tuple. *Disposition:* in the new independent try/except, tolerate a missing `_queue_obj` and catch at least the same exception tuple, so queue-lease closure still runs — this is what makes the plan's "log ordinary cleanup failures independently" real.

## Out-of-scope observations (not blockers, not worsened)

- The `simplebroker>=8.2.2` floor (`pyproject.toml:34`) still admits 8.3.0 on fresh installs, so which version detects the regression depends on what's installed (currently 8.2.2). The plan explicitly accepts "no dependency bump" and defers the durable fix to publication + BrokerSession. Only note: the guard is meaningful long-term if the suite runs against **both** 8.2.2 and 8.3.0 as a standing matrix, not Task 3's one-off run.
- The proposed guard reads `_drive_thread` without `_drive_owner_lock`, unlike other readers (`watcher.py:848`). The value is stable inside the single-shot close gate, so acceptable — noted only for consistency.


### Completion review and disposition

The plan-file write tool isn't enabled in this review context (only read/search tools are), so I can't persist the file — but the review itself is complete and delivered above.

**Summary verdict: PASS — no blocker.** One [P2] stylistic note (lock-free read of `self._drive_thread` at `watcher.py:1176`, benign). The owner-thread guard, ordering, and error isolation are correct, and both new tests are genuine matched proofs of the 8.3 regression and the cleanup-error isolation.

Disposition: no lock change. `_drive_thread` is stable once the owner claims
the reactor and reaches the single-shot cleanup boundary; stop already checks
live-owner and starting-thread state under `_drive_owner_lock`. The review's
benign lock-free-read observation does not justify another synchronization path.
After the review snapshot, explicit non-None assertions were added to the test
observers for type narrowing; both new tests passed again on both versions.

### Verification evidence

- `.venv/bin/python -m pytest tests/test_watcher.py -n 0 -q`: 95 passed on
  SimpleBroker 8.2.2. Same command under the isolated 8.3.0 environment: 95 passed.
- Isolated 8.3.0 `python -m pytest extensions/taut_summon/tests/test_control.py
  extensions/taut_summon/tests/test_controller.py
  extensions/taut_summon/tests/test_driver.py -n 0 -q`: 248 passed.
- `python -m pytest tests/test_docs_references.py -n 0 -q`: 12 passed.
- Ruff check and format check for `taut/watcher.py` and `tests/test_watcher.py`
  passed. Mypy on `taut/watcher.py` passed. Mypy on the test file has one
  pre-existing incompatible `TautClient` argument in the intentionally rejected
  direct `TautWatcher` constructor test; independently reproduced from HEAD's
  test file (baseline line 2960). No new type errors remain.
- `bin/check-doc-paths`, `bin/check-plan-status-index`,
  `bin/check-dom15-fixtures`, and `git diff --check` passed.
- Existing active-turn/foreign-stop and exception-finalization tests passed
  in both watcher runs. Inspection confirms never-driven `_drive_thread=None`
  skips the added block. The real peer test keeps resources alive throughout
  three owner exits; no mocked broker lifetime stands in for reclamation.

Changed surfaces: reactor cleanup, two regression tests, Unreleased changelog,
architecture rationale, core-spec plan backlink, this plan and its index row.
No dependency or package versions changed. No PostgreSQL run or publication is
claimed. Persistent-client worker retention remains separate integration work.
The call-agent skill was evaluated; no workflow change is warranted.
