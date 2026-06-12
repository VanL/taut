# Decision Hierarchy

Use this order whenever instructions or context seem inconsistent:

1. Explicit user instruction in the current thread.
2. Safety and repository constraints:
   dirty-tree discipline, no destructive commands, do-not-revert-others.
3. Task source-of-truth documents:
   relevant specs, invariants, active plan, and user-facing behavior docs.
4. Canonical repo context in `docs/agent-context/`.
5. Root agent files such as `AGENTS.md` and `CLAUDE.md`.
6. Existing code and test patterns.
7. Agent inference.

## Required Preflight Before Edits

- List the requested outcomes as a checklist.
- Identify the governing spec, or record plainly that no spec exists.
- Identify the active plan or create one if the change is non-trivial.
- Identify the review agent or review path for non-trivial work.
- Call out invariants that must not move.
- Record assumptions that could change correctness.
- Decide which commands can run in parallel and which must run in sequence.

## Conflict Handling

- If user correction conflicts with your inference, stop and re-derive.
- If specs and code disagree, follow the hierarchy above and call out the
  mismatch.
- If uncertainty remains on a high-impact change, ask once and narrowly.

## Completion Gate

Every requested item should have at least one evidence line:

- changed file and what changed
- verification command and result
- observed behavior or explicit residual risk
