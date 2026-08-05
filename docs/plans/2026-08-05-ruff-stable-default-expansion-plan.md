# Ruff Stable-Default Expansion Plan

Date: 2026-08-05
Status: completed — implementation, local verification, independent review,
and owner-authorized targeted landing complete; the concurrent SimpleBroker
floor change is excluded for a separate commit
Class: 5+P. This edits normative [DOM-10.2] policy and materially changes how
future Python work is accepted. The diagnostic cleanup spans core, extensions,
tests, CI helpers, and repository tools. No [DOM-5] risky trigger fires: no
product API, persistence, lifecycle, rollout, or one-way-door contract changes.
Plan type: implementation with spec revision
Hardening: N/A — no [DOM-5] risky trigger

## Goal

Make both active Taut Ruff configurations enable exactly the rules enabled by
SimpleBroker under Ruff 0.16.1: Ruff's stable defaults extended by `E`, `W`,
`F`, `I`, `B`, `C901`, `C4`, and `UP`, with `E501` and `B008` ignored and
preview rules disabled. Resolve the resulting diagnostics without changing
product behavior, and use the existing [DOM-10.2.1] suppression registry only
where a narrower behavior-preserving implementation would be worse.

## Requested Outcomes

- [x] Replace `lint.select` with the same `lint.extend-select` policy in the
  root and nested MCP Ruff configurations.
- [x] Prove both environments enable the same exact 453-rule inventory as
  SimpleBroker under the repository-pinned Ruff 0.16.1.
- [x] Preserve C901 at complexity 10, repository-wide lint discovery, the
  existing `E501`/`B008` ignores, and the existing explicit formatter scope.
- [x] Resolve every new normal diagnostic with a behavior-preserving change or
  an explicitly approved, narrow [DOM-10.2.1] suppression.
- [x] Preserve runtime behavior, public typing, exception containment,
  best-effort cleanup, resource lifetime, subprocess result handling, and test
  proof strength.
- [x] Reconcile the raw `--ignore-noqa` inventory and generated suppression
  index after activation.
- [x] Update the governing spec, implementation note, policy fixture, and plan
  index so the expanded contract is durable and executable.
- [x] Run targeted tests after each semantic slice, then the full repository
  static, product, extension, documentation, build, and release gates required
  for a repository-wide Python change. The Ruff change passes its gates; the
  root suite has one isolated, unrelated README/version mismatch from a
  concurrent SimpleBroker 6.0.1 floor edit, recorded below.
- [x] Obtain independent review of the plan; obtain further independent review
  of semantic slices and completed
  work; disposition every finding.

## Source Documents

Governing Taut policy:

- `docs/specs/01-development-documentation-operating-model.md` [DOM-5],
  [DOM-6], [DOM-10.2], [DOM-10.2.1], [DOM-11], and [DOM-15].
- `docs/agent-context/engineering-principles.md`, especially principles 4, 8,
  10, 12, 13, and 14.
- `docs/agent-context/runbooks/writing-plans.md`.
- `docs/agent-context/runbooks/testing-patterns.md`.
- `docs/agent-context/runbooks/maintaining-traceability.md`.
- `docs/implementation/08-complexity-and-suppression-policy.md`.
- `docs/plans/2026-08-04-ruff-complexity-and-suppression-registry-plan.md`,
  which introduced the current exact-version, discovery, complexity, and
  suppression-reconciliation gates.

SimpleBroker reference:

- `../simplebroker/pyproject.toml` at
  `6481ca08c7ec29f64280a745814387fc70ce1b54`.
- `../simplebroker/tests/fixtures/ruff-enabled-rules.txt` at the same commit.
- `../simplebroker/tests/test_ruff_policy.py` at the same commit.
- `../simplebroker/docs/plans/2026-07-29-ruff-lint-expansion-plan.md`, including
  its correction and suppression evidence.

Source product spec: None. This changes repository verification policy only;
product behavior is an invariant, not a target.

## Spec Baseline

- `9ec9d8757d6c1d0fa396a8d231bb8a9266e8ac7c` —
  `docs/specs/01-development-documentation-operating-model.md` at plan
  authoring time.
- This plan revises [DOM-10.2] and its related-plan backlinks.
- Promotion strategy: **A — in-file, text before dependent code claims**. Apply
  all reviewed [DOM-10.2] replacements and the backlink first. Record the resulting
  diff base plus spec blob as the promotion baseline before policy-test or
  configuration edits cite it.
- Promotion baseline identifier: base
  `9ec9d8757d6c1d0fa396a8d231bb8a9266e8ac7c` plus promoted spec blob
  `9a50a320c45dc88d53b4372c62f87052efd4cc9b`. At promotion,
  `tests/test_docs_references.py` passed 10 tests and the DOM-15 fixture gate
  passed; the full documentation path gate is rerun after all plan edits.

