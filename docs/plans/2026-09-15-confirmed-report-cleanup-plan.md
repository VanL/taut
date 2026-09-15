# Confirmed report cleanup

Status: Completed
Class: 5 — behavior, packaging, and release-compatibility contract changes.

## Goal

Fix the confirmed transcript-layout and Unicode excerpt defects; replace brittle
reply classification; remove confirmed private dead seams; make watcher
configuration truthful; keep developer helpers out of the wheel; and remove
the historical Summon/current-core compatibility path. Releases are
synchronized; cross-era core/extension combinations are unsupported.

## Boundaries

- Remove the deprecated `TautWatcher(client, ...)` constructor before external
  release; retain runtime-based advanced construction.
- Preserve presentation ownership of mention reply hints and do not split large
  modules for size.
- Keep current synchronized core/Summon wheel metadata and lifecycle checks.
- Encode synchronized compatibility in first-party extension metadata with an
  exact core-version pin; release scripts alone cannot constrain pip's resolver.
- Remove historical-wheel checkout/build/install checks and
  `taut._broker_retry`; do not replace them with another compatibility shim.
- Keep `taut/_scripts.py` available to source-tree developer tooling but exclude
  it from built wheels.
- Windows ConPTY close ownership requires native causal proof and remains in
  the active Windows lifecycle work; no inspection-only lifecycle edit here.

## Slices

1. Wire [TUI-5.3] production rendering to `transcript_metadata_layout`; prove
   wide/medium hanging continuation indent and compact stacking.
2. Execute Slice 6 of the 2026-08-24 plan with O(1)-space folded-offset mapping.
3. Replace reply error-string matching with a typed message-id error.
4. Reject unsupported watcher yield strategies; remove the unused counter and
   always-true predicate while retaining the legacy `check_interval` argument.
5. Remove the packaged-policy writer, unused mention argument, obsolete Summon
   handoff method/exit alias, and duplicate TUI member method.
6. Remove historical Summon/current-core matrix logic, tests, docs and the
   `_broker_retry` shim. Preserve current synchronized-wheel gates.
7. Exclude `taut/_scripts.py` from wheels and prove source tooling still works
   while installed wheels omit it.
8. Remove the unused `database_path_from_target` public helper before external
   release rather than carrying a credential-bearing compatibility surface.
9. Align specs, implementation docs, changelog and ownership maps; run changed
   root, Summon, TUI, wheel, Ruff, mypy and documentation gates. Complete an
   independent review of each slice and the final diff.

## Residuals

Native Windows lifecycle qualification remains owned by the Windows plan. No
commit, release, registry action, or publication without a separate request.

## Completion evidence

- Root non-slow, non-installed-wheel suite: 2,174 passed, 4 platform skips.
- TUI application and layout suites passed, including mounted OptionList strip
  rendering and row-height agreement.
- Summon driver suite passed.
- Release-script, synchronized-wheel matrix, installed-wheel packaging, search,
  reply, watcher, and architecture regressions passed.
- Ruff check and format, root/TUI/Summon mypy, documentation references,
  documentation paths, and `git diff --check` passed.
- Independent review passes found and closed the Textual rendering bypass,
  weak reply tests, unenforced synchronized-release paths, open dependency
  floors, a stale watcher type signature, and stale historical-probe claims.
  Final review found no remaining defect in those corrected slices.
