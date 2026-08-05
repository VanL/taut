# Development Documentation Operating Model

Status: Active

This spec defines the documentation operating model for this repository. It is
the source of truth for how agent context, specs, plans, implementation docs,
skills, agent reviews, bootstrap inventory, and lessons are expected to work
together.

## 1. Overview [DOM-1]

This repository uses a docs-first operating model for development.

Requirements:

- shared agent context is repository-owned and loaded at session start
- specs define intended behavior
- plans define execution for concrete changes
- independent review agents validate plans and completed work
- implementation docs explain current rationale and important boundaries
- skills capture reusable recurring workflows
- lessons capture durable corrections
- documentation should optimize for agent usability, not only human readability

Agent-usable documentation should make these explicit whenever they matter:

- owner: who acts or which surface owns the behavior
- boundary: when the rule applies and when it does not
- verification: how correctness is checked
- required action: what the reader should do next

## 2. Documentation Taxonomy [DOM-2]

The repository documentation surface is split by role:

- `docs/agent-context/`: canonical shared context and reusable runbooks
- `docs/specs/`: intended behavior, invariants, and verification expectations
- `docs/plans/`: dated execution documents for concrete work
- `docs/implementation/`: rationale, boundaries, repository maps, and current
  architecture notes
- `skills/`: reusable task-scoped workflow instructions
- `docs/lessons.md`: canonical lessons ledger

The roles should remain distinct. A document may link to another role, but it
should not collapse multiple roles into one file without a strong reason.

## 3. Agent Startup Context [DOM-3]

At the start of a session, agents follow the canonical order in
`docs/agent-context/README.md`. Root entry points and newcomer guides link to
that sequence and may add role-specific supplements, but must not maintain a
second ordered copy.

The shared agent context should stay repository-owned so multiple agent tools
can consume the same durable guidance.

Tool-specific root aliases should symlink to the canonical root entry point
when the environment supports symlinks. If symlinks are not practical, keep
those files as thin pointers back to the canonical entry point.

## 4. Traceability Requirements [DOM-4]

For material behavior changes, as defined in [DOM-6], the repository should
preserve the chain:

`spec section <-> plan <-> implementation doc <-> code`

Requirements:

- plans cite exact spec files and reference codes when they exist
- specs maintain backlinks to related plans
- implementation docs cite governing spec sections and key files or modules
- code should point back to the governing spec where ownership would otherwise
  be ambiguous

_Implementation snapshot_: the chain is live for product code. Taut behavior
specs (`docs/specs/02-taut-core.md`,
`docs/specs/03-identity-addressing-notifications.md`) backlink dated plans,
`docs/implementation/04-taut-architecture.md` carries the spec-code trace
table, module docstrings cite governing spec codes, and
`tests/test_docs_references.py` gates path and spec-code references against
drift.

## 5. Planning Standard [DOM-5]

Classify the task first ([DOM-15]). Classes 3 and above begin with a
dated plan in `docs/plans/`; classes 1–2 keep their planning record in
the commit history or handoff report instead. The lists below remain
the canonical trigger definitions [DOM-15] cites.

For this operating model, treat a change as non-trivial when any of these are
true:

- it changes intended behavior
- it crosses more than one major documentation surface or code boundary
- it introduces or revises a reusable workflow
- it would leave a zero-context implementer guessing without a plan

The plan must be executable by a zero-context engineer and include:

- goal
- source documents
- context and key files
- invariants and constraints
- dependency-ordered tasks
- testing plan
- verification and gates
- independent review loop
- out-of-scope statement
- fresh-eyes review

Plans should state invariants before or alongside tasks.

For this operating model, treat a change as risky when any of these are true:

- it introduces async, deferred, queued, or background work
- the same core behavior must run in more than one execution context
- it changes a public contract, compatibility surface, CLI shape, or storage
  format
- rollback depends on backward compatibility or rollout order
- it introduces a one-way door, destructive edge, new persistence, temp-file,
  cleanup, or deferred-input lifecycle

The narrow routine-release exception in [DOM-15] overrides the non-trivial
and risky trigger lists above only for execution of the established release
path itself. The exception does not transfer to product changes, preparation
outside `bin/release.py`, release-machinery changes, disabled gates, override
flags, manual publication, or ad hoc recovery that cannot be completed by
reinvoking the unchanged release path. Classify those as separate work against
the normal triggers.

Risky plans are not review-ready until they also make explicit:

- hidden couplings and boundary-crossing state
- stop-and-re-evaluate gates for risky tasks
- what should not be mocked
- current owner or current-structure context for the main edit points
- which auxiliary failures are best-effort versus fatal
- rollback path and rollout sequencing
- rollback written early enough to shape the task decomposition
- one-way doors
- post-deploy success signals
- required reading with comprehension questions for complex areas

This spec names the planning contract. The operational checklist, rewrite
criteria, and examples live in `docs/agent-context/runbooks/writing-plans.md`
and `docs/agent-context/runbooks/hardening-plans.md`.

## 6. Spec Standard [DOM-6]

Specs must define intended behavior and not merely document current file layout.

Requirements:

- use stable reference codes for requirements that need to be cited
- document invariants, interfaces, failure modes, and verification
- keep `## Related Plans` current
- update the spec before or with any material behavior change
- if wording is human-clear but agent-ambiguous, tighten it and suggest a more
  agent-usable formulation

For this operating model, treat a change as material when it changes intended
behavior, changes a governing boundary or invariant, or would alter how future
work should be planned, implemented, reviewed, or verified.

## 7. Implementation Docs Standard [DOM-7]

Implementation docs must explain why the current design exists.

Requirements:

- capture rationale, boundaries, tradeoffs, and key edit points
- cite governing spec sections
- remain concise and durable
- avoid turning into line-by-line code tours
- update when the rationale or ownership changes materially, meaning the current
  explanation of why the design exists or who owns the decision would no longer
  be reliable after the change
- prefer structures and wording that help agents locate decisions, boundaries,
  and edit points reliably

Helpful structures include:

- a dedicated governing-spec section
- explicit key-file or key-module lists
- change-guidance checklists
- named invariants rather than prose-only rationale

## 8. Documentation Maintenance Gate [DOM-8]

Documentation maintenance is part of the definition of done.

Requirements:

- plans, specs, implementation docs, and code must stay aligned within the same
  change
- if no governing spec exists, the plan must say so explicitly
- if a skill or runbook was central to the work, evaluate whether it should be
  improved while context is still fresh