## Measured Baseline

Both Taut configs currently use an explicit `lint.select` for `E`, `W`, `F`,
`I`, `B`, `C4`, `UP`, and `C901`. That resolves 171 rules. SimpleBroker uses
`lint.extend-select` for the same families and therefore retains Ruff 0.16.1's
expanded stable defaults; its accepted fixture contains 453 rules. The exact
set difference is 282 rules, with no Taut-only rule.

A first read-only isolated probe of the target policy over Taut reported 273
normal diagnostics in 80 files. Reproduction after plan review showed that
`--isolated` also erased each checked-in config's auxiliary
`isort.known-first-party` setting and therefore introduced 10 false `I001`
findings in MCP tests. The authoritative config-preserving probe selects the
exact 453 fixture codes while retaining all non-selection settings. It reports
263 normal diagnostics in 78 files across 29 codes, of which 132 offer a Ruff
fix. Its raw `--ignore-noqa` form reports 334 diagnostics in 82 files across 31
codes. The largest normal groups are `BLE001=62`, `RUF100=29`, `PLR0402=22`,
`PLW1510=19`, `FLY002=16`, `TRY004=15`, `RUF012=15`, `SIM117=14`,
`ISC004=12`, and `PYI034=10`. Raw output also includes the existing
`C901=38`, `F401=1`, and 32 currently suppressed `BLE001` diagnostics.

These counts are planning evidence, not allowlists. The accepted fixture and a
clean normal Ruff run are the durable gates. The raw inventory must be derived
again after cleanup and approved suppressions.

## Context and Key Files

### Configuration, contract, and proof owners

- `pyproject.toml`: root Ruff discovery and rule selection.
- `extensions/taut_mcp/pyproject.toml`: nested MCP Ruff rule selection. Ruff
  discovers this tree from the root but resolves this nested configuration, so
  both owners must change together.
- `tests/test_ruff_policy.py`: real-Ruff version, discovery, configuration,
  firing, effective-rule, raw-inventory, normal-lint, and registry proof.
- `tests/fixtures/ruff-enabled-rules.txt`: reviewed exact effective rule set.
- `docs/specs/01-development-documentation-operating-model.md` [DOM-10.2] and
  [DOM-10.2.1]: normative selection and suppression contract.
- `docs/implementation/08-complexity-and-suppression-policy.md`: current
  rationale and required editor workflow.
- `bin/ruff_suppression_index.py`: existing human-registry-to-source
  reconciler. Reuse it unchanged unless a demonstrated target-rule case
  exposes a real defect.

### Diagnostic edit surfaces

The target-policy probe, not a hand-maintained path list, owns the final source
inventory. Its current findings fall into these review groups:

- Safe/local syntax and deterministic-order cleanup: `ISC004`, `FLY002`,
  `FURB167`, `FURB188`, `PIE810`, `PLC0208`, `PLR0402`, `PLR1711`,
  `RET501`, `RUF015`, `RUF022`, `SIM102`, `SIM114`, and `SIM117`.
- Invocation and file ownership: `EXE001`, `N999`, `PLW1510`, and `LOG001`.
- Type and value contracts: `DTZ006`, `PYI034`, `PYI041`, `RUF012`, and
  `TRY004`.
- Exception, cleanup, and resource boundaries: `BLE001`, `G201`, `S110`, and
  `SIM115`.
- Suppression hygiene: `RUF100`, including currently non-enabled `SLF001`,
  `N802`, and `S310` directives whose explanatory intent may remain as ordinary
  comments even when the inactive Ruff directive is removed.

### Comprehension gates before semantic edits

The implementer must answer these from the owning code and tests:

1. Does a broad catch contain an untrusted plugin, worker, transport, cleanup,
   or observer failure? If so, which real test proves that containment?
2. Does adding `check=False` merely document an intentionally inspected or
   ignored return code, or does the call currently rely on an implicit result?
3. Does a context manager intentionally return a value other than `self`, or
   expose a public annotation that downstream callers can type-check?
4. Does a file stay open across a subprocess, thread, generator, or later
   assertion? Flattening or wrapping it must not shorten or extend ownership.
5. Is an exception type part of a public or tested contract? `TRY004` does not
   authorize silently changing `ValueError` to `TypeError`.
6. Is a mutable class attribute intentional shared fake state, or accidental
   cross-instance state? Preserve the former explicitly and remove the latter.

## Invariants and Constraints

1. Exact parity means the same 453 enabled rule codes as SimpleBroker at Ruff
   0.16.1. It does not mean `select = ["ALL"]`, preview rules, or future Ruff
   defaults without fixture review.
2. Preserve all product, CLI, storage, MCP wire, Summon lifecycle, release,
   exception-shape, logging, and public typing behavior.
