# Ruff Complexity and Suppression Registry Plan

Date: 2026-08-04
Status: completed — T1–T10 implemented, verified, and independently reviewed;
the owner authorized the targeted completion commit on 2026-08-05
Class: 5+P. The base class is 5 because this plan adds normative repository
verification policy under [DOM-10] and changes the required evidence for future
Python changes. The `+P` modifier applies because the policy, generator, CI gate,
and suppression approval workflow materially change future agent behavior. The
new repository-tool CLI and its atomic-replacement path also trigger the [DOM-5]
risky CLI and cleanup-lifecycle criteria.
Plan type: implementation with spec revision
Hardening: required

## Goal

Enable Ruff's `C901` McCabe-complexity rule at 10 across every first-party Python
surface, use the score as an audit signal rather than an automatic refactor
order, and port SimpleBroker's reviewed suppression-registry generator so every
retained finding remains locally visible, human-justified, location-auditable,
and mechanically reconciled.

The implementation must first make Ruff versioning and discovery deterministic.
It must then activate C901 atomically with reviewed initial dispositions,
source-local group pointers, the human registry, the generated symbol index,
policy tests, CI, and release gates. Later refactor slices may remove justified
temporary suppressions; they must not fragment cohesive lifecycle, protocol,
parser, or real-process proof owners merely to lower a score.

## Requested Outcomes

- [x] Pin one exact Ruff version across the root, PostgreSQL, Summon, and MCP
  development manifests and regenerate the two existing extension locks.
- [x] Make Ruff discovery cover every tracked `.py`, `.pyi`, and extensionless
  Python-shebang tool, including `.github/scripts/` and all extension trees.
- [x] Preserve the explicit formatter boundary; repository-wide lint discovery
  must not widen formatting ownership.
- [x] Retain the explicit `select` list in both active Ruff configurations, add
  only `C901` to the existing `E`, `W`, `F`, `I`, `B`, `C4`, and `UP`
  families, and set `lint.mccabe.max-complexity = 10`.
- [x] Disposition every initial C901 finding before activation. Use P1 for a
  concrete defect or clear ownership seam, P2 for an owner-local improvement,
  and P3 for a cohesive retained owner with a defensible reason and real proof.
- [x] Activate normal C901 enforcement with a narrow local suppression for
  every still-live finding; temporary P1/P2 suppressions must name their removal
  or re-evaluation slice.
- [x] Add the human-owned approved-suppression registry under [DOM-10.2.1].
- [x] Port SimpleBroker's `bin/ruff_suppression_index.py` and focused tests,
  adapted only for Taut's spec code, command, and repository paths.
- [x] Key generated review evidence on `path::qualified_symbol`, while retaining
  Ruff's physical `noqa_row` internally for diagnostic reconciliation.
- [x] Reconcile normal Ruff, raw `--ignore-noqa` diagnostics, exact source
  directives, human-approved rule/cardinality rows, the generated symbol index,
  and the global active-rule raw-diagnostic inventory.
- [x] Put repository-wide Ruff and suppression-index checks on root CI and the
  release helper. Keep PG and MCP lint jobs scoped to their existing extension
  paths as independent same-version/configuration proof.
- [x] Refactor only at named ownership seams, one independently reviewable slice
  at a time, with characterization or contract proof before structural edits.
- [x] Revisit refactors that reduced lexical lifecycle, release-order, state-
  transition, or test-proof locality; consolidate shallow seams and retain a
  reviewed suppression when cohesion leaves a score above 10.
- [x] Reconcile the final registry, implementation map, spec backlinks, policy
  fixtures, release gates, and plan status after all approved refactors.
- [x] Change no product API, CLI behavior, persistence format, delivery
  semantics, MCP wire behavior, Summon lifecycle contract, or release outcome.

## Premises and Decisions

1. **Complexity is evidence, not a verdict.** A score above 10 requires review
   and an explicit disposition. It does not prove that helper extraction would
   improve the code.
2. **Cohesion and failure locality outrank score reduction.** A parser,
   lifecycle owner, atomic release sequence, stateful reactor, or real-process
   test may remain complex when extraction would pass the same live state across
   more boundaries or obscure failure order.
3. **Every initial finding is visible on activation day.** The plan does not
   hide pre-existing findings in a baseline file, per-file ignore, global
   ignore, raised threshold, or unreviewed blanket suppression.
4. **Human approval and generated evidence have different owners.** Humans own
   rule scope, cardinality, protected invariant, proof, rejected alternatives,
   and approval. The generator owns only derived sites and actual counts.
5. **The generator cannot approve growth.** Copying an existing group ID fails
   until a reviewer explicitly changes that group's approved cardinality and
   confirms the new site is protected by the same rationale.
6. **Symbols are the review identity; lines remain the Ruff identity.** The
   generated index uses `path::qualified_symbol` to avoid line-movement churn
   and expose migration between functions. Raw diagnostics still reconcile by
   repository-relative path and Ruff's `noqa_row`.
7. **One root scanner owns the repository inventory.** The generator runs the
   exact root Ruff binary against `.`. Separate extension lint jobs remain as
   independent environment/configuration proof, but they use the same exact
   Ruff version and must agree on C901 behavior.
8. **The global inventory covers active-rule diagnostics, not textual comments
   for disabled families.** Taut currently has reasoned `noqa` comments for
   disabled families such as `BLE001`, `SLF001`, `N802`, and `S310`. This plan
   does not enable those families or pretend Ruff emits raw diagnostics for
   them. Every C901 exception is nevertheless grouped and exact.
9. **Reuse the shipped SimpleBroker tool.** Port the implementation at
   SimpleBroker commit `4d4f61be55d117c129e0a21fe1139772496282be`, including
   its symbol-keyed R1 correction and hostile-input tests. Do not re-create a
   smaller regex-only scanner or generalize it into a framework.
10. **Red-green TDD applies.** Configuration, discovery, reconciliation,
    generator failure modes, CI shape, and release-gate shape all receive
    failing tests before their implementation changes. Characterization tests
    precede behavior-preserving complexity refactors.

## Source Documents

Source specs and process:

- `docs/specs/01-development-documentation-operating-model.md` [DOM-5],
  [DOM-6], [DOM-10], [DOM-11], and [DOM-15].
- `docs/agent-context/decision-hierarchy.md`.
- `docs/agent-context/engineering-principles.md`, especially principles 3, 4,
  8, 9, 10, 12, 13, and 14.
- `docs/agent-context/runbooks/writing-plans.md`.
- `docs/agent-context/runbooks/hardening-plans.md`.
- `docs/agent-context/runbooks/testing-patterns.md`.
- `docs/agent-context/runbooks/adversarial-acceptance-probes.md`.
- `docs/agent-context/runbooks/maintaining-traceability.md`.

Current Taut implementation and gates:

- `pyproject.toml` and `extensions/taut_mcp/pyproject.toml`: the two active Ruff
  configurations.
- `extensions/taut_pg/pyproject.toml` and
  `extensions/taut_summon/pyproject.toml`: additional dev dependency owners.
- `extensions/taut_mcp/uv.lock` and `extensions/taut_summon/uv.lock`: existing
  Ruff lock owners.
- `.github/workflows/test.yml`, `.github/workflows/test-pg-extension.yml`, and
  `.github/workflows/test-mcp-extension.yml`: current split lint environments.
- `bin/release.py`: local release-gate planner. Ruff check and format currently
  share one explicit path tuple; this plan must split those owners before making
  lint repository-wide.
- `tests/test_github_workflows.py` and `tests/test_release_script.py`: executable
  workflow and release-command shape contracts.
- `tests/test_docs_references.py`: spec-code and maintained-path traceability.
- `docs/implementation/02-repository-map.md`: repository tool ownership map.

SimpleBroker reference implementation:

- `../simplebroker/docs/plans/2026-07-29-complexity-and-state-machine-hardening-plan.md`.
- `../simplebroker/docs/plans/2026-07-30-ruff-suppression-index-generator-plan.md`.
- `../simplebroker/bin/ruff_suppression_index.py` at `4d4f61be`.
- `../simplebroker/tests/test_ruff_policy.py` and
  `../simplebroker/tests/test_ruff_suppression_index.py` at `4d4f61be`.
- `../simplebroker/docs/specs/01-development-documentation-operating-model.md`
  [DOM-10.1] and [DOM-10.1.1] at `4d4f61be`.

Source product spec: None. This is repository tooling and verification policy;
product behavior must remain unchanged.

Program theory: no [THEORY-*], [REV-*], or [ALT-*] change. The work supports
the existing small-concept and debuggability principles but does not revise
Taut's product identity.

## Spec Baseline

- `1ad1b8d0cd593ff0b7a3b5bf3fa3ec92df5e9cb3` —
  `docs/specs/01-development-documentation-operating-model.md` at plan authoring.
- Plan type: implementation with spec revision.
- Proposed sections: new [DOM-10.2] and [DOM-10.2.1], inserted after existing
  [DOM-10.1] and before [DOM-11].
- Promotion strategy: **B — atomic**. The normative text, exact reviewed human
  registry, source directives, generator, generated block, Ruff configuration,
  policy tests, CI gate, implementation backlink, and reciprocal spec backlink
  activate in one policy slice. There is no main-branch state where C901 is
  required but unaccounted findings make normal Ruff fail, or where source cites
  a registry that does not yet exist.
- Promotion baseline identifier: pending. The activation implementer must record
  the commit SHA when committed, or the diff base plus worktree/spec blobs when
  reviewed uncommitted. Unlike the SimpleBroker source plan, this identifier
  must be captured before later refactor slices begin.

## Proposed Spec Delta

Promotion strategy B applies to the following exact normative insertion. The
activation slice also instantiates the human registry rows from the reviewed
initial disposition/group ledger and writes the generated block. Those rows are
approval evidence derived from the pinned audit, not additional behavior text;
their schema and required semantics are fixed here, and their exact values must
receive the activation review before promotion.

### [DOM-10.2] — insert after [DOM-10.1]

