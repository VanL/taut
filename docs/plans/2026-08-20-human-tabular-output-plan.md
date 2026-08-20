# Human Tabular Output Layering Correction Plan

Date: 2026-08-20

Owner: Taut maintainers

Class: 3 - the audit expanded a spec-conforming bug fix across the core CLI
and the separately packaged Summon CLI, which are distinct major surfaces.

Plan type: implementation against the existing spec; no spec revision.

Hardening: N/A - no [DOM-5] risky trigger fires. This changes neither CLI
grammar nor machine output, persistence, lifecycle, or compatibility shape.

## Goal

Keep trusted tabular separators as real terminal tabs in human `who`,
`whoami`, bare `summon status`, and named Summon status output while applying
the terminal safety policy exactly once to every dynamic field.

## Requested Outcomes

- [x] Reproduce the core `whoami` literal-`\\t` defect with an exact public
  command assertion.
- [x] Correct core member rows and cover both `whoami` and `who`, including a
  control character inside a dynamic persona.
- [x] Correct the two Summon tabular renderers and replace assertions that
  bless escaped structural tabs.
- [x] Audit CLI and TUI output for the same layering defect; record true
  findings and deliberate exceptions.
- [x] Align implementation notes, run focused/full relevant gates, and obtain
  independent completed-work review.

## Source Documents

Source specs:

- `docs/specs/02-taut-core.md` [TAUT-6.4], [TAUT-8.2]
- `docs/specs/04-summon.md` [SUM-3]
- `docs/specs/10-taut-tui.md` [TUI-5.3]
- `docs/specs/01-development-documentation-operating-model.md` [DOM-5],
  [DOM-10], [DOM-11], [DOM-15]

Canonical context consulted: `AGENTS.md`, `docs/program-theory.md`,
`docs/agent-context/{decision-hierarchy,principles,engineering-principles}.md`,
`docs/agent-context/runbooks/{testing-patterns,writing-plans}.md`, both lessons
surfaces required by the startup watermark, and
`docs/implementation/{03-agent-inventory,04-taut-architecture,05-taut-summon-architecture,12-taut-tui}.md`.

## Spec Baseline

- `b4ca0fda9767736bfd81eb08c2dfc1e1d2b03998` -
  `docs/specs/02-taut-core.md` [TAUT-6.4] and
  `docs/specs/04-summon.md` [SUM-3]. These already require dynamic fields to
  be escaped before trusted structural formatting. No spec delta or promotion
  slice is required.

## Context and Key Files

- `taut/commands/_rendering.py::emit_members` owns core member rows. The
  pre-fix code composed real tabs, then sent the whole row through
  `write_human_line`, so the packaged C0 policy converted separators to
  visible `\\t`.
- `extensions/taut_summon/taut_summon/cli.py::_print_live_member` and
  `_print_status` repeat that ordering through their local
  `_write_human_line`. Status details add a variable number of columns.
- `tests/test_command_registry.py` and
  `extensions/taut_summon/tests/test_summon_cli.py` exercise the public command
  paths and currently contain the test-blessed wart.
- `tests/test_cli.py::test_core_human_renderer_inventory_escapes_every_dynamic_model_field`
  and `tests/test_architecture_boundaries.py::test_first_party_terminal_sink_inventory_is_explicit`
  are the enumerable field/sink gates. Update the sink inventory for any new
  reviewed direct write.
- `extensions/taut_tui/taut_tui/widgets.py` intentionally preserves structural
  LF and decodes only message bodies. Search previews and metadata are explicit
  [TUI-5.3] non-decode cases, not targets.

## Invariants and Constraints

- Human layout tabs and renderer-owned LF are trusted structure and remain
  actual `0x09`/`0x0a` bytes.
- Every dynamic field, including extensible Summon detail keys/values, is
  escaped once before composition. Generated escape notation is never rescanned.
- Core `--json` output remains exact and unchanged. Standalone Summon status
  has no JSON mode and this work does not add one; Summon domain values remain
  exact.
- `whoami --explain` remains a valid JSON diagnostic line; its JSON escape
  notation is deliberate and must not be decoded.
- TUI message-body decoding stays scoped to [TUI-5.3]. No stored model value is
  mutated and no search or metadata decoding is added.
- Reuse each package's existing terminal-policy adapter. Do not add a shared
  cross-package formatter for two short rows.

## Deviation Log

| Spec ref | Planned behavior | Actual behavior | Rationale | Spec proposal |
|----------|------------------|-----------------|-----------|---------------|

## Tasks

1. Finish the core red-green slice in `tests/test_command_registry.py` and
   `taut/commands/_rendering.py`: assert exact real separators for both member
   commands and escaped dynamic persona content.
2. Add exact failing Summon command tests for bare and named status output,
   then update `_print_live_member` and `_print_status` to escape fields first
   and compose trusted tabs/LF afterward. Detail key and value safety must fire.
3. Reconcile the reviewed terminal-sink inventory,
   `docs/implementation/04-taut-architecture.md`, and
   `docs/implementation/05-taut-summon-architecture.md`. The Summon note must
   name field-first status rendering and the extensible detail key/value
   boundary. Stop if this requires a generalized output protocol or changes
   machine output.
