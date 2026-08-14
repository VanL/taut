# Command Context Continuity Token

Class: 5
Status: completed
Owner: Taut product owner
Hardening: required by [DOM-5] because the change renames a public command-extension field and crosses the core CLI and TUI extension boundaries.
Promotion strategy: D — clarify the existing [TAUT-8.6] execution-context
contract in place, with no change to `--token` selection semantics.

## Goal

Make the active product theory and command-extension contract describe the
system that exists. The theory must recognize the active product-section
registry and the human-first `taut-tui` surface. Its machine-output claim must
cover record-oriented CLI commands without misdescribing the raw-stdio MCP and
full-screen TUI transports. The public `CommandContext` identity-selection
field must be named `continuity_token`, matching the identity model and the
existing TUI form vocabulary.

The rename is intentionally fix-forward. `auth_token` is removed rather than
kept as a compatibility alias, because Taut does not authenticate with this
selector and retaining the old name would preserve the wrong contract.

## Source documents and proposed spec delta

- `docs/program-theory.md` [THEORY-1], [THEORY-2], [THEORY-4], and [THEORY-7]
  own the conceptual wording being corrected. The user explicitly authorized
  recommendations 1 and 2 in this task.
- `README.md` is updated as a restatement of the registry-backed CLI contract;
  its former "every command has `--json`" feature claim was broader than the
  active TUI and MCP transport contracts.
- `docs/specs/02-taut-core.md` [TAUT-8.6] owns the versioned command-module
  contract and will explicitly name `CommandContext.continuity_token` as the
  root `--token` value. This is a clarification of the active public shape
  after the fix-forward rename, not a change to token selection semantics.
- `docs/specs/10-taut-tui.md` [TUI-1] and [TUI-3.2] govern the TUI's role and
  root selection behavior. No TUI behavior or accepted flag changes.
- `docs/specs/product-section-registry.md` is the active authority table that
  [THEORY-7] must describe.
- `docs/implementation/06-command-extensions.md` and
  `docs/implementation/12-taut-tui.md` explain the current ownership and key
  files.

Exact proposed [TAUT-8.6] delta: state that the core-created command context
  carries `db_path`, `as_name`, `continuity_token`, the output-mode flags, the
  authoritative streams, and one lazy client; the `--token` root option maps
  to `continuity_token` and remains an identity selector, not authentication.

## Current structure and key files

`taut/commands/_protocol.py` owns the public `CommandContext` constructor,
slots, and lazy `TautClient` construction. `taut/commands/_dispatch.py` owns
root-value parsing, pre/post-verb merge, and context construction. The system
command checks whether explicit identity selection was supplied.

`extensions/taut_tui/taut_tui/command.py` adapts the command context into the
TUI launch API. The TUI launch facade, preflight wrapper, `TautApp`, and
`TuiSession` carry that value through to the real `TautClient`; the Summon
standalone CLI also constructs a real `CommandContext` for its command path.
Tests in `tests/test_command_registry.py`, the TUI test package, the Summon
CLI tests, and `bin/render-tui-screens` exercise those seams.

Before implementation, verify:

1. Does every path that consumes `--token` read the renamed context field
   without changing the wire spelling or identity behavior?
2. Does the TUI still reject its incompatible output flags before importing
   Textual while accepting `--db`, `--as`, and `--token`?

## Invariants and constraints

- The command-line spelling remains `--token`; only the Python field and
  parameter name change.
- `continuity_token` is passed to `TautClient(token=...)` unchanged. No token
  hashing, persistence, authentication, authorization, or identity-resolution
  semantics change.
- Core still owns parser policy, streams, lazy-client lifetime, cleanup, and
  exit classes. TUI still owns rich composition and ambient stdio.
- `taut-mcp` remains a raw JSON-RPC protocol transport and `taut-tui` remains a
  raw full-screen terminal transport. Neither receives `--json` as a claim.
- Record-oriented CLI commands retain their current JSON behavior. Summon's
  `summon` and `dismiss` manifests retain their declared global set.
- No compatibility alias, fallback constructor keyword, or deprecated public
  spelling is added for `auth_token`.
- No storage schema, queue, message, notification, identity-claim, or release
  behavior changes.
- Tests must prove the public field shape and real dispatcher/TUI forwarding;
  a repository-wide textual rename alone is insufficient.

## Rollback, rollout, and one-way door

The field rename is a one-way public API boundary for this repository's
versioned command-extension interface. Roll back the whole synchronized slice
by reverting the spec, implementation docs, theory wording, code, and tests
together. Do not roll back only core or only TUI: that creates a constructor
keyword mismatch and is worse than either coherent state.

There is no staged compatibility rollout because the user requested the
canonical name and the repository's extension interface is versioned in place.
Before landing, the full focused core and TUI gates must pass, and a final
`rg` audit must show no live `auth_token` command-context or TUI API references.
Historical plans may retain historical wording when they are records rather
than active contracts.

## Dependency-ordered tasks

1. Add or update a focused contract test to require
   `CommandContext(continuity_token=...)`, expose that value to the command
   adapter, and verify the old keyword is absent from the active public shape.
   Run it red before production edits. Stop if the test requires an alias or
   changes the `--token` spelling.
