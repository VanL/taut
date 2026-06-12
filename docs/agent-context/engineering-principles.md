# Engineering Principles

These are the reusable engineering rules that most often prevent agentic work
from drifting.

## 1. Extend the Existing Path Before Adding a New One

If a change touches an established flow, start by extending the current flow.
Do not introduce a second path, side channel, or compatibility shim unless the
governing spec explicitly requires it.

## 2. Canonicalize at Boundaries, Then Stay Strict

Normalize input at the boundary through one shared path. After that, internal
code should operate on the canonical form.

When a contract changes, update forward. Avoid permanent fallback readers that
silently accept incompatible shapes unless compatibility is explicitly required.

## 3. Read Spec, Code, Test, and Plan Before Inference

Do not infer behavior from file names or mental models alone. Read:

1. the relevant spec
2. the current implementation
3. the closest existing test
4. the active plan or implementation note

Then decide what to change.

## 4. Prefer Real Behavior Over Mock-Heavy Proof

For important lifecycle, integration, or contract behavior, test the real
surface whenever practical. Mock only boundaries that are external, slow, or
nondeterministic.

If a bug lives in the interaction between components, a test that replaces that
interaction with mocks is usually proving the wrong thing.

## 5. Keep Traceability Bidirectional

Treat documentation traceability as part of implementation, not optional
cleanup.

- Plans cite exact spec sections.
- Specs backlink the plans that implement them.
- Implementation docs explain the current rationale and ownership.
- Code points back to governing specs when ownership would otherwise be
  ambiguous.

## 6. Reuse Local Paths and Helpers Before Inventing New Ones

Prefer existing helpers, utilities, and patterns over new abstractions.
DRY means reusing the known good path, not creating a more generic one because
it feels elegant in the abstract.

## 7. Keep Future-Proofing Out Unless the Current Work Requires It

Apply YAGNI aggressively. Do not widen scope with speculative architecture,
extra abstraction layers, or policy changes unless the active spec or request
demands them.

## 8. Use Independent Review to Reduce Author Blindness

For non-trivial plans and implementations, run an independent review pass with
the governing specs, plan, implementation note, and touched files in view.

Prefer a different agent family or model from the original author when
available. The review is not complete until the authoring agent has considered
each point and either updated the work or documented why the existing path
remains correct.

## 9. Plan the Boundaries Before the Tasks

Strong plans do not only describe the new behavior. They describe what must not
change, where state crosses boundaries, and which proof must stay real.

For risky work, name up front:

- invariants and existing contracts that must survive
- hidden couplings or lifecycle dependencies
- what must not be mocked
- rollback or rollout sequencing
- one-way doors or destructive edges

If the plan only names the center of the change, implementation will usually
drift at the boundaries.

## Warning Signs

Sessions usually go sideways when one of these happens:

- a second path appears instead of extending the canonical one
- a change relies on intuition rather than reading the relevant docs and code
- a failing regression is replaced by a shallow happy-path test
- the docs are treated as post-hoc cleanup rather than part of delivery
- a later stage quietly changes the direction of the earlier plan
- the plan says what to build but not what must stay true
- rollback, rollout, or anti-mocking posture is left for the implementer to
  improvise
