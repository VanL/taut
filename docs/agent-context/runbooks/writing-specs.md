# Writing Specs

Specs define intended behavior. They are the source of truth for what the
system should do, not a narration of how the current code happens to work.

## Purpose

Use specs to document:

- system behavior and user-visible outcomes
- invariants and boundaries
- interfaces, contracts, and data shapes
- failure modes and edge cases
- verification expectations

Do not use specs for temporary implementation notes or task checklists.

Write specs so a strong zero-context agent can use them reliably, not just so a
human reader finds them reasonable.

Agent-usable spec writing should make these explicit whenever they matter:

- owner
- boundary
- verification
- required action

## File Placement

- Put specs in `docs/specs/`.
- Prefer stable filenames. Numbered prefixes are useful when the directory is a
  long-lived corpus.
- Add a `README.md` in the directory to explain the reading order and naming
  scheme.

## Reference Codes

Specs should use stable reference codes such as `[DOM-1]`, `[API-4]`, or
`[AUTH-2.3]`.

Rules:

- use codes on the requirements people will need to cite later
- prefer stable codes over prose-only references
- extend the existing code family instead of inventing a second style
- update backlinks when a section is split or replaced

## Recommended Spec Sections

### 1. Purpose and Scope

Explain what the spec governs and what it does not.

### 2. Mental Model

Describe the core concepts needed to reason about the system correctly.

### 3. Requirements

State the intended behavior using stable section or requirement codes.

### 4. Invariants and Constraints

Call out what must remain true even as the implementation evolves.

### 5. Interfaces and Data Contracts

Describe public behavior, payloads, state transitions, or file formats as
needed.

### 6. Failure Modes and Edge Cases

State what should happen under conflict, error, unsupported input, timing race,
or partial failure.

### 7. Verification Expectations

Name the evidence required to prove the behavior.

### 8. Related Plans

Link dated plans in `docs/plans/` that implement or materially revise the spec.

## Spec Maintenance Rules

- Update the spec before or with the code change when intended behavior shifts.
- Keep `## Related Plans` current.
- If an implementation note exists for the touched area, update it in the same
  change.
- If no spec exists for material new behavior, add one instead of burying the
  decision in a plan or commit message.
- If a change is intentionally spec-free, make that explicit in the plan.
- If a section is understandable to a human but likely ambiguous to an agent,
  rewrite it with clearer structure, references, examples, or explicit
  boundaries.
- When you notice that kind of ambiguity during work, notify the user and
  suggest a concrete improvement.

## Anti-Patterns

- specs that only describe current file layout
- vague requirements with no stable references
- prose that sounds clear in discussion but leaves an agent guessing about the
  boundary, owner, or required action
- missing verification guidance for an otherwise clear requirement
- mixing active task checklists into the spec body
- documenting speculative future behavior as if it were required now
- letting the spec drift while code and plans move underneath it
