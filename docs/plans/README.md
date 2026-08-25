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
| `2026-08-24-concurrency-and-schema-contract-alignment-plan.md` | completed | no | Class 5 contract alignment for live logical dump, SQLite search rotation, destructive-load input stability, and the future ordered core `ensure_schema` ladder; implementation, cross-backend verification, independent completed-work review, and owner-authorized targeted closeout passed. |
| `2026-08-24-extension-seams-process-containment-coverage-plan.md` | active | no | Class 5+P hardened plan; the E1 public activity-neutral core/MCP seams and historical compatibility canary are authorized and in progress, while E2 process containment and T1 coverage production remain unpromoted. |
| `2026-08-20-debug-payload-redaction-plan.md` | completed | no | Class 5 spec-changing plan for lazy, final-text, value-only credential redaction shared by both debug sinks; implementation, full local verification, independent completed-work review, and owner-authorized landing passed. |
| `2026-08-20-human-tabular-output-plan.md` | completed | no | Class 3 core/Summon field-before-structure correction; implementation, full local verification, independent completed-work review, and owner-authorized landing passed. |
| `2026-08-19-tui-setup-recovery-offer-plan.md` | active | no | Class 5 hardened successor exposing the setup-recovery offer natively in the TUI; Slice 0 at `8ec4cfe`, implementation landed at `efd6119`, Grok completed-work review passed with dispositions recorded at `9e13039`; completion awaits only the manual TUI observation (real terminal, re-gated Kimi). |
| `2026-08-18-summon-setup-gate-recovery-attach-plan.md` | completed | no | Completed at `f17612b`; setup-gate input-prompt confirmation, one acknowledged recovery attach, enriched give-up diagnostics, full local gates, and independent completed-work review passed before 0.9.4 preparation. |
| `2026-08-18-tui-deep-review-remediation-plan.md` | completed | no | Class 5 umbrella remediation of the 2026-08-18 TUI deep-review findings, completed at `cd88b5f`; all five hosted TUI lanes and the immutable 0.9.3 TUI publication gate passed on their first attempts. |
| `2026-08-17-scripted-provider-ready-signal-plan.md` | completed | no | Completed at `99995cc`; scripted-provider readiness publication is inside its bounded physical-SIGINT cleanup owner. |
| `2026-08-17-summon-shell-cancel-portability-plan.md` | completed | no | Completed at `99995cc`; Windows shell acknowledgement uses exact owned synchronous-read cancellation for console and pipe inputs. |
| `2026-08-17-mcp-tools-seed-lifecycle-plan.md` | completed | no | Completed at `99995cc`; the two-member MCP tools fixture bounds persistent seed ownership before reactor work. |
| `2026-08-17-tui-ci-bounded-parallelism-plan.md` | completed | no | Completed at `99995cc`; fixed two-worker, file-scoped TUI CI passed all five hosted lanes under unchanged caps. |
| `2026-08-17-tui-search-anchor-test-synchronization-plan.md` | completed | no | Completed at `99995cc`; exact-intent search restore proof uses a non-tail fixture and passed all hosted TUI lanes. |
| `2026-08-17-tui-text-command-alias-plan.md` | completed | no | Class 4 hardened correction keeping textual command entry focus-owned, adding guarded TUI-local `q`/`quit`, and making Ctrl-C/Ctrl-D any-mode guarded quit chords; implementation, full TUI/static/doc verification, and independent completed-work review passed. |
| `2026-08-17-summon-first-attach-handoff-plan.md` | completed | no | Class 5 hardened shell-first Summon attach handoff and TUI compatibility plan; implementation, verification, final review, and owner-authorized closeout passed. |
| `2026-08-17-tui-command-entry-correction-plan.md` | completed | no | Class 5 hardened correction for composer-known-command promotion and interactive argument-ready command completion; implementation, verification, final review, and owner-authorized close-out passed. |
| `2026-08-17-tui-multiline-whitespace-plan.md` | completed | no | Class 5 hardened TUI contract revision for multiline compose input, modified-key fallbacks, exact whitespace presentation, transcript gaps, and scroll-safe variable-height rows; implementation, PTY acceptance, final review, and owner-authorized close-out passed. |
| `2026-08-17-tui-scroll-anchor-test-synchronization-plan.md` | completed | no | Class 4 event-based correction for the nested Textual refresh boundary; local exact-event proof and all-five-job hosted TUI evidence passed at `56e8235`. |
| `2026-08-17-mcp-resource-seed-lifecycle-plan.md` | completed | no | Class 4 correction removing per-message runner teardown from a 102-message MCP resource seed phase; canonical Windows/macOS MCP evidence passed at `56e8235`. |
| `2026-08-18-mcp-resource-helper-seed-lifecycle-plan.md` | completed | no | Class 4 correction bounding the selected identity's persistent seed ownership after the 0.9.3 Windows MCP pre-tag gate sampled SQLite commit during resource fixture setup; fresh Windows MCP and coordinated 0.9.3 publication passed at `cd88b5f`. |
| `2026-08-18-mcp-windows-resource-timeout-budget-plan.md` | completed | no | Completed at `72cd6f3`; all six MCP resource-test outer deadlock caps scale by 3x only on Windows, all behavior deadlines and assertions remain exact, and fresh canonical Windows MCP passed 286 tests. |
| `2026-08-17-cli-subprocess-readiness-plan.md` | completed | no | Class 5 correction separating real CLI child readiness from the unchanged application deadline; full exact-SHA producer and 0.9.1 publication evidence passed at `56e8235`. |
| `2026-08-14-debug-failure-capture-plan.md` | completed | no | Class 5 hardened implementation of opt-in outer-boundary exception capture, operational metadata, local SimpleBroker retention with best-effort dedup, action stdin delivery, and cross-surface containment without changing the original failure; full SQLite/PostgreSQL and extension gates plus independent review passed before owner-authorized close-out. |
| `2026-08-14-cross-surface-command-capability-plan.md` | status-review | no | Owner-deferred after Grok and Claude Fable 5 blocked command paths as the universal semantic seam; reconsider only when the first-party root registry reaches 25 verbs (five beyond the checked 20-verb baseline). `status-review` is the closed-vocabulary quarantine for this deferred plan. |
| `2026-08-17-tui-command-mirror-plan.md` | completed | no | Class 5 textual TUI command mirror with native dispatch, grouped action browsing, typed `taut-summon` support, and completed 0.9.1 hosted/publication evidence at `56e8235`. |
| `2026-08-14-taut-tui-action-applicability-authority-plan.md` | completed | no | Class 5 hardened contract correction making ordered non-Summon input requirements authoritative across palette, mouse controls, and central dispatch; implementation, verification, and independent review passed. |
| `2026-08-14-command-context-continuity-token-plan.md` | completed | no | Class 5 contract correction aligning program theory, registry/TUI account, and the public command-context identity-selector name; local verification passed. |
| `2026-08-14-windows-postrelease-ci-determinism-plan.md` | completed | no | Class 5 event-based TUI correction, MCP test-lifecycle optimization, and fail-closed watcher coverage cleanup, verified at `eeb59ab`. |
| `2026-08-14-pypi-finalizer-consistency-plan.md` | completed | no | Class 5 correction making each independent GitHub finalizer boundedly verify exact PyPI visibility before immutable publication. |
| `2026-08-14-summon-stream-close-race-plan.md` | completed | no | Class 5 [SUM-7.1] lifecycle hardening after the release gate exposed a close-induced event-pump thread exception. |
| `2026-08-14-taut-tui-display-sink-coverage-plan.md` | completed | no | Class 3 structural ownership refactor making TUI display widgets enforce terminal escaping and adding an explicit sink inventory plus real-PTY proof. |
| `2026-08-14-taut-tui-action-route-contract-plan.md` | completed | no | Class 5 implementation of authoritative TUI route semantics with exhaustive 54-pair real-route and 32-action concrete-handler firing gates. |
| `2026-08-14-review-findings-remediation-plan.md` | completed | no | Class 5+P remediation of the verified 0.9.0 review findings; implementation, local verification, independent review, and owner-authorized landing are complete. |
| `2026-08-13-ranged-dependency-policy-plan.md` | completed | no | Completed: ranged declarations, lock-selected minimums, no duplicate version assertions, and all retained lock/test/static gates passed. |
| `2026-08-13-simplebroker-config-isolation-plan.md` | completed | no | Class 5 symmetric Taut/SimpleBroker configuration isolation; published 7.3.2 artifact, exhaustive mapping, cross-backend proof, and independent closeout review passed. |
| `2026-08-12-live-point-in-time-dump-plan.md` | completed | no | Completed: live logical dump, strict restore chronology, Taut-to-broker skew configuration, and integrated SQLite/PostgreSQL verification passed. |
| `2026-08-12-taut-tui-implementation-plan.md` | completed | no | Completed: human-first TUI, responsive reflow, native system actions, Summon rich-host lifecycle, and full retained-environment verification passed. |
| `2026-06-17-implementation-review-followups-plan.md` | retired-pending | no | Soft-retired 2026-08-24 after the four-part harvest gate passed; source `348eae9`. |
| `2026-06-17-taut-pg-extension-plan.md` | retired-pending | no | Soft-retired 2026-08-24 after the four-part harvest gate passed; source `24dc2bc`. |
| `2026-06-18-member-identity-addressing-plan.md` | retired-pending | no | Soft-retired 2026-08-24 after the four-part harvest gate passed; source `3cae1f4`. |
| `2026-06-18-simplebroker-latest-timestamp-plan.md` | retired-pending | no | Soft-retired 2026-08-24 after the four-part harvest gate passed; source `348eae9`. |
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
| `2026-07-14-smaller-quality-followups-plan.md` | completed | no | Completed; evidence reconciled from the plan and repository history. |
| `2026-07-14-taut-mcp-extension-plan.md` | completed | no | Completed; landed evidence includes `4d25deb`. |
| `2026-07-14-taut-tui-cross-reference-correction-plan.md` | completed | no | Completed; landed evidence includes `b2da819`. |
| `2026-07-14-trusted-identity-selector-fast-path-plan.md` | completed | no | Completed; landed evidence includes `b2da819`. |
| `2026-07-14-universal-release-gates-plan.md` | completed | no | Completed; landed evidence includes `ce2bbb1`. |
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
| `2026-08-06-taut-search-plan.md` | completed | no | Class 5 search implementation, verification, and explicit Opus review completed before the owner-authorized final commit. |
| `2026-08-06-taut-search-spec-draft.md` | superseded | no | Historical reviewed draft superseded by active `docs/specs/06-search.md`. |
| `2026-08-07-program-theory-crystallization-plan.md` | completed | no | Class 5 product program theory crystallized from the README-first contract, five durable alternatives adopted, independent semantic review ADOPT-WITH-EDITS applied, owner-ratified Active, wired into startup order and [DOM-2]/[DOM-3]. |
| `2026-08-07-agent-theory-delta-wave-plan.md` | completed | no | Class 5+P agent-theory delta wave (source `0423923`); scoped review F1-F9 applied; landed 2026-08-07. |
| `2026-08-07-information-architecture-plan.md` | completed | no | Class 5+P Diataxis cutover completed 2026-08-08: registry, [DOM-10.1] widening with red-first probes, equivalence + extraction ledgers, kernel/llms.txt/docs-README surfaces, rendered-link gate, codex completion review applied. |
| `2026-08-07-taut-dump-load-plan.md` | completed | no | Class 5 composite persistence I/O; SQLite/PostgreSQL reciprocal round trips, destructive-failure guards, strict format tests, and final Opus review passed before owner-authorized close-out. |
| `2026-08-07-taut-dump-load-spec-draft.md` | superseded | no | Historical reviewed [PIO-*] draft superseded by active `docs/specs/08-persistence-io.md`. |
| `2026-08-10-mcp-search-plan.md` | completed | no | Class 5 explicit MCP adapter for core search; exact manifest/result contracts, immutable selector transport, real SQLite/stdio/PostgreSQL proof, documentation, and final Opus review passed before owner-authorized close-out. |
| `2026-08-10-simplebroker-7-json-id-boundary-plan.md` | completed | no | Class 5 SimpleBroker 7 floor and external JSON timestamp-string compatibility migration; implementation, local verification, and independent review passed before the owner-authorized close-out commit. |
| `2026-08-10-stable-dm-send-plan.md` | active | no | Class 5 existing-conversation stable-handle `say` target; `@route` remains the sole DM creator; focused Opus plan review passed. |
| `2026-08-10-system-doctor-plan.md` | completed | no | Class 5 actor-free report-only system doctor; implementation, real SQLite/PostgreSQL verification, final Opus review, and owner-authorized close-out passed. |
| `2026-08-10-test-quality-remediation-plan.md` | completed | no | Class 4 repository-wide test-oracle remediation; 81 audited dispositions with hosted OS/Python, required-path, and coverage-preservation evidence recorded in the plan. |
| `2026-08-11-eventually-test-helper-adoption-plan.md` | completed | no | Class 5+P repository-only sync/async eventual-evidence helper; seven eligible loop migrations, one audited Summon retention, full local verification, and final independent review passed before owner-authorized close-out. |
| `2026-08-11-ci-factor-and-release-order-plan.md` | completed | no | Completed at `f4830b0`: exact factor coverage, producer-first release ordering, and coordinated immutable 0.8.5 publication passed. |
| `2026-08-12-extension-main-path-and-all-extra-plan.md` | completed | no | Class 5 command-extension contract, protocol-clean `taut mcp`, and `taut-chat[all]` convenience bundle; full verification and independent review passed before owner-authorized closeout. |
| `2026-08-14-tui-pretag-gate-plan.md` | completed | no | Class 4 extraction of TUI's retained matrix into independent exact-SHA pre-tag evidence for all five coordinated releases. |