3. Keep `mccabe.max-complexity = 10`; do not undo the reviewed locality choices
   or refactor cohesive owners merely because another enabled rule suggests a
   shorter form.
4. Keep global ignores exactly `E501` and `B008`. Add no per-file ignores,
   blanket file directives, threshold inflation, or baseline allowlist.
5. Target zero new suppressions. A surviving diagnostic may be registered only
   when the code is clearer and safer as-is, the protected invariant and real
   proof are named, rejected alternatives are concrete, an independent reviewer
   agrees, and the user explicitly approves every human-owned registry field.
6. Existing active local suppressions are not grandfathered automatically.
   `RUF100` must be clean. Remove a stale directive; if its prose explains a
   real white-box or network boundary, retain that prose as an ordinary comment.
7. Do not use `--unsafe-fixes`. Preview every safe-fix slice with `--diff`,
   apply only a coherent rule group, inspect the diff, then run its nearest
   proof before continuing.
8. Context-manager rewrites preserve enter order, exit order, and primary-error
   precedence. Resource changes preserve the exact lifetime required by child
   processes, background threads, and delayed reads.
9. Broad-catch rewrites preserve contained exception types and failure
   ownership. Do not add noisy logging or propagate an intentionally contained
   failure only to satisfy `BLE001` or `S110`.
10. `EXE001` is resolved from actual invocation ownership: directly invoked
    scripts keep a shebang and executable bit; module-only scripts lose the
    shebang. `N999` must not force public script renames in this change. The six
    public hyphenated `bin/*.py` names stay unchanged; if their findings remain,
    they require a narrow multi-site [DOM-10.2.1] group with the same independent
    review and explicit user approval as every other new suppression. Do not
    exclude the files or add `N999` to a global ignore.
11. Formatting remains on the existing explicit path sets. Repository-wide
    lint discovery does not authorize repository-wide formatting.
12. Add no dependency, package version, changelog entry, or product claim.
13. Stop and revise this plan if a rule requires a public contract change, a
    new cross-subsystem abstraction, a global ignore, or weaker tests.

## Proposed Spec Delta

Promotion strategy A applies to this exact replacement.

### [DOM-10.2] — replace the opening selection paragraph

> Taut's Python lint gate uses one exact Ruff version across the root,
> PostgreSQL, Summon, and MCP development manifests and existing lockfiles.
> `pyproject.toml` and `extensions/taut_mcp/pyproject.toml` own their respective
> Ruff configuration; both enable Ruff's stable defaults and extend them with
> `E`, `W`, `F`, `I`, `B`, `C901`, `C4`, and `UP`, use
> `mccabe.max-complexity = 10`, ignore only `E501` and `B008`, and keep preview
> rules opt-in. The two configurations must resolve the exact reviewed rule
> inventory recorded in `tests/fixtures/ruff-enabled-rules.txt`. A Ruff-version
> change must update every manifest and existing lock in one reviewed change,
> regenerate the effective-rule fixture, and re-run the raw suppression audit
> before adoption.

### [DOM-10.2] — replace the final sentence of the raw-inventory paragraph

> Per-file ignores, unreviewed global ignores beyond `E501` and `B008`, blanket
> file directives, threshold inflation, and baseline allowlists are not
> permitted as alternatives to review.

### [DOM-10.2] — replace the verification sentence in the ownership paragraph

> Verification: `tests/test_ruff_policy.py` invokes the real canonical Ruff
> binary, compares effective discovery and enabled rules with reviewed
> inventories, proves a stable-default rule and a retained-family rule both
> fire, proves complexity 10 passes and 11 fails, and checks CI and release
> command shape.

### Related-plan backlink — append under `## Related Plans`

> - `docs/plans/2026-08-05-ruff-stable-default-expansion-plan.md`: aligns both
>   Taut Ruff configurations with SimpleBroker's Ruff 0.16.1 stable-default
>   plus retained-family policy and resolves the expanded diagnostic surface.

## Dependency-Ordered Tasks

### T1 — Independent plan review (complete)

- Give the reviewer this plan, the current [DOM-10.2]/[DOM-10.2.1] text, both
  Ruff configs, the policy test, the implementation note, SimpleBroker's plan,
  config, fixture, and current measured diagnostic inventory.
- Ask whether exact parity is defined unambiguously, the suppression gate is
  enforceable, and semantic stop conditions protect behavior without turning
  lint cleanup into performative refactoring.
- Record and disposition every finding. Do not start source edits until the
  reviewer can implement the plan confidently and predicts no degradation.
- Result: Grok 4.5 returned `PASS` after verifying the 453-rule set and all
  measured counts from source. The six findings and their dispositions are in
  `## Review Log`. A preceding Claude Opus invocation timed out without a
  result; the repository review skill's fallback path was followed.

### T2 — Promote the contract and create red policy proof