- if a correction reveals a reusable rule, add it to `docs/lessons.md`
- if an external note, review comment, or one-off plan fix produces a durable
  planning rule, promote it into the relevant runbook instead of leaving it
  buried in a single plan
- if something remains human-readable but agent-confusing, notify the user and
  suggest a concrete improvement

## 9. Lessons Learned [DOM-9]

Durable lessons live in `docs/lessons.md`.

Lessons should be:

- short
- dated
- written as reusable rules
- added when they would prevent future rework

Durable means the lesson should still help on future sessions or future changes,
not just the task that happened to reveal it.

When recurring lessons describe a stable workflow rather than a one-off rule,
promote them into a skill or runbook.

## 10. Verification and Completion [DOM-10]

Each completed task should leave behind explicit evidence.

At minimum, completion should name:

- the file(s) changed
- the verification command or inspection gate
- the observed result or residual risk

Docs-only changes may be verified by inspection, link checks, formatting checks,
and targeted grep-based assertions when runtime behavior is not involved.

For runtime behavior changes, completion should also name the intended rollout
observation or rollback path when those materially affect operational safety.

For risky changes, completion should also say whether the rollout or rollback
assumptions still hold and whether post-deploy observation is pending or
complete.

### [DOM-10.1] Executable CLI claims

Maintained documentation claims about executable Taut command paths must be
checked against the deterministic core command registry. The repository owns
one CLI-claim grammar and source list in its pytest gate; a standalone bin
entry point imports that contract rather than duplicating it.

Recognized claims are shell-like `taut ...` invocations in Markdown inline
code or fenced code. Validation covers the top-level verb and any required
nested operation exposed by a core adapter. It uses
`CommandRegistry(entry_points=())` plus side-effect-free parser configuration,
and performs no ambient entry-point discovery, client construction, project
resolution, database access, or command execution. Full positional and shell
grammar remain outside this claim gate.

The exact source set is `README.md`, `AGENTS.md`, `CLAUDE.md`,
`docs/README.md`, `docs/coalescing.md`, `docs/plans/README.md`,
`extensions/*/README.md`, `docs/agent-context/*.md`,
`docs/agent-context/runbooks/*.md`, `skills/**/*.md`,
`docs/implementation/*.md`, and `docs/specs/*.md`. `CHANGELOG.md`,
`docs/lessons.md`, and individual dated plan bodies are explicitly historical
and excluded.

A deliberately future, invalid-example, or external-extension command path
requires a source-scoped exact exemption with a non-empty reason. An exemption
that now resolves is itself a failure. Failures identify source, line, command
path, and reason. The standalone checker exits 0 for success, 1 for claim
failures, and 2 for invocation or environment failure.

### [DOM-10.2] Repository static-analysis and complexity gate

Taut's Python lint gate uses one exact Ruff version across the root,
PostgreSQL, Summon, and MCP development manifests and existing lockfiles.
`pyproject.toml` and `extensions/taut_mcp/pyproject.toml` own their respective
Ruff configuration; both explicitly select `E`, `W`, `F`, `I`, `B`, `C4`,
`UP`, and `C901`, use `mccabe.max-complexity = 10`, and keep preview rules
opt-in. A Ruff-version change must update every manifest and
existing lock in one reviewed change, regenerate the effective-rule fixture,
and re-run the raw suppression audit before adoption.

Owner: the Ruff configurations own rule selection and discovery; the root CI
lint job owns repository-wide enforcement; the PG and MCP lint jobs provide
independent extension-environment proof. Boundary: every tracked first-party
`.py` and `.pyi` file and every tracked extensionless Python-shebang tool,
including repository tools, `.github/scripts`, tests, and all extension
projects. Verification: `tests/test_ruff_policy.py` invokes the real canonical
Ruff binary, compares effective discovery and enabled rules with reviewed
inventories, proves complexity 10 passes and 11 fails, and checks CI and
release command shape. Required action: normal lint uses `ruff check .`; Ruff
formatting retains its explicit existing path boundary and does not expand to
repository-wide formatting merely because lint discovery expands.

Ruff's C901 score is a visibility signal, not a design verdict. Each finding
must either be simplified at a real ownership seam with behavior-preserving
proof or carry a narrow local C901 suppression registered in [DOM-10.2.1]. A
retained finding requires a protected coupling, debugging-locality, or
semantic-risk reason; real behavioral proof; rejected decompositions; and
explicit approval. A cohesive parser, lifecycle owner, protocol dispatcher,
atomic release sequence, stateful reactor, or real-process proof must not be
fragmented merely to lower its score.

The policy gate runs normal Ruff and a raw audit with `--ignore-noqa`. Source
directives, human-owned [DOM-10.2.1] groups, the generated symbol index, and
raw diagnostics at tagged locations using Ruff's `noqa_row` must reconcile
exactly, including each group's approved directive and per-code raw-diagnostic
cardinalities. A new unsuppressed finding, malformed or unregistered tagged
directive, unknown or empty group, rule-scope mismatch, cardinality change,
stale directive, stale generated index, or mismatched raw finding fails.

A separate movement-stable global raw-diagnostic inventory records every
diagnostic exposed by `--ignore-noqa` under the active repository rule set,
including reasoned local suppressions outside the grouped registry. It is an
exact aggregate by rule code, not a claim that disabled rule families are
audited and not a second identity registry. Per-file ignores, global ignores,
blanket file directives, threshold inflation, and baseline allowlists are not
permitted as alternatives to review.

#### [DOM-10.2.1] Approved Ruff suppression registry

This subsection owns every approved suppression group and its human-reviewed
meaning. The human table owns the stable group ID, allowed rules, approved
directive count, approved raw-diagnostic count by rule, protected invariant,
real proof, rejected alternatives, and approval. The local source directive
owns its exact rule codes and group pointer. The generated index owns only
derived repository-relative paths, qualified symbols, and actual counts.

A generated symbol is the outermost enclosing function, qualified by enclosing
class names, or `<module>` when no function owns the line. Decorator lines
belong to their decorated function. The generator retains the physical line as
internal identity for raw-diagnostic reconciliation and errors, but it renders
one sorted `path::qualified_symbol` site per group. This makes ordinary line
movement stable and makes a suppression moving between functions visible in
review. Removing and adding the same rule within the same qualified symbol can
remain invisible when both site set and cardinality stay fixed; this is an
accepted residual, not a broader approval.