> ### [DOM-10.2] Repository static-analysis and complexity gate
>
> Taut's Python lint gate uses one exact Ruff version across the root,
> PostgreSQL, Summon, and MCP development manifests and existing lockfiles.
> `pyproject.toml` and `extensions/taut_mcp/pyproject.toml` own their respective
> Ruff configuration; both explicitly select `E`, `W`, `F`, `I`, `B`, `C4`,
> `UP`, and `C901`, use `mccabe.max-complexity = 10`, and keep preview rules
> opt-in. A Ruff-version change must update every manifest and
> existing lock in one reviewed change, regenerate the effective-rule fixture,
> and re-run the raw suppression audit before adoption.
>
> Owner: the Ruff configurations own rule selection and discovery; the root CI
> lint job owns repository-wide enforcement; the PG and MCP lint jobs provide
> independent extension-environment proof. Boundary: every tracked first-party
> `.py` and `.pyi` file and every tracked extensionless Python-shebang tool,
> including repository tools, `.github/scripts`, tests, and all extension
> projects. Verification: `tests/test_ruff_policy.py` invokes the real canonical
> Ruff binary, compares effective discovery and enabled rules with reviewed
> inventories, proves complexity 10 passes and 11 fails, and checks CI and
> release command shape. Required action: normal lint uses `ruff check .`; Ruff
> formatting retains its explicit existing path boundary and does not expand to
> repository-wide formatting merely because lint discovery expands.
>
> Ruff's C901 score is a visibility signal, not a design verdict. Each finding
> must either be simplified at a real ownership seam with behavior-preserving
> proof or carry a narrow local C901 suppression registered in [DOM-10.2.1]. A
> retained finding requires a protected coupling, debugging-locality, or
> semantic-risk reason; real behavioral proof; rejected decompositions; and
> explicit approval. A cohesive parser, lifecycle owner, protocol dispatcher,
> atomic release sequence, stateful reactor, or real-process proof must not be
> fragmented merely to lower its score.
>
> The policy gate runs normal Ruff and a raw audit with `--ignore-noqa`. Source
> directives, human-owned [DOM-10.2.1] groups, the generated symbol index, and
> raw diagnostics at tagged locations using Ruff's `noqa_row` must reconcile
> exactly, including each group's approved directive and per-code raw-diagnostic
> cardinalities. A new unsuppressed finding, malformed or unregistered tagged
> directive, unknown or empty group, rule-scope mismatch, cardinality change,
> stale directive, stale generated index, or mismatched raw finding fails.
>
> A separate movement-stable global raw-diagnostic inventory records every
> diagnostic exposed by `--ignore-noqa` under the active repository rule set,
> including reasoned local suppressions outside the grouped registry. It is an
> exact aggregate by rule code, not a claim that disabled rule families are
> audited and not a second identity registry. Per-file ignores, global ignores,
> blanket file directives, threshold inflation, and baseline allowlists are not
> permitted as alternatives to review.
>
> #### [DOM-10.2.1] Approved Ruff suppression registry
>
> This subsection owns every approved suppression group and its human-reviewed
> meaning. The human table owns the stable group ID, allowed rules, approved
> directive count, approved raw-diagnostic count by rule, protected invariant,
> real proof, rejected alternatives, and approval. The local source directive
> owns its exact rule codes and group pointer. The generated index owns only
> derived repository-relative paths, qualified symbols, and actual counts.
>
> A generated symbol is the outermost enclosing function, qualified by enclosing
> class names, or `<module>` when no function owns the line. Decorator lines
> belong to their decorated function. The generator retains the physical line as
> internal identity for raw-diagnostic reconciliation and errors, but it renders
> one sorted `path::qualified_symbol` site per group. This makes ordinary line
> movement stable and makes a suppression moving between functions visible in
> review. Removing and adding the same rule within the same qualified symbol can
> remain invisible when both site set and cardinality stay fixed; this is an
> accepted residual, not a broader approval.
>
> The required local form is
> `# noqa: <codes> approved [DOM-10.2.1] [RUFF-SUP-NNN] exception`.
> The stable group points to the single durable full
> reason; source comments do not duplicate that rationale. Group IDs are unique,
> match `RUFF-SUP-[0-9]{3}`, and are never reused after retirement. A temporary
> group also names the active plan task that removes or re-evaluates it.
>
> The human table columns are `Group`, `Rules`, `Approved cardinality`,
> `Protected invariant`, `Real proof`, `Rejected alternatives`, and `Approval`.
> Approved cardinality states both directive count and raw count by code. Every
> group has at least one live directive; every human-owned rationale cell is
> non-empty. The subsection also owns exactly one canonical, lexically sorted
> `Global raw-noqa inventory:` line using backticked `CODE=count` entries.
>
> The generated location index is enclosed by unique begin/end markers and has
> columns `Group`, `Locations`, `Directives`, and `Raw diagnostics`. Rows are
> sorted by group ID; sites use repository-relative POSIX paths and qualified
> symbols; codes are lexical. Content outside the markers is human-owned and
> remains byte-for-byte unchanged during regeneration. The generator may never
> create or edit a group, rule approval, cardinality approval, invariant, proof,
> rejected alternative, or approval record.
>
> Verification commands are `uv run --extra dev python
> bin/ruff_suppression_index.py --check` and, after explicit human approval of
> every changed human-owned field, `uv run --extra dev python
> bin/ruff_suppression_index.py --write`. Check mode never writes. Write mode
> validates the complete evidence graph before replacing only the generated
> block through a same-directory temporary file and atomic `os.replace`.
> Anticipated policy mismatches exit 1; invocation, decoding, Ruff, source-read,
> and replacement failures exit 2 with one diagnostic and no traceback;
> unexpected programming errors retain their traceback. Any failure before
> replacement leaves the spec byte-for-byte unchanged.

### Related-plan backlink — append under `## Related Plans`

> - `docs/plans/2026-08-04-ruff-complexity-and-suppression-registry-plan.md`:
>   activates repository-wide C901 visibility at 10 and the reviewed,
>   symbol-keyed suppression registry and generator.

## Current Structure and Measured Baseline

The baseline commands were read-only and ran against HEAD `1ad1b8d`.

| Concern | Current evidence | Consequence for implementation |
|---------|------------------|--------------------------------|
| Ruff versions | Root environment: 0.16.1; MCP lock/environment: 0.15.21; all four dev manifests allow `ruff>=0.1.0` | Pin one exact version before freezing counts. Use 0.16.1 unless the activation review records a newer owner-approved baseline. |
| Configuration owners | Root and MCP each have `select = [E,W,F,I,B,C4,UP]`; PG and Summon inherit root configuration in their root-run gates | Retain explicit selection, add only `C901`, update both active configs together, and test semantic agreement. Root discovery descends into MCP, but Ruff resolves the nested MCP configuration for those paths; root settings do not override it. |
| Normal lint | `uv run --extra dev ruff check .` and the MCP project-local lint command both pass | Activation can start from a clean normal baseline. |
| Discovery | Root `ruff check --show-files .` discovers ordinary Python across all extension trees but misses `bin/check-cli-claims`, `bin/check-doc-paths`, `bin/check-dom15-fixtures`, `bin/check-plan-status-index`, `bin/coalesce-check`, and `bin/pytest-pg` | Add `extend-include = ["bin/*"]`; compare Ruff's filtered inventory with tracked Python/shebang paths. |
| Initial complexity | Default discovery reports 59 C901 findings. Explicitly checking the six missed scripts adds four: `bin/check-dom15-fixtures::check`, `bin/check-plan-status-index::parse_rows`, `bin/check-plan-status-index::self_test`, and `bin/coalesce-check::main`, for 63 total. Scores range 11–54. | The pinned/discovery-complete audit must reproduce 63 or stop and explain the delta before source suppressions are added. |
| Finding split | Candidate baseline: 42 production/tool findings and 21 test findings after including the four extensionless-tool findings | Review production and tests by ownership; test complexity is not automatically exempt. |
| Existing active-rule raw suppressions | Current selected rules expose one raw F401 diagnostic under `--ignore-noqa` | Expected activation aggregate is initially `C901=63`, `F401=1`, then shrinks as refactors remove C901 findings. Recompute from pinned Ruff rather than copying this estimate. |
| Disabled-family comments | Source contains reasoned `BLE001`, `SLF001`, `N802`, and `S310` `noqa` comments, but those families are not selected | Do not widen the plan into unrelated lint-family adoption; do not claim those comments are raw diagnostics. |
| CI boundary | Root lint uses explicit core/Summon paths; PG and MCP have separate lint jobs | Root CI becomes the comprehensive repository gate; extension jobs remain independent proof with the same version. |
| Release boundary | `bin/release.py` builds Ruff check and format from one shared explicit tool-path tuple | Split lint paths (`.`) from formatter paths (existing explicit set), then add the suppression check after normal Ruff. |
| Packaging | Hatch includes only `/taut/**`, README, and LICENSE; `bin/` is excluded | Adding `bin/__init__.py` for importable tests does not make the repository tool part of the wheel. Verify the wheel anyway. |

### Required reading comprehension gates

Before editing, the implementer must answer in the plan execution log:

1. Why does adding C901 only to root `pyproject.toml` fail to enforce MCP's
   project-local lint path?
2. Which six extensionless Python tools are absent from current Ruff discovery,
   and which four additional C901 findings do they contribute?
3. Why must `bin/release.py` split lint paths from format paths before lint can
   become repository-wide?
4. Which fields may `--write` change, and which human-owned fields must remain
   byte-for-byte untouched?
5. Why is `path::qualified_symbol` review identity while `noqa_row` remains the
   reconciliation identity?
6. Which existing `noqa` comments are outside the active-rule raw inventory,
   and why does this plan not enable their rule families?

If any answer is uncertain, stop and re-read the named source files and the
SimpleBroker R1 plan before editing.

## Initial C901 Disposition Ledger

The complete pinned-version audit must preserve one row per initial finding.
The plan-authoring audit below is the proposed starting disposition, not an
approval to suppress. Exact group assignment, human rationale text, and
cardinalities receive independent activation review before the strategy-B
slice. P1/P2 rows use temporary groups tied to their named refactor tasks; P3
rows may receive permanent groups only after their real proof is reproduced.

### Core, client, commands, repository tools, and release tooling

| Disposition | Finding | Score | Proposed seam or protected coupling | Real proof and stop gate |
|-------------|---------|------:|--------------------------------------|--------------------------|
| P1 | `.github/scripts/release_publication.py::read_publication` | 18 | Separate strict manifest parsing/schema and local byte verification within the standalone workflow script. Do not create a shared import dependency on local release tooling. | `tests/test_release_publication.py` manifest/allowlist/adversarial cases and cross-tool bundle acceptance. Stop on field, error-order, symlink, two-file, or digest-timing drift. |
| P3 | `.github/scripts/release_publication.py::pypi_release_files` | 11 | Retain one external-boundary parser for request, only-404 absence, normalized identity, and exact filename/digest extraction. | PyPI HTTP contract, malformed identity, digest, and network-failure tests. Reject generic fetch/response layers; reopen only for a second real parser caller. |
| P1 | `bin/release-artifact.py::verify_bundle` | 18 | Extract same-file identity, manifest, allowlist/byte, and optional-copy validators; retain one orchestration owner. | `tests/test_release_artifact.py` success, tag-family, and every-manifest-contract cases. Stop on validation/copy order or physical-file proof drift. |
| P3 | `bin/release.py::plan_tag_action` | 13 | Retain the explicit fail-closed decision table over publication and local/remote tag state. | `test_plan_tag_action*`, published-version refusal, and remote-tag conflict tests. Reject a generic rule engine or one helper per branch. |
| P2 | `bin/release.py::_run_batch_release` | 21 | Name candidate/preparation planning and dry-run rendering while retaining one batch safety-order owner. | Batch checks, filtering/no-op, release-fence, and dry-run tests. Stop if dry-run and real planning diverge or precheck/build/commit/fence/tag/push order moves. |
| P1 | `bin/release.py::main` | 12 | Extract `_run_single_release(args, target)`; keep parse, repository-settings/check-only gates, and batch selection in `main`. | Public release rerun, checks-only, dry-run, and settings-gate tests. Reject a flag-heavy unified batch/single runner. |
| P3 | `bin/check-dom15-fixtures::check` | 12 | Retain the cohesive enumerable-contract audit over one fixture table. | Tool self-test mutations, live checker, and DOM-15 fixture gate. Reject a general Markdown policy engine; require every declared rule to keep a mutation probe. |
| P2 | `bin/coalesce-check::main` | 14 | Separate pure claim/cue classification from reporting/exit selection. | Add focused characterization fixtures plus live `bin/coalesce-check`. Stop if informational local-only/foreign claims become failures or broken cues become success. |
| P3 | `bin/check-plan-status-index::parse_rows` | 14 | Retain the fail-closed parser for one Markdown section/table grammar. | `tests/test_plan_status_index.py` status/exemplar, defect, malformed, and self-application cases. Reject a general Markdown parser or partial acceptance. |
| P3 | `bin/check-plan-status-index::self_test` | 12 | Retain one bounded installed-tool mutation smoke over the closed vocabulary. | Direct `--self-test` plus the stronger pytest matrix. Reject a mini test framework inside the executable. |
| P3 | `taut/_scripts.py::_extract_pytest_runner_overrides` | 12 | Retain the single-pass argv grammar and precedence; SimpleBroker retained the same owner. | `tests/test_dev_scripts.py` joined/separate/repeated/missing-value cases. Stop on token order or pass-through grammar drift. |
| P2 | `taut/client/__init__.py::TautClient.watch` | 12 | Extract only canonical filter resolution/deduplication; retain identity, DM cache, validation, then runtime construction order. | Watcher invalid-filter/persistent-handle and DM route/dedup/corruption tests. Stop if invalid filters allocate runtime or aliases schedule twice. |
| P3 | `taut/client/_base.py::_ClientBase._resolve_target` | 11 | Retain one target-precedence and backend error-translation boundary. | Explicit missing path, trusted handoff, incomplete/conflicting config, and shared backend tests. Reject backend-specific or separate ambient resolvers. |
| P3 | `taut/client/_identity.py::IdentityMixin._resolve_member` | 43 | Retain the explicit selector/token/claim/anchor-healing/human-fallback/creation state owner. | Dense real-state identity and shared rejoin/claim-migration suites. Reopen only if a named resolution context reduces duplication without moving capture, timestamp, mutation, healing, or race precedence. |
| P3 | `taut/client/_identity.py::IdentityMixin._create_member` | 11 | Retain the bounded collision/race/recovery protocol and evidence publication. | Collision, lost-race, explicit-selection, claim-authority, and unowned-claim tests. Reject generic retry machinery or split publication. |
| P2 | `taut/client/_messaging.py::MessagingMixin.read_unread` | 12 | Extract one same-file membership-page reader; decode a full page before advancing that membership cursor. | Per-membership limit, one-page cursor, decode-failure, validation, and shared pagination tests. Stop on partial cursor advancement or global-limit drift. |
| P2 | `taut/commands/_dispatch.py::_dispatch` | 22 | Separate selected-command parse/setup from run/error/cleanup lifecycle while retaining one public bootstrap boundary. | Registry load/run, parser/error containment, lazy close, primary-over-cleanup, and terminal-policy tests. Stop on exit, stream, lazy-load, or cleanup-precedence drift. |
| P2 | `taut/commands/_registry.py::CommandRegistry.__init__` | 12 | Extract pure external-manifest normalization/collision selection; retain one immutable snapshot owner. | Reserved slot, broken/incompatible manifest, deterministic conflict/order, side-effect-free discovery, and installed-wheel tests. Stop on mutable or repeated entry-point discovery. |
| P3 | `taut/identity.py::capture_host_identity` | 11 | Retain the ordered Linux/Darwin/hostname portability fallback. | Platform-ID preference/failure/fallback tests. Reject strategy classes or subprocess abstractions solely for score. |