- Apply all reviewed spec replacements and the backlink; record the promotion
  baseline identifier in this plan.
- Change `tests/test_ruff_policy.py` first so it requires `lint.select` to be
  absent, requires exact `lint.extend-select` in both configs, checks only the
  two approved global ignores, and compares both real environments with the
  reviewed 453-rule fixture.
- Add real stdin firing probes for a newly inherited stable-default rule
  (`BLE001`), a retained legacy-family rule (`B904`), and existing `C901`.
- Replace the fixture with the exact reviewed SimpleBroker rule-code inventory.
- Observe the focused policy test fail against the old configs. This is the red
  proof. The config activation remains last so ordinary Ruff stays usable while
  cleanup proceeds.

### T3 — Apply and verify local safe fixes

- Preview Ruff's safe fixes by coherent rule group. Apply only locally
  equivalent syntax/order rewrites and inspect every diff.
- Handle `RUF100` manually where automatic removal would erase useful intent:
  replace inactive directive syntax with an ordinary explanatory comment.
- Keep the checked-in configs on the old clean policy through T5. Preview and
  verify target-policy cleanup by selecting the exact accepted fixture while
  retaining each config's discovery, mccabe, and isort settings (add
  `--fix --diff` only for the coherent rule group being reviewed):

  ```bash
  rule_codes=$(paste -sd, tests/fixtures/ruff-enabled-rules.txt)
  uv run --extra dev ruff check \
    --select "$rule_codes" --ignore E501,B008 .
  ```

  Run the nearest tests for each touched module. Run format only on touched
  files already inside a formatter-owned scope.
- Stop and move a finding to T4/T5 when the fix changes order, ownership,
  exception shape, type contract, resource lifetime, or assertion meaning.

### T4 — Resolve invocation, resource, type, and value-contract findings

- Audit every `EXE001`, `N999`, `PLW1510`, `SIM115`, `PYI034`, `PYI041`,
  `RUF012`, `TRY004`, and `DTZ006` site individually against the comprehension
  gates.
- Add `check=False` only where ignoring or separately inspecting the child
  return code is already intentional. Use `check=True` only where failure is
  already required to raise.
- Preserve exported context-manager annotations. A public annotation that Ruff
  dislikes becomes a suppression candidate unless compatibility is proven.
- Preserve local-time rendering semantics at `DTZ006`; do not silently switch
  user output to UTC.
- For each behavior-sensitive change, run the closest existing test before and
  after. Add a characterization test first if the owning contract lacks one.
- Obtain a scoped independent review of this slice before proceeding.

### T5 — Audit exception and cleanup boundaries

- Classify every `BLE001`, `G201`, and `S110` site as public translation,
  worker/plugin containment, retry, cleanup, observer isolation, test capture,
  or accidentally broad handling.
- Audit the raw inventory, not only normal Ruff: all 94 current raw `BLE001`
  sites are in scope, including the 32 sites hidden by existing untagged
  directives. A surviving site must use the approved [DOM-10.2.1] form; no
  existing `BLE001` directive is grandfathered or left as an ungrouped local.
- Narrow only when all intended failure types are known and covered. Preserve
  broad catches at true containment boundaries as suppression candidates.
- Use `logger.exception` only when it preserves the same logger, level,
  message, formatting arguments, traceback, and observer-visible behavior.
- Do not add logging to silent best-effort cleanup unless logging is already
  part of its contract. Prefer a clear named discard only when it improves the
  code; otherwise propose a narrow suppression.
- Inventory surviving candidates by group with exact sites, raw counts,
  protected invariant, real proof, rejected alternatives, and proposed
  approval text. Obtain independent review and explicit user approval before
  editing human-owned [DOM-10.2.1] rows or running generator write mode.

### T6 — Activate exact policy and reconcile suppressions

- Replace `lint.select` with identical `lint.extend-select` lists in the root
  and MCP configs. Keep the root `extend-include`, both mccabe settings, and
  both ignore lists unchanged.
- Apply only the user-approved local suppressions and registry rows. Run the
  generator in write mode only after approval, then immediately check it.
- Derive and update the exact global raw inventory. Do not copy planning counts.
- Run the red policy proof and ordinary `ruff check .` to green. Confirm the
  root and MCP enabled sets both match the 453-rule fixture exactly.
- Update the implementation note to explain stable-default extension, fixture
  ownership, and the rule-refresh/suppression workflow.

### T7 — Repository verification

- Run the exact gates in `## Testing and Verification` from the current state.
- Inspect the full diff for semantic changes, broad formatting churn, weakened
  assertions, and config drift.
- Reconcile the spec, plan, implementation note, policy test, fixture, configs,
  raw inventory, and generated index.

### T8 — Independent completed-work review and close

- Give the reviewer the promoted spec baseline, plan, implementation note,
  complete diff, suppression dispositions, and current verification evidence.