2. Promote the exact [TAUT-8.6] wording, add this plan to the core spec's
   related-plan list, and update the implementation command-context table.
   Stop if the spec change implies different identity or parser semantics.
3. Rename the field through `_RootValues`, global extraction/merge, context
   construction, core consumers, and the TUI and Summon public wrappers. Update
   all live tests and the screen-render helper in the same slice.
4. Update `docs/program-theory.md` and the README restatement to describe the
   active registry, include `taut-tui` in the extension model, distinguish
   human-first TUI from agent-first MCP, and narrow the `--json` claim to
   record-oriented CLI commands and their native rich/protocol exceptions.
5. Run focused tests, documentation/reference gates, static checks, and the
   final live-reference audit. Perform a fresh-eyes review against the plan's
   invariants and record any deviation here before completion.

## Testing and verification

Red/green proof starts with the focused command-context test. The core proof is
the real `dispatch()` path and `tests/test_command_registry.py`, including
pre-verb and post-verb `--token` forwarding and the command adapter's observed
context. TUI proof uses the existing Textual contract and launch tests with the
real public launch constructors; do not replace the TUI session or client with
a fake merely to make the keyword rename pass. Limited test doubles remain
acceptable for existing terminal and controller seams that those tests already
isolate.

Run at minimum:

- `uv run --locked pytest tests/test_command_registry.py`
- `uv run --project extensions/taut_tui --extra dev --locked pytest extensions/taut_tui/tests/test_tui_launch.py extensions/taut_tui/tests/test_tui_app.py extensions/taut_tui/tests/test_tui_chat.py extensions/taut_tui/tests/test_tui_textual_contract.py`
- `uv run --locked pytest extensions/taut_summon/tests/test_summon_cli.py`
- `uv run --locked pytest tests/test_docs_references.py tests/test_cli_claims.py`
- the repository's focused Ruff and mypy commands for core and TUI, if the
  changed files trigger those package gates
- `rg -n "auth_token"` scoped to live code, tests, and maintained docs, with
  historical plan records explicitly reviewed rather than mechanically edited
- `bin/check-plan-status-index`

Success means the focused tests pass, the docs gates accept the updated
references and theory claims, the live API has only `continuity_token`, and
the `--token` CLI behavior is unchanged. There is no production telemetry for
this internal Python field; post-landing observation is a clean extension
install/import smoke and absence of third-party adapter failures in CI.

## Out of scope

Do not redesign command manifests, introduce a shared CLI/TUI action registry,
change MCP wire schemas, alter TUI action routing, change root option names,
add authentication, or update historical plan prose solely to make the global
search empty. Do not add a compatibility shim or broaden the registry beyond
the current active rows.

## Independent review and fresh-eyes record

The plan requires independent review before implementation and a completed
work review under [DOM-11]. If no second agent is available in this session,
use the repository-authorized fresh-eyes substitute, disclose that limitation
in the final handoff, and review the exact spec delta, live-reference audit,
rollback coherence, and focused test output against every invariant above.

## Deviations and completion evidence

Implementation completed with one scope correction: the README's matching
"every command has `--json`" feature claim was also stale, so it was narrowed
alongside the program-theory wording. The core spec already described the
execution context conceptually as a continuity token; its exact Python field
name is now stated at the existing execution-context paragraph rather than in
a duplicate paragraph.

Fresh-eyes review substituted for independent review because no second review
agent was available through the current session tools. The review received
the governing spec, this plan, the command-extension and TUI implementation
notes, and the complete touched-file set. It checked the no-alias boundary,
`--token` forwarding, TUI preflight behavior, the registry/theory account,
historical-plan handling, and the verification commands. The README stale
claim and duplicate-spec wording were found and corrected; no unresolved
review findings remain.

Verification evidence:

- `uv run --locked pytest -q tests/test_command_registry.py` — passed.
- `uv run --locked pytest -q extensions/taut_summon/tests/test_summon_cli.py` —
  passed.
- `uv run --project extensions/taut_tui --extra dev --locked pytest -q
  extensions/taut_tui/tests/test_tui_launch.py
  extensions/taut_tui/tests/test_tui_app.py
  extensions/taut_tui/tests/test_tui_chat.py
  extensions/taut_tui/tests/test_tui_textual_contract.py` — passed.
- `uv run --locked pytest -q extensions/taut_pg/tests/test_pg_tui.py` — one
  PostgreSQL test skipped because `SIMPLEBROKER_PG_TEST_DSN` was not set.
- `uv run --locked pytest -q tests/test_docs_references.py
  tests/test_cli_claims.py` — passed.
- `uv run bin/check-doc-paths`, `uv run bin/check-cli-claims`, and
  `uv run bin/check-plan-status-index` — passed.
- Changed-file Ruff check and format check, core/TUI mypy, and `git diff
  --check` — passed.
- The live-source audit finds no `auth_token` API or implementation
  reference; the one remaining test string explicitly asserts that the old
  field is absent, and the historical plan record remains unchanged.

Do not record transient uncommitted-state claims in this plan.

## Related plans

- `docs/plans/2026-08-12-taut-tui-implementation-plan.md` — original TUI
  implementation and contract promotion.
- `docs/plans/2026-08-07-program-theory-crystallization-plan.md` — original
  owner-ratified program theory.