### Summon production and test-support owners

| Disposition | Finding | Score | Proposed seam or protected coupling | Real proof and stop gate |
|-------------|---------|------:|--------------------------------------|--------------------------|
| P2 | `extensions/taut_summon/taut_summon/_control.py::ControlLoop.run` | 20 | Extract terminal STOP outcome construction after the reactor turn/recovery loop; retain process/wait/recovery in one owner. | Control-loop, correlated/cross-process ping, and STOP release-confirmation tests. Stop on generation reacquisition or reply-after-release order drift. |
| P3 | `extensions/taut_summon/taut_summon/_driver.py::SummonDriver._first_summon` | 19 | Retain the compensating claim/create/detect/close/publish/release transaction. | First-summon, collision, exhaustion, cleanup, and concurrent implied-summon tests. Reject helpers that pass partial creator/member/claim ownership. |
| P1 | `extensions/taut_summon/taut_summon/_driver.py::SummonDriver._supervise` | 25 | Keep one outer lifecycle owner but extract named bootstrap, orientation, live-wait, teardown, and crash/backoff phase results. | Attach, pump failure, watcher rebuild, crash/resume, orientation STOP, and control-fatal tests. Reclassify P3 if helpers shuttle most live state or obscure teardown order. |
| P3 | `extensions/taut_summon/taut_summon/_driver.py::SummonDriver._teardown_generation` | 14 | Retain the single primary/close/join/note/error-publication precedence owner. | Generation cleanup and join-timeout precedence tests. Reject separate close/join exception owners. |
| P2 | `extensions/taut_summon/taut_summon/_driver.py::SummonDriver._pump_event` | 13 | Extract owner-local event handlers while retaining the generation lock through dispatch and side effects. | Stale-generation, flood/ledger, terminal-mode, and post-failure tests. Stop if lock or `last_activity` ownership moves. |
| P2 | `extensions/taut_summon/taut_summon/_driver.py::SummonDriver._attach_if_needed` | 17 | Separate availability/preflight reporting from terminal-lease execution; retain exact lease exit/exception precedence. | Attach, unavailable-terminal, lease acquire/restore, and rich-host tests. Reject generic context wrapping that hides `__exit__` arguments. |
| P1 | `extensions/taut_summon/taut_summon/_driver.py::SummonDriver._start_watcher_thread` | 15 | Promote the nested attempt lifecycle to a named owner-local method/value; retain one thread owner. | Watcher failure/rebuild, pre-publication stop, checked join, and provider-close isolation tests. Stop on stop-capture, publish/recheck, join, or cursor drift. |
| P1 | `extensions/taut_summon/taut_summon/_driver.py::_run_watcher` (nested raw Ruff symbol) | 13 | Same refactor and temporary group as the preceding row. The generated site is `extensions/taut_summon/taut_summon/_driver.py::SummonDriver._start_watcher_thread`; until removal, that one site has two directives and raw `C901=2`. | Same watcher-attempt suite. Stop if a second/global watcher owner appears. |
| P3 | `extensions/taut_summon/taut_summon/_pty.py::PtyHandle.attach` | 18 | Retain one select-loop owner for three inputs, detach state, wake/shutdown, restoration, and bridge teardown. | PTY bridge/chord, forwarding, injection, wake, output-failure, and restoration tests. Reject per-fd threads or fragmented multiplex ownership. |
| P3 | `extensions/taut_summon/taut_summon/_pty.py::PtyHandle._event_stream` | 12 | Retain the single-consumer read/reply/activity/exit/master-retirement state machine. | Responder, failed reply, close/full-input, and single-consumer tests. Reject separating response state from activity and master-close ownership. |
| P3 | `extensions/taut_summon/taut_summon/_pty.py::PtyHandle._write_all` | 11 | Retain fd lease, epoch rechecks, serialized writes, wait retry, and retirement together. | Cancellation, retirement, fd-reuse, signal-reentry, and full-input tests. Reject generic write loops without pre/post syscall checks. |
| P2 | `extensions/taut_summon/taut_summon/_pty.py::_validate_spec` | 11 | Extract small ordered dimension/timing/quiet-period validators. | Unsafe spawn/timing and conformance malformed/numeric cases. Stop on accepted types, first-failure order, or message drift. |
| P3 | `extensions/taut_summon/taut_summon/_pty.py::_TerminalResponder._handle_csi` | 14 | Retain explicit query/reply protocol dispatch and unsupported-query marking. | Live query, startup/clamp, incomplete-scan, and recovery tests. Reject opaque callback tables or protocol modules without a real subprotocol owner. |
| P3 | `extensions/taut_summon/taut_summon/_stream.py::StreamJsonHandle.close` | 12 | Retain concurrent close election, escalation, streams, errors, and primary-error precedence in the sole blocking finalizer. | Concurrent close, one terminal request, timeout, primary preservation, and reap tests. Reject separate kill/stream-close owners. |
| P3 | `extensions/taut_summon/taut_summon/scripted_provider.py::_run_steps` | 16 | Retain the compact executable scenario-opcode dispatcher. | Scripted echo/session/flood/stall/exit/raw-line and driver activity tests. Require a firing test per opcode; reject one trivial function per opcode. |
| P2 | `extensions/taut_summon/tests/fixtures/fake_tui.py::main` | 16 | Extract fixture-local onboarding and command-loop phases. | PTY responder/attach/orientation/rich-host/live fixture tests. Stop on byte/JSONL/raw-mode/RUN behavior drift; do not move into production. |
| P2 | `extensions/taut_summon/tests/fixtures/local_llm_tui.py::_call_local_llm` | 11 | Extract pure OpenAI-shaped response validation from real HTTP transport. | URL, timeout, HTTP, malformed-response, and sentinel tests. Keep real `urlopen`; stop on diagnostic shape drift. |
| P2 | `extensions/taut_summon/tests/test_interaction.py::test_controller_signal_opt_in_restores_exact_handlers` | 12 | Move setup/expected outcome into parameter data/helper; retain real signal install/restore. | The test plus install rollback and restore-precedence neighbors. Stop if real signal boundary becomes mocked. |
| P3 | `extensions/taut_summon/tests/test_interaction.py::test_rich_host_real_pty_lease_wires_once_then_wired_resume_skips_lease` | 16 | Retain the cross-generation real-PTY first-run/wired-resume/STOP causal proof. | The test and stop-during-attach restoration neighbor. Reject splitting the cross-generation assertion. |
| P2 | `extensions/taut_summon/tests/test_live_harness.py::test_live_pty_harness_reaches_ready_and_accepts_injection` | 22 | Extract narrowly named readiness and cursor-catch-up polling helpers. | Live matrix plus readiness/fatal-reason tests. Keep real installed harness/controller; stop on deadline or strict/skip policy drift. |
| P2 | `extensions/taut_summon/tests/test_live_local_llm.py::_CountingProxy.__enter__` | 11 | Move handler construction/forwarding to a named test-harness owner. | Local-LLM failure and sentinel tests through real loopback HTTP. Stop on body/status/header/502 evidence drift. |
| P3 | `extensions/taut_summon/tests/test_live_local_llm.py::test_local_llm_pty_harness_posts_sentinel` | 11 | Retain one end-to-end discovery/prewire/proxy/PTY/sentinel/cleanup acceptance story. | The test plus diagnostics and recovery helpers. Reject mocked stage splitting. |

### MCP, PostgreSQL, root tests, and reusable probes

| Disposition | Finding | Score | Proposed seam or protected coupling | Real proof and stop gate |
|-------------|---------|------:|--------------------------------------|--------------------------|
| P3 | `extensions/taut_mcp/taut_mcp/_commands.py::execute_command` | 29 | Retain the explicit closed 17-tool allowlist and per-tool validation/public-client/result semantics. | Ordinary proxy, owner-thread, and first-lazy-request matrices. Reject handler maps, CLI reflection, or generic adapters. |
| P3 | `extensions/taut_mcp/taut_mcp/_commands.py::record_object` | 11 | Retain the closed type-discriminated serializer as the output-shape audit surface. | Exact deletion/reaction/notification/channel/thread and schema tests. Reject reflection or generic dataclass serialization. |
| P2 | `extensions/taut_mcp/taut_mcp/_process_reactor.py::ProcessReactor.ensure_workspace` | 16 | Extract pure UTF-8/path/existing/candidate/capacity preflight; retain creation, secret clearing, publication, deadline, and shielded cancellation together. | Idempotent alias, concurrent publication, failure, timeout, and cancellation tests. Stop if token/fingerprint cleanup or candidate publication gains two owners. |
| P3 | `extensions/taut_mcp/taut_mcp/_process_reactor.py::ProcessReactor._on_resolved` | 11 | Retain one alias/candidate/fingerprint/retirement/deadline/validation arbitration transition. | Alias, concurrent candidate, and normative routing-matrix tests. Reject predicate helpers that obscure terminal action order. |
| P3 | `extensions/taut_mcp/taut_mcp/_process_reactor.py::ProcessReactor._drain_events` | 11 | Retain the closed event dispatcher plus mandatory dead-owner reap. | Maintenance, terminal, fault, detach, and identity-loss tests. Reject visitor/handler registries. |
| P3 | `extensions/taut_mcp/taut_mcp/_process_reactor.py::ProcessReactor.aclose` | 15 | Retain admission close, timer/task cancel, candidate/entry settlement, bounded drain, escalation, and clearing in one nonblocking owner. | Normal shutdown, hard deadline, and stdio EOF/transport tests. Stop if event loop blocks or normal stop becomes fault. |
| P1 | `extensions/taut_mcp/taut_mcp/_workspace_reactor.py::run_workspace_reactor` | 54 | Introduce one private same-module state owner with named wait/control, bootstrap, validation/publication, command/cancel, snapshot, and cleanup phases; retain exactly one child thread. | Full process-reactor, owner-thread/cancel/identity-loss, resource, and live PG suites. Reclassify P3 if phase methods pass most live state or create another owner. |
| P3 | `extensions/taut_mcp/taut_mcp/server.py::create_server` | 27 | Retain one server assembly unit whose nested handlers share bus, listener, lifespan, protocol-era, tool, and SDK registration state. | Dual-era, empty stdio, discovery, and unknown-tool tests. Reject top-level handler churn or parallel legacy/modern servers. |
| P3 | `extensions/taut_mcp/tests/test_stdio_server.py::test_broken_stdout_after_initialize_is_a_clean_transport_exit` | 13 | Retain one real-pipe subprocess transport protocol through peer close, saturation, clean exit, and cleanup. | The test plus broken-transport platform classifier cases. Stop if pipes/process are mocked or forced cleanup counts as clean exit. |
| P2 | `extensions/taut_mcp/tests/test_stdio_server.py::test_stdio_cancellation_sends_no_result_and_keeps_server_live` | 14 | Extract only a raw-stdio JSON-RPC harness; retain both wire-era frame sequences and absent-id/present-id assertions in the test. | The test in legacy/modern modes plus process-reactor cancellation tests. Stop if harness interprets cancellation or hides frames. |
| P3 | `extensions/taut_pg/tests/test_reactor.py::test_taut_watcher_polls_and_refreshes_membership_without_native_waiter` | 12 | Retain one live-PG fallback refresh/delivery/cursor/health/cleanup scenario. | The test plus shared watcher lifecycle tests. Reject mocked PG/watcher/threads. |
| P3 | `extensions/taut_pg/tests/test_reactor.py::test_taut_watcher_native_waiter_rebinds_on_membership_topology_change` | 11 | Retain the causal add/remove/rebind/close/native-wake sequence. | The test plus shared topology tests. Reject split add/remove tests or fake waiters. |
| P3 | `tests/helpers/base_reactor_sigint_probe.py::_run_probe` | 11 | Retain the isolated real-signal waiter-replacement/topology/close protocol. | Reentrant SIGINT and watchdog tests. Reject in-process or mocked-signal proof. |
| P3 | `tests/test_cli.py::test_cli_watch_json_flushes_records_while_live` | 12 | Retain the real-subprocess pre-exit message/notification NDJSON flush proof. | The test plus adjacent cursor/policy cases. Reject post-exit-only observation or fake pipes. |
| P3 | `tests/test_cli_claims.py::_shell_claim_tokens` | 13 | Retain the one-pass shell precedence parser. | Extraction/tokenization matrices. Reject generic parser combinators or branch predicates. |
| P3 | `tests/test_cli_claims.py::_validate_sources` | 12 | Retain deterministic extraction/resolution/exemption/stale/count audit ownership. | Validation defects and repository self-application. Reject broad or unconsumed exemptions. |
| P2 | `tests/test_command_registry.py::test_registry_watch_sigint_path_stops_watcher_and_closes_client` | 11 | Extract a local stream/client/watcher harness and separate JSON shutdown from human safe-render assertions. | Current test plus watch rendering/lifecycle neighbors. Stop if exact stop, close, flush, or escaping assertions weaken. |
| P3 | `tests/test_command_registry.py::test_registry_watch_flushes_dynamic_membership_and_preserves_broken_pipe_cursor` | 13 | Retain the real SQLite/thread/output/cursor replay transaction-boundary proof. | The test plus closed-pipe cursor case. Reject call-count storage/output mocks. |
| P2 | `tests/test_direct_messages.py::test_corrupt_dm_state_fails_closed_before_queue_or_watch_runtime` | 16 | Extract only a named helper for the 13 real-state corruptions; retain all fail-closed operations and no-construction assertions. | Parameter matrix and DM integrity tests. Stop if any corruption loses a firing case or storage becomes synthetic. |
| P3 | `tests/test_identity.py::test_capture_psutil_process_reads_best_effort_fields` | 11 | Retain the local fake protocol beside one exact `ProcessInfo` assertion. | The test and psutil-failure neighbors. Reject a reusable fake hierarchy. |
| P3 | `tests/test_release_artifact.py::test_verify_bundle_fails_closed_for_each_manifest_contract` | 11 | Retain the explicit adversarial manifest/filesystem/tag checklist. | Parameterized test plus bundle success/CLI failure tests. Reject mutation DSLs or synthetic verifier inputs. |
| P2 | `tests/test_release_script.py::test_public_release_flow_commits_preparation_then_reuses_it_after_failure` | 13 | Extract repository builder and event-recording transport; retain real Git, failed precheck, preparation commit, reused SHA, and phase order in one test. | The test and release precheck/metadata/tag/rerun suites. Stop if Git becomes mocked or rerun/order evidence weakens. |