- Ask specifically whether any change altered exception containment, resource
  lifetime, subprocess handling, public annotations, local-time rendering,
  executable-script behavior, or test strength; ask whether any suppression is
  avoidable or too broad.
- Reproduce and disposition every finding; run scoped confirmation for accepted
  corrections.
- Mark this plan and its index row completed only after all gates pass. Land by
  explicit file-list staging only when the user requests a commit.

## Testing and Verification

### Focused policy and suppression proof

```bash
uv run --extra dev pytest tests/test_ruff_policy.py tests/test_ruff_suppression_index.py
uv run --extra dev ruff check .
uv run --extra dev python bin/ruff_suppression_index.py --check
```

Success means both real Ruff environments match the exact 453-rule fixture,
the stable-default and retained-family sentinels fire, normal Ruff is clean,
`RUF100` is clean, and raw diagnostics reconcile exactly.

### Static and formatting proof

```bash
uv run --extra dev ruff format --check taut tests bin .github/scripts
uv run --extra dev ruff format --check extensions/taut_pg/taut_pg extensions/taut_pg/tests bin/pytest-pg
uv run --extra dev ruff format --check extensions/taut_summon/taut_summon extensions/taut_summon/tests
uv run --project extensions/taut_mcp --extra dev ruff format --check extensions/taut_mcp/taut_mcp extensions/taut_mcp/tests
uv run --extra dev mypy taut tests bin/release.py .github/scripts
uv run --extra dev mypy taut/_scripts.py extensions/taut_pg/taut_pg extensions/taut_pg/tests --config-file pyproject.toml
uv run --extra dev mypy extensions/taut_summon/taut_summon extensions/taut_summon/tests --config-file pyproject.toml
uv run --project extensions/taut_mcp --extra dev mypy extensions/taut_mcp/taut_mcp extensions/taut_mcp/tests --config-file extensions/taut_mcp/pyproject.toml
```

### Product and extension proof

Run the nearest tests after each behavior-sensitive slice. The final gate is
the same repository-wide sequence that passed the preceding Ruff policy work:

```bash
uv run --extra dev pytest
uv run --extra dev --with-editable extensions/taut_pg pytest extensions/taut_pg/tests
uv run --project extensions/taut_summon --extra dev pytest extensions/taut_summon/tests
uv run --project extensions/taut_mcp --extra dev pytest extensions/taut_mcp/tests
```

Run the repository's separately owned live PostgreSQL and local-model lanes
when the ordinary invocations skip them; do not claim those integrations from
skip-only output.

### Documentation, lock, build, and release proof

```bash
uv lock --check --directory extensions/taut_summon
uv lock --check --directory extensions/taut_mcp
uv run --extra dev pytest tests/test_docs_references.py tests/test_ruff_policy.py
python3 bin/check-dom15-fixtures
bin/check-plan-status-index
uv run --extra dev bin/check-doc-paths
git diff --check
uv build
uv build --directory extensions/taut_pg
uv build --directory extensions/taut_summon
uv build --directory extensions/taut_mcp
uv run --extra dev python bin/release.py --dry-run
```

The release dry-run prints rather than executes its live-service commands; it
does not replace their separately executed acceptance lanes.

## Suppression Registry Delta

The user approved these exact human-owned fields on 2026-08-05. They are copied
into [DOM-10.2.1], and the generated index reconciles every corresponding
source directive. The independent semantic review accepted every row after
reducing `SIM117` from 14 sites to the seven true ownership-boundary nests.

