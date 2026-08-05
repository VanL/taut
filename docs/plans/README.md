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

## Plan Status Index

This table is the canonical status source for every plan file in this
directory. Run `bin/check-plan-status-index` after changing it.

| Plan | Status | Exemplar | Note |
|------|--------|----------|------|
| `2026-06-12-taut-0.1.1-hardening-plan.md` | completed | no | Completed; evidence reconciled from the plan and repository history. |
| `2026-06-12-taut-foundation-plan.md` | completed | no | Completed; evidence reconciled from the plan and repository history. |
| `2026-06-17-github-actions-release-workflows-plan.md` | completed | no | Completed; evidence reconciled from the plan and repository history. |
| `2026-06-17-github-release-helper-plan.md` | completed | no | Completed; evidence reconciled from the plan and repository history. |
| `2026-06-17-implementation-review-followups-plan.md` | completed | no | Completed; evidence reconciled from the plan and repository history. |
| `2026-06-17-taut-pg-extension-plan.md` | completed | no | Completed; evidence reconciled from the plan and repository history. |
| `2026-06-18-member-identity-addressing-plan.md` | completed | no | Completed; evidence reconciled from the plan and repository history. |
| `2026-06-18-simplebroker-latest-timestamp-plan.md` | completed | no | Completed; evidence reconciled from the plan and repository history. |
| `2026-06-30-assets-reference-cleanup-plan.md` | completed | no | Completed; evidence reconciled from the plan and repository history. |
| `2026-06-30-client-module-split-plan.md` | completed | no | Completed; evidence reconciled from the plan and repository history. |
| `2026-07-01-schema-shim-retirement-plan.md` | completed | no | Completed; evidence reconciled from the plan and repository history. |
| `2026-07-01-taut-state-sql-dialect-plan.md` | completed | no | Completed; evidence reconciled from the plan and repository history. |
| `2026-07-01-taut-watch-runtime-plan.md` | completed | no | Completed; evidence reconciled from the plan and repository history. |
| `2026-07-06-evaluation-findings-remediation-plan.md` | completed | no | Completed; landed evidence includes `663ff867`. |
| `2026-07-06-taut-summon-plan.md` | completed | no | Completed; landed evidence includes `d5e3078`. |
| `2026-07-06-taut-summon-spec-draft.md` | superseded | no | Superseded by the promoted Summon specification. |
| `2026-07-07-taut-summon-pty-harness-adapter-plan.md` | completed | no | Completed; landed evidence includes `587e6e3`. |
| `2026-07-08-release-helper-simplebroker-port-plan.md` | completed | no | Completed; landed evidence includes `9f16343a`. |
| `2026-07-08-taut-sqlite-contention-hardening-plan.md` | superseded | no | Explicitly replaced by the 2026-07-09 reactor-safety plan. |
| `2026-07-09-taut-reactor-safety-plan.md` | completed | no | Completed; landed evidence includes `7ba4def`. |
| `2026-07-10-ci-failure-remediation-plan.md` | completed | no | Completed; evidence reconciled from the plan and repository history. |
| `2026-07-10-taut-dynamic-native-waiter-replacement-plan.md` | completed | no | Completed; evidence reconciled from the plan and repository history. |
| `2026-07-10-taut-summon-quality-remediation-plan.md` | completed | no | Completed; evidence reconciled from the plan and repository history. |
| `2026-07-11-multi-factor-review-remediation-plan.md` | completed | no | Completed; evidence reconciled from the plan and repository history. |
| `2026-07-11-v0.5.2-coordinated-release-plan.md` | completed | no | Completed; evidence reconciled from the plan and repository history. |
| `2026-07-12-automatic-display-name-capitalization-plan.md` | completed | no | Completed; landed evidence includes `b8d145e`. |
| `2026-07-12-lazy-command-extensions-and-rich-tui-composition-plan.md` | completed | no | Completed; evidence reconciled from the plan and repository history. |
| `2026-07-13-bounded-summon-process-test-parallelism-plan.md` | completed | no | Completed; evidence reconciled from the plan and repository history. |
| `2026-07-13-ci-speed-determinism-release-evidence-plan.md` | completed | no | Completed; evidence reconciled from the plan and repository history. |
| `2026-07-13-release-metadata-preparation-plan.md` | completed | no | Completed; evidence reconciled from the plan and repository history. |
| `2026-07-13-summon-stop-release-race-plan.md` | completed | no | Completed; evidence reconciled from the plan and repository history. |
| `2026-07-14-agent-guidance-propagation-plan.md` | completed | no | Completed; landed evidence includes `c09e95e`. |
| `2026-07-14-agent-interfaces-runbook-adoption-plan.md` | completed | yes | Completed exemplar retained for its review dispositions. |
| `2026-07-14-blank-message-no-op-plan.md` | completed | no | Completed; evidence reconciled from the plan and repository history. |
| `2026-07-14-routine-release-classification-plan.md` | completed | no | Completed; landed evidence includes `b2da819`. |
| `2026-07-14-single-project-config-source-spec-plan.md` | completed | no | Completed; evidence reconciled from the plan and repository history. |
| `2026-07-14-smaller-quality-followups-plan.md` | completed | no | Completed; evidence reconciled from the plan and repository history. |
| `2026-07-14-taut-mcp-extension-plan.md` | completed | no | Completed; landed evidence includes `4d25deb`. |
| `2026-07-14-taut-tui-cross-reference-correction-plan.md` | completed | no | Completed; landed evidence includes `b2da819`. |
| `2026-07-14-terminal-output-safety-plan.md` | completed | no | Completed; evidence reconciled from the plan and repository history. |
| `2026-07-14-trusted-identity-selector-fast-path-plan.md` | completed | no | Completed; landed evidence includes `b2da819`. |
| `2026-07-14-universal-release-gates-plan.md` | completed | no | Completed; landed evidence includes `ce2bbb1`. |
| `2026-07-15-per-call-read-limit-plan.md` | completed | no | Completed; evidence reconciled from the plan and repository history. |
| `2026-07-15-taut-0.7.1-portability-and-coverage-plan.md` | completed | no | Completed; evidence reconciled from the plan and repository history. |
| `2026-07-15-taut-mcp-release-integration-plan.md` | completed | no | Completed; landed evidence includes `dd699e4`. |
| `2026-07-28-agent-guidance-delta-wave-plan.md` | completed | no | Class 3+P propagation of the agent-guidance wave at `51626db`; transplants applied and local gates green, independent review and landing authorization outstanding. |
| `2026-07-17-agent-guidance-propagation-plan.md` | completed | no | Completed; landed evidence includes `9221cbd`. |
| `2026-07-27-message-show-delete-plan.md` | completed | no | Completed; landed evidence includes `8509dc4`. |
| `2026-07-28-coalescing-wave-plan.md` | completed | no | Bounded-maintenance process, checked plan index, and coalescing derivation landed after independent review. |
| `2026-07-28-channel-topics-plan.md` | completed | no | Class 5 channel-topic, command-rehome, MCP-naming, and CLI-claim-gate implementation; all implementation, verification, and independent-review gates passed before the owner-authorized targeted landing. |
| `2026-07-28-direct-message-navigation-plan.md` | completed | no | Class 5 DM navigation implementation; all behavior slices, backend gates, and independent reviews complete. |
| `2026-07-28-message-react-plan.md` | completed | no | Completed; landed evidence includes `788cdd3`. |
| `2026-07-28-summon-terminal-retirement-plan.md` | completed | no | Class 5+P Summon terminal-retirement and coverage-integrity implementation; all local verification and independent-review gates passed before the owner-authorized targeted landing. |
| `2026-07-28-taut-mcp-dual-era-sessionless-plan.md` | active | no | Class 5 dual-era MCP implementation, local proof, and targeted commit are complete; hosted CI OS/Python evidence remains. |
| `2026-07-29-taut-chat-pypi-publication-plan.md` | active | no | Class 5 core-distribution rename and exact-artifact PyPI Trusted Publishing plan; independent Opus review passed after factual corrections. |
| `2026-07-31-simplebroker-6-reconciliation-plan.md` | completed | no | Class 5 compatibility reconciliation for the user-selected SimpleBroker 6.0.0 and SimpleBroker-PG 3.5.0 floors; implementation and completed-work review passed. |
| `2026-08-01-summon-rich-host-global-state-plan.md` | completed | no | Class 5 rich-host environment, provider-child identity, and explicit signal-ownership implementation; all local gates and independent reviews passed before the owner-authorized targeted commit. |
| `2026-08-04-ruff-complexity-and-suppression-registry-plan.md` | completed | no | Class 5+P repository-wide C901 visibility, symbol-keyed suppression registry, reviewed ownership refactors, and locality remediation completed with current local gates and independent review. |
| `2026-08-05-ruff-stable-default-expansion-plan.md` | completed | no | Class 5+P exact SimpleBroker Ruff 0.16.1 rule parity; implementation, local verification, independent review, and owner-authorized targeted landing completed. |

## Retired Plans

One line per retired plan; the body lives in git at the source SHA.

| Plan | Dates | Outcome | Absorbed into | Source SHA |
|------|-------|---------|---------------|------------|
