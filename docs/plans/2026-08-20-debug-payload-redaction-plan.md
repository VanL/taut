# Debug Payload Value Redaction Plan

Class: 5 — this revises the public debug-capture disclosure contract and adds
one shared core transform used by both local and action sinks. The hardening
runbook is mandatory because the same final payload crosses two execution
contexts and failure handling must remain subordinate to the original error.

Plan type: implementation with spec revision.

## Goal

Add a private, standard-library-only `taut/_redact.py` helper that removes
recognizable credential **values** from the final rendered debug-event text
without hiding the identifier or surrounding evidence that a credential was
present. Apply the helper at the single serialized-payload choke point before
either local persistence or action dispatch. Compile its regular expressions
lazily on first use and cache them thereafter.

This is defense in depth, not a promise that debug events are safe to publish.
Debug capture remains opt-in, retains rich traceback and local evidence, and
stays inside Taut's published storage trust model.

## Source Documents

Source specs:

- `docs/specs/02-taut-core.md` [TAUT-13.2] through [TAUT-13.6]
- `docs/specs/01-development-documentation-operating-model.md` [DOM-5],
  [DOM-6], [DOM-10], [DOM-11], [DOM-15]

Supporting sources:

- `docs/program-theory.md` [THEORY-1], [THEORY-4], [THEORY-6]
- `docs/implementation/04-taut-architecture.md`, “Debug failure capture is
  one deep core module”
- `docs/implementation/02-repository-map.md`, product-code ownership table
- `docs/plans/2026-08-14-debug-failure-capture-plan.md`, especially its
  historical decision to keep payloads unredacted
- `docs/agent-context/runbooks/writing-plans.md`
- `docs/agent-context/runbooks/hardening-plans.md`
- `docs/agent-context/runbooks/testing-patterns.md`
- `../mm/apps/secret_scanner/services/engine.py`
- `../mm/apps/secret_scanner/services/scanner.py`
- `../mm/apps/secret_scanner/fixtures/detectors.yaml`

The sibling scanner is design input only. Taut must not import it, read its
YAML at runtime, add PyYAML, or create a cross-repository release dependency.

## Spec Baseline

- `46ee6bdf8017353a4ca9aad146d1afb0f34e47c5` —
  `docs/specs/02-taut-core.md` at plan authoring time.
- Plan type: implementation with spec revision.
- Promotion baseline: `46ee6bdf8017353a4ca9aad146d1afb0f34e47c5`
  plus the worktree diff for `docs/specs/02-taut-core.md` produced by Task 2.
  The implementation is reviewed uncommitted, so this rerunnable diff is the
  governing promotion identifier until owner-authorized landing supplies a
  commit SHA.

## Decisions Harvested

1. Redaction operates on the final serialized text, not on selected event
   fields. This catches exception messages, formatted tracebacks, rendered
   locals, and any later textual field through one choke point.
2. Rules identify the exact value span. Replacement preserves the key,
   provider prefix, URI structure, authorization scheme, PEM boundary, and
   other surrounding evidence whenever that structure exists.
3. `taut/_redact.py` is the sole rule and span-replacement owner. It is a
   private package-root module because converting `taut/debug.py` into a
   package only to host one helper would add migration cost with no depth.
4. Raw rule declarations are cheap import-time data. A zero-argument cached
   compiler creates `re.Pattern` objects only on the first call to the public
   private-module operation, then reuses the immutable tuple.
5. Taut adapts the sibling scanner's detector-ID plus secret-capture-group
   model, but does not transplant its whole vendor catalog. The initial set is
   bounded to concrete Taut debug paths and high-confidence structures.
6. Taut continuity tokens are deliberately not secret credentials. Bare
   `token`, `TAUT_TOKEN`, and `continuity_token` labels do not trigger
   label-based redaction. Provider/API token labels and self-identifying
   credential formats may still trigger their narrower rules.
7. A redaction failure fails closed for the debug event: `capture_exception()`
   swallows the helper failure and sends or stores nothing. It never falls
   back to the unredacted payload and never changes the primary exception.
8. Previously retained `taut.debug` rows are not rewritten. Operators who no
   longer want old unredacted events must remove them through SimpleBroker.
9. A selected value span in final JSON text must start and end on complete
   encoded characters. Quote-delimited rules are escape-aware; they never stop
   between a backslash and the escaped character it protects.

Rejected alternatives:

- Structured-field redaction was rejected because it creates parallel paths
  and misses future rendered fields.
- Hiding the whole match was rejected where a narrower value span exists. It
  would erase useful facts such as which identifier, URI host, or key type was
  present.
- Importing or packaging `mm`'s scanner was rejected because Taut's small
  runtime helper does not justify a sibling application or YAML dependency.
- Copying every detector from the sibling scanner was rejected as an
  unbounded maintenance contract with weak connection to Taut's concrete
  exposure paths.
- Redacting every field named `token` was rejected because it contradicts
  Taut's continuity-token model and would add noise without reducing an
  authorization boundary.
- Scrubbing retained rows in place was rejected because this change needs no
  storage migration and must not silently mutate operator-owned diagnostic
  history.

## Current Structure and Key Files

Files to add:

- `taut/_redact.py` — pure rule declaration, lazy compilation, match-span
  collection, and value-only replacement
- `tests/test_redact.py` — exhaustive pure-helper contract tests

Files to modify:

- `taut/debug.py` — route every candidate serialized payload through the
  helper before accepting its encoded size or selecting a sink
- `tests/test_debug_capture.py` — real local-queue and real action-stdin
  integration proof