| Group | Rules | Approved cardinality | Protected invariant | Real proof | Rejected alternatives | Approval |
|-------|-------|----------------------|---------------------|------------|-----------------------|----------|
| `[RUFF-SUP-065]` | `BLE001` | `10` directives; raw: `BLE001=10` | Repository tools, the MCP CLI, and pytest-pg orchestration translate any operational or environment failure into their established concise exit contract | Checker self-tests, CLI tests, workflow command-shape tests, and no-traceback assertions | Guessed environment exception lists or leaking tool tracebacks | User approved exact fields 2026-08-05. |
| `[RUFF-SUP-066]` | `BLE001` | `11` directives; raw: `BLE001=11` | MCP process and workspace reactors contain arbitrary child, callback, transport, plugin, and shutdown failures at the owning reactor boundary | MCP routing, crash, cancellation, notification, and shutdown suites | Narrowing third-party or user callbacks, or propagating across event-loop and thread ownership | User approved exact fields 2026-08-05. |
| `[RUFF-SUP-067]` | `BLE001` | `8` directives; raw: `BLE001=8` | Summon control, driver, and PTY lifecycle owners preserve primary-error precedence and contain arbitrary child, adapter, and cleanup failures | Summon teardown, signal, control, PTY, and restoration suites | Guessed exception lists or split cleanup owners | User approved exact fields 2026-08-05. |
| `[RUFF-SUP-068]` | `BLE001` | `3` directives; raw: `BLE001=3` | Optional notification, reaction, and login-name integrations remain best-effort across backend and platform failures | Messaging, notification, and identity fallback tests | Making optional side effects fail the owning operation or enumerating backend and platform exception classes | User approved exact fields 2026-08-05. |
| `[RUFF-SUP-069]` | `BLE001` | `1` directive; raw: `BLE001=1` | The release preparation worker captures any `BaseException` and re-raises it at the owner wait gate | Local-LLM preparation and wait-failure tests | Allowing thread failure to disappear or excluding control-flow exceptions from relay | User approved exact fields 2026-08-05. |
| `[RUFF-SUP-070]` | `BLE001` | `35` directives; raw: `BLE001=35` | Concurrency and real-process test harnesses capture any `BaseException` from worker threads so the owning test can join and assert the exact outcome | Affected tests plus their live-thread, join, and captured-failure assertions | `Exception`-only capture, hidden thread warnings, or mocked concurrency | User approved exact fields 2026-08-05. |
| `[RUFF-SUP-071]` | `BLE001` | `21` directives; raw: `BLE001=21` | Race, transient-service, and harness tests retain any contender or fixture `Exception` as diagnostic or expected-race evidence | Affected PostgreSQL, Summon, and core race and diagnostic tests | Guessed production exception lists in adversarial harnesses or discarding evidence without a later assertion or diagnostic | User approved exact fields 2026-08-05. |
| `[RUFF-SUP-072]` | `FLY002` | `16` directives; raw: `FLY002=16` | Line-oriented fixture and configuration text remains readable as structured rows with visible blank-line and trailing-newline intent | Exact parser, configuration, claim, terminal-text, and release-fixture tests | Monolithic escaped one-line literals or new dedent helpers and imports | User approved exact fields 2026-08-05. |
| `[RUFF-SUP-073]` | `TRY004` | `15` directives; raw: `TRY004=15` | Malformed external data, storage rows, scenarios, and internal invariants retain their established domain error categories | Malformed response, state, scenario, SQL, and structured-probe tests | `TypeError`, which would mislabel decoded or internal data as a Python call-site type contract | User approved exact fields 2026-08-05. |
| `[RUFF-SUP-074]` | `SIM117` | `7` directives; raw: `SIM117=7` | Distinct assertion and resource scopes keep acquisition, cleanup, and the lifetime under test visually separate | Multi-client, `pytest.raises`, cleanup, SQL cursor, signal-probe, and shared-contract tests | Merging contexts that obscures the asserted exit or distinct resource owner | User approved exact fields 2026-08-05. |
| `[RUFF-SUP-075]` | `N999` | `6` directives; raw: `N999=6` | Stable documented and workflow-invoked public hyphenated script filenames remain unchanged | Workflow, release, documentation, and command-shape tests | Rename, exclusion, global ignore, or duplicate compatibility shims | User approved exact fields 2026-08-05. |
| `[RUFF-SUP-076]` | `SIM115` | `3` directives; raw: `SIM115=3` | Stderr handles stay open for exactly the subprocess lifetime and close through the existing lifecycle owner | Driver-process and live-harness cleanup tests | Indenting whole process scenarios under `with` blocks or adding an `ExitStack` owner solely for lint | User approved exact fields 2026-08-05. |
| `[RUFF-SUP-077]` | `RUF015` | `2` directives; raw: `RUF015=2` | Direct single-row materialization preserves the existing `IndexError` failure and locally exposes the result-shape assertion | Claim-cleanup tests | `next(iter(...))`, which changes empty-result failure to `StopIteration` and is less clear | User approved exact fields 2026-08-05. |
| `[RUFF-SUP-078]` | `DTZ006` | `1` directive; raw: `DTZ006=1` | User-facing timestamps retain local-time rendering | Rendering tests | Silently changing output to UTC or attaching an invented timezone | User approved exact fields 2026-08-05. |
| `[RUFF-SUP-079]` | `FURB122` | `1` directive; raw: `FURB122=1` | GitHub output records remain an explicit local one-record-per-write loop | Release-publication output tests | A generator passed to `writelines`, which decreases locality without changing ownership or behavior | User approved exact fields 2026-08-05. |
| `[RUFF-SUP-080]` | `LOG001` | `1` directive; raw: `LOG001=1` | Formatter-test logging remains isolated from the process-global logger registry and pre-existing handlers | Exact formatter and bootstrap test | `getLogger`, which adds global registry state to a unit test | User approved exact fields 2026-08-05. |
| `[RUFF-SUP-081]` | `PYI041` | `1` directive; raw: `PYI041=1` | The live-harness helper explicitly mirrors the complete `JSONPrimitive` vocabulary, including both `int` and `float` | `SummonStatus` construction, live-harness tests, and static typing | Dropping `int` through numeric-tower compatibility, which makes the runtime data vocabulary less clear | User approved exact fields 2026-08-05. |