The required local form is
`# noqa: <codes> approved [DOM-10.2.1] [RUFF-SUP-NNN] exception`.
The stable group points to the single durable full
reason; source comments do not duplicate that rationale. Group IDs are unique,
match `RUFF-SUP-[0-9]{3}`, and are never reused after retirement. A temporary
group also names the active plan task that removes or re-evaluates it.

The human table columns are `Group`, `Rules`, `Approved cardinality`,
`Protected invariant`, `Real proof`, `Rejected alternatives`, and `Approval`.
Approved cardinality states both directive count and raw count by code. Every
group has at least one live directive; every human-owned rationale cell is
non-empty. The subsection also owns exactly one canonical, lexically sorted
`Global raw-noqa inventory:` line using backticked `CODE=count` entries.

The generated location index is enclosed by unique begin/end markers and has
columns `Group`, `Locations`, `Directives`, and `Raw diagnostics`. Rows are
sorted by group ID; sites use repository-relative POSIX paths and qualified
symbols; codes are lexical. Content outside the markers is human-owned and
remains byte-for-byte unchanged during regeneration. The generator may never
create or edit a group, rule approval, cardinality approval, invariant, proof,
rejected alternative, or approval record.

Verification commands are `uv run --extra dev python
bin/ruff_suppression_index.py --check` and, after explicit human approval of
every changed human-owned field, `uv run --extra dev python
bin/ruff_suppression_index.py --write`. Check mode never writes. Write mode
validates the complete evidence graph before replacing only the generated
block through a same-directory temporary file and atomic `os.replace`.
Anticipated policy mismatches exit 1; invocation, decoding, Ruff, source-read,
and replacement failures exit 2 with one diagnostic and no traceback;
unexpected programming errors retain their traceback. Any failure before
replacement leaves the spec byte-for-byte unchanged.