- `docs/specs/02-taut-core.md` — promote [TAUT-13.3.1] and amend
  [TAUT-13.5]/[TAUT-13.6]
- `README.md` — describe best-effort value redaction while retaining the
  warning that debug events may contain sensitive data
- `docs/implementation/04-taut-architecture.md` — record the final-text choke
  point, fail-closed behavior, and residual risk
- `docs/implementation/02-repository-map.md` — add `_redact.py` ownership
- this plan and `docs/plans/README.md` — traceability, review, and status

Read before editing:

- `taut/debug.py:capture_exception`, `_serialize_event`, `_json_payload`,
  `_write_local`, and `_send_to_action`
- `tests/test_debug_capture.py` local queue, action fixture, payload-size,
  truncation, and best-effort failure cases
- `taut/_scripts.py:redact_backend_target` only for the repository's existing
  `<redacted>` spelling; do not reuse its structured-URL helper for arbitrary
  text
- the sibling scanner files named above, especially `secret_group`; adapt
  patterns rather than copying its loader or singleton

Current data flow:

```text
Exception
  -> _build_event()                 # rich Python values become bounded text
  -> _serialize_event()             # compact JSON and size-reduction passes
  -> _write_local() OR _send_to_action()
```

Required data flow:

```text
Exception
  -> _build_event()
  -> _serialize_event()
       -> compact JSON candidate
       -> redact_sensitive_text(candidate)
       -> encoded-size decision
  -> _write_local() OR _send_to_action()   # scrubbed text only
```

`_serialize_event()` currently renders up to three JSON candidates while
reducing traceback and locals to fit `_MAX_EVENT_BYTES`. Redaction must occur
before each candidate's byte check. Calling it only after `_serialize_event()`
returns could expand a replacement marker beyond the accepted byte bound.

The fingerprint is currently computed before serialization from bounded
exception and frame identity. Keep that calculation unchanged. A secret may
influence the one-way fingerprint, but no raw value is recoverable from it;
changing the calculation would alter deduplication and is outside this plan.

### Comprehension gate

Before Task 3, the implementer records answers in the execution log:

1. **Where is the only legal sink-independent redaction seam?** Expected
   answer: inside `_serialize_event()`'s candidate rendering path, after JSON
   text exists and before that candidate's encoded-size acceptance; neither
   `_write_local()` nor `_send_to_action()` owns a second scrub pass.
2. **What happens if pattern compilation or substitution raises?** Expected
   answer: the exception reaches `capture_exception()`'s existing broad
   containment, the debug event is dropped, the unredacted payload is never
   delivered, and the original application failure remains primary.
3. **Why must `TAUT_TOKEN` survive label-based redaction?** Expected answer:
   it is a continuity selector under Taut's published non-authentication model,
   not a credential that expands storage authority; generic token redaction
   would encode the wrong security model.

Any incorrect answer blocks implementation until the cited code and spec are
reread.

## Proposed Spec Delta

Promotion strategy: **A — in-file edit, text before link claims**. Promote the
requirement and plan backlink into the existing active core spec after plan
review. Add implementation mapping/backlinks only with the code and tests so
the traceability gate does not carry a false implementation claim.

| Spec file | Strategy | Sections touched |
|-----------|----------|------------------|
| `docs/specs/02-taut-core.md` | A — in-file, text before link claims | add [TAUT-13.3.1]; amend [TAUT-13.5], [TAUT-13.6], Related Plans |

### [TAUT-13.3] replacement paragraph

Replace the paragraph beginning “The local sink writes one UTF-8 JSON object”
through its sensitive-data warning with:

> The local sink writes one UTF-8 JSON object to the core-owned, unregistered,
> reserved queue `taut.debug`. The version-1 event contains a type and version,
> UTC capture time, display-safe target, stable surface and operation labels,
> exception type and message, formatted traceback, bounded frame locals,
> bounded runtime/process metadata, a deterministic SHA-256 fingerprint, and
> the literal sentinel `taut-debug:<fingerprint>`. Before either sink receives
> it, recognizable credential values are redacted under [TAUT-13.3.1]. The
> event may still contain credentials not recognized by the bounded rule set,
> plus message bodies, paths, prompts, continuity tokens, and other sensitive
> process data. Its schema is exceptional diagnostic data, not a compatibility
> contract; later readers must tolerate added, removed, truncated, redacted,
> or changed metadata.

### New [TAUT-13.3.1] — Final-text credential-value redaction

Insert after the first [TAUT-13.3] paragraph:

> #### [TAUT-13.3.1] Final-text credential-value redaction
>
> Core renders each candidate event as compact JSON text, then passes that
> complete text through one core-owned redaction helper before encoded-size
> acceptance and before local persistence or action dispatch. Both sinks
> therefore receive the same valid, bounded, scrubbed JSON. Callers and sinks
> do not perform their own redaction.
>
> Each rule identifies a credential-value span. Taut replaces only that span
> with the literal `<redacted>` and preserves the surrounding identifier,
> delimiter, authorization scheme, URI structure, provider/type prefix, or PEM
> boundary that establishes what was present. Overlapping value spans are
> coalesced before right-to-left replacement. The initial rules cover:
>
> 1. quoted or unquoted assignments and mapping entries whose normalized label
>    is `access_key`, `api_key`, `auth_key`, `authorization`, `client_secret`,
>    `credential`, `credentials`, `encryption_key`, `password`, `passwd`,
>    `private_key`, `pwd`, `secret`, or `secret_key`, or ends with exactly one
>    of `_access_key`, `_api_key`, `_auth_key`, `_authorization`,
>    `_client_secret`, `_credential`, `_credentials`, `_encryption_key`,
>    `_password`, `_passwd`, `_private_key`, `_pwd`, `_secret`, or
>    `_secret_key`;
> 2. quoted or unquoted assignments and mapping entries whose normalized label
>    is `api_token`, `access_token`, or `auth_token`, or ends with exactly one
>    of `_access_token`, `_api_token`, or `_auth_token`. Bare `token`, a label
>    ending `_token` without one of those three qualifiers, `TAUT_TOKEN`, and
>    `continuity_token` do not fire this label rule;
> 3. `Authorization` Basic/Bearer values, user-info passwords in PostgreSQL,
>    MongoDB, Redis, AMQP, and FTP-family URIs, password parameters in
>    conninfo/JDBC-like text, and private-key PEM bodies; and
> 4. a bounded internal manifest of high-confidence, self-identifying
>    Anthropic, OpenAI, Google, GitHub, AWS, Stripe-secret, Slack, and SendGrid
>    credential formats adapted from established detectors.
>
> A selected value span in the final JSON text must begin and end on complete
> encoded characters. In particular, a quote-delimited rule is escape-aware
> and cannot stop between a backslash and its escaped quote, backslash, or other
> encoded character. Redaction must not make a valid serialized event invalid.
>
> Raw rule declarations are import-time constants. Compiled regular
> expressions are created lazily on the first redaction call and cached for
> later calls. Taut adds no detector-file loader or runtime dependency.
>
> Redaction is defense in depth, not a completeness or safe-to-share promise.
> Unknown formats, secrets without recognizable context, false negatives, and
> conservative false positives remain possible. Taut continuity tokens are
> intentionally outside label-based credential redaction. A helper failure
> drops that debug event under [TAUT-13.5]; Taut never falls back to sending or
> storing the unredacted text.

### [TAUT-13.5] addition

Append to the first paragraph:

> Redaction compilation, matching, span coalescing, and substitution are part
> of event construction. Their failure is best-effort with respect to the
> primary application error but fail-closed with respect to disclosure: the
> event is dropped and no unredacted sink fallback is attempted.

### [TAUT-13.6] addition

Append:

> Pure-helper tests exercise every declared rule ID and every normative label,
> preserve identifiers and structural evidence, prove the matched value is
> absent, cover overlapping and repeated matches, retain explicit continuity-
> token exceptions, preserve valid JSON, and prove lazy one-time compilation
> under sequential use. Integration tests use a real local queue and a real
> action fixture to prove both receive identical scrubbed payloads and no raw
> sentinel secret. A forced helper failure proves no sink is reached and the
> primary failure behavior remains unchanged. Hostile maximum-sized text must
> complete within a subprocess test deadline without catastrophic regular-
> expression behavior.

### Related Plans addition

Add:

> - `docs/plans/2026-08-20-debug-payload-redaction-plan.md` revises
>   [TAUT-13.3] through [TAUT-13.6] with final-text, value-only credential
>   redaction shared by both debug sinks.

## Invariants and Constraints

- Only credential values are replaced. When a rule has structural context,
  the key/name, separator, URI host and username, auth scheme, provider prefix,
  or PEM begin/end lines remain visible.
- Every delivered payload remains valid UTF-8 JSON and stays within
  `_MAX_EVENT_BYTES`.
- The exact original secret sentinel is absent from delivered local and action
  payloads for every firing rule.
- Both sinks receive the same result from one core transform. There is no
  sink-specific rule, second scrubber, or caller-owned redaction.
- Disabled capture behavior and cost are unchanged. Regexes do not compile on
  module import or while capture is disabled.
- `capture_exception()` remains total. Redaction failure drops only the debug
  event and never replaces the original error, exit status, diagnostic, or
  cleanup priority.
- A redaction failure never sends or stores the unredacted candidate.
- Fingerprint, sentinel, deduplication, truncation, local locking, action
  timeout, no-local-fallback action policy, setting lookup, and payload schema
  version remain unchanged.
- `TAUT_TOKEN`, `continuity_token`, and a bare `token` label are negative cases
  for label-based rules. A value may still be redacted by an independently
  firing, high-confidence credential-format rule.
- Rule declarations are immutable and locally owned. Each has a stable private
  ID, one regex source, flags, and one secret-value group. Every ID has a firing
  test so the manifest cannot silently rot.
- Pattern compilation is lazy and cached. Importing `taut._redact` compiles
  nothing; the first call compiles the manifest; later sequential calls do not
  compile again.
- Patterns must use bounded context and avoid nested ambiguous quantifiers or
  other catastrophic-backtracking shapes. Input is already bounded, but the
  helper remains failure-path code and must not amplify latency.
- Quote-delimited rules use escape-aware atoms, such as the equivalent of
  `(?:[^"\\]|\\.)*` for an unembedded double-quoted value, adjusted for the
  final JSON escape level. A match span may not begin or end inside an escape
  sequence. Tests must exercise quotes and backslashes inside the selected
  secret, not merely around it.
- Use only the Python standard library. Do not load sibling files, YAML, or
  detector updates at runtime.
- Existing retained debug events remain byte-for-byte untouched. Documentation
  must not imply retroactive scrubbing.
- Debug output remains sensitive diagnostic material and is not safe to share
  solely because recognizable credential values were removed.
- No new public Python symbol, CLI flag, configuration key, event field,
  schema version, queue, persistence table, or dependency is introduced.

## Rule Manifest Boundary

Implement `taut/_redact.py` around two immutable private records:

- `_Rule(id, pattern, secret_group, flags=0)` for source declarations
- `_CompiledRule(rule, regex)` for cached executable rules

