# Extension Main Path and `all` Extra Plan

Status: Completed
Class: 5 — spec-changing. Risky trigger: public CLI and extension-manifest
contract change, plus the same long-lived stdio server gaining a second launch
surface. Hardening is mandatory.
Plan type: implementation with spec revision

## Goal

Make every command-bearing Taut extension usable through the installed `taut`
executable, add `taut mcp` as a protocol-clean alias over the existing MCP
server runner, and add `taut-chat[all]` as the complete first-party extension
bundle. Separate extension executables remain supported conveniences that tool
installers may expose explicitly; they are not the only usable path.

## Source Documents

- `docs/specs/02-taut-core.md` [TAUT-8.6], [TAUT-12.5]
- `docs/specs/05-taut-mcp.md` [MCP-3], [MCP-12]
- `docs/implementation/06-command-extensions.md`
- `docs/implementation/07-taut-mcp-architecture.md`
- `README.md` installation and MCP sections
- User direction in this thread: a standalone extension binary is supported,
  and installers may expose it, but the extension must also support its main
  `taut` extension path.

## Spec Baseline

- `b064924394613320fc837d3699d5953e849507d3` — committed baseline for
  `docs/specs/02-taut-core.md` and `docs/specs/05-taut-mcp.md`.
- Promotion baseline: committed base
  `b064924394613320fc837d3699d5953e849507d3` plus worktree spec diff SHA-256
  `7086dd85875cc9b4e5f44e8d7f5c2713c9cc85bd5291596d58ca04f721daa72f` for
  `docs/specs/02-taut-core.md` and `docs/specs/05-taut-mcp.md`. The user has
  not asked for an intermediate commit.

## Context and Key Files

- `taut/commands/_protocol.py` owns the exact version-1 manifest and adapter
  protocols. `taut/commands/_dispatch.py` builds a selected adapter, parses it,
  and currently runs the human-output-policy preflight for every non-JSON
  invocation before calling the adapter.
- `extensions/taut_mcp/taut_mcp/cli.py` owns standalone argument parsing and
  process-level error mapping. `server.run_server()` owns the SDK stdio
  transport. The SDK claims file descriptors 0 and 1 when no explicit streams
  are passed, diverts accidental process output away from the wire, and
  restores the descriptors on exit. The main-path adapter must preserve that
  call shape.
- `extensions/taut_mcp/pyproject.toml` currently publishes only the
  `taut-mcp` console script. Summon's `command_manifest.py` and `commands/`
  show the installed `taut.commands` pattern.
- `pyproject.toml` has only the contributor-facing `dev` extra. Adding `all`
  introduces three derived first-party version floors. `bin/release.py` owns
  synchronized release metadata and must keep those floors aligned with the
  extension manifests. Because `taut-summon` will occur in both `dev` and
  `all`, synchronization must be section-anchored rather than use the current
  file-global first match. Root uv sources and the lock must also add the local
  editable MCP project, matching the existing core/Summon editable cycle.
- `extensions/taut_mcp/tests/test_stdio_server.py` provides real subprocess,
  MCP-client, and installed-wheel proof. `tests/test_command_registry.py`
  provides manifest/dispatch proof. `tests/test_release_script.py` and
  `tests/test_project_metadata_consistency.py` own metadata synchronization.

### Comprehension gates

1. Why may the MCP adapter not merely call the server through the ordinary
   command path? Expected answer: ordinary non-JSON dispatch preflights ambient
   project terminal policy, while [MCP-3] forbids inferred current-workspace
   startup state; the SDK must also retain ownership of raw process stdio and
   its descriptor-diversion guard.
2. What is shared between `taut mcp` and `taut-mcp`? Expected answer: one
   process runner owns `asyncio.run`, broken-transport handling, fixed fatal
   diagnostics, and return status; each surface is only a thin parser/adapter.
3. Which metadata becomes derived? Expected answer: the `taut-pg`,
   `taut-summon`, and `taut-mcp` floors in root `all`; release preparation must
   derive each from its owning extension manifest rather than assume coordinated
   versions.

Implementation is blocked until these answers are recorded correctly in the
execution log.

## Invariants and Constraints

- `taut mcp` and `taut-mcp` launch the same server runner with identical
  `--claude-channel`, version, lifecycle, broken-transport, fixed-diagnostic,
  and exit behavior. Neither invokes or parses the other console surface.
  Their version strings use their actual program names (`taut mcp X` versus
  `taut-mcp X`) and the same version value.