4. Run focused suites, package static checks, docs/status gates, then request an
   independent fresh-eyes completed-work review and disposition every finding.

## Testing Plan

Use real command dispatch/runners and real terminal policy. Do not mock the
escaping helper. Exact literals must independently distinguish structural tabs
from printable `\\t` and include an unsafe dynamic field. The Summon runner
fixture strips output, so its bare/named status tests prove command rows and
real tabs after stripping; the direct renderer/capture test separately proves
the exact final LF, every dynamic field, and the absence of nonstructural
controls. Update the core and Summon `_assert_only_structural_newlines` gates
to permit and count only the expected structural tabs.
Run:

```text
uv run pytest tests/test_command_registry.py tests/test_cli.py tests/test_architecture_boundaries.py -q
uv run --project extensions/taut_summon pytest extensions/taut_summon/tests/test_summon_cli.py -q
```

## Verification and Gates

Final gates: the focused suites above; repository and Summon Ruff format/check;
relevant mypy scopes if configured by package scripts; `bin/check-plan-status-index`;
`bin/check-doc-paths`; documentation-reference tests; `git diff --check`. Success
means exact real tabs on all four human paths, escaped dynamic controls, unchanged
JSON behavior, and no unreviewed terminal sink. Rollback is a normal source/test
revert; no rollout order or post-deploy state applies. A manual installed CLI
smoke test is optional residual confidence, not a substitute for the real runners.

## Independent Review Loop

Use a review-eligible agent family different from the author when available.
The reviewer reads [TAUT-6.4], this plan, both renderer files, both public command
test files, the sink inventory, and the diff. Required stance: look for dynamic
fields left unescaped, trusted separators rescanned, JSON/TUI contract drift, and
unnecessary abstraction. Findings are appended below with accepted fixes or
explicit rebuttals. A blocker prevents completion.

## Out of Scope

No CLI syntax, alignment policy, JSON schema, TUI decoding expansion, terminal
policy regex change, or broad rewrite of human renderers.

## Execution and Review Log

- 2026-08-20: Class 2 core red test observed the exact failure (`0x09` expected,
  printable `\\t` received). The core slice passed after field-first composition.
- 2026-08-20: Read-only audits found the two Summon analogues. The TUI audit
  found no matching defect and identified search previews/Summon logs as
  deliberate non-message-body cases. Classification escalated to Class 3 before
  editing the Summon surface.
- 2026-08-20: Independent plan review returned BLOCKED: Python 3.11 rejected
  a backslash-bearing f-string expression; the token-leak assertion had been
  weakened; the plan named a nonexistent Summon JSON mode and omitted [SUM-3];
  Summon LF proof was ambiguous because the runner strips output; and the
  Summon architecture target was unnamed. All five findings were accepted.
  The one-write expression was changed to concatenation, the token boundary
  restored by asserting on the actual one-time token value, and the plan
  corrected before re-review.
- 2026-08-20: After correction, Python 3.11.15 collected and passed
  the focused member-rendering test; the plan
  status-index gate also passed.
- 2026-08-20: Review round two correctly rejected the `secret` terminology and
  requested [SUM-3] in the baseline. Both were accepted. Its proposed raw word
  assertion was rebutted with observed evidence: `whoami --explain` captures
  pytest argv, whose node id itself contains `token`. The test now retains the
  domain-correct token name, captures the one-time creation token, and asserts
  that exact value does not reappear. This is stronger and avoids argv noise.
- 2026-08-20: Plan review round three returned PASS. Summon red tests observed
  literal separators under the packaged and project policies; field-first live
  and named status rendering then passed. The real-driver test exposed that
  extensible detail values are JSON primitives, so rendering now preserves the
  prior `str(value)` conversion before escaping; the integration test passed.
- 2026-08-20: Focused core command/CLI/sink suites passed (one existing
  Windows-only skip). Focused Summon CLI/driver suites passed. The full root
  suite passed with the same Windows-only skip; the full Summon suite passed
  with one environment-only local-LLM skip. Root/Summon Ruff format and lint,
  root/Summon mypy, plan-index, doc-path, documentation-reference, and diff
  whitespace gates passed.
- 2026-08-20: Independent completed-work review returned BLOCKED only on
  missing nonnormative plan backlinks in the two governing specs; no code,
  test, architecture, or TUI defect remained. Backlinks were added to both
  `Related Plans` sections, then doc-path, documentation-reference,
  plan-index, and diff-whitespace gates passed.
- 2026-08-20: Completed-work re-review returned PASS after checking both
  backlinks and the rerun evidence. No code, test, architecture, classification,
  TUI, or scope blocker remains.
- 2026-08-20: The owner authorized close-out and commit. The plan moved to
  completed after the final documentation, status-index, and diff gates passed;
  landing is verified from Git history after the commit.

## Fresh-Eyes Review

Before closure, verify every named path exists, every affected tabular path has
an exact command-level assertion, the inventory records all direct writes, the
deviation log is still honest, and the status-index row matches the evidence.