Expose one module operation:

```python
def redact_sensitive_text(text: str) -> str:
    """Replace recognized credential-value spans while preserving context."""
```

`_compiled_rules()` is decorated with `functools.cache`. It validates at first
use that each `secret_group` exists. It returns a tuple and reads no external
state. Duplicate concurrent first-call compilation is acceptable under
`functools.cache`'s documented race behavior; correctness cannot depend on
compile count across threads. The contractual once-only proof is sequential.

For each match, collect the selected group's non-empty `(start, end)` span.
Sort and coalesce overlapping or adjacent spans, then replace from right to
left with `<redacted>`. Do not perform iterative substitutions that scan newly
inserted markers. Returning the original `str` object when no rule fires is a
permitted optimization, not a contract.

Rule sources are grouped in the file by the four normative families. Each
declaration carries a short provenance comment when adapted from
`../mm/apps/secret_scanner/fixtures/detectors.yaml`. Do not reproduce its YAML
loader, public finding model, entity taxonomy, or all-provider inventory.

The closed qualified-label suffixes are:

```text
_access_key, _api_key, _auth_key, _authorization, _client_secret,
_credential, _credentials, _encryption_key, _password, _passwd,
_private_key, _pwd, _secret, _secret_key
```

The closed bare credential-token labels are `access_token`, `api_token`, and
`auth_token`. The closed credential-token suffixes are `_access_token`,
`_api_token`, and `_auth_token`. Bare `token`, a label ending `_token` without
one of those three qualifiers, `TAUT_TOKEN`, and `continuity_token` do not fire
this label rule. The specification and test-case inventory must use these exact
sets.

The label family must recognize the forms that can appear in final JSON text:

- direct JSON key/value text
- JSON-escaped Python `repr()` mappings inside event strings
- single-quoted Python mappings
- shell/env and conninfo assignments
- URL/JDBC query parameters

It must also recognize one additional JSON-escape layer around those mapping
forms, covering a JSON blob or rendered mapping already escaped inside an
exception string before the event itself is serialized. Arbitrarily recursive
escaping is not required.

Provider rules preserve the identifying prefix where possible. For example,
an adapted GitHub rule renders `ghp_<redacted>`, an Anthropic rule renders
`sk-ant-api03-<redacted>`, and an AWS access-key-shaped value renders
`AKIA<redacted>` rather than erasing the whole match. If a format cannot keep a
stable identifying prefix and isolate a non-empty value span, drop it from the
initial manifest under Task 3's stop gate rather than consuming the context.

Tests, not increasingly permissive regexes, decide whether a new surface is
needed. If supporting those forms requires parsing JSON and walking fields,
stop and re-plan; the owner selected one final-text transform deliberately.

## Rollout, Rollback, and Residual Risk

This is an additive transform with no storage migration and no one-way door.
Promote the spec first, then land helper plus serializer wiring atomically so
no released code claims the new contract without enforcing it. Root and all
extension surfaces inherit the change through `capture_exception()`; no
extension release ordering is required beyond its existing core-version floor.

Rollback is a normal code/spec/docs revert. Newly written events remain valid
version-1 JSON and older readers already tolerate changed metadata. A rollback
does not restore removed credential values and must not rewrite retained rows.
If the helper causes missed diagnostics, operators can disable capture while a
fix is prepared; do not advise bypassing redaction with an environment switch.

Post-deploy success signals:

- an induced local capture containing synthetic provider and DSN secrets
  leaves the identifiers and URI structure visible but no sentinel value;
- the same fixture through `TAUT_DEBUG_ACTION` produces the same scrubbed JSON;
- ordinary capture volume, deduplication, and action timing do not materially
  change;
- a redaction defect produces a missing optional debug event, never a changed
  primary error and never a raw fallback event.

Residual risks:

- regex redaction cannot recognize every credential and can conservatively
  redact benign values;
- traceback and locals still disclose non-credential messages, prompts, paths,
  business data, and other host state permitted by the debug contract;
- action subprocesses still inherit the parent environment. Payload redaction
  does not and cannot sanitize that separate operator-owned process boundary;
- debug events retained before this rollout stay unredacted until the operator
  deletes them;
- because fingerprinting precedes redaction, different secret-bearing messages
  can still produce different opaque fingerprints.
- mapping text nested under more than one pre-existing JSON-escape layer may
  evade label rules; high-confidence standalone-format rules can still fire,
  but arbitrary recursive unescaping is deliberately outside the bounded
  helper.

## Dependency-Ordered Tasks

### Task 1: Review and accept the contract

Files to read:

- this plan, including Proposed Spec Delta and Rule Manifest Boundary
- all source documents and current files named above
- the concrete sibling-scanner source files, not just this plan's summary

Actions:

1. Run the independent plan review defined below.
2. Disposition every finding in the append-only Review Log.
3. Confirm owner acceptance of the bounded rule families, continuity-token
   exceptions, `<redacted>` marker, lazy compilation, and fail-closed event
   drop.
4. Record the three comprehension answers.

Stop gate: disagreement about what counts as a credential label, whether
provider prefixes remain visible, or whether helper failure drops the event
blocks spec promotion. Do not let the implementer invent policy in regex code.

Done signal: independent verdict PASS, all findings dispositioned, and no open
owner decision remains.

### Task 2: Promote the core specification

Files:

- `docs/specs/02-taut-core.md`
- this plan

Actions:

1. Apply the accepted exact delta using promotion strategy A.
2. Add the Related Plans backlink but no premature implementation mapping.
3. Run the documentation reference and diff gates.
4. Record the promotion baseline identifier above.