- A valid `taut mcp` launch emits no root help, human preflight output, or other
  stdout before MCP framing. It does not inspect ambient project config.
- The SDK continues to receive no explicit stdio streams, so its descriptor
  claiming and stray-output diversion remain active. Tests must not mock that
  transport seam.
- Existing version-1 manifests remain source and binary compatible: the new
  raw-stdio declaration has a safe default, and ordinary commands retain
  authoritative context streams plus terminal-policy preflight.
- Raw-stdio ownership is explicit manifest metadata, not a verb-name special
  case. It exempts execution from human-output preflight and context-stream
  authority only; help and usage remain core-owned.
- The MCP manifest declares no post-verb root globals. Registry validation
  rejects a non-boolean raw-stdio declaration before implementation loading.
- The standalone `taut-mcp` script remains supported. `pipx --include-apps`
  and `uv tool install --with-executables-from` may expose optional extension
  scripts, but the primary installed `taut` path is complete without them.
- `taut-chat[all]` contains all three first-party extension distributions and
  no development tools. Individual extension installs remain supported.
- Root runtime dependencies stay exactly `simplebroker` and `psutil`; extras do
  not become unconditional dependencies. No new third-party dependency enters.
- PostgreSQL, Summon, MCP wire semantics, and release ordering do not change.

### Hidden couplings and error priority

- Root manifest discovery imports all installed manifests for external-command
  selection; MCP manifest import must remain lightweight and side-effect free.
- Human-output preflight currently happens after parsing but before adapter
  execution. Only a declared raw-stdio command skips it. Parser errors/help
  happen before this boundary and remain ordinary text behavior.
- MCP fatal errors remain fatal and content-free; broken transport remains a
  clean exit. Registry/parser failures happen before server ownership and use
  normal root diagnostics.
- Release preparation runs extension version writes before root dependency
  reconciliation. The synchronizer must read current manifest versions so
  independent package versions remain valid.

## Rollout and Rollback

Roll out core and MCP together at the next coordinated release: an older core
will reject the new manifest capability, while a new core safely defaults old
manifests to ordinary text mode. The root `all` extra floors prevent selecting
an older MCP wheel that lacks `taut mcp`. Post-release success is a fresh tool
environment where `taut --help` lists `mcp`, `taut mcp` completes MCP
initialization with clean stdout, and `taut-mcp` still does the same.

Rollback is one coordinated revert of the extra, MCP entry point/adapter, raw
stdio manifest field, and documentation. No storage or protocol data migrates,
so there is no one-way door. The standalone `taut-mcp` path remains available
throughout rollout and rollback.

Stop and re-plan if the implementation requires explicit streams passed to the
SDK, a second server lifecycle, an MCP dependency in core, a verb-name special
case in dispatch, or changes to MCP tool/wire semantics.

## Proposed Spec Delta

Promotion strategy: **A — in-file edit, text before link claims**. Promote the
normative text after independent review, then add code/test mapping claims with
the implementation slice.

| Spec file | Strategy | Sections touched |
|-----------|----------|------------------|
| `docs/specs/02-taut-core.md` | A | [TAUT-8.6], [TAUT-12.5] |
| `docs/specs/05-taut-mcp.md` | A | [MCP-3], [MCP-12] |

### [TAUT-8.6] — insert after the installed-entry-point discovery paragraphs

> A Taut extension may additionally publish one or more standalone console
> scripts. Installers may expose those scripts explicitly, including
> `pipx inject --include-apps` and `uv tool install
> --with-executables-from`; those scripts are supported convenience surfaces,
> not substitutes for the main command interface. Every extension that
> publishes a standalone script must also expose its primary executable
> capability through one or more installed `taut.commands` manifests and the
> primary `taut` executable. A standalone script may retain additional
> administrative or convenience subcommands, but it cannot be the only way to
> operate the extension's main capability. Equivalent operations across the
> two surfaces share one typed domain or process runner; neither invokes the
> other executable or parses its output. An extension with no executable
> operation, such as a backend selected by project configuration, need not
> invent a command.
>
> A command whose operation is itself a raw stdio protocol transport declares
> that ownership in its manifest. On successful execution, core skips the
> human-terminal-output policy preflight and the adapter owns ambient process
> stdin/stdout rather than the ordinary command-context text streams. Root and
> command help, usage errors, and manifest diagnostics remain core-owned text
> before protocol startup. The declaration is not inferred from a command name
> and does not permit protocol output before adapter execution. All ordinary
> commands retain context-stream authority and terminal-policy preflight.
>
> The core distribution publishes an `all` optional-dependency extra containing
> the compatible `taut-pg`, `taut-summon`, and `taut-mcp` distributions. It is
> a convenience bundle, not a merger of package ownership: each extension
> remains separately versioned and directly installable, and core does not
> import or initialize an extension until its registered surface is selected.