Plan-authoring totals: **63 findings: 7 P1, 20 P2, and 36 P3**. The two
watcher-thread diagnostics share one generated symbol until T7 removes the
nested owner; the initial raw cardinality must count both diagnostics even
though the generated site set renders once.

Disposition meanings:

- **P1:** a concrete correctness weakness, false-confidence test, or clear
  ownership seam should be addressed in the first structural slice.
- **P2:** an owner-local extraction or duplication removal is plausible and
  should be attempted with characterization proof; retain only if the proposed
  seam passes the stated stop gate.
- **P3:** retain as one cohesive owner; the registry records why a score-only
  split would make ownership, error order, atomicity, or causal proof worse.

### Temporary-task assignment and activation-group freeze

The temporary-task owner is deterministic, not left for activation-time
inference:

- P1/P2 production and repository-tool rows under `taut/`, `bin/`, or
  `.github/scripts/` belong to T5.
- P1/P2 rows under `extensions/taut_mcp/` or `extensions/taut_pg/` belong to
  T6, including a test row when it is closed in the same reviewable change as
  its production owner.
- P1/P2 rows under `extensions/taut_summon/` belong to T7, including a test row
  when it is closed in the same reviewable change as its production owner.
- All other P1/P2 test and harness rows belong to T8. If T5–T7 deliberately
  defer an extension test row, its group is revised under review to name T8
  before that owner slice closes.

T3A freezes the exact activation groups after the pinned T2 audit and before
any source directive is added. It appends a complete table to this plan or a
content-addressed audit artifact linked from the execution evidence with these
columns:

| Group | Rules | Directives | Raw by code | Member raw findings | Lifetime/task | Protected invariant and proof |
|-------|-------|-----------:|-------------|---------------------|---------------|-------------------------------|

Every one of the 63 raw findings must appear exactly once. P3 groups are
permanent candidates. P1/P2 groups name T5, T6, T7, or T8 using the rules
above. The outer and nested watcher findings share one T7 group with two
directives, raw `C901=2`, and one rendered generated site. No group ID, merge,
cardinality, or rationale is invented while editing source in T4.

## Invariants and Constraints

### Static-analysis and approval invariants

- One exact Ruff version owns all recorded findings. No manifest, lock, CI job,
  or local documented command may silently resolve a different version.
- Normal Ruff is clean at every completed slice. Raw Ruff remains intentionally
  nonzero and exactly reconciled.
- Every C901 finding has exactly one local directive and exactly one approved
  group; no finding is approved only because it existed before activation.
- No per-file ignore, global C901 ignore, blanket `# ruff: noqa`, threshold above
  10, or baseline allowlist is introduced.
- A group approves only its declared rule set, directive count, raw count, and
  protected invariant. IDs are never reassigned to unrelated owners.
- The generator uses Ruff as the sole discovery and diagnostic owner. It does
  not reimplement rule semantics or infer diagnostics from source text.
- The generated block is review evidence, not authority. It cannot update the
  human table or source directives.
- Root and project-local MCP C901 results must agree for MCP paths under the
  pinned version. A mismatch is a stop condition, not a count to normalize.

### Behavior and architecture invariants

- Public Python signatures, CLI help/exit codes/output, MCP schemas and wire
  behavior, Summon signal/PTY/control semantics, SQL behavior, and release
  publication order remain unchanged.
- Extract helpers only at named ownership seams. Do not create pass-through
  wrappers, generic dispatcher frameworks, generic state-machine runtimes, or
  cross-module helpers solely to lower a score.
- Keep transaction, lock, cancellation, cleanup, terminal-event, release SHA,
  and primary-error precedence with their current owner unless a targeted test
  proves the new seam preserves them.
- Tests that currently express causal thread/process/PTY/SQLite behavior remain
  real. A lower score obtained by mocking the owner is a regression.
- Existing separate root, PG, Summon, and MCP test/type-check environments stay
  separate. A shared Ruff version does not authorize merging dependency graphs.
- No new runtime or development dependency is introduced. Tightening the
  existing Ruff dependency is the only dependency-manifest change.
- No unrelated lint family is enabled. Preview, BLE, SLF, N, and S adoption are
  separate policy decisions.

### Generator and failure-path invariants

- Check mode is read-only. Write mode validates first and atomically replaces
  only the unique generated block.
- Missing/duplicate/reversed markers, malformed human rows, malformed source
  pointers, unknown/empty groups, rule mismatch, count mismatch, stale index,
  invalid Python, unreadable input, unsafe Markdown paths, and replacement
  failure all fail closed without partial writes.
- Policy mismatch is exit 1. Evidence/tool failure is exit 2. Unexpected code
  defects retain tracebacks.
- CRLF, non-ASCII content, permissions, and all bytes outside the generated
  markers survive a successful write.
- The same-symbol remove/add blind spot documented in [DOM-10.2.1] is accepted;
  do not silently claim stronger identity semantics.

## Anti-Mocking Rules

- Run the real pinned Ruff executable for discovery, normal lint, raw JSON, and
  threshold probes. Do not mock Ruff output in acceptance tests.
- Use real temporary repositories, files, Markdown, AST parsing, tokenization,
  newline styles, and the production CLI for generator tests.
- Use real `os.replace` on the success path. A focused failure-injection test may
  replace only `os.replace` to prove original-file preservation and temp cleanup.
- Use real Git tracked-file output or a checked fixture generated from it for the
  repository discovery comparison; do not hand-maintain a second source list.
- Complexity refactors retain their closest real SQLite, process, thread, PTY,
  backend, workflow, or subprocess proof. Mocks may remain only at existing
  external/nondeterministic boundaries.
- Workflow and release command-shape tests may parse text or inspect planned
  command tuples, but the direct Ruff and generator commands must also run.

## Rollout, Rollback, and One-Way Doors

Safe sequence:

1. review this plan, the proposed spec delta, and every initial disposition;
2. pin and reproduce the exact audit in a read-only activation revision;
3. atomically promote [DOM-10.2]/[DOM-10.2.1] with configuration, initial
   directives/groups, tool, generated index, tests, CI/release gates, and docs;
4. capture the promotion baseline identifier;
5. land characterization proof before each structural refactor;
6. refactor one ownership slice at a time and remove only the suppressions that
   no longer fire;
7. reconcile the final registry and run every repository/extension/package gate.

Rollback:

- The activation slice is one atomic policy unit. Reverting it removes the spec
  policy, version pins, configuration, directives, tool, generated block, and
  enforcement together. Do not revert only the generated index or only C901.
- After activation, each structural slice is independently revertible while the
  audit policy remains. Reverting a refactor must regenerate/reconcile any
  suppression that becomes live again; do not raise the threshold.
- Keep the exact Ruff pin during partial rollback. A version rollback requires a
  fresh raw audit and registry reconciliation in the same change.
- There is no data migration, public rollout, or expected one-way door. The only
  filesystem mutation is the generator's atomic spec rewrite; its original-file
  preservation is an acceptance gate.

Post-merge success is observable in CI: normal root and extension Ruff jobs are
clean, the suppression-index check is current, and no unreviewed C901 finding can
merge. There is no runtime post-deploy signal because product behavior does not
change. A runtime regression discovered after a refactor reverts that refactor
slice while retaining the policy and characterization test.

## Dependency-Ordered Tasks

### T1 — Independent plan, delta, and disposition review

Files/read set:

- this plan and its `## Proposed Spec Delta`
- both active Ruff configurations and all four dev manifests
- current CI/release gate owners
- the complete 63-finding audit and source owners
- the SimpleBroker source plans, generator, and R1 tests at `4d4f61be`

Actions:

1. Have a different-family reviewer challenge the class, exact policy text,
   version/discovery boundary, every P1/P2/P3 disposition, proposed group
   boundaries, test realism, activation atomicity, and rollback.
2. Reproduce every factual finding before changing this plan.
3. Append every disposition to `## Review Log`; revise the mutable plan text for
   accepted findings and record material scope/authority revisions in
   `## Revision Log`.

Done signal: reviewer can implement the plan confidently and correctly and
returns PASS after all blockers are resolved.

Stop if review finds that one repository-wide Ruff binary cannot faithfully
audit a nested project configuration, or that exact version alignment changes
effective diagnostics in a way the current ledger does not cover.

### T2 — Freeze the canonical Ruff and discovery baseline

Files:

- `pyproject.toml`
- `extensions/taut_pg/pyproject.toml`
- `extensions/taut_summon/pyproject.toml`
- `extensions/taut_mcp/pyproject.toml`
- `extensions/taut_summon/uv.lock`
- `extensions/taut_mcp/uv.lock`
- this plan's execution evidence and initial ledger

Actions:

1. Use Ruff 0.16.1 as the candidate canonical version. Tighten all four
   existing dev dependencies to `ruff==0.16.1`; regenerate only the two existing
   locks. Do not introduce a root or PG lock as an incidental policy change.
2. Before landing configuration changes, run the candidate binary explicitly
   over `.` plus the six extensionless scripts and record the JSON/blobs that
   reproduce the 63-finding ledger.
3. Compare root and MCP project-local results for MCP paths. Require exact
   path/`noqa_row`/code agreement.
4. If the count or identity differs, update the ledger and human-group proposal,
   explain the cause, and re-run the T1 review on that delta.
5. Record the implementation baseline SHA or diff-base plus manifest/lock blobs.

Red proof: add policy fixtures that fail on divergent Ruff constraints and
missing tracked Python/shebang paths before changing manifests/configuration.
The version test compares each running Ruff binary with the exact manifest pin;
matching manifest strings alone are insufficient.

Done signal: one exact Ruff version and one complete 63-finding JSON audit are
reviewed and reproducible; root/MCP overlap agrees exactly.

Stop if lock regeneration changes any non-Ruff dependency, the candidate Ruff
cannot parse all supported Python versions, or the root/MCP result sets differ.

### T3 — Port the generator and hostile-input contract under red tests

Files:

- `bin/__init__.py`
- `bin/ruff_suppression_index.py`
- `tests/test_ruff_suppression_index.py`

Actions:

1. Port the SimpleBroker R1 implementation and tests from `4d4f61be`.
2. Adapt only the default spec path, [DOM-10.2.1] heading/pointer grammar,
   documented Taut commands, fixture text, and Taut path expectations.
3. Retain Ruff-owned discovery; filtered `.py`/`.pyi`/Python-shebang inventory;
   AST outermost/class-qualified symbol resolution; Python-comment-token source
   scanning; raw JSON multiplicity; strict human grammar; global inventory;
   complete reconciliation; symbol rendering; byte-preserving marker rewrite;
   atomic replacement; and exit 0/1/2 behavior.