Stop gate: if the accepted delta needs a new public event field, config switch,
or payload version, reclassify and re-plan before code.

Done signal: the active spec contains the accepted requirement and reference
checks pass from the recorded promotion baseline.

### Task 3: Write red tests for the pure helper

Files:

- `tests/test_redact.py` (new)
- no production file yet

Actions:

1. Add a table-driven positive case for every `_Rule.id` planned for the
   manifest and every normative label in [TAUT-13.3.1]. Each case uses a unique
   synthetic sentinel and asserts: the sentinel is gone, `<redacted>` appears,
   and named context remains.
2. Cover direct JSON, JSON-escaped repr, single-quoted repr, env assignment,
   conninfo/query, URI userinfo, Authorization, PEM, repeated hits, adjacent
   hits, and overlapping rules.
3. For direct double-quoted and single-quoted repr forms, include synthetic
   secret values containing embedded quotes and backslashes. Assert the match
   consumes complete escape sequences, the raw sentinel is absent, and the
   final event remains valid JSON. Add one positive mapping case that already
   has one JSON-escape layer before event serialization.
4. Add negative cases for bare `token`, `TAUT_TOKEN`, `continuity_token`,
   passwordless URIs, public Stripe `pk_live_` values, ordinary database URLs,
   key metadata such as `primary_key`, and near-miss provider prefixes.
5. Prove input without matches is unchanged and Unicode surrounding text
   survives.
6. Prove import performs no `re.compile`; after cache reset, first sequential
   call compiles the exact manifest and a second call performs no more
   compilation. Limited spying on `re.compile` is allowed for this internal
   lifecycle contract; it is not the behavioral redaction proof.
7. Run a maximum-sized adversarial string in a subprocess with a generous
   fixed timeout. The test proves completion and containment, not a fragile
   micro-benchmark threshold.
8. Observe and record the intended failures before adding production code.

Stop gate: if a rule cannot identify only the value span without consuming its
label or structural evidence, narrow or drop that rule. Do not weaken the
value-only invariant to increase detector count.

Done signal: targeted tests fail only because `taut._redact` and its behavior
do not yet exist.

### Task 4: Implement the lazy value-only helper

Files:

- `taut/_redact.py` (new)
- `tests/test_redact.py`

Actions:

1. Add the private records, immutable manifest, cached compiler, span
   validation/coalescing, and one-pass right-to-left replacement exactly as
   specified.
2. Adapt only the named Taut-focused high-confidence formats from the sibling
   scanner. Preserve provider/type prefixes where possible by choosing the
   smallest secret group.
3. Keep all compile work below `_compiled_rules()` and all I/O out of the
   module.
4. Make the red suite green, then run Ruff and mypy on the new module and test.

Stop gate: a new dependency, fixture loader, public detector API, more than the
four rule families, or import-time compilation requires re-planning.

Done signal: every manifest rule fires, every negative case stays intact, and
lazy sequential compilation plus hostile-input containment pass.

### Task 5: Wire the one final-text choke point red-first

Files:

- `tests/test_debug_capture.py`
- `taut/debug.py`

Actions:

1. First add a real SQLite queue test whose exception message, traceback, and
   local repr contain distinct synthetic credentials. Assert the stored JSON
   is valid and bounded, context remains, and every raw sentinel is absent.
2. Add a real action-fixture test with the same evidence and assert its stdin
   payload equals the local payload after excluding existing nondeterministic
   event fields through the test's current normalization helper. Do not mock
   `_write_local`, `_send_to_action`, SimpleBroker, or subprocess transport for
   the main proof.
3. Add a helper-failure case. Limited monkeypatching of
   `redact_sensitive_text` to raise is correct only here; assert neither real
   sink receives an event and the outer boundary's original result is
   unchanged.
4. Observe the red failures.
5. Route every `_json_payload()` candidate through
   `redact_sensitive_text()` before `_serialize_event()` checks encoded size.
   Do not add calls in either sink.
6. Preserve the existing three-stage truncation behavior and prove a marker
   expansion near the byte bound still yields a bounded valid JSON object.

Stop gate: if one sink needs special handling, or if the only implementation
is a post-return scrub that bypasses the size check, stop and re-plan.

Done signal: local and action integration tests pass with identical scrubbed
text, helper failure reaches no sink, and all existing debug-capture tests stay
green.

### Task 6: Align durable documentation and traceability

Files:

- `README.md`
- `docs/implementation/04-taut-architecture.md`
- `docs/implementation/02-repository-map.md`
- `docs/specs/02-taut-core.md`
- this plan

Actions:

1. Replace the “unredacted by design” implementation rationale with the
   bounded final-text defense-in-depth rationale and residual-risk warning.
2. Add `_redact.py` to the repository map as the private rule/transform owner;
   keep `debug.py` as the deep workflow owner.
3. Update README guidance: recognizable credential values are redacted, but
   captured events may still contain sensitive process data and old rows are
   unchanged.
4. Add reciprocal implementation/test mapping only now that the code exists.
5. Reconcile the proposed delta against the promoted spec and record any
   deviation before changing behavior.

Stop gate: documentation must not use “sanitized,” “safe,” “all secrets,” or
equivalent completeness language.

Done signal: spec, implementation notes, README, repository map, code, and
tests tell one consistent story.

### Task 7: Final verification and completed-work review

Actions:

1. Run every command in Verification and Gates.
2. Perform an independent different-family completed-work review of the full
   diff and evidence. Disposition every finding.