### [TAUT-12.5] — extend deterministic metadata ownership

> The PG, Summon, and MCP manifests respectively own the three version floors
> in the root `all` extra; normal release preparation reconciles all three on
> every invocation after selected manifest versions are written.

### [MCP-3] — replace the opening packaging paragraph

> The distribution name is `taut-mcp`. It registers `mcp` in the
> `taut.commands` entry-point group, making `taut mcp` the main Taut extension
> path, and also publishes the supported convenience console script
> `taut-mcp`. Both surfaces accept the same launch flags and call one shared
> process runner; neither surface invokes the other. The `mcp` command declares
> raw stdio protocol ownership under [TAUT-8.6], so successful dispatch performs
> no ambient project terminal-policy preflight and the MCP SDK retains direct
> ownership of process stdin/stdout. It declares `mcp>=2.0.0,<3` and uses that
> SDK's native support for legacy `2025-11-25` and modern `2026-07-28` clients
> from one handler set. The SDK owns legacy initialization, modern discovery,
> protocol negotiation, stdio framing, and era-specific wire envelopes. Taut
> application code does not branch on protocol version for tool semantics.

### [MCP-12] — extend verification expectations

> Installed-artifact verification launches the same real stdio initialization
> through both `taut mcp` and `taut-mcp`, proves both launch-flag parsers and
> fixed failure classes, and proves the main path emits no human preflight or
> other non-protocol stdout. Metadata verification requires the installed MCP
> wheel to register its `mcp` manifest.

## Deviation Log

| Spec ref | Planned behavior | Actual behavior | Rationale | Spec proposal |
|----------|------------------|-----------------|-----------|---------------|
| [TAUT-12.5] | Add and synchronize three `all` floors. | Also reconcile the existing root lock after adding the local editable MCP source. | Independent review identified that root development resolution would otherwise select the published MCP wheel and miss the new entry point. | Promoted [TAUT-12.5] release-metadata paragraph. |
| [TAUT-8.6] | Require every standalone-script operation to have a main-path equivalent. | Require the extension's primary executable capability on the main path; permit standalone-only administrative conveniences. | The broader draft would retroactively outlaw `taut-summon status`, exceeding the user's extension-path requirement and this plan's no-Summon-redesign boundary. | Revised promoted [TAUT-8.6] paragraph and command-extension rationale. |

## Tasks

1. **Independently review and promote the contract.**
   - Review this plan, exact delta, current registry/dispatch code, MCP runner,
     release synchronizer, and affected tests with a different agent family.
   - Disposition every finding. Apply strategy A to both specs, update Related
     Plans, record the promotion baseline, and run documentation reference and
     plan-index gates.
   - Stop if raw-stdio ownership cannot be expressed compatibly in manifest v1.

2. **Tracer: register and launch `taut mcp` through real stdio.**
   - First add one installed/public-path test in
     `extensions/taut_mcp/tests/test_stdio_server.py` proving real MCP
     initialization through `taut mcp`; observe RED because no manifest exists.
   - Add lightweight `command_manifest.py` with an empty
     `post_verb_globals`, a command adapter, and the
     `taut.commands` metadata. Extract one shared process runner from `cli.py`;
     keep both parsers thin and preserve `cli.run_server` as the existing
     monkeypatch seam used by focused fatal/cancellation tests.
   - Add the raw-stdio manifest declaration and dispatcher behavior only as
     required to make the tracer green. Do not mock the registry, subprocess,
     SDK stdio, or MCP client.

3. **Close command and failure contracts incrementally.**
   - One red-green cycle at a time: lightweight manifest/help discovery,
     `--claude-channel` and `--version` parity, invalid syntax, fatal failure,
     broken transport, program-name-specific version text with the same version
     value, absence of ambient project-policy preflight, no stdout
     contamination, unchanged preflight for an ordinary extension command, and
     installed-wheel registration/invocation.
   - Validate that raw-stdio metadata is boolean. Add architecture-boundary/type
     checks if the new modules enter an existing closed inventory. Keep the
     field default-compatible.

