# Plans

This directory contains dated implementation plans.

## Rules

- Follow [DOM-15]: Classes 3 and above use dated plans; Classes 1 and 2 keep
  their record in git or the handoff. The sole irreversible Class 2 exception
  is an explicitly requested routine release through unchanged `bin/release.py`
  with every [TAUT-12.5]-required normal gate enabled.
- Prefer filenames like `YYYY-MM-DD-short-name-plan.md`.
- Plans should cite exact spec sections when they exist.
- Plans should stay current enough to reflect what is being implemented.
- Completed plans should retain their verification and review notes as history.
- Prefer over-prescriptive plans on risky work: invariants, hidden couplings,
  rollback, rollout, and anti-mocking guidance should be explicit.
- Do not start risky implementation work until the hardening checklist is
  satisfied and the rollback or sequencing story is written clearly enough to
  survive review.

## Standard

Every plan should include:

- goal
- source documents
- context and key files
- invariants and constraints
- dependency-ordered tasks
- testing plan
- verification and gates
- independent review loop
- out of scope
- fresh-eyes review

For risky changes, also include the plan-hardening material documented in:

- `docs/agent-context/runbooks/hardening-plans.md`

Risky plans are blocked if they do not make explicit:

- what must not change
- enough current-structure context to find the right edit point
- what must stay real in tests
- rollback or rollout sequencing when compatibility depends on it

## Active Plans

- `2026-07-28-coalescing-wave-plan.md` — derive all [DOM-14] tier counts,
  harvest plan and promotion candidates, and record an additive-only wave that
  preserves the live product worktree and defers retirement to a
  landing-authorized follow-up.
- `2026-07-28-message-react-plan.md` — implemented and locally verified, but
  uncommitted, configured exact-message reactions as per-recipient consumable
  notification pointers across Python, nested CLI, and MCP. The implementation
  uses current exact-thread membership, excludes the actor, advances the
  actor's high-water cursor, and makes one best-effort SimpleBroker 5.6.1
  full-requested-set broadcast without maintained reaction state.
- `2026-07-27-message-show-delete-plan.md` — add exact-ID
  `message show` and author-only physical `message delete` across the Python
  API, nested CLI, and MCP; show advances the acting member's existing
  high-water seen cursor, while delete performs no notification, thread,
  membership, or cursor cascade.
- `2026-07-17-agent-guidance-propagation-plan.md` — land the agent-guidance
  delta wave (source `b248e1c`): [DOM-14] fold-unit trigger promotion, six
  coalescing-skill method refinements, the new interface-review skill,
  writing-plans and review-loops additions, the unified verdict vocabulary,
  and the call-agent review-brief standard.
- `2026-07-15-taut-0.7.1-portability-and-coverage-plan.md` — completed macOS
  and Windows SQLite-only MCP proof, direct root coverage recovery,
  publication-record correction, and coordinated 0.7.1 release.
- `2026-07-15-taut-mcp-release-integration-plan.md` — add `taut-mcp` as the
  fourth GitHub-only exact-SHA release target, root-owned immutable artifact,
  universal release proof member, and same-run MCP coverage producer without
  performing a release.
- `2026-07-15-per-call-read-limit-plan.md` — make unread page size a
  per-call core keyword with exact cursor pagination, a 1,000 core default,
  a 100-message MCP default, and shared SQLite/PostgreSQL firing tests.
- `2026-07-14-agent-interfaces-runbook-adoption-plan.md` — adopt the
  designing-agent-facing-interfaces runbook from agent-guidance `a4b4345`
  (completed; kept for its review dispositions).
- `2026-07-14-taut-mcp-extension-plan.md` — propose a separately packaged,
  client-lifetime stdio MCP server with dynamic path-scoped workspace
  attachment, a master connection reactor over token-bound workspace reactors,
  explicit CLI-shaped tools, an aggregate read-only current-notifications
  resource, standard edge hints, and an optional experimental Claude adapter.
- `2026-07-14-routine-release-classification-plan.md` — classify explicitly
  requested releases through unchanged normal machinery as Class 2 without a
  dated release plan, while preserving escalation for bypasses, retagging,
  manual publication, recovery outside the built-in resumable path, and
  machinery changes.