3. Re-run affected gates after any accepted fix.
4. Reconcile every task against executable evidence, close the Deviation Log,
   update the plan index only when implementation is actually complete, and
   record the final commit identifier after owner-authorized landing.

Stop gate: any raw positive-case sentinel in either sink, invalid/oversized
JSON, untested manifest ID, import-time compilation, unsanitized fallback, or
changed primary error blocks completion.

Done signal: all local gates and independent review pass, the traceability
chain is closed, and the owner authorizes landing. Do not claim completion
from an uncommitted worktree.

## Testing Plan

Red-green TDD is mandatory for Tasks 3 and 5. Record the red command and the
expected failure before implementing each slice.

Use the narrowest real boundary:

- `tests/test_redact.py`: pure deterministic helper contract, enumerable-rule
  firing gate, negative cases, lazy compilation, overlap handling, and hostile
  input containment
- `tests/test_debug_capture.py`: real SQLite metadata and queue, real action
  fixture stdin, JSON validity and bound, sink equivalence, and primary-error
  containment
- `tests/test_architecture_boundaries.py`: add a source-structure assertion
  only if needed to prevent sink-local redaction or sibling imports; it is
  supporting proof, never a substitute for the real sink tests

Do not mock:

- the final `redact_sensitive_text()` operation in positive integration tests
- SimpleBroker queue creation/search/write/read for local proof
- the action subprocess and stdin transport for action proof
- `_serialize_event()` when proving validity and size
- the outer containment boundary when proving the original result survives

Permitted controlled seams:

- spy on `re.compile` after clearing the private cache for the lazy lifecycle
  test
- force the helper to raise only for the fail-closed integration case
- control time/process metadata using existing debug test helpers
- use synthetic, obviously fake credential values; never place a real secret
  in source, fixtures, logs, or review prompts

The positive-case table is the firing manifest. Adding a production `_Rule.id`
without a corresponding case fails the test by comparing the declared ID set
with the case ID set.

## Verification and Gates

Per-task commands:

```bash
uv run --locked pytest -q tests/test_redact.py
uv run --locked pytest -q tests/test_debug_capture.py
uv run --locked ruff check taut/_redact.py taut/debug.py tests/test_redact.py tests/test_debug_capture.py
uv run --locked ruff format --check taut/_redact.py taut/debug.py tests/test_redact.py tests/test_debug_capture.py
uv run --locked mypy taut tests/test_redact.py tests/test_debug_capture.py
```

Documentation and traceability gates:

```bash
uv run --locked pytest -q tests/test_docs_references.py tests/test_architecture_boundaries.py
uv run --locked bin/check-doc-paths
bin/check-plan-status-index
git diff --check
```

No CLI claim changes are planned. If implementation changes a maintained
command example, also run `uv run --locked bin/check-cli-claims`; otherwise
record it as not applicable rather than running an unrelated gate silently.

Final root gates:

```bash
uv run --locked pytest -q
uv run --locked ruff check taut tests
uv run --locked ruff format --check taut tests
uv run --locked mypy taut tests
```

Run the existing PostgreSQL/shared contract only if the core debug test matrix
or source changes make backend-specific capture behavior reachable. The helper
and serialized choke point are backend-independent, so a mandatory PostgreSQL
service run would add cost without extra proof unless review finds a real
backend coupling.

Success means all commands exit zero, every rule ID fires, both real sinks omit
all synthetic secret sentinels, delivered JSON is valid and bounded, the
continuity-token negative cases remain, and original boundary behavior is
unchanged. Record skipped or unavailable evidence as residual risk; do not
convert a skipped-everything run into a completion claim.

## Independent Review Loop

Before spec promotion, use a review-eligible agent family different from the
author through `skills/call-agent/SKILL.md`. The reviewer reads:

- this entire plan, especially Proposed Spec Delta and Rule Manifest Boundary
- `docs/specs/02-taut-core.md` [TAUT-13]
- `taut/debug.py`
- the relevant sibling scanner sources
- `tests/test_debug_capture.py`
- `docs/implementation/04-taut-architecture.md`

Review stance:

> You are reviewing; do not implement or modify anything. Existence-check
> every named seam and command first. Look for errors, bad ideas, latent
> ambiguity, unsafe regex behavior, missed final-text encodings, and
> performative overengineering. Prefer removing machinery when it does not
> address a concrete disclosure path. Accepted product direction: value-only
> final-text redaction, continuity tokens are not credentials, no retroactive
> row rewrite, and no safe-to-share promise. Pre-existing debug disclosure is
> out of scope unless this change worsens it. Answer PASS or BLOCKED based on
> whether the plan is implementable confidently and whether it would degrade
> security or robustness. Put scope expansions in a separate observations
> section.

After implementation, run a scoped completed-work review against the promoted
baseline and full diff. Every finding is accepted and fixed, rejected with
evidence, or deferred with a named reopen condition. A BLOCKED verdict or a
finding that changes rule scope, failure policy, or sink ownership returns the
plan to Task 1 and requires review of the revised delta.

## Assumptions and Open Questions

- **Assumption, owner: plan implementer.** `<redacted>` is the replacement for
  every non-empty selected value span. Reopen if preserving JSON validity or
  the byte bound cannot be achieved without a context-specific marker.
- **Assumption, owner: product owner.** The bounded Taut-focused provider set is
  preferable to vendoring the sibling scanner's full catalog. Reopen when a
  concrete Taut debug event exposes a high-confidence format outside the seed
  set, or when the sibling detector catalog becomes a supported shared
  library with compatible release ownership.