| Group | Rules | Approved cardinality | Protected invariant | Real proof | Rejected alternatives | Approval |
|-------|-------|----------------------|---------------------|------------|-----------------------|----------|
| `[RUFF-SUP-002]` | `C901` | `1` directive; raw: `C901=1` | One external-boundary request/404/identity/filename/digest parser | PyPI HTTP and malformed-response tests | Generic fetch/response layer before a second real caller exists | P3 retained; T3A independent no-blocker review; user-authorized implementation 2026-08-04. |
| `[RUFF-SUP-003]` | `C901` | `1` directive; raw: `C901=1` | One enumerable fixture-table audit with a mutation probe per rule | checker self-test and live gate | General Markdown policy engine | P3 retained; T3A independent no-blocker review; user-authorized implementation 2026-08-04. |
| `[RUFF-SUP-004]` | `C901` | `1` directive; raw: `C901=1` | Fail-closed parser for one section/table grammar | malformed/status/exemplar/self-application tests | General Markdown parser or partial-row acceptance | P3 retained; T3A independent no-blocker review; user-authorized implementation 2026-08-04. |
| `[RUFF-SUP-005]` | `C901` | `1` directive; raw: `C901=1` | Bounded installed-tool mutation smoke over the closed vocabulary | direct self-test plus pytest matrix | Mini test framework inside the executable | P3 retained; T3A independent no-blocker review; user-authorized implementation 2026-08-04. |
| `[RUFF-SUP-008]` | `C901` | `1` directive; raw: `C901=1` | Explicit fail-closed publication/local/remote tag decision table | plan-tag and conflict tests | Generic rule engine or one helper per branch | P3 retained; T3A independent no-blocker review; user-authorized implementation 2026-08-04. |
| `[RUFF-SUP-011]` | `C901` | `1` directive; raw: `C901=1` | Closed 17-tool allowlist with explicit validation, public-client calls and result semantics | proxy and owner-thread matrices | Handler maps, CLI reflection or generic tool adapters | P3 retained; T3A independent no-blocker review; user-authorized implementation 2026-08-04. |
| `[RUFF-SUP-012]` | `C901` | `1` directive; raw: `C901=1` | Closed type-discriminated output serializer | exact object and schema tests | Reflection or generic dataclass serialization | P3 retained; T3A independent no-blocker review; user-authorized implementation 2026-08-04. |
| `[RUFF-SUP-014]` | `C901` | `1` directive; raw: `C901=1` | One alias/candidate/fingerprint/retirement/deadline arbitration transition | routing and concurrent-candidate tests | Predicate helpers that hide terminal-action order | P3 retained; T3A independent no-blocker review; user-authorized implementation 2026-08-04. |
| `[RUFF-SUP-015]` | `C901` | `1` directive; raw: `C901=1` | Closed event dispatcher with mandatory dead-owner reap | maintenance/fault/detach/identity-loss tests | Visitor or handler registry | P3 retained; T3A independent no-blocker review; user-authorized implementation 2026-08-04. |
| `[RUFF-SUP-016]` | `C901` | `1` directive; raw: `C901=1` | Nonblocking owner for admission close, cancellation, settlement, bounded drain, escalation and clearing | shutdown/deadline/transport tests | Split cleanup owners or event-loop blocking shutdown | P3 retained; T3A independent no-blocker review; user-authorized implementation 2026-08-04. |
| `[RUFF-SUP-018]` | `C901` | `1` directive; raw: `C901=1` | One server assembly unit shares bus, lifespan, protocol-era and registration state | dual-era/discovery/unknown-tool tests | Top-level handler churn or parallel legacy/modern servers | P3 retained; T3A independent no-blocker review; user-authorized implementation 2026-08-04. |
| `[RUFF-SUP-019]` | `C901` | `1` directive; raw: `C901=1` | Real-pipe peer-close, saturation, clean-exit and cleanup protocol | test plus platform classifier cases | Mocked pipes/process or counting forced cleanup as clean exit | P3 retained; T3A independent no-blocker review; user-authorized implementation 2026-08-04. |
| `[RUFF-SUP-021]` | `C901` | `1` directive; raw: `C901=1` | Real-PG fallback refresh, delivery, cursor, health and cleanup scenario | shared watcher lifecycle proof | Mocked PG, watcher or threads | P3 retained; T3A independent no-blocker review; user-authorized implementation 2026-08-04. |
| `[RUFF-SUP-022]` | `C901` | `1` directive; raw: `C901=1` | Causal add/remove/rebind/close/native-wake sequence | test plus topology suite | Split add/remove tests or fake waiters | P3 retained; T3A independent no-blocker review; user-authorized implementation 2026-08-04. |
| `[RUFF-SUP-024]` | `C901` | `1` directive; raw: `C901=1` | Compensating claim/create/detect/close/publish/release transaction | collision, exhaustion, cleanup and concurrency tests | Helpers passing partial creator/member/claim ownership | P3 retained; T3A independent no-blocker review; user-authorized implementation 2026-08-04. |
| `[RUFF-SUP-026]` | `C901` | `1` directive; raw: `C901=1` | Single inherited-primary/close/join/note/error-publication precedence owner | cleanup and timeout-precedence tests | Separate close and join exception owners | P3 retained; T3A independent no-blocker review; user-authorized implementation 2026-08-04. |
| `[RUFF-SUP-030]` | `C901` | `1` directive; raw: `C901=1` | One select-loop owner multiplexes input, PTY, wake, detach and terminal restoration | bridge/chord/forwarding/injection/wake/failure tests | Per-fd threads or fragmented multiplex ownership | P3 retained; T3A independent no-blocker review; user-authorized implementation 2026-08-04. |
| `[RUFF-SUP-031]` | `C901` | `1` directive; raw: `C901=1` | Single-consumer read/reply/activity/exit/master-retirement state machine | responder, close and consumer tests | Separating responder state from activity or master-close ownership | P3 retained; T3A independent no-blocker review; user-authorized implementation 2026-08-04. |
| `[RUFF-SUP-032]` | `C901` | `1` directive; raw: `C901=1` | FD lease, epoch rechecks, serialized writes, wait retry and retirement stay together | cancellation/fd-reuse/signal tests | Generic write loop lacking every pre/post-syscall epoch check | P3 retained; T3A independent no-blocker review; user-authorized implementation 2026-08-04. |
| `[RUFF-SUP-034]` | `C901` | `1` directive; raw: `C901=1` | Explicit query/reply dispatch and unsupported-query marking | live/startup/incomplete-scan tests | Opaque callback table or protocol module without a real subprotocol owner | P3 retained; T3A independent no-blocker review; user-authorized implementation 2026-08-04. |
| `[RUFF-SUP-035]` | `C901` | `1` directive; raw: `C901=1` | Sole blocking finalizer owns concurrent close election, escalation, streams and primary-error precedence | close/timeout/reap tests | Separate kill and stream-close owners | P3 retained; T3A independent no-blocker review; user-authorized implementation 2026-08-04. |
| `[RUFF-SUP-036]` | `C901` | `1` directive; raw: `C901=1` | Compact enumerable scenario-opcode dispatcher with firing proof per opcode | scripted and driver scenario suites | One trivial function per opcode | P3 retained; T3A independent no-blocker review; user-authorized implementation 2026-08-04. |
| `[RUFF-SUP-040]` | `C901` | `1` directive; raw: `C901=1` | Cross-generation real-PTY proof binds first lease, wired persistence, resumed no-lease and STOP ordering | neighboring restoration test | Splitting first run and resume into independent scenarios | P3 retained; T3A independent no-blocker review; user-authorized implementation 2026-08-04. |
| `[RUFF-SUP-043]` | `C901` | `1` directive; raw: `C901=1` | One real discovery/prewire/proxy/PTY/sentinel/cleanup story with exactly one completion and no pre-success recovery | diagnostic tests | Mocked or independently split stages | P3 retained; T3A independent no-blocker review; user-authorized implementation 2026-08-04. |
| `[RUFF-SUP-044]` | `C901` | `1` directive; raw: `C901=1` | Single-pass argv grammar and precedence | joined/separate/repeated/missing-value tests | Parser combinator or reordered token pass-through | P3 retained; T3A independent no-blocker review; user-authorized implementation 2026-08-04. |
| `[RUFF-SUP-046]` | `C901` | `1` directive; raw: `C901=1` | One target-precedence and backend error-translation boundary | path/config/handoff/shared-backend tests | Backend-specific or separate ambient resolvers | P3 retained; T3A independent no-blocker review; user-authorized implementation 2026-08-04. |
| `[RUFF-SUP-047]` | `C901` | `1` directive; raw: `C901=1` | One selector/token/claim/anchor-healing/human-fallback/creation owner preserves mutation and race precedence | dense identity/rejoin suites | Decomposition without a named resolution context that owns all shared evidence | P3 retained; T3A independent no-blocker review; user-authorized implementation 2026-08-04. |
| `[RUFF-SUP-048]` | `C901` | `1` directive; raw: `C901=1` | Bounded collision/race/recovery and evidence publication protocol | collision/claim/authority tests | Generic retry machinery or split publication | P3 retained; T3A independent no-blocker review; user-authorized implementation 2026-08-04. |
| `[RUFF-SUP-052]` | `C901` | `1` directive; raw: `C901=1` | Ordered Linux/Darwin/hostname portability fallback | platform preference/failure tests | Strategy classes or subprocess abstraction solely for score | P3 retained; T3A independent no-blocker review; user-authorized implementation 2026-08-04. |
| `[RUFF-SUP-053]` | `C901` | `1` directive; raw: `C901=1` | Isolated real-signal waiter replacement, topology and close protocol | reentrant SIGINT and watchdog tests | In-process or mocked-signal proof | P3 retained; T3A independent no-blocker review; user-authorized implementation 2026-08-04. |
| `[RUFF-SUP-054]` | `C901` | `1` directive; raw: `C901=1` | Real subprocess proves pre-exit message/notification NDJSON flush | adjacent cursor/policy cases | Post-exit-only observation or fake pipes | P3 retained; T3A independent no-blocker review; user-authorized implementation 2026-08-04. |
| `[RUFF-SUP-055]` | `C901` | `1` directive; raw: `C901=1` | One-pass shell precedence parser | extraction and tokenization matrices | Generic parser combinators or branch predicates | P3 retained; T3A independent no-blocker review; user-authorized implementation 2026-08-04. |
| `[RUFF-SUP-056]` | `C901` | `1` directive; raw: `C901=1` | Deterministic extraction/resolution/exemption/stale/count audit | defect fixtures and repository self-application | Broad or unconsumed exemptions | P3 retained; T3A independent no-blocker review; user-authorized implementation 2026-08-04. |
| `[RUFF-SUP-058]` | `C901` | `1` directive; raw: `C901=1` | Real SQLite/thread/output/cursor replay transaction boundary | test plus closed-pipe case | Storage/output call-count mocks | P3 retained; T3A independent no-blocker review; user-authorized implementation 2026-08-04. |
| `[RUFF-SUP-060]` | `C901` | `1` directive; raw: `C901=1` | Local fake protocol remains beside one exact ProcessInfo assertion | psutil failure neighbors | Reusable fake hierarchy | P3 retained; T3A independent no-blocker review; user-authorized implementation 2026-08-04. |
| `[RUFF-SUP-061]` | `C901` | `1` directive; raw: `C901=1` | Explicit adversarial manifest/filesystem/tag checklist | parameter matrix plus success and CLI-failure tests | Mutation DSL or synthetic verifier inputs | P3 retained; T3A independent no-blocker review; user-authorized implementation 2026-08-04. |
| `[RUFF-SUP-063]` | `C901` | `1` directive; raw: `C901=1` | One batch release owner preserves checks-only, dirty-worktree, discovery, changelog, dry-run, preparation/commit/precheck/postupdate/fresh-fence/tag/push order | Batch checks-only, no-op, dry-run, preparation-rerun, fence, wheel-failure, and explicit-version tests in `tests/test_release_script.py` | Branch-displacing admission helpers or a divergent dry-run planning path | P3 retained after T10 locality remediation and independent review; user-authorized implementation 2026-08-05. |
| `[RUFF-SUP-064]` | `C901` | `1` directive; raw: `C901=1` | One attempt-local watcher owner preserves construction, publication/recheck, run, failure classification, watcher/client cleanup, and rebuild wake order | Watcher failure, pre-publication harness death, fatal bounded-join, and provider-isolation tests in `extensions/taut_summon/tests/test_driver.py` | A cleanup helper that mirrors attempt locals or a second/global watcher owner | P3 retained after T10 locality remediation and independent review; user-authorized implementation 2026-08-05. |