4. Preserve the script's importable `run()` seam and thin `main()` CLI. Do not
   add a library package, plugin system, generic Markdown framework, or alternate
   source scanner.
5. Confirm `bin/__init__.py` does not enter built wheels.
6. Document that Taut intentionally uses `uv run --extra dev` without
   SimpleBroker's `--frozen --no-sync`: Taut has no root lockfile, while exact
   manifest pins and running-binary policy tests own reproducibility here.

Red/green cases include clean check, stale index, idempotent write, group growth
and shrinkage, unknown/empty/duplicate groups, malformed source pointer, rule
outside group, raw multiplicity, invalid syntax, unreadable source, fenced and
string marker mimicry, missing/duplicate/reversed markers, unsafe Markdown path,
CRLF/non-ASCII preservation, repository paths with spaces, non-Python Ruff
discovery entries, replacement failure, clean exit classes, and self-application.

Done signal: the isolated fixture suite passes with the real pinned Ruff; the
repository self-check fails closed only because the not-yet-promoted registry is
absent.

Stop if the port needs to weaken a SimpleBroker failure case, catch unexpected
exceptions, write outside the generated markers, or invent a second config.

### T3A — Freeze and review exact activation groups

Files/evidence:

- the pinned T2 raw JSON audit;
- the complete 63-row disposition ledger;
- this plan's `Temporary-task assignment and activation-group freeze` table or
  a content-addressed audit artifact linked from `## Execution Evidence`.

Actions:

1. Assign stable `RUFF-SUP-NNN` IDs and group only findings that share one
   protected invariant, proof owner, lifetime, and task.
2. Record rules, directive count, raw count by code, every member raw finding,
   permanent-candidate versus T5–T8 lifetime, protected invariant, proof, and
   rejected alternatives.
3. Prove all 63 raw findings occur exactly once and that the watcher pair is the
   deliberate two-directive/one-rendered-site group.
4. Obtain focused independent review of every merge, cardinality, and human
   rationale before T4 edits source.

Done signal: the activation table is complete, pinned to the T2 audit, and
independently accepted; T4 can copy exact IDs and counts without inventing
approval evidence.

Stop if any finding lacks one group, appears twice, or a proposed group spans
different invariants, proof owners, or removal tasks.

### T4 — Atomic spec, C901, registry, and enforcement activation

Files:

- all T2/T3 files
- `docs/specs/01-development-documentation-operating-model.md`
- every live initial C901 source location
- `tests/test_ruff_policy.py`
- `tests/fixtures/ruff-enabled-rules.txt`
- `.github/workflows/test.yml`
- `.github/workflows/test-pg-extension.yml`
- `.github/workflows/test-mcp-extension.yml`
- `bin/release.py`
- `tests/test_github_workflows.py`
- `tests/test_release_script.py`
- `docs/implementation/02-repository-map.md`
- new `docs/implementation/08-complexity-and-suppression-policy.md`
- `docs/implementation/00-implementation-index.md`
- this plan and `docs/plans/README.md`

Actions:

1. Promote the exact [DOM-10.2]/[DOM-10.2.1] delta and spec backlink.
2. Set `extend-include = ["bin/*"]`; retain both configurations' explicit
   `select` lists and add only `C901`; add `mccabe.max-complexity = 10`; retain
   existing global ignores and explicit format paths.
3. Copy the reviewed T3A human groups and global raw inventory. Add exactly
   one approved source pointer to every live C901 finding, including temporary
   T5–T8 groups.
4. Run `--write` once to create the generated symbol index, then run `--check`.
5. Add the policy suite proving version alignment, effective rule inventory,
   tracked discovery, threshold 10/11 firing, absence of broad suppression
   paths, normal Ruff cleanliness, and delegation to the production reconciler.
6. Make root CI run `ruff check .`, then the generator `--check`. Retain the
   separate PG and MCP lint jobs over their existing scoped paths with the
   canonical version/configuration; they do not run the repository-wide
   generator.
7. Split `bin/release.py` lint and format path ownership. Ruff check uses `.`;
   format retains the existing explicit paths. Add the generator check after
   normal Ruff and before formatting/type checking.
8. Add/update workflow and release command-shape firing tests.
9. Add the implementation note explaining ownership, symbol-vs-line identity,
   approval boundary, failure behavior, the accepted same-symbol residual, and
   why Taut's no-root-lock invocation uses exact pins plus binary proof instead
   of SimpleBroker's `--frozen --no-sync` flags.
10. Record the promotion baseline identifier before any structural refactor.

Done signal: normal Ruff is clean; raw audit reports the exact reviewed initial
inventory; every C901 location/directive/group/generated row matches; root and
MCP overlap agrees; focused policy/generator/workflow/release tests pass; the
spec/implementation/code backlink chain closes.

Stop if activation requires a per-file ignore, threshold change, undocumented
group, formatting expansion, product behavior change, or unreviewed registry
row. Do not begin T5 without the promotion baseline.

### T5 — Core, repository-tool, and release ownership refactors

Scope: P1/P2 rows in `taut/`, `bin/`, and `.github/scripts/` assigned to this
slice by the initial ledger.

Actions for each finding:

1. Add or identify the closest characterization/contract test and watch it pass
   before editing. Add a failing regression first if the audit found a concrete
   defect or false-confidence test.
2. Extract only the named ownership seam; record before/after score.
3. Preserve error priority, release order/exact SHA, parser precedence,
   transaction/lock ownership, and output contracts named by the ledger.
4. Run the closest real suite, normal Ruff, raw reconciliation, mypy for touched
   production/tests, and generator `--check`.
5. Remove a directive/group only when raw Ruff proves the finding is gone. If a
   row remains above 10, update its permanent rationale only after focused
   independent review.

Done signal: every scoped P1/P2 row is at or below 10 or independently
reclassified P3 with current real proof; no temporary T5 approval remains.

Stop when extraction passes more live state than it removes, duplicates an
execution path, crosses an ownership module without two real adapters, or
changes a public/release result.

### T6 — MCP and PostgreSQL ownership refactors

Scope: P1/P2 rows in `extensions/taut_mcp/` and `extensions/taut_pg/`.

Actions:

1. Preserve MCP legacy/modern wire behavior, workspace/token continuity,
   cancellation, notification, stdio error, and reactor ownership contracts.
2. Keep process/workspace reactors real in tests. Do not turn their state into
   mock call counts or build a generic state-machine runtime.
3. Preserve PG watcher membership, waiter replacement, and real backend proof.
4. Run root and MCP project-local Ruff after every MCP edit and require exact
   C901 agreement under the pinned version.
5. Use the same remove-or-reviewed-reclassify process as T5.

Done signal: every scoped temporary group is removed or permanently reapproved;
MCP and PG focused suites, type checks, both Ruff contexts, and registry check
pass.

Stop if a refactor changes MCP schemas/metadata, process ownership, cancellation
order, PG backend semantics, or requires merging extension environments.

### T7 — Summon lifecycle and PTY ownership refactors

Scope: P1/P2 rows under `extensions/taut_summon/`.

Actions:

1. Preserve object-local rich-host state, provider-child identity, explicit
   signal ownership, one-signal terminal retirement, generation/PTY/write
   leases, event ordering, ledger/control behavior, and cleanup precedence.
2. Keep real PTYs, threads, subprocesses, signal paths, and deterministic
   synchronization real where they are the behavior under proof.
3. Separate mode parsing, immutable request construction, or terminal result
   formatting only when the ledger names that seam; do not split the live driver
   state machine across shallow helpers.
4. Run the deterministic, live-harness, and local-LLM lanes in their existing
   fresh invocations; do not collapse them into one worker lifetime.
5. Use the same remove-or-reviewed-reclassify process as T5.

Done signal: every scoped temporary group is removed or permanently reapproved;
Summon focused/real-process lanes, typing, normal/raw Ruff, and registry check
pass.

Stop if a lower score weakens lifecycle ownership, timeout diagnostics, PTY
cleanup, signal behavior, or the separation of fresh real-process lanes.

### T8 — Complex test and harness proof review

Scope: P1/P2 test findings not closed with their production owner in T5–T7.

Actions:

1. Treat causal real-process, thread, PTY, SQLite, workflow, release, and
   manifest tests as proof owners, not production refactor opportunities.
2. Extract setup/assertion helpers only when the helper has a stable semantic
   name and reduces duplicated state without hiding actor identity, order,
   liveness, cleanup, or the exact failing case.
3. Reject generic test DSLs and fixture abstractions that make the scenario
   harder to read or replace the owner under proof.
4. Strengthen any audit-discovered false-confidence assertion before reducing
   complexity.
5. Use the same remove-or-reviewed-reclassify process as T5.

Done signal: every test temporary group is removed or permanently reapproved;
each retained test has a causal-proof rationale and the real owner still runs.

Stop if extraction hides which actor/event failed, replaces real behavior with
mocks, or makes cleanup success indistinguishable from forced fallback.

### T9 — Final registry, traceability, and repository closure

Files:

- final source directives
- [DOM-10.2.1] human registry and generated block
- Ruff policy/generator tests and enabled-rule fixture
- implementation note/index/repository map
- CI/release gates and their tests
- this plan and status index
- `docs/lessons.md` only for a genuinely reusable correction

Actions:

1. Re-run raw Ruff and remove every obsolete directive/group. Never renumber or
   reuse surviving/retired IDs.
2. Independently challenge each remaining rationale against final code and real
   proof. Reject score-only, mock-only, stale, or generic reasons.
3. Reconcile spec, plan, implementation note, source, tests, CI, release helper,
   and generated evidence.
4. Run full root, PG, Summon, MCP, docs, static, packaging, and release-planning
   gates from the current state.
5. Run independent completed-work review with the promotion baseline, final
   disposition/count delta, full diff, and verification evidence.
6. Update the execution/review/deviation logs and flip the status index to
   `completed` only after implementation is committed and current gates pass.
7. Evaluate whether the port exposed a durable correction to planning, testing,
   or generator guidance; update `docs/lessons.md` only when it did.

Done signal: no temporary group remains; normal Ruff is clean; every raw active
suppression is accounted for; generated evidence is current; all required gates
and completed-work review pass; the committed plan status is closed.

### T10 — Post-review locality remediation

Class: continuation of this Class 5+P plan. The human [DOM-10.2.1] registry may
gain reviewed permanent groups. The user-directed MCP traceback decision also
revises [MCP-4]/[MCP-10], so T10 is implementation with a spec revision;
promotion strategy B applies to the exact small delta below.

Baseline: `docs/specs/05-taut-mcp.md` at committed diff base
`1ad1b8d0cd593ff0b7a3b5bf3fa3ec92df5e9cb3`; the file was unchanged in the
worktree before this T10 delta. The remaining T10 baseline is the uncommitted
worktree against that diff base, after T9 implementation and the 2026-08-05
expert locality review. The promoted atomic worktree identifier is
`spec-sha256:1e792adf8c13c2a81ec6837b5a437bbd9ec7610ee3d0fffb6653a32f5fb74d4b`.

#### T10 proposed spec delta

| Spec file | Strategy | Sections touched |
|-----------|----------|------------------|
| `docs/specs/05-taut-mcp.md` | B — atomic | [MCP-4] fingerprint lifecycle paragraphs; matching exact tool-description and host-instruction text in [MCP-5]/[MCP-9]; [MCP-10] trust/retention paragraphs; matching proof language in [MCP-12] |

Under [MCP-4], in the larger fingerprint-lifecycle paragraph beginning
“Ensuring a `ready` canonical workspace”, replace only the sentence sequence
from “The process reactor drops its raw-token reference” through the sentence
ending “the exposure described by [MCP-10].” Keep every preceding sentence in
that paragraph unchanged. Then replace the following two paragraphs beginning
“Any transient request digest” and “Any charged master-side rejection”. The
replacement text is:

> The process reactor removes its raw-token reference from live reactor state
> immediately after successful candidate-thread dispatch, completing a direct
> ready-entry fingerprint comparison, or completing rollback. SDK- or
> host-owned request copies remain the exposure described by [MCP-10]. Caught
> internal exception traceback frames may retain a request token or fingerprint
> until traceback collection; this is allowed local debugging state, not a
> persistent or externally emitted copy.
>
> Any transient request digest not transferred into a hidden seat or ready
> entry is removed from live reactor state before its result is settled,
> including direct-ready idempotent success and different-token conflict.
>
> Any charged master-side rejection that installs no hidden seat, including
> exact-hidden busy, cap exhaustion, direct degraded/detaching status, or a
> path/token semantic failure, removes its transient request digest and raw-token
> reference from live reactor state before returning the fixed result. A caught
> traceback may retain the rejected request values as described by [MCP-10].

