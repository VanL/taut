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

At the start of a session, agents should load:

1. the root agent entry point
2. the read order defined in `docs/agent-context/README.md`
3. the current agent availability inventory, if one exists
4. the relevant spec, active plan, implementation note, and skill for the task

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

_Implementation snapshot_: the current repository setup models this chain with
the documentation system itself because product code has not been added yet.

## 5. Planning Standard [DOM-5]

Non-trivial changes should begin with a dated plan in `docs/plans/`.

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

## 11. Independent Review Workflow [DOM-11]

Non-trivial plans and completed work should receive an independent review.

Requirements:

- the reviewer receives the governing spec, active plan, relevant
  implementation note, and touched files
- the review focuses on errors, bad ideas, latent ambiguities, and whether a
  different engineer could implement the plan confidently and correctly
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

## Related Plans

- `docs/plans/2026-04-07-development-documentation-foundation-plan.md`
- `docs/plans/2026-04-07-plan-hardening-guidance-plan.md`
- `docs/plans/2026-04-07-review-skills-bootstrap-plan.md`
- `docs/plans/2026-04-07-specs-index-renumbering-plan.md`
