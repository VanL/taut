# MCP rate prose and static-proof correction

Date: 2026-09-28
Class: 5+P. This corrects normative [MCP-*] prose and materially tightens a
workflow verification gate; neither change alters shipped product behavior.
Plan type: spec-authoring clarification plus test correction.
Hardening: N/A — no risky trigger. No public behavior, persistence, rollout,
or runtime lifecycle changes.
Lifecycle status: `docs/plans/README.md` is authoritative.

## Goal

Remove stale MCP rate-charging claims after the bucket's removal, replace a
Textual-private-source assertion with retained behavior proof, and make the
root static-coverage gate reject conditional Ruff/mypy checks. Leave bounded
history reads and TUI notification-burst work outside this change.

## Source Documents and Baseline

- Baseline `bda67a1`: `docs/specs/05-taut-mcp.md` [MCP-2], [MCP-3],
  [MCP-10]–[MCP-12]; `docs/specs/10-taut-tui.md` [TUI-8.2];
  `docs/specs/01-development-documentation-operating-model.md` [DOM-15].
- `docs/program-theory.md` [THEORY-1]–[THEORY-5], especially the no-auth
  and no-required-daemon alternatives [THEORY-5.A3] and [THEORY-5.A4].
- `docs/implementation/07-taut-mcp-architecture.md`,
  `extensions/taut_mcp/taut_mcp/_process_reactor.py`,
  `tests/test_github_workflows.py`, `.github/workflows/test.yml`,
  `extensions/taut_tui/tests/test_tui_textual_contract.py`, and
  `extensions/taut_tui/tests/test_tui_selection.py`.
- Owner direction in this chat: defer history-read optimization; require
  evidence before TUI burst coalescing; fix MCP prose and both brittle tests.

## Context, Invariants, and Scope

The master MCP reactor no longer owns a process request-rate bucket, and
[MCP-10] says so. Five older spec claims remain: [MCP-2] `rate state`, [MCP-3]
`rate charging`, [MCP-11] `rate` in process-local state, and two [MCP-12]
mentions of rate charge or token non-refund. Four architecture-note phrases
also remain. This task removes those claims only; the busy slot, resident cap,
schema validation, SDK framing, and tool response shape stay unchanged.

The root lint job is currently unconditional. Its test parses Ruff formatting
and mypy paths and rejects `continue-on-error` and shell failure masking, but
ignores a job or counted check-step `if`. This gate should require those
coverage-bearing checks to be unconditional, not interpret GitHub Actions
expressions or govern unrelated future lint steps. The workflow itself needs
no change.

The Textual test's `inspect.getsource` assertions pin private method text.
Keep its public/property and real OSC 52 checks, and use the existing real
drag, selection, and auto-copy tests as the behavior proof. The private
selection-change callback itself is not promised as a test seam: completion
cancels the prior timer, and the timer rechecks the selected text before copy
(`taut_tui/app.py:1064` and `:1089`). Framework-owned repaint internals are
not a Taut contract. Do not simulate Textual internals or add another
selection framework.

No new Ruff suppression, dependency, product code, compatibility path, or
performance redesign is in scope. If a source edit would require a new
suppression, attempt a refactor and independent judgment before proposing it.

## Proposed Spec Delta

Promotion strategy D: clarification of already-shipped behavior. Apply this
exact wording to the active spec after independent plan/delta review. The
spec baseline is `bda67a1`; record the promotion diff after it exists. No
product code cites a new requirement.

- [MCP-2]: remove `rate state, ` from the process reactor's owner list.
- [MCP-3]: replace `Validation completes before rate charging or semantic
  work.` with `Validation completes before semantic work.`
- [MCP-11]: remove `rate, ` from the process-local state reset list.
- [MCP-12]: replace `before rate charge, registry inspection` with `before
  registry inspection`.
- [MCP-12]: remove `charged-token non-refund; ` from the cancellation proof.

The architecture note removes both `rate state` descriptions, drops `rate`
from the `test_stdio_server.py` ownership row, and removes the obsolete clock
and rate-policy fake advice from its anti-mocking guidance.
No other [MCP-10] rate-limit language changes.

## Dependency-Ordered Tasks and Proof

1. Independent reviewer checks the exact clarification and bounded test-gate
   proposal against the baseline spec, implementation, workflow, and tests.
   Reject proposals that reintroduce a bucket or a generic Actions evaluator.
2. Spec-promotion slice: apply the five [MCP-*] edits; then update the
   implementation note. Inspect all maintained MCP prose for the obsolete
   phrases, and run `tests/test_docs_references.py` and `bin/check-doc-paths`.