Under [MCP-10], replace the opening paragraph beginning “Taut's trust model”
with:

> Taut's trust model remains [TAUT-9]. Storage access is the security boundary.
> A continuity token is an opaque identity-continuity selector inside its
> selected workspace. It is not a remote-authentication credential, an access-
> control token, or an additional security boundary. Possession can select an
> existing identity through Taut's public continuity paths, so a deployment may
> still choose to treat it as sensitive application data. Supplying it as an MCP
> tool argument can expose it to the client, model context, or host transcript;
> `taut-mcp` does not claim to prevent or redact those host-owned copies. The
> local stdio boundary does not authorize a remote listener. This contract
> defines no `TAUT_TOKEN`, token-file, or launch-time workspace-token map for
> the MCP extension. A future non-transcript channel would need its own
> workspace-keying, file-authority, redaction, and host-compatibility contract;
> it is not inferred from core CLI environment rules.

Replace the following paragraph beginning “Each request host may temporarily
hold” with:

> Each request host may temporarily hold its supplied token string. The process
> reactor computes only the exact-byte SHA-256 fingerprint needed for resident
> binding comparison and removes the raw-token and transient-digest references
> from live reactor state after their owner transition. The child validates the
> raw token and clears its bootstrap envelope and local request copy. The one
> child-owned `TautClient` retains its constructor token because core public
> operations use it for continuity; that canonical client is not a second host
> copy. Caught internal exception traceback frames may retain request tokens or
> fingerprints temporarily because that context can aid local debugging. Core
> Taut member storage retains the existing continuity token; `taut-mcp`
> persists no additional request-token copy or fingerprint. Expected
> attachment failures do not return or log request tokens or fingerprints,
> place them in fixed diagnostics, serialize them to protocol output, or emit
> them to stderr.

For consistency with that reviewed boundary, make the same narrow terminology
change in enumerable contract surfaces: [MCP-4]'s earlier direct-hit paragraph
and [MCP-12]'s firing list say removal is from live reactor state and allow
caught internal traceback retention; [MCP-5]'s exact token description removes
the unsupported `Sensitive` classification; [MCP-9]'s exact instruction calls
the token an opaque identity selector rather than a secret. The agent-facing
tool manifest and initialization instruction constants change atomically with
their exact snapshot hashes. These edits do not weaken the existing ban on
returning or logging a request token, persisting an additional MCP-owned copy
or fingerprint, placing either in fixed diagnostics, serializing either to
protocol output, emitting either to stderr, or placing a token in chat. Core
Taut's canonical member-token storage remains explicit rather than being
misdescribed as absent.

Files and ownership decisions:

1. `extensions/taut_summon/taut_summon/_driver.py`: inline watcher cleanup into
   the attempt owner. Keep thread construction and the repeated stop predicate
   separate. If the lexical owner exceeds 10, add permanent `RUFF-SUP-064` for
   construction, publication/recheck, run, failure classification, cleanup,
   and rebuild-wake order; reject the five-local cleanup helper and any second
   watcher owner.
2. `bin/release.py`: retain the checks-only mode executor with an `int` return,
   but make its branch explicit at `_run_batch_release`; inline no-candidate reporting and candidate
   changelog admission. If the cohesive release owner exceeds 10, add permanent
   `RUFF-SUP-063` protecting checks-only, dirty-worktree, discovery, changelog,
   dry-run, prepare/commit/precheck/postupdate/fresh-fence/tag/push order; reject
   branch-displacing admission helpers and a divergent dry-run planner.
3. `extensions/taut_mcp/taut_mcp/_workspace_reactor.py`: keep the single
   `_WorkspaceReactor` owner and replace the command-refresh `bool | None`
   interface with a named closed outcome. No second reactor or generic state-
   machine module.
4. `extensions/taut_mcp/taut_mcp/_process_reactor.py`: let request validation
   and workspace preflight raise fixed `WorkspaceToolError` values directly.
   Preflight returns only an existing result or admission. Traceback frames may
   retain request tokens or fingerprints for debugging; request copies must not
   remain in live reactor state, expected outputs must not expose them, and the
   MCP extension must persist no additional token copy or fingerprint.
5. `extensions/taut_mcp/taut_mcp/_tools.py`, `server.py`, and their exact
   snapshot tests: keep agent-facing wording aligned with the promoted
   identity-selector contract. Do not claim the token is a credential, secret,
   or added security boundary; retain the non-echo and no-chat rules.
6. `bin/coalesce-check`: keep claim classification as a semantic phase, derive
   its hits/cues from the text it owns, and return a named result rather than
   four positional collections.
7. `tests/test_command_registry.py`: split JSON shutdown and human rendering
   into two tests that share typed transport scaffolding. Keep actor values,
   stop/join, client close, flush count, and escaping assertions visible in
   each scenario.

Invariants and hidden couplings:

- Release output, exit codes, exact-SHA fence, and mutation order do not change.
- Workspace legacy/modern wire behavior, cancellation, identity-loss versus
  crash transitions, and the single child-thread owner do not change.
- Watcher attempt-local stop survives construction delay; publication is
  rechecked before readiness/run; cleanup is best-effort; unexpected exit alone
  requests rebuild; no old owner overlaps a new attempt.
- The command watch tests continue through the real dispatcher and retain exact
  cleanup and rendering proof. Production watcher behavior is not mocked away.
- No new dependency, public interface, storage shape, release action, or second
  execution path is introduced.
- Fixed public errors remain content-free. Internal caught tracebacks may retain
  request tokens or fingerprints for debugging, but expected attachment errors
  never emit those tracebacks or values to protocol output, stderr, logs, or
  persistence.

Conditional approved registry rows, used only when raw Ruff confirms exactly
one finding at the named owner after consolidation:

| Group | Rules | Approved cardinality | Protected invariant | Real proof | Rejected alternatives | Approval |
|-------|-------|----------------------|---------------------|------------|-----------------------|----------|
| `[RUFF-SUP-063]` | `C901` | `1` directive; raw: `C901=1` | One batch release owner preserves checks-only, dirty-worktree, discovery, changelog, dry-run, preparation/commit/precheck/postupdate/fresh-fence/tag/push order | Batch checks-only, no-op, dry-run, preparation-rerun, fence, wheel-failure, and explicit-version tests in `tests/test_release_script.py` | Branch-displacing admission helpers or a divergent dry-run planning path | P3 retained after T10 locality remediation and independent review; user-authorized implementation 2026-08-05. |
| `[RUFF-SUP-064]` | `C901` | `1` directive; raw: `C901=1` | One attempt-local watcher owner preserves construction, publication/recheck, run, failure classification, watcher/client cleanup, and rebuild wake order | Watcher failure, pre-publication harness death, fatal bounded-join, and provider-isolation tests in `extensions/taut_summon/tests/test_driver.py` | A cleanup helper that mirrors attempt locals or a second/global watcher owner | P3 retained after T10 locality remediation and independent review; user-authorized implementation 2026-08-05. |

Proof strategy: these are behavior-preserving locality corrections, not product
defects. Per T5–T8, run the closest characterization tests before editing, then
rerun the same real tests after editing. Source inspection, type checking, Ruff
scores, raw reconciliation, and an independent completed-slice review prove the
structural correction. A new product failure is not expected red; if a focused
characterization fails before editing, stop and reclassify it as a behavioral
defect requiring red-green TDD.

Verification:

```bash
uv run --extra dev pytest -q tests/test_release_script.py tests/test_coalesce_check.py tests/test_command_registry.py -k 'batch_checks_only or matching_batch_checks or release_wheel_failure or explicit_batch_version_prepares or all_published_explicit_batch or clean_rerun or release_fence or dry_run_treats_same_version or coalesce or watch_sigint'
uv run --project extensions/taut_mcp --extra dev pytest -q extensions/taut_mcp/tests/test_process_reactor.py extensions/taut_mcp/tests/test_tools.py extensions/taut_mcp/tests/test_stdio_server.py -k 'direct_rejections_keep_fixed_errors or fixed_attachment_rejections or post_command_snapshot or channel_show_does_not_refresh or channel_topic_identity_loss or child_fault_is_isolated or stdio_cancellation'
uv run --project extensions/taut_summon --extra dev pytest -q extensions/taut_summon/tests/test_driver.py -k 'watcher_failure or harness_death_before_watcher or live_watcher_after_bounded_join'
uv run --extra dev ruff check --select C901 --ignore-noqa --output-format json bin/release.py extensions/taut_summon/taut_summon/_driver.py
uv run --extra dev ruff check .
uv run --extra dev python bin/ruff_suppression_index.py --check
uv run --extra dev mypy taut tests bin/release.py --config-file pyproject.toml
uv run --project extensions/taut_mcp --extra dev mypy extensions/taut_mcp/taut_mcp extensions/taut_mcp/tests --config-file extensions/taut_mcp/pyproject.toml
uv run --extra dev mypy extensions/taut_summon/taut_summon extensions/taut_summon/tests --config-file extensions/taut_summon/pyproject.toml
```

The raw command is expected to include already registered findings in both
files. Inspect only `_run_batch_release` and `_run_watcher_attempt` for the T10
decision. For each target that newly exceeds 10, add only its exact conditional
row and directive above, then run `bin/ruff_suppression_index.py --write` once
before the final `--check`. If neither target exceeds 10, add no row/directive
and do not run `--write`.

Stop if consolidation changes an observable result, requires passing more live
state, creates a second owner, or if either target symbol's raw finding has a
cardinality other than the exact reviewed `RUFF-SUP-063`/`RUFF-SUP-064`
proposal. Existing registered findings elsewhere in those files are expected
and do not trigger this stop gate. Rollback is the
T10-only source/spec/plan delta; no data or external state changes and there is
no one-way door. Post-deploy observation is normal CI/release-gate success; no
runtime rollout is required for a behavior-preserving source refactor.

Skill evaluation: the `codebase-design` deep-module and locality guidance
correctly exposed helpers that merely displaced branch or cleanup reasoning.
No skill correction is needed; the repository-specific choice to retain a
cohesive owner under an audited suppression remains plan and registry policy.

## Testing Plan

### `tests/test_ruff_policy.py`

Use the real pinned Ruff binary to prove:

- all four dev manifests declare the exact same Ruff version, existing locks
  resolve it, and each running root/MCP Ruff binary equals that exact pin;
- root and MCP configs retain the reviewed stable families and enable C901 at
  exactly 10 without preview;
- the effective enabled-rule set matches a reviewed generated fixture;
- complexity 10 passes and 11 fails under normal configuration;
- Ruff discovery, filtered to Python and Python-shebang sources, equals the
  tracked inventory and includes all six extensionless tools;
- root and project-local MCP C901 JSON agree for MCP paths;
- normal repository Ruff is clean;
- no C901 per-file/global/blanket/baseline suppression path exists;
- the production reconciler enforces source/group/raw/generated agreement;
- CI and release helper run repository-wide lint before the index check while
  formatting remains explicit.

### `tests/test_ruff_suppression_index.py`

Port the SimpleBroker production-path and adversarial matrix. Each enumerable
exit class, marker defect, human-row grammar defect, source-pointer defect,
cardinality defect, raw mismatch, path/newline case, and write-failure case has
at least one firing test. Run real Ruff and real temporary repositories; mock
only the deliberate replacement failure.

### Complexity refactor proof

For every P1/P2 row, record:

- before/after score;
- the targeted characterization or regression test;
- the real owner that remained unmocked;
- normal Ruff and raw reconciliation result;
- whether the suppression was removed or permanently reapproved;
- independent review at each meaningful owner slice.

No row closes from score output alone.

## Verification and Gates

### Baseline and focused policy

```bash
uv run --extra dev ruff --version
uv run --project extensions/taut_mcp --extra dev ruff --version
uv run --extra dev ruff check .
uv run --extra dev ruff check --select C901 --ignore-noqa --output-format json .
uv run --extra dev pytest -q tests/test_ruff_policy.py tests/test_ruff_suppression_index.py
uv run --extra dev python bin/ruff_suppression_index.py --check
```

Success: root and MCP versions are identical to each other and to the exact
manifest pin; normal Ruff is clean; raw results match the reviewed inventory;
focused policy and hostile-input cases pass; check mode is silent and read-only.

### Static, documentation, workflow, and packaging