## Rollout and Rollback

Activation is atomic at the merge boundary: cleanup, approved suppressions,
both configs, fixture, raw inventory, tests, spec, and implementation note land
together. Do not land only one config or activate the policy before the tree is
clean.

There is no data or deployment rollback. If one stable rule proves incompatible
with an intentional contract, stop at T5. Prefer a narrow approved suppression;
do not silently drop the rule because that would break exact SimpleBroker
parity. If activation itself must be reverted, behavior-preserving cleanup may
remain, but both configs, fixture, spec, implementation note, raw inventory,
and policy tests revert as one contract unit.

## Out of Scope

- Ruff preview rules, `select = ["ALL"]`, or rules SimpleBroker does not enable.
- A Ruff version change, dependency refresh, formatter expansion, or new tool.
- Product API, CLI, wire, storage, lifecycle, release, or security-posture
  changes.
- Broad architectural refactors, file splitting, or helper extraction done
  only to satisfy lint.
- Renaming public scripts solely for `N999`.
- Weakening tests or changing asserted behavior to make a lint rewrite pass.

## Deviation Log

| Spec ref | Planned behavior | Actual behavior | Rationale | Spec proposal |
|----------|------------------|-----------------|-----------|---------------|
| T7 verification commands | Extension commands used project-relative source paths | Commands now use repository-relative paths, matching checked-in workflows; ordinary PG collection uses the root dev environment plus the editable PG package, while the canonical live lane remains `uv run ./bin/pytest-pg` | `uv --project` selects dependencies but does not change the process working directory. Root dev alone omits `taut_pg`; PG project dev alone omits the cross-package Summon test dependency. The original PG probe also generated the intentionally absent ignored `extensions/taut_pg/uv.lock`, which was immediately removed. | None; verification-command correction only. |
| T3 `RUF022` cleanup | The first safe-fix pass sorted public `__all__` lists; the root suite initially appeared to make historical order a contract | Retained lexical sorting and changed root and Summon public-export tests to assert the exact set plus no duplicates | The owner explicitly clarified that membership, not iteration order, is the public contract. Registering a suppression would have overclaimed compatibility requirements. | None; test now expresses the intended contract. |
| T7 release dry-run | Planned `--dry-run --skip-live` | Canonical command is `--dry-run`; it prints all live commands without executing them | `--skip-live` is not a release CLI option. The initially planned invocation failed at argument parsing; the corrected dry-run completed. | None; verification-command correction only. |

## Review Log

| Review | Date | Verdict | Disposition |
|--------|------|---------|-------------|
| Claude Opus plan review | 2026-08-05 | No result | Timed out after the repository skill's 540-second ceiling. No finding was inferred; fallback used without retry. |
| Grok 4.5 plan review | 2026-08-05 | PASS with findings | Verified the 453-rule parity and 273 normal/344 raw baseline. F1 accepted: corrected the invalid SimpleBroker full SHA to `6481ca08c7ec29f64280a745814387fc70ce1b54`. F2 accepted: fixed the public-hyphenated-script `N999` disposition to reviewed local registry coverage rather than rename/exclude/global ignore. F3 accepted: specified the exact isolated target-policy command before activation. F4 accepted: brought all 94 raw `BLE001` sites, including 32 existing directives, into T5 and forbade grandfathering. F5 accepted: escalated the declared class from 3+P to 5+P because normative [DOM-10.2] changes. F6 accepted: added the stable-default and retained-family firing requirement to the exact spec delta. |
| Grok 4.5 scoped plan confirmation | 2026-08-05 | PASS | Verified F1–F6 and found no new defect. Its only non-blocking wording note (singular “replacement” for three spec edits) was corrected. A subsequent author reproduction found the reviewed isolated probe erased auxiliary isort settings; that correction is recorded separately below. |
| Author reproduction of target-policy probe | 2026-08-05 | Corrected reviewed command | The exact 453-code selection under the checked-in root and nested configs reports 263 normal/334 raw diagnostics. The prior isolated command reported 10 artificial MCP `I001` findings because it erased `known-first-party`; T3 and the measured baseline now preserve auxiliary config. Scoped confirmation required before semantic source edits. |
| Grok 4.5 scoped probe-correction review | 2026-08-05 | FAIL; finding accepted | Confirmed the corrected command, counts, exact rule set, auxiliary config, mccabe threshold, and discovery. Found one stale `I001=10` entry in the authoritative group list and the corresponding edit-surface bullet; both were removed because the final-policy-equivalent probe emits no `I001`. |
| Grok 4.5 stale-`I001` correction confirmation | 2026-08-05 | PASS | Verified both stale live references were removed, all remaining `I001` mentions are properly historical, and the correction introduced no new defect. |
| Grok 4.5 semantic-cleanup and suppression review | 2026-08-05 | BLOCKED on F1; accepted | Reproduced 117 normal and 188 raw target-policy diagnostics; found no defect in the applied rewrites and accepted proposed groups 1–9 and 11–17. F1 found seven simple MCP stdio/session nests matching an already improved sibling; those were combined instead of suppressed, reducing `SIM117` from 14 to 7. F2 wording was accepted: group 1 now names repository tools, the MCP CLI, and pytest-pg orchestration rather than “PG entry points.” |
| Grok 4.5 F1 correction confirmation | 2026-08-05 | PASS | Verified exactly seven new simple stdio/session merges, unchanged enter/exit order and lifetime, exactly seven true ownership-boundary `SIM117` findings remaining, normal 110/raw 181 counts, and no new defect. |
| Grok 4.5 root `RUF022` follow-up | 2026-08-05 | PASS on proposed suppression; owner rejected premise | The root suite exposed an exact-order assertion and the reviewer found a one-site suppression internally consistent. The owner then clarified that public export membership, not ordering, is the contract. The sort was retained, both exact public-export tests now assert the set plus no duplicates, and proposed `RUFF-SUP-082` was removed. |
| Grok 4.5 completed-work review | 2026-08-05 | PASS; no findings | Independently reproduced both configs' exact 453-rule inventory, normal Ruff cleanliness, raw inventory `181`, registered directive count `180`, groups `RUFF-SUP-001` through `RUFF-SUP-081` with retired gaps, and the independent `F401=1`. Confirmed the cleanups preserve exception containment, resource lifetime, subprocess handling, local-time rendering, executable-script behavior, public typing, and test strength. Confirmed the public-export tests prove exact membership and uniqueness without treating order as a contract. Excluded the concurrent SimpleBroker 6.0.1 manifest and lock hunks from the Ruff landing assessment and found the remaining change landable by explicit staging. |