Global raw-`noqa` inventory: `C901=38`, `F401=1`

<!-- BEGIN GENERATED RUFF SUPPRESSION INDEX -->
| Group | Locations | Directives | Raw diagnostics |
|-------|-----------|-----------:|-----------------|
| `[RUFF-SUP-002]` | `.github/scripts/release_publication.py::pypi_release_files` | 1 | `C901=1` |
| `[RUFF-SUP-003]` | `bin/check-dom15-fixtures::check` | 1 | `C901=1` |
| `[RUFF-SUP-004]` | `bin/check-plan-status-index::parse_rows` | 1 | `C901=1` |
| `[RUFF-SUP-005]` | `bin/check-plan-status-index::self_test` | 1 | `C901=1` |
| `[RUFF-SUP-008]` | `bin/release.py::plan_tag_action` | 1 | `C901=1` |
| `[RUFF-SUP-011]` | `extensions/taut_mcp/taut_mcp/_commands.py::execute_command` | 1 | `C901=1` |
| `[RUFF-SUP-012]` | `extensions/taut_mcp/taut_mcp/_commands.py::record_object` | 1 | `C901=1` |
| `[RUFF-SUP-014]` | `extensions/taut_mcp/taut_mcp/_process_reactor.py::ProcessReactor._on_resolved` | 1 | `C901=1` |
| `[RUFF-SUP-015]` | `extensions/taut_mcp/taut_mcp/_process_reactor.py::ProcessReactor._drain_events` | 1 | `C901=1` |
| `[RUFF-SUP-016]` | `extensions/taut_mcp/taut_mcp/_process_reactor.py::ProcessReactor.aclose` | 1 | `C901=1` |
| `[RUFF-SUP-018]` | `extensions/taut_mcp/taut_mcp/server.py::create_server` | 1 | `C901=1` |
| `[RUFF-SUP-019]` | `extensions/taut_mcp/tests/test_stdio_server.py::test_broken_stdout_after_initialize_is_a_clean_transport_exit` | 1 | `C901=1` |
| `[RUFF-SUP-021]` | `extensions/taut_pg/tests/test_reactor.py::test_taut_watcher_polls_and_refreshes_membership_without_native_waiter` | 1 | `C901=1` |
| `[RUFF-SUP-022]` | `extensions/taut_pg/tests/test_reactor.py::test_taut_watcher_native_waiter_rebinds_on_membership_topology_change` | 1 | `C901=1` |
| `[RUFF-SUP-024]` | `extensions/taut_summon/taut_summon/_driver.py::SummonDriver._first_summon` | 1 | `C901=1` |
| `[RUFF-SUP-026]` | `extensions/taut_summon/taut_summon/_driver.py::SummonDriver._teardown_generation` | 1 | `C901=1` |
| `[RUFF-SUP-030]` | `extensions/taut_summon/taut_summon/_pty.py::PtyHandle.attach` | 1 | `C901=1` |
| `[RUFF-SUP-031]` | `extensions/taut_summon/taut_summon/_pty.py::PtyHandle._event_stream` | 1 | `C901=1` |
| `[RUFF-SUP-032]` | `extensions/taut_summon/taut_summon/_pty.py::PtyHandle._write_all` | 1 | `C901=1` |
| `[RUFF-SUP-034]` | `extensions/taut_summon/taut_summon/_pty.py::_TerminalResponder._handle_csi` | 1 | `C901=1` |
| `[RUFF-SUP-035]` | `extensions/taut_summon/taut_summon/_stream.py::StreamJsonHandle.close` | 1 | `C901=1` |
| `[RUFF-SUP-036]` | `extensions/taut_summon/taut_summon/scripted_provider.py::_run_steps` | 1 | `C901=1` |
| `[RUFF-SUP-040]` | `extensions/taut_summon/tests/test_interaction.py::test_rich_host_real_pty_lease_wires_once_then_wired_resume_skips_lease` | 1 | `C901=1` |
| `[RUFF-SUP-043]` | `extensions/taut_summon/tests/test_live_local_llm.py::test_local_llm_pty_harness_posts_sentinel` | 1 | `C901=1` |
| `[RUFF-SUP-044]` | `taut/_scripts.py::_extract_pytest_runner_overrides` | 1 | `C901=1` |
| `[RUFF-SUP-046]` | `taut/client/_base.py::_ClientBase._resolve_target` | 1 | `C901=1` |
| `[RUFF-SUP-047]` | `taut/client/_identity.py::IdentityMixin._resolve_member` | 1 | `C901=1` |
| `[RUFF-SUP-048]` | `taut/client/_identity.py::IdentityMixin._create_member` | 1 | `C901=1` |
| `[RUFF-SUP-052]` | `taut/identity.py::capture_host_identity` | 1 | `C901=1` |
| `[RUFF-SUP-053]` | `tests/helpers/base_reactor_sigint_probe.py::_run_probe` | 1 | `C901=1` |
| `[RUFF-SUP-054]` | `tests/test_cli.py::test_cli_watch_json_flushes_records_while_live` | 1 | `C901=1` |
| `[RUFF-SUP-055]` | `tests/test_cli_claims.py::_shell_claim_tokens` | 1 | `C901=1` |
| `[RUFF-SUP-056]` | `tests/test_cli_claims.py::_validate_sources` | 1 | `C901=1` |
| `[RUFF-SUP-058]` | `tests/test_command_registry.py::test_registry_watch_flushes_dynamic_membership_and_preserves_broken_pipe_cursor` | 1 | `C901=1` |
| `[RUFF-SUP-060]` | `tests/test_identity.py::test_capture_psutil_process_reads_best_effort_fields` | 1 | `C901=1` |
| `[RUFF-SUP-061]` | `tests/test_release_artifact.py::test_verify_bundle_fails_closed_for_each_manifest_contract` | 1 | `C901=1` |
| `[RUFF-SUP-063]` | `bin/release.py::_run_batch_release` | 1 | `C901=1` |
| `[RUFF-SUP-064]` | `extensions/taut_summon/taut_summon/_driver.py::SummonDriver._run_watcher_attempt` | 1 | `C901=1` |
<!-- END GENERATED RUFF SUPPRESSION INDEX -->