- **Assumption, owner: implementation reviewer.** Python's `functools.cache`
  sequential reuse is sufficient; exact once-only compilation during a
  concurrent first call is not required. Reopen only if profiling shows first-
  failure concurrency causes material duplicate work.

No open question blocks the initial plan review. The reviewer may force one
open if the final JSON encodings cannot be handled with bounded regexes while
preserving value-only spans.

## Out of Scope

- retroactive mutation, migration, or purge of retained `taut.debug` rows
- automatic retention, expiry, report-management commands, or queue cleanup
- changing which locals, tracebacks, messages, prompts, or runtime fields are
  captured
- making debug output safe to share or complete secret-detection claims
- encryption, access-control, storage-permission, or shared-storage changes
- changing action environment inheritance, cwd, timeout, or no-fallback policy
- continuity-token semantics, identity, authentication, or authorization
- a public scanning/redaction API, plugin hook, config key, user-supplied rule
  file, detector update service, or vendor-catalog synchronization
- loading YAML or depending on `mm`, TruffleHog, detect-secrets, or another
  scanner package
- changing fingerprints, sentinels, deduplication, payload version, logical
  dump/load, or database schema
- scrubbing ordinary chat messages, dumps, logs, CLI diagnostics, or any path
  other than [TAUT-13] debug-event delivery

## Deviation Log

| Spec ref | Planned behavior | Actual behavior | Rationale | Spec proposal |
|----------|------------------|-----------------|-----------|---------------|
| None | The promoted [TAUT-13.3.1] contract | Implemented as promoted | No implementation deviation | None |

## Review Log

Append-only. Record reviewer family, command/timeout outcome, baseline, verdict,
each finding, and its disposition. Do not infer a verdict from a failed or
timed-out invocation.

| Date | Reviewer | Baseline | Finding | Disposition |
|------|----------|----------|---------|-------------|
| 2026-08-20 | Claude Sonnet 4.6, read-only plan review; completed in 377 seconds with exit 0 | `46ee6bdf8017353a4ca9aad146d1afb0f34e47c5` plus initial draft | BLOCKED F1: quote-delimited matching could end inside an escaped quote/backslash and make final JSON invalid. | Accepted. Added the complete-encoded-character invariant, escape-aware rule requirement, and embedded quote/backslash positive cases for double- and single-quoted forms. |
| 2026-08-20 | Claude Sonnet 4.6 | same | F2: “corresponding qualified suffix” left the normative label vocabulary open. | Accepted. Enumerated the exact qualified and credential-token suffix sets in the proposed spec, manifest boundary, and firing-test obligation. |
| 2026-08-20 | Claude Sonnet 4.6 | same | F3: no worked example showed how full-match sibling detectors become prefix-preserving value spans. | Accepted. Added GitHub, Anthropic, and AWS before/after examples plus a drop-rather-than-overmatch stop gate. |
| 2026-08-20 | Claude Sonnet 4.6 | same | F4: a mapping already escaped before event serialization could evade the named forms. | Accepted with a bound. Require one pre-existing JSON-escape layer and record deeper recursive escaping as residual risk rather than building an unbounded parser. |
| 2026-08-20 | Claude Sonnet 4.6, round 2; completed in 160 seconds with exit 0 | revised draft after F1–F4 | FAIL: F2 remained open-ended in the Proposed Spec Delta because token labels said “such as,” despite the closed implementation set. F1, F3, and F4 verified. | Accepted. Replaced the proposed-spec wording with the exact `access_token`/`api_token`/`auth_token` bare labels and `_access_token`/`_api_token`/`_auth_token` suffixes. |
| 2026-08-20 | Claude Sonnet 4.6, round 3; completed in 102 seconds with exit 0 | revised F2 spec wording | FAIL: the Proposed Spec Delta closed both bare token labels and suffixes, but Rule Manifest Boundary explicitly closed only suffixes. | Accepted. Added the identical closed bare-label set beside the suffix set in Rule Manifest Boundary. |
| 2026-08-20 | Claude Sonnet 4.6, round 4; completed in 94 seconds with exit 0 | revised F2 bare/suffix symmetry | FAIL: positive sets matched, but only Rule Manifest Boundary explicitly rejected other unqualified `_token` suffixes. Reviewer judged this textual non-identity, not a behavior difference. | Accepted. Made the full negative-case sentence identical in both sections. |
| 2026-08-20 | Claude Sonnet 4.6, round 5; completed in 56 seconds with exit 0 | revised F2 positive and negative sets | PASS: Proposed Spec Delta and Rule Manifest Boundary now have semantically identical closed bare positives, suffix positives, and negative cases; no new defect. | Accepted. Independent plan review is closed; implementation remains gated by Task 1 owner acceptance and Task 2 spec promotion. |
| 2026-08-20 | Claude Sonnet 4.6, completed-work attempt; read-only, 540-second bound | full implementation delta from `46ee6bdf` | Invocation timed out with exit 124 and no output. No verdict was produced. | Recorded as a failed attempt. Switched to a separately review-eligible family under the review runbook; no finding is inferred. |
| 2026-08-20 | Grok, completed-work attempt; OS-enforced read-only sandbox, 540-second bound | full implementation delta from `46ee6bdf` | Invocation timed out with exit 124 and no verdict. Hook warnings reported a missing unrelated `TOOL_NAME` environment variable; no sandbox fail-open warning occurred. | Recorded as a failed attempt. No finding is inferred. Per owner direction, all subsequent reviewer bounds are 900 seconds. |
| 2026-08-20 | Claude Sonnet 4.6, completed-work review; read-only, 900-second bound; completed in 369 seconds with exit 0 | full implementation delta from `46ee6bdf` | BLOCKED F1 (P2): `credentialed_uri` required a non-empty username and leaked password-only URI forms such as `redis://:password@host`. | Accepted and reproduced with a failing public helper test. Changed the username quantifier from `+` to `*`; the focused URI slice passed. |
| 2026-08-20 | Claude Sonnet 4.6 | same | F2 (P3): the plan index still said implementation had not started. | Accepted. Updated the active-plan note to reflect implemented and locally gated work under completed-work review remediation. |
| 2026-08-20 | Claude Sonnet 4.6 | same | F3 (nit): the final serializer return does not recheck size after redaction can expand short matched values. | Declined as non-actionable residual risk. The reviewer confirmed this is practically unreachable because the final-stage event is bounded by construction. A second clamp would duplicate truncation policy without a firing failure case. |
| 2026-08-20 | Claude Sonnet 4.6 | same | Observation: camelCase label normalization is implemented but not stated explicitly in [TAUT-13.3.1]. | Deferred as a scope expansion, not a defect. The promoted contract defines normalized closed labels; changing its reviewed prose is not needed to correct F1. |
| 2026-08-20 | Claude Sonnet 4.6, narrow completed-work round 2; read-only, 900-second bound; completed in 56 seconds with exit 0 | accepted F1 remediation only | PASS / no blocker: password-only credentialed URIs redact; username-bearing and passwordless forms retain their prior behavior; no new ambiguous quantifier or concrete false positive was introduced. | Accepted. F1 is closed and the independent completed-work review passes. |

