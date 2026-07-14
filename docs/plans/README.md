# Plans

This directory contains dated implementation plans.

## Rules

- Use plans for non-trivial changes, architectural work, or any change where a
  zero-context engineer would otherwise need to rediscover the approach.
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