## 11. Independent Review Workflow [DOM-11]

Non-trivial plans and completed work should receive an independent review.

Requirements:

- the reviewer receives the governing spec, active plan, relevant
  implementation note, and touched files
- the review focuses on errors, bad ideas, latent ambiguities, performative
  overengineering — process, abstraction, or ceremony that does not address
  a real risk or improve correctness — and whether a different engineer
  could implement the plan confidently and correctly
- the authoring agent considers each review point explicitly
- the authoring agent either updates the work or records why the current path
  remains the best choice
- prefer a different agent family or model than the original author when one is
  available

## 12. Skills Lifecycle [DOM-12]

Reusable skills live in `skills/`.

Requirements:

- create a skill when repeated work in a stable area would benefit from shared
  instructions
- common candidates include running, adding, testing, debugging, release, or
  domain-specific workflows
- skills should complement runbooks: skills are task-scoped instructions,
  runbooks are repository process guidance
- after using a skill, evaluate whether it should be updated

Useful evaluation questions:

- did the skill omit a required command, check, or failure mode?
- did it leave the owner, boundary, verification, or required action unclear?
- did the work require repeated clarification that should become part of the
  skill?

## 13. Agent Availability Bootstrap [DOM-13]

At session start and periodically over time, record which agent families are
available in the current environment.

Requirements:

- note which agents are available for independent review work
- distinguish between present, verified usable, and blocked states when
  recording availability
- refresh the inventory when tooling changes materially, meaning agent
  availability, credentials, invocation path, or review preference has changed
  enough to alter how review work should be assigned
- prefer a different agent, not just a same-family subagent, for plan review
  when one is available

## 14. Coalescing and Memory Maintenance [DOM-14]

The documentation surface is a tiered memory. Raw, dated records (lesson
entries; completed plans) are the moment tier. Distilled rules (golden
rules, runbook amendments), the plans ledger, and promoted skills are
summary tiers. The working tree holds only the current, assembled state;
git history is the archive. Docs change in place to match reality — going
back in time is git's job, not the working tree's.

Requirements:

- each repository keeps coalescing state in `docs/coalescing.md`: declared
  per-tier thresholds, per-tier watermarks, and a one-line-per-run log
- coalescing triggers are event-derived, not calendar-based: counts are
  computed from the watermark and the current tree, never stored, and are
  denominated in the repository's fold unit — a domain-grouped ledger
  counts per section, not repo-wide — counting only fold-eligible (cold,
  unfolded) material; the fold unit and its matching progress model are
  declared in the repository's `docs/coalescing.md` (per-section
  watermarks for domain-grouped ledgers; a fold-records index, not a date
  cursor, for ledgers folded by theme-cluster across dates, since a date
  cursor falsely claims older unfolded material behind it was folded)
- the session-start trigger check is read-only: a tripped threshold is
  reported to the user, never acted on mid-task. All coalescing writes —
  including checked-deferred records — happen only inside an authorized
  maintenance task (user request, or agreed completion-boundary work).
  Silently ignoring a trip is the only invalid response; reporting costs
  one sentence
- an authorized coalescing sweep is both memory compaction and bounded
  maintenance. Before distillation or retirement, inspect the coalescing
  surfaces for defects that make memory inaccurate, non-derivable,
  unreachable, or unverifiable. Repair an observed defect in the same wave
  when the repair is inside the declared coalescing boundary, reversible, and
  supported by current-tree or source-SHA evidence. Merely logging such a
  repairable defect is not a valid completed sweep
- bounded maintenance is not general cleanup. It covers the lesson ledger,
  plan status index and retirement ledger, fold cues and watermarks,
  traceability needed to retrieve folded material, promotion ownership, and
  the coalescing gates themselves. Product behavior, unrelated documentation,
  and speculative redesign remain outside the sweep
- ambiguous repairs, destructive actions, and changes that require new
  authority are deferred explicitly with the evidence gap, owner, and
  reconsideration condition. Existing landing authorization remains mandatory
  for deletion, watermark advancement, plan soft-retirement, and other
  destructive or archival transitions
- enumerable coalescing metadata uses an executable gate. In this repository,
  every plan file appears exactly once in a structured status index with an
  allowed lifecycle status and explicit exemplar marker. The closed status
  vocabulary is `draft`, `active`, `status-review`, `completed`, `superseded`,
  and `retired-pending`; `status-review` is a conservative maintenance
  quarantine, not a completion state. The exemplar field is exactly `yes` or
  `no`. Missing rows, duplicate rows, nonexistent-path rows, unknown statuses,
  unknown exemplar values, and malformed status tables fail the gate. A sweep
  repairs gate failures before trusting the affected trigger count
- coalescing is additive-first across commit boundaries: distillation
  drafts and retirement candidates may exist uncommitted; deleting raw
  material, advancing watermarks, and retiring plans require a
  landing-authorized phase with a durable checkpoint