4. **Add and synchronize `taut-chat[all]`.**
   - First add failing metadata tests for the exact three-member bundle and for
     release reconciliation from independently versioned extension manifests.
   - Add the extra and minimally generalize `bin/release.py` so all three floors
     are derived. Anchor Summon's `dev` and `all` occurrences independently,
     and update the closed synchronization-call inventory. Add the local
     editable `taut-mcp` uv source and refresh the root lock, matching the
     existing safe core/Summon cycle. Update dry-run text, release tests, and
     [TAUT-12.5] mapping.
   - Build wheels and inspect `Requires-Dist` markers; do not rely only on TOML
     parsing.

5. **Reconcile user and implementation documentation.**
   - Update README install examples for `taut-chat[all]`, the primary
     `taut mcp` launch form, optional pipx `--include-apps`, and uv
     `--with-executables-from` exposure. Update both implementation notes and
     mapping tables without implying standalone scripts are deprecated.
   - Run CLI-claim and documentation gates.

6. **Final verification and independent completed-work review.**
   - Run targeted tests after each slice, then MCP non-PG suite, command
     registry/lazy-import/metadata/release suites, Ruff, format check, strict
     mypy, wheel inspection, CLI claims, traceability checks, and available
     installed-wheel tests.
   - Ask the different-family reviewer to inspect the final diff and concrete
     evidence. Disposition findings, rerun affected gates, update this execution
     log, and leave the work uncommitted unless the user explicitly asks for a
     commit.

## Testing Plan

Use real installed metadata, subprocesses, MCP SDK clients, and stdio framing
for the main proof. Unit tests may isolate the shared process runner's failure
mapping, but must not replace the real public launch test. Use real built wheel
metadata for `all`. No database is needed for empty MCP initialization; no
PostgreSQL behavior changes, so existing live PG conformance is neighboring
regression evidence rather than a new semantic proof.

Target commands (exact selectors may be narrowed as tests are added):

```bash
uv run --project extensions/taut_mcp pytest extensions/taut_mcp/tests/test_stdio_server.py
uv run pytest tests/test_command_registry.py tests/test_lazy_imports.py tests/test_project_metadata_consistency.py tests/test_release_script.py
uv run ruff check taut extensions/taut_mcp bin/release.py tests
uv run ruff format --check taut extensions/taut_mcp bin/release.py tests
uv run mypy taut extensions/taut_mcp/taut_mcp
uv run bin/check-cli-claims
uv run bin/check-doc-paths
uv run bin/check-plan-status-index
```

## Verification and Gates

- Per slice: the new test fails for the intended missing behavior before code,
  then passes with the smallest implementation.
- Final behavior: real MCP initialization succeeds through both executable
  shapes with protocol-clean stdout; ordinary commands still preflight human
  output; invalid/fatal/broken-transport classes remain exact.
- Packaging: built core metadata exposes exactly `all`; built MCP metadata has
  both the script and `taut.commands` registration; release preparation repairs
  all derived floors idempotently.
- Documentation: CLI claims, references, paths, traceability, and plan status
  are green with reciprocal spec/plan/implementation/code links.
- Post-deploy signal: a fresh `pipx install 'taut-chat[all]'` exposes `taut`,
  `taut --help` lists `mcp`, and an MCP client launches `taut mcp`. Optional
  standalone exposure is separately smoke-tested when installer tooling is
  available.

## Independent Review Loop

Use the repository `call-agent` skill with Claude Opus in read-only review
posture for both the pre-implementation plan/delta gate and the completed-work
gate. The reviewer must existence-check every named field, flag, test seam,
and release ordering claim, prefer removal of unnecessary machinery, and
answer PASS/BLOCKED for the plan. Record full findings and dispositions below;
accepted fixes receive a scoped round-2 review when material.

## Out of Scope

- Changing MCP tools, schemas, protocol versions, workspace selection, or
  reactor lifecycle.
- Adding commands for backend-only `taut-pg`.
- Removing or deprecating `taut-mcp` or `taut-summon` scripts.
- Exposing every dependency script by default or changing pipx/uv behavior.
- General command API v2, nested extension namespaces, aliases, or hot reload.
- Publishing a release or committing on the user's behalf.

## Review Log