## Completion Evidence

Implementation, verification, independent review, and owner-authorized
targeted landing are complete. The unrelated SimpleBroker floor change is
excluded from this Ruff unit and handled in a separate commit.

- Policy and suppression proof: `ruff check .`, the suppression-index check,
  and 40 focused policy/index tests passed. Both configurations resolve the
  exact sorted 453-rule fixture. The raw inventory is `181` diagnostics:
  `BLE001=89`, `C901=38`, `DTZ006=1`, `F401=1`, `FLY002=16`, `FURB122=1`,
  `LOG001=1`, `N999=6`, `PYI041=1`, `RUF015=2`, `SIM115=3`, `SIM117=7`, and
  `TRY004=15`. The generated registry owns 180 directives; the existing
  side-effect-import `F401` directive remains independently justified.
- Static and format proof: all four scoped Ruff format checks passed. Root,
  PostgreSQL, Summon, and MCP mypy checks passed over 101, 5, 36, and 18 files
  respectively.
- Product proof: the root suite passes 1,502 tests with one skip when the
  unrelated metadata test is deselected. The unfiltered root run has exactly
  one unrelated failure: `test_readme_install_examples_use_public_distribution_names`
  observes a concurrent `simplebroker>=6.0.1` manifest floor while README still
  documents 6.0.0. Summon passes 528 tests with one local-Ollama-model skip;
  MCP passes 205 ordinary tests with six live-PostgreSQL skips; PostgreSQL
  passes its ordinary test with 13 live skips. The canonical live PostgreSQL
  lane then passes 242 shared root tests and all 14 PostgreSQL tests. MCP's
  separately run live PostgreSQL lane passes all six selected tests. Temporary
  PostgreSQL containers were removed after both lanes.
- Contract proof for the owner correction: root and Summon public API tests
  pass 30 tests. They assert exact export-set equality plus equal list, set,
  and expected-set cardinality, so missing, extra, and duplicate exports fail
  while lexical order remains free to change.
- Documentation and packaging proof: 22 focused documentation/policy tests,
  DOM-15 fixtures, plan-index validation, documentation path validation (49
  sources and 999 claims), coalescing validation, both lock checks, all four
  wheel/sdist builds, release dry-run, and `git diff --check` passed.
- Independent completed-work review returned PASS with no P1/P2 findings. It
  specifically checked behavior-sensitive cleanup, every approved suppression
  group, the large MCP stdio test reindent, and the export-set correction.
- Concurrent out-of-scope state: root `pyproject.toml` also contains the
  owner's SimpleBroker 6.0.1 floor edit, and the Summon/MCP locks were refreshed
  to that floor by verification. The targeted Ruff landing excludes the floor
  hunk and both lockfiles; the owner requested them as a separate commit.