## Execution Evidence

Append-only. Record red/green commands, observed results, promotion baseline,
meaningful-slice reviews, final gates, landing identifier, and post-deploy
observation. Record only completed evidence, not predicted success.

- 2026-08-20 plan-authoring gates: `bin/check-plan-status-index`,
  `git diff --check`, and
  `uv run --locked pytest -q tests/test_docs_references.py` passed (10 tests).
- 2026-08-20 independent different-family review: initial review BLOCKED on
  final-JSON escape-boundary safety; all four findings were accepted. Narrow
  rounds 2–4 found and closed exact-vocabulary asymmetries. Round 5 returned
  PASS. Full findings and dispositions are retained in Review Log.
- 2026-08-20 Task 2 spec promotion: applied the reviewed [TAUT-13.3] through
  [TAUT-13.6] delta and Related Plans backlink against baseline `46ee6bdf`.
  Promotion identifier is that baseline plus the current
  `docs/specs/02-taut-core.md` worktree diff.
- 2026-08-20 comprehension gate: the only legal redaction seam is the
  `_serialize_event()` candidate renderer before encoded-size acceptance;
  helper failure reaches `capture_exception()` containment and drops the
  optional event without a raw fallback; `TAUT_TOKEN` remains because it is a
  continuity selector, not a credential or authorization grant.
- 2026-08-20 Tasks 3–4 helper TDD: the first test failed with
  `ModuleNotFoundError: taut._redact`; subsequent vertical red slices exposed
  escaped JSON, single-quoted repr, camelCase labels, authorization schemes,
  credentialed URIs, quoted conninfo, final-JSON assignments, PEM bodies, and
  provider formats before each implementation increment. Final helper suite:
  `uv run --locked pytest -q tests/test_redact.py` passed 87 cases, including
  every rule ID, lazy compilation, near misses, overlap, and hostile input.
- 2026-08-20 Task 5 sink TDD: the real local/action test first retained the raw
  exception password, then exposed the direct-JSON frame-local form after the
  shared serializer hook landed. After adding that explicit rule,
  `uv run --locked pytest -q tests/test_redact.py tests/test_debug_capture.py`
  passed 145 tests. The same proof covers real SQLite, real action stdin,
  fail-closed helper failure, continuity-token retention, and size fitting.
- 2026-08-20 Tasks 6–7 local gates: full root pytest passed with one expected
  Windows-only skip; Ruff check and format, mypy, documentation references,
  architecture boundaries, doc-path claims, plan index, and `git diff --check`
  all passed. PostgreSQL was not run because the helper and serializer seam are
  backend-independent and the real SQLite/action proofs exercise the changed
  boundary.
- 2026-08-20 completed-work review remediation: a 900-second Claude review
  reproduced a password-only credentialed-URI gap. The new
  `redis://:debug-db-password@db.example/0` case failed before the matcher
  correction and passed after the username quantifier changed from `+` to `*`.
  Full post-remediation pytest, Ruff check and format, mypy, documentation
  references, architecture boundaries, doc paths, plan index, and diff gates
  passed. A narrow 900-second review then returned `no blocker`; F1 is closed.
- 2026-08-20 owner-authorized close-out: the owner requested closure and
  commit. The plan index moved to completed after all implementation,
  verification, review, disposition, traceability, and deviation gates passed;
  the landing commit is verified from Git history after the commit.

## Fresh-Eyes Review Checklist

Before this plan is accepted or implementation is claimed complete, verify:

- every named file, function, command, spec code, and test seam exists;
- the proposed spec says value-only and retains residual-risk language;
- rule families are bounded and every private rule ID has a firing case;
- lazy compilation is proved without making concurrent exact-once a false
  contract;
- redaction occurs before every encoded-size decision and both sinks;
- no failure path can deliver the original unredacted candidate;
- continuity-token negative cases are explicit;
- real local and action paths remain in the proof;
- rollback does not claim to restore removed data or rewrite old rows;
- old retained events and inherited action environment remain visible residual
  risks;
- traceability and plan-index gates are named;
- review dispositions and deviations are closed before completion.