| Date | Reviewer | Unit | Verdict/findings | Disposition |
|------|----------|------|------------------|-------------|
| 2026-08-12 | Claude Opus | Full plan and proposed delta at `b064924` | PASS. P2: Summon's existing `dev` floor collides with a second file-global `all` match. P2: root needs a local MCP uv source and lock update. P3: preserve `cli.run_server` patch seam; decide version prefix; state empty globals and validate raw-stdio metadata. | Accepted all. Context/tasks now require section-anchored synchronization and call-inventory coverage, local MCP source/lock, the existing patch seam, program-specific version prefixes with one version value, empty globals, and boolean validation. No round 2 needed before promotion because the verdict was PASS and the corrections are explicit plan constraints. |
| 2026-08-12 | Claude Opus | Completed worktree diff and verification evidence | PASS. No blocking or medium findings. Low observations: wheel marker quote sensitivity, shared fixed `taut-mcp:` fatal prefix, root-lock resolution cost, and ignored pre-verb core globals. | No code changes required. The installed-wheel suite already passed, proving the emitted marker shape. The fixed fatal text, root lock, and universal pre-verb root grammar are specified behavior; MCP-local flags remain identical and the adapter ignores core context. |

## Execution Log

| Date | Slice | Evidence | Result |
|------|-------|----------|--------|
| 2026-08-12 | Preflight | Read startup context, [TAUT-8.6], [TAUT-12.5], [MCP-3], [MCP-12], both implementation notes, command/MCP/release code and tests; ran `uv run bin/coalesce-check` and `uv run bin/check-plan-status-index`. | Class 5 risky plan required. Coalescing cues resolve and the plan index is green. Comprehension answers match the expected answers above. |
| 2026-08-12 | Plan review and spec promotion | Claude Opus returned PASS with five accepted corrections. Promoted [TAUT-8.6], [TAUT-12.5], [MCP-3], and [MCP-12] using strategy A; `uv run bin/check-plan-status-index`, `uv run bin/check-doc-paths`, and `git diff --check` passed. | Promotion baseline recorded above. Implementation now targets the active spec tree. |
| 2026-08-12 | Main-path tracer and raw stdio boundary | The initial real `taut mcp` subprocess tracer failed with `unknown command: mcp`. Added the installed manifest, thin adapter, shared runner, and explicit raw-stdio manifest field. A second red test showed help imported the server runtime; `_version.py` and a lazy `cli.run_server` wrapper closed that boundary. | Real legacy and modern MCP initialization now pass through both `taut mcp` and `taut-mcp`; `--claude-channel`, version naming, invalid syntax, fatal diagnostics, broken transport, clean stdout, lazy help, and unchanged ordinary-command preflight have firing tests. |
| 2026-08-12 | Bundle and release metadata | Added failing exact-membership and independent-version reconciliation tests before adding root `all`, the local editable MCP source, section-anchored release synchronization, and lock refresh ordering. Built-wheel tests inspect both `Requires-Dist` markers and the installed `taut.commands` entry point. | `taut-chat[all]` contains exactly PG, Summon, and MCP. Root, Summon, and MCP locks resolve; release tests and 28 installed-wheel tests pass. |
| 2026-08-12 | Documentation and generated registry | Updated user install/launch guidance, both implementation notes, repository map, changelog, and CLI-claim exemptions. Regenerated the Ruff suppression registry after moving the approved process-boundary catch from `cli.main` to the shared `cli.run_process`. | CLI claims, document paths, DOM-15 fixtures, suppression-index, plan-index, and diff whitespace gates pass. The generated [DOM-10.2.1] row is the only incidental spec-file change. |
| 2026-08-12 | Full verification before final review | `uv lock --check` for root, Summon, and MCP; root non-slow/non-wheel suite; MCP non-PG suite; installed-wheel suite; repository Ruff lint; targeted Ruff format; root and MCP mypy; all documentation gates. | Root suite passed with one platform skip; MCP suite passed; 28 wheel tests passed; lint and type checks passed. Repository-wide format check remains blocked only by three pre-existing, untouched historical plan files, so changed Python files were checked directly and all 22 pass. |
| 2026-08-12 | Completed-work review | Claude Opus inspected the full diff and traced dispatch, lazy imports, installed metadata, release ordering, and both launch adapters; verdict PASS with no blocking or medium findings. A follow-up `python bin/release.py core --dry-run` stopped at the existing-version publication guard before preparation, as designed. | All review findings dispositioned above. The owner subsequently authorized closeout and commit; the plan is complete. |