## Retired Plans

One line per retired plan; the body lives in git at the source SHA.

| Plan | Dates | Outcome | Absorbed into | Source SHA |
|------|-------|---------|---------------|------------|
| `2026-06-12-taut-0.1.1-hardening-plan.md` | 2026-06-12, soft-retired 2026-08-14 | Post-0.1 hardening: process-evidence identity repair, cross-platform capture quality, watcher proof, and review burndown | [TAUT-8]/[TAUT-11], `docs/implementation/04-taut-architecture.md`, and the retained 2026-06-12 lessons | `f1259c0` |
| `2026-06-12-taut-foundation-plan.md` | 2026-06-12, soft-retired 2026-08-14 | Initial package, storage, identity, envelope, client, watcher, CLI, and review foundation | [TAUT-2]–[TAUT-11], `docs/implementation/04-taut-architecture.md`, and the retained early-foundation lesson fold | `f1259c0` |
| `2026-06-17-github-actions-release-workflows-plan.md` | 2026-06-17, soft-retired 2026-08-14 | Initial reusable CI and GitHub-release workflows with bounded setup and release fences | [TAUT-12.5] and the current release architecture; the GitHub-only/no-PyPI boundary was transitional and is not durable | `33e13ee` |
| `2026-06-17-github-release-helper-plan.md` | 2026-06-17, soft-retired 2026-08-14 | Initial fail-closed release helper, remote inspection, and tag planning | [TAUT-12.5] and the current release architecture; GitHub-only publication was transitional, while helper-owned planning and no direct byte upload remain durable | `dadd324` |
| `2026-06-17-implementation-review-followups-plan.md` | 2026-06-17, soft-retired 2026-08-24 | Post-review hardening centralized missing-PostgreSQL install hints under `TautError`, restored bounded limited-history retention, and expanded real backend-resolution and conformance proof | [TAUT-3.2], [TAUT-8.1]–[TAUT-8.3], [TAUT-11], [TAUT-12.1], `docs/implementation/04-taut-architecture.md`, and the retained 2026-06-17 backend-selection lesson; exact upstream error variants were compatibility detail, not durable | `348eae9` |
| `2026-06-17-taut-pg-extension-plan.md` | 2026-06-17, soft-retired 2026-08-24 | Introduced the separate `taut-pg` project, project-resolved PostgreSQL support through the core path, real dual-backend conformance, and the extension release target | [TAUT-3.2]–[TAUT-3.4], [TAUT-8.2], [TAUT-11], [TAUT-12.1]/[TAUT-12.5], `docs/implementation/04-taut-architecture.md`, and the retained 2026-06-17 BIGINT lesson; the initial GitHub-only/no-PyPI and no-root-extra boundaries were transitional | `24dc2bc` |
| `2026-06-18-member-identity-addressing-plan.md` | 2026-06-18, soft-retired 2026-08-24 | Migrated handle identity to stable member ids with mutable names, deterministic claims, sender snapshots, direct messages, consumable notification inboxes, and recoverable channel rename | [TAUT-3]–[TAUT-8], [IAN-2]–[IAN-10], and `docs/implementation/04-taut-architecture.md`; the schema cutover, plan-era file layout, and old live-write mechanics were transitional; no separate lesson was owed | `3cae1f4` |
| `2026-06-18-simplebroker-latest-timestamp-plan.md` | 2026-06-18, soft-retired 2026-08-24 | Replaced the list-time O(history) `last_ts` scan with SimpleBroker's indexed latest-pending-timestamp API without changing public output or persisted state | [TAUT-3.1], [TAUT-3.4], [TAUT-7.1], [TAUT-7.3], [TAUT-8.2], and `docs/implementation/04-taut-architecture.md`; the original dependency floors and release framing were historical; no separate lesson was owed | `348eae9` |
| `2026-07-10-ci-failure-remediation-plan.md` | 2026-07-10, soft-retired 2026-08-08 | v0.5.1 CI remediation: PTY write leases, watcher pre-publication stop, artifact fixture portability, deterministic waiter-rebind proof | [TAUT-8.5] rebind proof text, [SUM-*] related-plan history, and five 2026-07-10 lessons | `b03709452` |
| `2026-07-14-single-project-config-source-spec-plan.md` | 2026-07-14, soft-retired 2026-08-08 | Spec-authoring clarification making `.taut.toml` the sole project settings file, rejecting alternate-manifest scanning | [TAUT-2]/[TAUT-3.2] (the governing spec is the durable record) | `db67b94b` |
| `2026-07-14-terminal-output-safety-plan.md` | 2026-07-14, soft-retired 2026-08-08 | Packaged and project-customizable terminal-text safety policy, public escape utility, raw-PTY exemption | [TAUT-3.2]/[TAUT-6.4], Summon terminal-safety text, `taut/terminal.py` + `taut/defaults.toml`, and two 2026-07-14 lessons | `281f04fa` |
| `2026-07-15-per-call-read-limit-plan.md` | 2026-07-15, soft-retired 2026-08-08 | Bounded per-call unread pages with exact cursor advancement and dual-backend proof | [TAUT-7.2] (request-policy limit, rejected persistent-config and post-read-slicing alternatives) and the 04-taut-architecture traceability row | `4a129e94` |