- `2026-07-14-blank-message-no-op-plan.md` — treat empty, runtime-Unicode
  whitespace, and `Cf`-only user messages as typed no-ops, with silent CLI
  exit 2 and Summon terminal-mode handling.
- `2026-07-14-trusted-identity-selector-fast-path-plan.md` — preserve
  selector-free identity magic while letting existing `as` and token selectors
  bypass process capture, keeping creation command-gated and `rejoin` the sole
  explicit process-claim association path.
- `2026-07-14-taut-tui-cross-reference-correction-plan.md` — correct the
  stale [TAUT-1] TUI citation from watcher section [TAUT-8.4] to the rich-TUI
  roadmap contract in [TAUT-12.4], with no behavior change.
- `2026-07-14-agent-guidance-propagation-plan.md` — adopt the 2026-07-14
  agent-guidance wave ([DOM-14] coalescing, [DOM-15] task classification,
  review lens, crosswalk, four skills) with SHA-pinned provenance.

- `2026-07-14-smaller-quality-followups-plan.md` — add credential and 0.6.1
  release-note hygiene, prove the real PostgreSQL polling fallback, add one
  bounded client state machine, and optimize caught-up unread counting with a
  measured public-API fast path.
- `2026-07-14-single-project-config-source-spec-plan.md` — make `.taut.toml`
  the explicit single project-configuration source while preserving no-config
  SQLite and config-required PostgreSQL behavior.
- `2026-07-14-terminal-output-safety-plan.md` — add packaged safe defaults,
  human `.taut.toml` customization, and one public terminal-control escape
  function shared by core and extensions, while preserving exact storage/JSON
  content and Taut's stated trust boundary.
- `2026-07-14-universal-release-gates-plan.md` — make every package release
  target use one universal core, PostgreSQL, and Summon local gate by default,
  preserve the explicit human override, and require both canonical exact-SHA
  workflows without enqueueing duplicate matrices.
- `2026-07-13-ci-speed-determinism-release-evidence-plan.md` — remove
  coverage-only test reruns, give expensive artifacts and signal probes safe
  owners, keep strict local-LLM CI proof, and reuse exact-SHA test artifacts
  across coordinated release tags.
- `2026-07-13-release-metadata-preparation-plan.md` — make release metadata a
  deterministic helper-owned preparation phase before consistency gates, while
  keeping changelog prose human-owned and irreversible release actions last.
- `2026-07-13-summon-stop-release-race-plan.md` — hypothesis-driven diagnosis
  and root fix for the second-generation rich-host PTY STOP/release race while
  preserving fixed-width xdist load and existing timeout budgets.
- `2026-07-13-bounded-summon-process-test-parallelism-plan.md` — fixed-width
  deterministic Summon process pressure: four local workers, two CI workers,
  and retained one-worker external-live/local-LLM boundaries.
- `2026-07-12-lazy-command-extensions-and-rich-tui-composition-plan.md` —
  implemented and verified, but uncommitted, command-extension registry,
  subsystem-lazy imports, public Summon controller/host interaction, and rich
  future TUI composition contract; no release action has been performed.
- `2026-07-10-ci-failure-remediation-plan.md` — v0.5.1 CI remediation for
  PTY interrupt ordering, watcher pre-publication stop, Windows artifact
  fixture placement, and deterministic topology-rebind proof.
- `2026-07-10-taut-dynamic-native-waiter-replacement-plan.md` — narrow
  SimpleBroker 5.3 live waiter-replacement correction for Taut's owner-thread
  membership generations and taut-pg native acceptance proof.
- `2026-07-10-taut-summon-quality-remediation-plan.md` — confirmed state,
  lifecycle, control, CLI, artifact-release, coverage, and documentation
  remediation for the paired core/Summon surface.
- `2026-07-09-taut-reactor-safety-plan.md` — two-track core watcher and
  Summon control-reactor lifecycle, ownership, wake, recovery, and supervision
  hardening plan.

## Retired Plans

One line per retired plan; the body lives in git at the source SHA.

| Plan | Dates | Outcome | Absorbed into | Source SHA |
|------|-------|---------|---------------|------------|