3. Extend the existing red mutation test in `tests/test_github_workflows.py`:
   set `if: ${{ false }}` on either the lint job or the Ruff-format/mypy step
   and observe the current coverage assertion erroneously pass. Then reject
   any `if` on the lint job or on a counted Ruff-format/mypy step. Keep actual path,
   exclusion, failure-mask, and `continue-on-error` checks intact. The green
   gate must reject both mutation sites for both tools.
4. Remove only the Textual private-source string/order assertions and their
   now-unused imports; update the test docstring. Retain
   `OptionList.ALLOW_SELECT`, `TextSelected.bubble`, and real OSC 52 behavior
   checks. Run the retained drag/selection/auto-copy tests. Red-green is not
   applicable to the deletion itself: the substitute proof is the real
   behavior suite plus inspection that no `inspect.getsource` pin remains in
   this test.
5. Reconcile spec, plan, implementation note, tests, and workflow; run the
   final gates and a read-only independent implementation review. Record each
   finding's disposition here. Do not commit merely to satisfy a completion
   gate; report the worktree state to the owner.

## Verification

From repository root:

```sh
uv run --extra dev pytest tests/test_github_workflows.py tests/test_docs_references.py -n 0 -q
uv run --project extensions/taut_tui --extra dev pytest extensions/taut_tui/tests/test_tui_textual_contract.py extensions/taut_tui/tests/test_tui_selection.py -n 0 -q
uv run bin/check-doc-paths
uv run bin/check-plan-status-index
git diff --check
```

The root mutation tests must first be observed red and then green. The TUI
tests use real Textual pilot behavior and a captured driver write; they must
not replace selection or clipboard code with mocks. Because no runtime code
changes, there is no deploy or rollback sequencing beyond reverting the
documentation/test correction if its proof is wrong.

## Independent Review and Out of Scope

Use a read-only, different-family reviewer for the plan/delta and completed
change. Provide this plan, baseline, relevant code/tests, and applicable
[THEORY-5] alternatives. Findings are claims to reproduce and disposition;
pre-existing concerns are observations unless worsened. Prefer removal over
new scaffolding. History-read optimization, TUI refresh coalescing, SQLite
search query redesign, and broader CI workflow interpretation are deferred.

## Deviation Log

| Spec ref | Planned behavior | Actual behavior | Rationale | Spec proposal |
|----------|------------------|-----------------|-----------|---------------|

## Review Log

2026-09-28, different-family final implementation review: Claude Opus returned
`no blocker`. F1 nit noted that the job-level Ruff/mypy parameterizations hit
the same guard; accepted and clarified in the execution evidence. F2 nit
suggested more specific exception-text matches; declined because each test
mutates only one owner and the existing `conditional` match proves rejection
without pinning diagnostic prose. F3 P3 requested the plan-index gate and
status update; the gate passed. Status remains active until the repository
commit gate is satisfied. The reviewer found no new suppression, dependency,
product-code change, or [THEORY-5] reconsideration trigger.

2026-09-28, scoped round-2 plan review: Claude Opus returned PASS on the
accepted corrections, with one P3 introduced wording mismatch (`three` edits
after the delta became five). Corrected that task count before promotion.
The optional architecture heading `rate control` remains because its paragraph
now describes the deliberate absence of a bucket; it is not a stale claim.
No [THEORY-5] reconsideration was requested.

2026-09-28, different-family plan/delta review: Claude Opus returned BLOCKED
because the exact delta missed [MCP-11] `rate` and [MCP-12] charged-token
non-refund. Accepted and added both; also accepted the two additional stale
architecture-note phrases, corrected baseline and wording, and removed
now-unused test imports from the task. The reviewer observed that the
Textual selection-change callback has no separate behavioral proof; accepted
as a deliberate non-contract because completion cancels the prior timer and
the copy timer checks the current selected text. The reviewer suggested
rejecting `if` on every lint step. Declined as scope expansion: this gate's
claim is effective Ruff-format/mypy file coverage; it checks the lint job and
the counted steps, while unrelated future steps may be conditional. No
[THEORY-5] reconsideration was requested.

## Execution Log

Plan baseline: `bda67a1`. The spec-promotion slice is the diff from that
baseline to `docs/specs/05-taut-mcp.md` in this change; no product code moved.
The five stale spec claims and four stale architecture-note phrases were
removed or corrected. The root workflow mutation test went red in all four
new `if: ${{ false }}` parameterizations (one job-level guard exercised twice,
plus distinct Ruff/mypy step guards), then green after the two
unconditionality checks. The original four `continue-on-error` cases stayed
green. `tests/test_github_workflows.py` plus
`tests/test_docs_references.py` passed; the focused Textual contract and
selection suites passed. Ruff check/format and mypy passed for both touched
test files; `bin/check-doc-paths` and `git diff --check` passed. No new Ruff
suppression was added. Final review found no blocker, and the plan-index gate
passed. Landing follows the repository's explicit commit gate.