```bash
uv run --extra dev ruff format --check \
  taut tests bin \
  extensions/taut_summon/taut_summon extensions/taut_summon/tests
uv run --extra dev ruff format --check \
  extensions/taut_pg/taut_pg extensions/taut_pg/tests bin/pytest-pg
uv run --project extensions/taut_mcp --extra dev ruff format --check \
  extensions/taut_mcp/taut_mcp extensions/taut_mcp/tests
uv run --extra dev mypy taut tests bin/release.py \
  bin/ruff_suppression_index.py --config-file pyproject.toml
uv run --project extensions/taut_mcp --extra dev mypy \
  extensions/taut_mcp/taut_mcp extensions/taut_mcp/tests \
  --config-file extensions/taut_mcp/pyproject.toml
uv run --extra dev pytest -q \
  tests/test_github_workflows.py tests/test_release_script.py \
  tests/test_project_metadata_consistency.py tests/test_docs_references.py \
  tests/test_plan_status_index.py
python3 bin/check-dom15-fixtures
uv run bin/check-doc-paths
bin/check-plan-status-index
git diff --check
uv build
uv build --project extensions/taut_pg
uv build --project extensions/taut_summon
uv build --project extensions/taut_mcp
```

Success: format scope is unchanged; all typed owners pass; workflow/release and
metadata locks agree; docs and plan indexes resolve; wheels exclude repository
tools; no whitespace errors exist.

### Final behavior gates

```bash
uv run --extra dev pytest
uv run ./bin/pytest-pg
uv run --project extensions/taut_summon --extra dev pytest \
  extensions/taut_summon/tests
uv run --project extensions/taut_mcp --extra dev pytest \
  extensions/taut_mcp/tests
python bin/release.py --dry-run
```

The command uses the current unpublished package version, prints the release
plan, and does not write files, create tags, or contact remotes. Never use
`--publish`, omit `--dry-run`, or create a tag as verification for this plan.
The exact final result belongs in the execution evidence.

Success: all product and extension behavior remains green; release planning
preserves exact order and does not publish; normal/raw Ruff and the registry
remain reconciled after the suites.

## Independent Review Loop

Plan review preference: Claude or Grok, because Codex authored the plan and the
current agent inventory records both as review-eligible. Give the reviewer:

- this plan and exact `## Proposed Spec Delta`;
- the complete C901 JSON and disposition ledger;
- all Ruff manifests/configs/locks and current CI/release gates;
- SimpleBroker's two source plans, tool, focused tests, and R1 correction;
- representative P1/P2/P3 production and real-process test owners.

Required review stance:

> Read the plan, proposed [DOM-10.2]/[DOM-10.2.1] delta, complete finding
> ledger, and named current code. Look for wrong dispositions, score-driven
> fragmentation, weak or generic suppression reasons, a generator path that can
> approve growth, Ruff-version or nested-config drift, incomplete discovery,
> formatter-scope expansion, unsafe write behavior, mock-heavy proof, oversized
> slices, missing rollback, and performative process. Challenge every retained
> finding: does it protect real coupling/debugging locality/semantic risk and
> cite proof that exercises the real owner? Do not implement. Could a
> zero-context engineer execute every slice confidently and correctly?

Meaningful-slice review is required after:

1. canonical version/discovery audit and final activation-row proposal;
2. generator tracer and hostile-input suite;
3. atomic policy activation;
4. core/tool/release refactors;
5. MCP/PG refactors;
6. Summon refactors;
7. complex test/harness review;
8. final registry reconciliation.

The author reproduces each review claim and either updates the mutable task
text, records a reasoned rejection, or marks a bounded exclusion. A BLOCKED
verdict prevents the next dependent slice.

## Stop and Re-Plan Gates

Stop rather than improvising if:

- the pinned Ruff version changes the finding identity/count without a reviewed
  ledger revision;
- root and MCP project-local Ruff disagree on overlapping files;
- complete discovery requires linting generated/vendor/environment files rather
  than tracked first-party sources;
- activation requires an ignore, higher threshold, or unreviewed suppression;
- the generator can alter human-owned text or approve a new site implicitly;
- a proposed extraction creates a second execution path, circular import,
  generic framework, or helper with more live-state parameters than the code it
  replaces;
- a refactor changes product/API/CLI/wire/storage/release behavior;
- real process/thread/PTY/backend behavior can pass only after being mocked;
- formatter scope would need to widen to match lint scope;
- lock regeneration changes unrelated dependencies;
- a new dependency appears necessary;
- the strategy-B activation cannot capture an immutable promotion baseline.

## Out of Scope

- Enabling `BLE`, `SLF`, `N`, `S`, Ruff preview, or `select = ["ALL"]`.
- Removing or rewriting existing reasoned `noqa` comments for disabled rules.
- Raising/lowering the complexity threshold from 10 after activation review.
- Refactoring a function solely because it is long or because its score exceeds
  10.
- Splitting cohesive files or introducing generic command/state-machine/test
  frameworks.
- Product features, CLI commands, public API changes, MCP protocol changes,
  Summon lifecycle changes, storage migrations, or release publication.
- Adding root/PG lockfiles or redesigning dependency management.
- Merging root, PG, Summon, and MCP test/type-check environments.
- Publishing the generator as part of a wheel or public Taut CLI.
- Auto-writing the generated index during pytest or CI.
- Generalizing the SimpleBroker tool beyond this concrete registry.
- Repairing unrelated lint, formatting, typing, documentation, or test debt.

## Deviation Log

| Spec ref | Planned behavior | Actual behavior | Rationale | Spec proposal |
|----------|------------------|-----------------|-----------|---------------|
| [DOM-10.2.1] | The isolated SimpleBroker port would prove the adapted Taut registry seam. | The isolated fixture and generator initially shared the wrong heading order; an active-spec firing test failed before T4 and the heading was corrected. | Isolated fixtures cannot independently prove a live document seam they duplicate. | None. The active-spec integration test and durable lesson close the proof gap. |
| [DOM-10] verification | Structural refactors would preserve existing repository proof sentinels. | The first full root gate found the Summon driver entry marker stale after its call became multiline; focused product suites had remained green. | The marker is a separate coverage contract and needed to follow the unique executed `.run()` line. | None. The focused sentinel test failed red, the marker was updated, and the full root suite then passed. |
| Plan verification command | `bin/check-doc-paths` would run from a normal shell. | The checker requires the project pytest environment and rejected the bare invocation. | The executable itself prescribes `uv run bin/check-doc-paths`. | None. The plan command now matches the tool's required environment. |
| [MCP-4]/[MCP-10] traceback retention | T10 initially preserved the baseline rule that request tokens and fingerprints do not remain in caught traceback frames. | User clarified that continuity tokens are not credentials and that traceback retention is acceptable and useful for debugging; public error/output surfaces remain content-free. | The old error-as-data tuple weakened locality for an internal retention rule that the owner explicitly rejects. | T10 proposed spec delta above; promote atomically before completing the process-reactor edit. |

## Revision Log

| Date | Reviewed baseline | Revision | Reason | Re-review |
|------|-------------------|----------|--------|-----------|
| 2026-08-04 | Initial draft at `1ad1b8d` | Port SimpleBroker's final symbol-keyed design directly; require exact Ruff-version alignment and complete extensionless discovery before activation; scope the global inventory to active raw diagnostics rather than disabled textual `noqa` comments. | Taut has split Ruff environments, no root lock, six undiscovered Python tools, and many reasoned suppressions for disabled families. Copying the SimpleBroker wording verbatim would overclaim coverage. | Pending independent plan review. |
| 2026-08-04 | Grok round-1 review of the initial draft | Retain explicit Ruff `select` and add only C901; narrow extension-job ownership; restore exact formatter paths; enumerate missed tools/findings; normalize the nested watcher identity; add deterministic T5–T8 assignment and the reviewed T3A activation-group freeze; document binary-version and no-root-lock proof. | R1/R2 exposed a blocking defaults-surface contradiction. R3–R11 identified implementation ambiguities that would otherwise widen scope or force approval decisions during source edits. | Focused round-2 verification required. |
| 2026-08-05 | T9 uncommitted worktree at diff base `1ad1b8d` | Add T10 to repair six refactors whose shallow interfaces or displaced branches reduced locality; preapprove exact permanent groups 063/064 only if consolidation restores those two C901 findings. | Expert review found that most ownership refactors were sound, but score-driven branch and cleanup extraction contradicted the plan's cohesion guardrails. | Independent T10 plan review required before source edits. |
| 2026-08-05 | T10 plan-review PASS baseline | Replace the mistaken secret-derived traceback constraint with the user's explicit debugging-locality decision; add the exact [MCP-4]/[MCP-10] delta and strategy-B promotion. | Storage access is the security boundary. Continuity tokens are local identity selectors, not authentication credentials or a separate security boundary; retaining caught internal traceback context is acceptable while public outputs remain content-free. | Independent review of the exact spec delta required before promotion. |

## Review Log

| Review/finding | Date | Verdict | Disposition |
|----------------|------|---------|-------------|
| Grok R1/R2 — `extend-select` contradicts the C901-only inventory | 2026-08-04 | BLOCKED, gate 1 | Accepted. Both configs retain explicit `select` and add only C901; normative “stable defaults” language was removed. |
| Grok R3 — extension jobs ambiguously own the repository generator | 2026-08-04 | P2 | Accepted. Root CI and release own the full generator; PG/MCP retain scoped Ruff proof only. |
| Grok R4 — verification widened formatter ownership | 2026-08-04 | P2 | Accepted. Verification now mirrors the existing root/Summon, PG, and MCP formatter path sets exactly. |
| Grok R5 — temporary findings lacked deterministic T5–T8 assignment | 2026-08-04 | P2 | Accepted. A path/owner mapping assigns every P1/P2 row before group creation. |
| Grok R6 — no pre-source activation-group freeze | 2026-08-04 | P2 | Accepted. New T3A freezes IDs, membership, cardinality, lifetime, rationale, and proof under independent review before T4 source edits. |
| Grok R7 — six missed tools were not enumerated | 2026-08-04 | P2 | Accepted. The baseline names all six tools and the four added C901 symbols. |
| Grok R8 — nested watcher key was not a stable raw identity | 2026-08-04 | P3 | Accepted. The raw symbol and shared generated site/group/cardinality are explicit. |
| Grok R9 — exact pins without root/PG locks need running-binary proof | 2026-08-04 | P3 | Accepted. T2 requires each running binary to equal its exact manifest pin. |
| Grok R10 — Taut intentionally cannot copy SimpleBroker's frozen invocation | 2026-08-04 | P3 | Accepted. T3 and the implementation note must document why no-root-lock Taut uses exact pins plus binary tests instead. |
| Grok R11 — nested MCP config resolution needed an explicit warning | 2026-08-04 | P3 | Accepted. The baseline states root discovery does not override MCP's nested rule table. |
| Grok R12 — `+P` is informal | 2026-08-04 | nit | Retained with explanation. The class remains DOM Class 5; `+P` is explicitly described as a plan-risk modifier, not a DOM class value. |
| Grok R13 — several P1 rows are seams, not known defects | 2026-08-04 | nit | Retained. The plan's P1 definition deliberately includes clear ownership seams and does not claim each is a bug. |
| Grok round 2 — R1–R11 fix verification | 2026-08-04 | PASS | Every accepted finding verified fixed. N1/N2 carry-through nits were accepted: verification now requires binary=pin, and T4 requires the implementation note to explain the intentional no-root-lock invocation. |
| Claude T2/T3 implementation review | 2026-08-04 | no blocker | F1 accepted: T2/T3 evidence and the immutable baseline are recorded below. F2/F3 were equivalent/inert fixture spelling differences from SimpleBroker and required no change. The reviewer verified the generator implementation is otherwise identical to `4d4f61be` under the sanctioned Taut substitutions. |
| Claude T3A activation-ledger review | 2026-08-04 | no blocker | The reviewer verified all 63 memberships, 62 groups, dispositions, lifetimes, cardinalities, and the watcher/F401 exceptions. F1/F2 wording bleed was accepted and corrected in groups 009 and 030 before the artifact hash was refreshed. |
| Claude T4 atomic-activation review | 2026-08-04 | no blocker | No findings. The reviewer reconciled config scope, 62 human/generated rows, 63 directives/raw C901 diagnostics, the watcher exception, CI/release ordering, unchanged formatter boundaries, and the spec/implementation backlink chain. |
| Grok T5–T8 completed-work review attempt | 2026-08-04 | no verdict; timed out | The read-only reviewer spent its 540-second bound rerunning Summon tests and returned no assessment. Silence was not treated as approval. Two cross-agent reviews replaced it. |
| Cross-review: T5/T8 root and T6 MCP | 2026-08-04 | no blocker | An agent that authored neither slice found no findings. It rechecked release phase/exact-SHA order, decode-before-cursor, primary-over-cleanup, one MCP reactor owner, legacy/modern cancellation frames, real proof, and all 15 retired groups; 66 root tests, 26 MCP tests, 3 coalesce tests, Ruff, raw audit, and index check passed. |
| Cross-review: T7 Summon and final reconciliation | 2026-08-04 | no blocker | An agent that authored neither slice found no findings. It rechecked signal, PTY/lease/error precedence, watcher publication/cleanup, teardown, crash budget, STOP ordering, real process proof, all 11 retired groups covering 12 findings, and the final `C901=36`/36-group/36-directive reconciliation. |
| T9 final retained-rationale challenge | 2026-08-04 | no blocker | The two cross-reviewers challenged all 36 retained groups against final source and cited proof: 26 non-Summon and 10 Summon. No rationale was stale, generic, score-only, mock-only, or contradicted by the final ownership boundary; enumerable matrices and rejected splits remain specific and firing. |
| T10 locality-remediation plan review | 2026-08-05 | BLOCKED on four findings | Three findings were accepted: exact conditional rows 063/064, raw audit plus explicit `--write` before `--check`, and focused behavior proof. The proposed traceback-scrubbing outcome was rejected by the owner before implementation because it treated an identity selector as secret-derived credential material and reduced locality. No such outcome remains. |
| T10 plan-review round 2 | 2026-08-05 | FAIL on conditional activation | Accepted. Raw inspection now scopes its decision to the two T10 symbols while tolerating existing registered findings, and `--write` runs only after at least one reviewed row/directive is actually added. |
| T10 plan-review final verification | 2026-08-05 | PASS | The reviewer confirmed both accepted round-2 fixes: symbol-scoped raw disposition and conditional generation only when group 063 and/or 064 is materialized. Source edits may begin. |
| T10 user correction: traceback retention | 2026-08-05 | Prior plan premise rejected by owner | Accepted. Implementation paused; exact [MCP-4]/[MCP-10] delta now permits caught internal traceback retention for debugging while preserving content-free public surfaces. |
| T10 MCP spec-delta review | 2026-08-05 | BLOCKED on replacement targeting | Accepted. The plan now replaces only the final sentence sequence inside [MCP-4]'s larger fingerprint-lifecycle paragraph, preserving all preceding lifecycle requirements, then replaces the two following paragraphs. |
| T10 MCP spec-delta round 2 | 2026-08-05 | PASS | The reviewer confirmed the exact replacement boundary preserves the larger fingerprint lifecycle; the revised security posture and direct-raise implementation are internally consistent with TAUT-9 and the accepted user decision. |
| T10 completed-work review | 2026-08-05 | BLOCKED on security-claim precision and stale bookkeeping | Accepted. [MCP-10] and the implementation note now distinguish core member-token persistence from additional MCP-owned copies; attachment provenance from participant-authored result content; internal tracebacks from emitted surfaces; and identity selectors from credentials. Rewritten tests use neutral token names. The plan status and promotion hash were refreshed. |
| T10 completed-work re-review | 2026-08-05 | PASS | No remaining blocker or actionable finding. The reviewer found the six locality corrections cohesive, the two new suppression groups exact and justified, the protocol snapshots current, and the security wording precise without overstating confidentiality. |