- deferrals have real state: a checked-deferred record carries
  `checked_through` (date and SHA), the derived counts, the reason, and a
  reconsideration condition — so an unchanged count does not re-nag every
  session, and a changed count does
- coalescing is two-phase and additive-first: distill, verify links and
  cues, then retire; every fold leaves a retrieval cue — the date range
  plus a `source_sha`, a pre-fold commit that verifiably contains the raw
  material — in the surviving summary or ledger line. The fold commit may
  be recorded in the run log after it exists, but it is never the cue
- recent or still-cited raw material stays verbatim; golden rules and
  safety invariants carry an importance floor — exempt from automated
  decay, changed only by explicit revision, supersession, or deprecation
  with a `(revised YYYY-MM-DD; was: <gist>)` marker
- active plans keep instructions mutable and logs append-only, and become
  immutable at closure; retirement is two-step — the sweep soft-retires
  (status `retired-pending`, backlinks converted, ledger line written)
  only after the harvest gate in `runbooks/writing-plans.md` passes, and
  physical deletion happens in a dedicated follow-up change after the
  gate is independently verified; plans marked `exemplar` in the status
  index are exempt until their exemplar role is superseded
- run-log entries are claims: each fold line must be spot-checkable against the
  diff of the fold commit. Each run-log entry records both folds and maintenance
  repairs. If a detected defect is deferred, the log names why it was unsafe or
  unauthorized to repair rather than presenting diagnosis alone as maintenance

Owner: whoever the sweep check nags — any agent that observes a tripped
threshold at session start. Boundary: lessons, plans, runbook and skill
promotion, retrieval cues and watermarks, the gates that make those
coalescing surfaces accurate and derivable, and (for the guidance repo)
cross-repo fold-up; product behavior and unrelated cleanup remain outside the
sweep, while specs and implementation docs are living documents maintained
per [DOM-6] and [DOM-7], not coalesced. Verification: the run log, the
repository traceability gate, and every executable coalescing metadata gate
(in this repository, `bin/check-plan-status-index`). Required action: report a
session-start trip; inside an authorized sweep, repair reversible,
evidence-backed in-boundary defects before folding, and explicitly defer only
ambiguous, destructive, or unauthorized repairs with their owner and
reconsideration condition.

## 15. Task Classification [DOM-15]

Every unit of work is classified before the repository preflight or
first edit. The unit of work is the whole requested outcome; slices
inherit the unit's minimum class. Classification scales planning
artifacts and review machinery; it never scales the verification floor —
evidence lines, completion claims backed by reruns from current state,
firing tests for touched enumerable contracts, failing-test-first with
its named exit (engineering principle §10), declared deviations,
formatter ownership, no agent self-attribution, and dirty-tree
discipline apply identically at every class.

The class is the **highest trigger that fires**, judged by what the
change requires — not by what the author chooses to produce:

| Class | Fires when | Planning artifact | Review |
|-------|-----------|-------------------|--------|
| 0 — Read-only | Nothing in the repository changes | None | None; claims cite evidence and distinguish verified from inferred |
| 1 — Trivial | A change with no observable behavior change and no normative doc force (typos, comments, link repairs, formatting) | Classification line plus what/why/verification, recorded in the commit message — or in the handoff report when the work is left uncommitted for review | None |
| 2 — Small | Observable behavior changes but **conforms to existing intended behavior**, evidenced by something independently inspectable — a governing spec section, an explicit user requirement in the session, or an existing contract test. Author inference is not intent evidence; without it, the class is 3. Also requires: reversible, and **no [DOM-5] non-trivial or risky trigger fires** | The abbreviated preflight, pre-edit: (1) outcome checklist, (2) the intent evidence or `Source spec: None — <reason>`, (3) invariants that must not move, (4) the planned verification command. The observed result is appended at completion. Recorded in the commit/PR description or handoff report | Author fresh-eyes |
| 3 — Standard | Any **[DOM-5] non-trivial trigger** | Full dated plan per `runbooks/writing-plans.md`, status-index row, deviation log | Independent review of the plan **and** of the completed work ([DOM-11]) |
| 4 — Risky | Any **[DOM-5] risky trigger** | Class 3 plus the hardening-plans checklist | Class 3 plus review before implementation begins |
| 5 — Spec-changing | **[DOM-6] requires a spec change** (whether or not one has been drafted), or any normative spec text is edited — including clarification-only edits, which use promotion strategy D per `writing-plans.md` §4c | Class 3 plus spec baseline, exact proposed delta, named promotion strategy; the hardening-plans checklist **only if a [DOM-5] risky trigger also fires** — otherwise declare `hardening: N/A — no risky trigger` | Class 3 reviews plus independent review of the delta before the spec-promotion slice; review-before-implementation when hardening applies |
| +P — Process-changing (modifier, not a class) | The change is [DOM-6]-material to how future work is **planned, implemented, reviewed, or verified** — regardless of which surface hosts it. A non-material edit to a skill or runbook (a typo, a link fix) is not +P; a material process change hiding in an "implementation" doc is | Declared as `Class N+P`; effective requirements are `max(N, 5)`'s | Effective class's review plus pre-landing review, different agent family preferred |

Routine release execution is the sole Class 2 exception to Class 2's
reversibility and no-[DOM-5]-trigger requirements. It applies only when the
user explicitly requests a release and the agent invokes the documented
`bin/release.py` path for the requested target without changing the release
machinery or disabling any normal gate required by [TAUT-12.5]. The
abbreviated Class 2 preflight records the requested target and version, release
invariants, and the exact normal verification command; no dated release plan
is created.
Publication is observable and irreversible, so this is never Class 1.
Product changes and preparation outside `bin/release.py` are separate units
of work and do not inherit the exception. `--skip-checks`, `--retag`, tag
movement, manual tag or artifact publication, and any recovery that departs
from the unchanged `bin/release.py` path are outside the exception and are
classified against [DOM-5]/[DOM-6] normally. Reinvoking the same normal command
after a failed or partially completed release remains inside the exception when
[TAUT-12.5]'s built-in resumable path is sufficient; classify any separate
corrective change before that rerun.

Rules:

- the review and verification floors accumulate; planning artifacts
  **subsume**: a higher-class plan replaces the lower-class records, it
  does not add to them (a class-3 plan is the planning record — no
  separate class-2 preflight note is owed). The hardening-plans
  checklist is required by the class-4 trigger, never by inheritance:
  class-5 work with no [DOM-5] risky trigger declares `hardening: N/A —
  no risky trigger` instead of writing empty rollback sections. [DOM-5]
  risk and [DOM-6] materiality are different axes; they combine when
  both fire
- class-3 independent review may return a short structured brief —
  goal, class claim, invariants, verification, top risks. The brief is
  an **output** form only: the reviewer still receives the canonical
  inputs (governing spec, plan, touched files) and the disposition loop
  still runs in full. Classes 4 and 5 keep the full output bar. Author
  fresh-eyes substitutes for independent review only when no second
  agent is available, with the limitation disclosed — at every class
- classification is a one-line declared claim citing its trigger
  reasoning ("Class 2: restores spec section XYZ-3 intent, reversible, no DOM-5
  trigger"); an undeclared class on non-read-only work fails the
  completion gate
- escalators are one-way and declared mid-flight: when any [DOM-5]
  trigger or [DOM-6]-material discovery fires during work, the class
  rises to that trigger's class at that moment. The engineering
  warning signs (a second path appearing, rollback becoming
  undescribable) are not triggers of their own — they force
  re-classification against the same [DOM-5]/[DOM-6] lists. Silent
  continuation at the old class is the violation, not the escalation
- `+P` is a modifier: it combines with the base class as
  `max(base, 5)` plus the pre-landing different-family review; there
  is exactly one declaration format, `Class N+P`
- classes 1–2 keep their record in the commit history (or the handoff
  report when uncommitted) — git is the ledger for small work, which
  also keeps `docs/plans/` free of [DOM-14] harvest debt
- when classification is genuinely uncertain after reading the [DOM-5]
  lists, ask once, narrowly

Classification fixtures. This table is [DOM-15]'s enumerable contract
(engineering principle §12) and carries an executable gate: a
repository adopting this section ships a structural checker that fails
when a fixture names an unknown class, a class or the `+P` modifier
has no fixture, a class-1/2 fixture omits its negative-trigger facts,
the routine-release exception fixture is absent, or the
cumulative-requirements rule is absent (this repository:
`bin/check-dom15-fixtures`, exit nonzero on violation). Semantic
classification of real tasks remains judgment, verified by the
declared-claim line and by review; repositories with test harnesses
additionally encode these fixtures as firing tests over their own
tooling. Fixture rows state their trigger facts explicitly — class
follows from the stated facts, never from file topology. Edits to
[DOM-5]'s trigger lists update these fixtures in the same change: the
checker enforces presence, review enforces meaning.

| Fixture (trigger facts stated) | Class |
|---------|-------|
| Answer an architecture question; survey a repo — nothing changes | 0 |
| Fix a spelling error; repair a broken doc link — no behavior change, no normative force, no [DOM-5] trigger fires | 1 |
| Behavior-preserving refactor, one module, following the established pattern — given: no [DOM-5] non-trivial or risky trigger fires (in particular, no zero-context ambiguity) | 1 |
| Behavior-preserving refactor across two modules with unclear ownership — zero-context ambiguity, a [DOM-5] non-trivial trigger, fires | 3 |
| Bug fix restoring validation that a cited spec section requires — the cited section is the intent evidence; reversible; given: no [DOM-5] trigger fires | 2 |
| Same fix, but no spec, no stated user requirement, no contract test — intent evidence absent | 3 |
| Fix spanning a producer and a consumer — given: the two sides are distinct major surfaces, so a [DOM-5] non-trivial trigger fires | 3 |
| Same shape, but both sides live inside one module — reversible, spec-cited intent, and no other [DOM-5] trigger fires | 2 |
| Explicit user request is intent evidence for a routine release through unchanged `bin/release.py`; every [TAUT-12.5]-required normal gate remains enabled; the [DOM-15] routine-release exception overrides reversibility and [DOM-5] triggers for release execution only; no bypass, retag, manual publication, or recovery outside that unchanged path is involved; built-in resumable reinvocation under [TAUT-12.5] remains the same routine release | 2 |
| Implement an already-specified CLI flag — CLI shape changes ([DOM-5] risky) | 4 |
| Introduce background or deferred processing whose intended behavior an existing spec already governs — a [DOM-5] risky trigger fires; no [DOM-6] spec change is required | 4 |
| Clarify normative spec wording, behavior unchanged — normative spec text edited; no risky trigger, so `hardening: N/A` | 5 (strategy D) |
| New feature whose intended behavior is undocumented and [DOM-6]-material — a spec is required first | 5 |
| Materially change a skill, runbook, or gate — [DOM-6]-material to future process; base class 3 | Class 3+P (effective 5) |
| Typo fix inside a skill file — not [DOM-6]-material | 1 |
| Class-2 fix discovers a storage-format edit is needed — a [DOM-5] risky trigger fires mid-flight | Escalate to 4 at that moment, declared |

Owner: the agent starting the work declares the class; any reviewer
may challenge it. Boundary: every unit of work from promotion of this
section forward; explicit user instructions and safety constraints
still rank above classification in the decision hierarchy.
Verification: the declared class line plus the class-required
artifacts existing; new classification guidance checked against the
fixture table. Required action: declare the class before the first
edit; escalate loudly the moment a trigger fires.

## Related Plans

- `docs/plans/2026-07-06-evaluation-findings-remediation-plan.md` — S8
  reconciled this spec's stale snapshot and backlinks and added the
  `tests/test_docs_references.py` reference gate.

The original documentation-system bootstrap predates the retained plan
archive; plans in `docs/plans/` cite this spec's [DOM-*] codes when they
touch the operating model.
- `docs/plans/2026-07-14-agent-guidance-propagation-plan.md`
- `docs/plans/2026-07-14-routine-release-classification-plan.md`: added the
  narrow Class 2 exception for explicitly requested execution of unchanged
  normal release machinery.
- `docs/plans/2026-07-28-coalescing-wave-plan.md`: added bounded maintenance
  before distillation and retirement, plus the structured plan-status gate.
- `docs/plans/2026-07-28-channel-topics-plan.md`: adds the deterministic
  executable CLI-claim gate alongside the channel command rehome that exposed
  the prior prose-only gap.
- `docs/plans/2026-08-04-ruff-complexity-and-suppression-registry-plan.md`:
  activates repository-wide C901 visibility at 10 and the reviewed,
  symbol-keyed suppression registry and generator.
