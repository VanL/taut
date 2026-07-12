# Review Loops and Agent Bootstrap

This runbook covers two linked workflows:

- bootstrapping which agents are available in the current environment
- using independent review agents for plans and completed work

## Operating Metadata

- **Owner:** the top-level task agent or engineer requesting the review.
- **Boundary:** read-only agent inventory and independent review; reviewers do
  not implement or silently edit the reviewed work.
- **Verification:** record the dated probe result, full findings, and the
  disposition of every finding.
- **Required action:** refresh stale inventory before relying on it and close
  the review loop before declaring non-trivial work complete.

## 1. Bootstrap Available Agents

At session start, check which agent families are available and record them in
the current agent inventory note.

Recommended candidates to look for:

- Claude
- Codex
- Qwen
- Gemini
- Kimi

Rules:

- refresh the inventory when tooling changes materially
- prefer concrete names over vague “another model”
- record both availability and the date of the last refresh
- distinguish between present, verified usable, and blocked states
- keep the inventory concise and operational

Verification method:

- run a small read-only prompt or review task
- record whether the agent was:
  - verified usable
  - present but blocked by credentials or configuration
  - present but failing at invocation time

The repository inventory lives in:

- `docs/implementation/03-agent-inventory.md`

## 2. Independent Review Requirement

For non-trivial plans and completed work, run an independent review.

Preferred order:

1. a different agent family than the authoring agent
2. if not available, a same-family agent with a clearly separate review role
3. if no second agent is available, do a strict fresh-eyes review and note the
   limitation

For large changes, run review:

- after each meaningful slice of work
- and again before completion

## 3. What To Give the Reviewer

Always point the reviewer at:

- the governing spec (baseline identifier) and, when present, the plan's
  `## Proposed Spec Delta`
- the active plan
- the relevant implementation note
- the current touched files
- any important tests or verification commands

Do not ask the reviewer to implement. The point is to surface errors, bad
ideas, and latent ambiguities before the work is treated as done.

When the reviewer is a sandboxed CLI agent (for example `codex exec`):

- run it read-only (`codex exec --sandbox read-only`) — a reviewer needs
  no write access
- run it from a working directory that encloses every repository the
  plan cites (for sibling-repo references like `../simplebroker`, run
  from the parent directory), or the reviewer silently cannot verify
  cross-repo claims
- some reviewer CLIs misbehave outside a git repository (codex needs
  `--skip-git-repo-check`; grok hangs). If the CLI must run inside one
  repo and the sibling sources are out of reach, scope the prompt to
  in-repo material and state explicitly which claims a prior reviewer
  already verified against source, so the reviewer attacks design
  rather than re-deriving or guessing API facts
- probe the reviewer with a trivial file-reading prompt before burning
  a long review run; record auth/configuration failures in the agent
  inventory with the exact error
- capture the full output and record the findings and their resolutions
  in the plan's review appendix

## 4. Recommended Plan Review Prompt

Use this or a close variant:

> Read the plan at [path] and its `## Proposed Spec Delta` (if present),
> including the named promotion strategy. Carefully examine the plan, the
> proposed spec text, and the associated code. Look for errors, bad ideas, and
> latent ambiguities. Don't do any implementation, but answer carefully: Could
> you implement this confidently and correctly against the delta as promoted,
> if asked?

If the review is for completed work rather than a plan draft, swap in the
changed files and current verification evidence while keeping the same review
stance.

## 5. Review Handoff Loop

After the review returns:

1. give the feedback back to the original planning or authoring agent
2. ask that agent to consider each point explicitly
3. update the plan or changed work accordingly
4. if the authoring agent disagrees with a point, record why the current path
   remains the best choice

The loop is not complete until each review point has been:

- accepted and addressed
- rejected with reasoning
- or marked out of scope with reasoning

If the reviewer says they could not implement confidently and correctly, treat
that as a blocker until the missing detail is fixed or the limitation is
recorded explicitly.

## 6. Review Output Standard

Reviewer output should prioritize findings first.

Recommended structure:

- finding
- why it matters
- what file, section, or step is affected
- whether the reviewer could implement confidently after the fix

Avoid bland approval language. If there are no findings, say so explicitly and
name any residual risk.