## Execution Evidence

Record completed evidence only. Do not freeze transient worktree status here.

| Slice | Baseline | Changed files | Command/evidence | Observed result | Independent review | Residual risk |
|-------|----------|---------------|------------------|-----------------|--------------------|---------------|
| T2 canonical Ruff baseline | HEAD `1ad1b8d0cd593ff0b7a3b5bf3fa3ec92df5e9cb3`; four manifest blobs and two lock diffs against that tree | Four manifests, Summon/MCP locks, `tests/test_ruff_policy.py` | Red: focused policy suite `3 failed, 1 passed`; green: `4 passed`; structural lock comparison excluding Ruff entries; root/MCP C901 JSON identity comparison | All manifests and both locks use 0.16.1; 170 tracked Python/shebang files; 63 C901 findings; 10 MCP findings agree exactly; no non-Ruff lock change | Claude: no blocker | Root and PG intentionally have no lock; running-binary equality is the substitute proof. |
| T3 generator port | SimpleBroker `4d4f61be55d117c129e0a21fe1139772496282be` | `bin/__init__.py`, `bin/ruff_suppression_index.py`, `tests/test_ruff_suppression_index.py` | Tracer import RED; full port RED `22 failed, 4 passed`; green `28 passed`; integrated T2/T3 `32 passed`; Ruff, format, mypy; wheel inspection | Symbol-keyed R1 tool and hostile-input/exit/atomic-write contract pass; wheel excludes `bin/`; repository self-check fails only for the pending DOM-10.2.1 heading | Claude: no blocker | Active-spec command assertion and repository self-check remain intentionally deferred to T4. |
| T3A activation ledger freeze | T2 raw audit at `1ad1b8d`; reviewed artifact SHA-256 `4df6a416074e0ac3bc48bea8c8e83c88e53e222453918a342e59b099743300a1` | `docs/plans/artifacts/2026-08-04-ruff-suppression-activation-ledger.tsv` | TSV schema/contiguous-ID/cardinality/membership validator | 62 groups; 63 directives; raw `C901=63`; 63 memberships; watcher pair alone shares one group/site; baseline global raw inventory also has ungrouped `F401=1` | Claude: no blocker; wording nits corrected | The artifact is approval input, not authority; T4 must copy it exactly and regenerate locations. |
| T4 atomic activation | Uncommitted promotion baseline: diff base `1ad1b8d0cd593ff0b7a3b5bf3fa3ec92df5e9cb3`; promoted spec SHA-256 `68135eb73c1997157fed754913113c93a024665c7c5a5e6c0b6659f1d8ab0c60` | Ruff configs; DOM-10.2/10.2.1; 63 source pointers; generator heading integration; policy fixture/tests; root CI/release gates; implementation docs | Focused suite `218 passed`; `ruff check .`; generator `--check`; mypy; docs paths; plan index; DOM-15; diff check | All gates passed; 62 groups/generated rows reconcile 63 C901 directives/raw diagnostics plus ungrouped raw `F401=1`; formatter paths unchanged | Claude: no findings, no blocker | Same-symbol remove/add and the watcher shared-site case remain the two documented identity residuals. |
| T5/T8 core, tools, release, and proof refactors | T4 promotion baseline above | Root client/command owners; release publication/artifact/planner; coalesce tool; focused tests | Before/after scores: `18→1`, `14→7`, `18→2`, `21→10`, `12→4`, `12→6`, `12→8`, `22→8`, `12→1`, `11→1`, `16→4`, `13→1`; integrated closest suites, Ruff, format, mypy, and registry check | All 12 assigned findings/groups removed with no reclassification; real Git, SQLite, dispatch cleanup, page decode, and release SHA/phase proof remain | Cross-review: no findings, no blocker | None beyond the final repository gates. |
| T6 MCP ownership refactors | T4 promotion baseline above | MCP process/workspace reactors and raw stdio cancellation test | Scores `16→10`, `54→1` (coordinator `6`), `14→3`; 151 focused MCP cases; root/MCP C901 identity; scoped mypy | Groups 013, 017, and 020 removed; one workspace state owner and one child thread remain; protocol/cancellation proof passed | Cross-review: no findings, no blocker | The slice initially lacked `SIMPLEBROKER_PG_TEST_DSN`; T9 later ran all six MCP PG-conformance cases against disposable PostgreSQL 18 and passed. |
| T7 Summon ownership refactors | T4 promotion baseline above | Summon control/driver/PTY owners and lifecycle fixtures/tests | Scores `20→10`, `25→10`, `13→6`, `17→4`, watcher `15→1` with named owner `6`, `11→4`, `16→1`, `11→5`, `12→6`, `22→8`, `11→1`; 282 unit, 238 real-process, and 8 installed live-harness cases during the slice | Eleven groups covering 12 findings removed; signal, PTY, lease, teardown, watcher, and crash-budget ownership remain real | Cross-review: no findings, no blocker | The local-model sentinel requires an installed endpoint/model; transport, timeout, HTTP, malformed-response, proxy, and installed-harness lanes passed. |
| T9 final closure gates | Current uncommitted worktree against `1ad1b8d0cd593ff0b7a3b5bf3fa3ec92df5e9cb3` | Final registry/spec/docs/tests/CI/release integration plus coverage-sentinel repair | Root `1500 passed, 1 skipped`; real PG `242 + 14 passed`; Summon `528 passed, 1 skipped`; MCP `203 passed, 6 skipped` plus all six skipped PG cases passed separately against PostgreSQL 18; policy/generator `39 passed`; all Ruff format/lint, four mypy scopes, docs/status/DOM checks, four builds, `git diff --check`, release `--dry-run` | Raw `C901=36`; 36 human groups, source directives, and generated rows; 26 retired groups cover 27 removed findings; no temporary group remains; dry-run performed no release action | Two cross-reviews: no findings, no blocker; Grok attempt timed out without verdict | One Summon local-model sentinel remains environment-skipped because the endpoint lacks the named model. Worktree is intentionally uncommitted; per T9/DoD, plan and status index remain `active` until the user authorizes a commit and current gates are reconfirmed. |
| T10 locality remediation and MCP terminology correction | T9 uncommitted worktree at diff base `1ad1b8d0cd593ff0b7a3b5bf3fa3ec92df5e9cb3`; promoted MCP spec SHA-256 `1e792adf8c13c2a81ec6837b5a437bbd9ec7610ee3d0fffb6653a32f5fb74d4b` | Release/coalesce owners and tests; Summon watcher owner; MCP process/workspace reactors, manifest/instructions, snapshots and tests; command-watch tests; DOM registry; MCP spec/implementation note; lesson and plan evidence | Pre-edit characterization `15 + 12 + 4 passed`; added firing cases `1 + 3 passed`; post-edit focused selections `16 + 11 + 4 passed`; complete owner suites `329 + 147 + 142 passed`; policy/docs suite `70 passed`; raw target audit; registry write/check; repository Ruff; format checks; mypy `100 + 18 + 37` files; docs/path/status/DOM gates; `git diff --check` | `_run_batch_release` and `_run_watcher_attempt` each restored one cohesive lifecycle and materialized exactly one reviewed C901 finding; `RUFF-SUP-063/064` reconcile with global raw `C901=38`, `F401=1`; enum/named-result/direct-raise/test-locality corrections passed without observed behavior change; MCP wording distinguishes storage authority, core persistence, MCP copies, caught tracebacks, and emitted content | Independent completed-work review: initial precision findings accepted; final PASS with no remaining finding | No T10 runtime residual. The unrelated local-model sentinel still requires the configured endpoint/model; hosted CI remains the post-commit platform signal. |
| Targeted completion gate | Final T10 worktree after owner authorization | Plan status/checklist and status index closure; Ruff-owned formatting of `bin/coalesce-check` | Repository Ruff and index clean; formatter scopes `151 + 6 + 18` files clean; mypy `101 + 18 + 37 + 5` files clean; workflow/release/metadata/docs/policy selection passed; DOM/path/status/diff gates passed; four packages built; root `1502 passed, 1 skipped`; live PG `242 + 14 passed`; Summon `528 passed, 1 skipped`; MCP `205 passed, 6 skipped` plus all six MCP PG cases passed against disposable PostgreSQL 18; release `--dry-run` completed without mutation | Final raw inventory remains `C901=38`, `F401=1`; every reviewed local and full behavior gate passed; dry-run planned only and performed no release action | T10 completed-work reviewer already returned final PASS; closeout changed only generated-format conformance and plan state/evidence | One environment-only Summon local-model skip remains because the configured endpoint does not list the named model. The disposable PostgreSQL container was removed after the six MCP PG cases passed. |

## Fresh-Eyes Checklist

- [x] Every initial finding appears exactly once in the disposition ledger.
- [x] Every P1/P2 row names its removal/re-evaluation task, proof, and stop gate.
- [x] Every P3 row names protected coupling, real proof, and rejected split.
- [x] Root, PG, Summon, and MCP Ruff version/configuration ownership is explicit.
- [x] The six extensionless tools and four additional findings are accounted for.
- [x] Human approval, source pointer, raw line identity, and generated symbol
  identity have distinct owners.
- [x] The generator cannot approve growth, rewrite rationale, or partially write.
- [x] The active-rule global inventory does not overclaim disabled-family
  coverage.
- [x] Strategy-B promotion, immutable promotion baseline, backlink timing, and
  rollback are explicit.
- [x] Lint becomes repository-wide while formatter paths remain explicit.
- [x] Release check and format path ownership is split before widening lint.
- [x] Important filesystem/process/thread/PTY/backend proof stays real.
- [x] Each meaningful slice has independent review and a stop gate.
- [x] No new dependency, public contract, storage format, or release action is
  implied.
- [x] Final traceability and status-index closure are executable gates; status
  closure remains pending the user-authorized commit required by T9.
