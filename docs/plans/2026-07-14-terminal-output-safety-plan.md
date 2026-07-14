# Terminal Output Safety Plan

Date: 2026-07-14

Status: implemented and verified. Independent plan and implementation reviews
approved. The repository owner authorized inclusion in 0.6.4 on 2026-07-14;
the ordinary exact-tree release gates remain the publication boundary.

Plan type: implementation with spec revision.

Owner: the implementing engineer owns the spec-promotion slice, the public
terminal-text utility, package-data loading, core and first-party extension
renderer integration, adversarial verification, and documentation
reconciliation. Extension authors own any additional or replacement patterns
they opt into through the public function.

## 1. Goal

Make Taut's human-readable terminal output safe by default when a trusted
participant accidentally relays untrusted text, such as text copied from a web
page after prompt injection. Add one typed, public `taut.escape_terminal_text`
function, drive its default regex policy from a packaged `taut/defaults.toml`,
and route core human rendering through that function without changing stored
content, Python API values, or JSON output.

This is a defense-in-depth safety control. It is not authentication, content
validation, or a new sandbox boundary. Taut's filesystem/database trust model
in [TAUT-9] remains unchanged.

## 2. Requested Outcomes

- Human output does not emit raw C0 controls, DEL, or C1 controls under the
  shipped default policy.
- OSC title-setting, OSC 52 clipboard, CSI, BEL, carriage return, backspace,
  tab, newline, and their 8-bit C1 introducers render as visible ASCII escapes.
- Exact text remains unchanged in broker storage, `Message` and `Notification`
  objects, and NDJSON output.
- `taut.escape_terminal_text` is a typed, lazy root-package export available to
  embedding callers and extension implementations.
- `taut/defaults.toml` is the single shipped source of default escape regexes
  and is present in source distributions and installed wheels.
- Callers may add regexes, replace the defaults, or explicitly disable them.
  That configurability is consistent with Taut's stated trust boundary.
- Core and first-party command renderers use one shared function and do not
  grow a second sanitizer or a mutable registration system.
- Taut-owned text diagnostics from the standalone Summon CLI and non-interactive
  driver logging use the same function. Intentional raw PTY byte forwarding is
  documented and remains byte-transparent.
- The implementation remains standard-library-only and handles a maximum-size
  10 MB message without an accidental quadratic path.

## 3. Source Documents

Source specs:

- `docs/specs/02-taut-core.md` [TAUT-3.2], [TAUT-6.3], [TAUT-6.4],
  [TAUT-8.2], [TAUT-8.3], [TAUT-8.6], [TAUT-9]
- `docs/specs/03-identity-addressing-notifications.md` [IAN-7.2], [IAN-7.4]
- `docs/specs/04-summon.md` [SUM-2], [SUM-3], [SUM-7.4], [SUM-13]
- `docs/specs/01-development-documentation-operating-model.md` [DOM-4],
  [DOM-5], [DOM-6], [DOM-8], [DOM-10], [DOM-11]

Implementation and product context:

- `README.md`, especially "Why is every message a little JSON envelope?" and
  "Why no auth, signing, or encryption?"
- `docs/implementation/04-taut-architecture.md`
- `docs/implementation/06-command-extensions.md`
- `taut/commands/_rendering.py`
- `taut/commands/_dispatch.py`
- `taut/__init__.py`
- `extensions/taut_summon/taut_summon/commands/`
- `pyproject.toml`

Required process guidance:

- `AGENTS.md`
- `docs/agent-context/decision-hierarchy.md`
- `docs/agent-context/engineering-principles.md`
- `docs/agent-context/runbooks/writing-plans.md`
- `docs/agent-context/runbooks/hardening-plans.md`
- `docs/agent-context/runbooks/testing-patterns.md`
- `docs/agent-context/runbooks/adversarial-acceptance-probes.md`
- `docs/agent-context/runbooks/maintaining-traceability.md`
- `docs/lessons.md`

No new runtime dependency is approved. Use `importlib.resources`, `re`, and
`tomllib` from Python 3.11's standard library.

## 4. Spec Baseline

- `ce2bbb1ddd5f416e30ae93d76c49cea301648551` is the committed baseline for
  the governing specs, implementation notes, source, and tests after the plan's
  independent review. Authoring began at `d12adcf`; the unrelated universal
  release-gates work landed as `ce2bbb1` during review. Its [TAUT-13] and release
  documentation changes were re-read and do not alter this plan's [TAUT-6],
  [TAUT-8], or [TAUT-9] decisions.
- The remaining worktree changes are this untracked plan and its additive entry
  in `docs/plans/README.md`.
- This plan revises intended behavior. The committed specs govern until the
  spec-promotion slice applies the reviewed delta.
- Promotion strategy: **A, active requirement text before implementation-link
  claims**. Promote the safety-control and public-API text first without
  claiming implementation links. Add reciprocal implementation mappings only
  with the code and tests that satisfy them. Do not reclassify the active spec.
- Promotion baseline: `ce2bbb1ddd5f416e30ae93d76c49cea301648551` plus the
  uncommitted diff limited to `docs/specs/02-taut-core.md` and
  `docs/specs/04-summon.md`, inspectable with
  `git diff ce2bbb1 -- docs/specs/02-taut-core.md docs/specs/04-summon.md`.

## 5. Scope and Threat-Model Decision

The initiating scenario is a trusted local agent that reads untrusted content
and then echoes it through Taut. Raw terminal controls may then reach the human
operator's terminal. Safe defaults reduce that accidental relay risk.

This plan does not treat another Taut participant as an attacker outside the
documented boundary. [TAUT-9] says that a participant with storage access can
already alter Taut state directly. An external tool sandbox that grants only
`taut say` is a stronger boundary owned by that sandbox, not a guarantee Taut
currently makes. Therefore:

1. the default policy is safe and is used by all core human renderers;
2. storage and machine-readable output retain exact content;
3. trusted callers may explicitly replace or disable the policy; and
4. documentation must call the feature a safety control, not an authentication
   control, input validator, malware filter, prompt-injection defense, or shell
   sandbox.

The safety boundary is Taut-owned **text rendering**. It excludes the explicit
terminal lease in `taut_summon.interaction` and the raw PTY byte bridge in
`taut_summon._pty`. Attached terminal applications require byte-transparent
terminal semantics; applying text escaping there would corrupt the hosted
terminal. Documentation and tests must state that an attached PTY can still
emit terminal controls by design.

### 5.1 Configuration boundary

Create `taut/defaults.toml` as packaged, versioned baseline data and let humans
customize the effective CLI policy through the existing `.taut.toml`. Taut owns
the optional `[terminal_text]` table; SimpleBroker continues to own and validate
the root storage keys and ignores the presentation table.

The public and project precedence is:

| Call/config state | Effective patterns |
|---|---|
| public `inherit_defaults=False` | `additional_patterns` only; no CWD discovery or packaged-resource access |
| inherited call, no project section | packaged + public additions |
| project `inherit_defaults=true` | packaged + project + public additions |
| project `inherit_defaults=false` | project + public additions |
| project false, empty list, no public additions | pass-through |

Presentation discovery resolves the process CWD, walks to the filesystem root,
and uses the nearest `.taut.toml`. It deliberately has no artificial depth cap.
It ignores `.taut.db`, `.broker.toml`, backend selectors, and `BROKER_*` path
variables. `--db`, `TAUT_DB`, and API `db_path=` select storage independently;
they neither relocate nor suppress the CWD presentation policy. This is a
separate, explicit contract because SimpleBroker does not export its config-file
finder without also resolving a backend.

Discovery runs on every inherited call so edits, deletion, and a newly created
nearer file take effect on the next call. Parsed policy uses a bounded cache
keyed by path, device, inode, modification timestamp, and size. A malformed
ambient policy fails with the fixed bootstrap diagnostic. Explicit public
replacement skips ambient and packaged policy entirely.

### 5.2 Client and extension boundary

Do not add rendering methods to `TautClient`. The client owns exact domain
values; it must not mutate message text for display. The public root-package
function is the embedding and extension seam:

```python
from taut import escape_terminal_text
```

Core command rendering and first-party command extensions call that same
function. `taut.commands` remains the command-protocol surface; it must not
duplicate or wrap the terminal utility under a second public import path.

## 6. Current Context and Key Files

### 6.1 Current data and rendering path

- `taut/client/_messaging.py` stores exact message text in a JSON envelope.
- `taut/envelope.py` decodes an envelope's `from` and `text` fields as strings;
  a raw foreign body remains arbitrary text.
- `taut/client/_codec.py` decodes notification actor, thread, warning, and raw
  fields without terminal escaping. This is correct for the domain layer.
- `taut/commands/_rendering.py` owns shared core human and JSON rendering.
  Human paths currently write interpolated values directly to the supplied
  stream. JSON uses `json.dumps` and must remain exact after parsing.
- `log`, `read`, and `watch` converge on `emit_messages`; `inbox` and
  notification watch items converge on `emit_notifications`; `who` and
  `whoami` converge on `emit_members`.
- `taut/commands/_dispatch.py` owns unexpected and extension-command error
  rendering outside `_rendering.py`.
- `taut/commands/_protocol.py` lets argparse render dynamic usage errors that
  can quote caller argv.
- `_write_root_help` renders installed command summaries and discovery
  diagnostics; selected-command load errors render distribution, entry-point,
  implementation, and exception values.
- first-party Summon adapters write a small number of human result and warning
  lines directly through `CommandContext` streams.
- the standalone `taut-summon` CLI prints dynamic member, session, status,
  error, and database values through ambient streams.
- non-interactive Summon driver mode logs raw assistant text to its configured
  error stream. Interactive mode separately forwards PTY bytes through
  `os.write`; that byte bridge is an intentional exemption.
- the temporary 0.5.4 Summon compatibility command redirects legacy Python
  text output into core streams but cannot require the old extension to import
  the new helper. Its redirected text needs a core-owned line-buffering escape
  proxy; raw PTY fd writes continue to bypass that proxy intentionally.

### 6.2 Public and packaging path

- `taut/__init__.py` provides lazy public exports. `escape_terminal_text` must
  use the same lazy map so `import taut` retains its current import floor.
- `tests/test_public_api.py` asserts the exact root `__all__` contract.
- `pyproject.toml` currently includes Python files and `py.typed`, but no TOML
  package resource. The build include list must name `taut/defaults.toml`.
- installed-wheel tests and release artifact checks must prove the function can
  load the real packaged resource without a source checkout.

### 6.3 Required reading comprehension gate

Before editing, the implementer must answer these in the plan execution log:

1. Why must storage, client objects, and JSON preserve exact controls while
   human rendering escapes them?
2. Which human commands converge on each shared renderer, and which dynamic
   writes still occur in protocol, dispatch, standalone Summon, driver logging,
   and the legacy compatibility bridge outside `_rendering.py`?
3. Why is `TautClient` the wrong owner for a presentation transform?
4. Why does [TAUT-9] permit an explicit caller to disable the defaults while
   still making safe defaults worthwhile?
5. How will the built wheel locate `taut/defaults.toml` without using the
   repository path or current working directory?
6. Which newline is content and must be escaped, and which newline is renderer
   structure and must be appended after escaping?
7. Why must every regex inspect the original input and why must overlapping
   match spans be merged before writing, instead of feeding generated escape
   text through later regexes?
8. Why are Taut-owned text logs escaped while raw PTY transport is explicitly
   byte-transparent?
9. Which fixed bootstrap diagnostic is safe when packaged or discovered project
   policy cannot load, and why must that path not call the public helper again?

If any answer is uncertain, stop and read the cited code and tests before
writing a failing test.

## 7. Proposed Public Interface and Default Schema

Public owner module: `taut/terminal.py`.

Lazy root export: `taut.escape_terminal_text`.

```python
def escape_terminal_text(
    text: str,
    *,
    additional_patterns: Iterable[str] = (),
    inherit_defaults: bool = True,
) -> str:
    """Return text with regex-selected code points rendered as visible escapes."""
```

Contract:

- `text` is not stored or mutated in place; the function returns a string.
- With no keyword arguments, patterns come from packaged defaults plus the
  nearest CWD project's optional policy.
- Additional patterns are appended in caller order after the effective project
  policy.
- With `inherit_defaults=False`, only `additional_patterns` apply; neither CWD
  discovery nor packaged-resource loading occurs.
- With `inherit_defaults=False` and an empty iterable, return `text` unchanged.
- A bare `str` is not a valid `additional_patterns` iterable; reject it with
  `TypeError` so it cannot become one regex per character. Reject every
  non-string iterable element with `TypeError`. Materialize and compile all
  caller patterns before scanning text so validation failure cannot produce a
  partial result.
- Compile each regex independently so inline flags, groups, and backreferences
  keep their ordinary Python `re` meaning. Run each matcher against the
  original input. Keep at most one live span per matcher in an
  O(number-of-patterns) merge heap, stream-merge overlapping spans, and escape
  the union once into an output buffer. Generated escape text is never
  reconsidered by a later rule.
- Every non-empty regex match is converted code point by code point. Use the
  familiar short escapes `\\a`, `\\b`, `\\t`, `\\n`, `\\v`, `\\f`, and
  `\\r`; use `\\xhh` through U+00FF, `\\uhhhh` through U+FFFF, and
  `\\Uhhhhhhhh` above U+FFFF, with lowercase hexadecimal digits.
- The replacement alphabet is printable ASCII. The function never copies a
  matched control code point into its result.
- Reject an invalid regex with `ValueError`. If a compiled matcher yields an
  empty span for the supplied input, reject that render call with `ValueError`.
  Categorical proof that a regex can never match empty is not required. Do not
  silently omit the rule or fall back to raw output.
- A malformed or missing packaged `defaults.toml`, or a discovered project
  policy with TOML, I/O, type, invalid-regex, or data-dependent empty-match
  failure, raises `RuntimeError` with one fixed printable-ASCII message that
  does not include parser or filesystem details. Callers emit that fixed
  message without calling the failed policy again. No extension imports a
  private core exception type. Do not carry a hard-coded fallback rule list.
  Core dispatch preserves [TAUT-3.2]'s malformed-file diagnostic with the
  static ASCII message `invalid .taut.toml: terminal output policy is
  unavailable`; it includes no dynamic path or parser text.
- Default and file-identity-keyed project policy may be cached. Caller-supplied pattern compilation
  may be cached only by an immutable tuple key and must not create an unbounded
  process-global registry.
- The function is a display transform, not a reversible wire encoding.

`taut/defaults.toml` begins with this exact schema:

```toml
[terminal_text]
escape_patterns = [
  '[\x00-\x1f]+',
  '[\x7f-\x9f]+',
]
```

The optional `.taut.toml` table is:

```toml
[terminal_text]
inherit_defaults = true
escape_patterns = []
```

An absent section means packaged defaults. In a present section, the boolean
defaults to `true`, the pattern list defaults to empty, and unknown keys are
ignored. A normal project-discovered command still needs valid SimpleBroker
root keys (`version`, `backend`, and `target`); a terminal-only table is not a
complete project config.

The first pattern covers all C0 controls, including LF and ESC. The second
covers DEL and all C1 controls. Keeping them separate makes the intended sets
reviewable. The `+` groups common runs, while independent compiled matchers and
a streaming span merge keep the maximum-size path linear for the shipped
two-rule policy without changing caller regex semantics.

Do not add replacement templates, named policy profiles, plugin registration,
environment variables, a new config filename, or a generic application-config
framework in this slice.

## 8. Invariants and Constraints

1. **Exact data invariant:** broker envelopes, sidecar state, `Message`,
   `Notification`, `Member.persona`, and parsed NDJSON preserve the exact input.
2. **Human default invariant:** absent an explicit trusted project/caller
   override, core human output never emits raw U+0000 through U+001F, U+007F,
   or U+0080 through U+009F from dynamic content. Renderer-owned structural LF
   is appended only after escaping the record body.
3. **One-function invariant:** core and first-party extension code import the
   public function; there is no private copy, second regex list, or per-command
   sanitizer.
4. **Trust-model invariant:** docs do not claim malicious participants, storage
   editors, or installed extensions are contained by this feature.
5. **Configurability invariant:** defaults are safe, but trusted humans through
   `.taut.toml` and trusted callers through the public function can extend,
   replace, or disable them explicitly.
6. **No hidden fallback invariant:** packaged config failure is loud. Rendering
   must not continue with raw dynamic text after policy-load failure. Its fixed
   bootstrap diagnostic must not invoke the failed policy recursively.
7. **Original-input invariant:** every regex sees only the original input;
   overlapping match spans are unioned, and generated escape output is not
   recursively filtered.
8. **Stream invariant:** all commands continue using injected `TextIO` streams;
   no helper reaches for ambient `sys.stdout` or `sys.stderr`.
9. **Lazy import invariant:** `import taut` and `taut --version` retain current
   subsystem import floors. The defaults file is loaded only on first use.
10. **Dependency invariant:** no runtime dependency is added.
11. **Performance invariant:** the shipped two-rule policy processes a 10 MB
    printable body and a 10 MB control-heavy body in O(input size plus output
    size). Do not implement a Python-level pattern-by-pattern test for every
    character or retain every match span in an unbounded list.
12. **Human-layout invariant:** alignment widths use escaped sender values, so
    a forged sender containing controls cannot distort following columns.
13. **Failure priority:** invalid trusted configuration is fatal to that render
    operation and produces a concise diagnostic. A successful storage operation
    must not be rolled back because later rendering fails.
14. **No one-way door:** no storage, envelope, notification, or command protocol
    changes are permitted.
15. **PTY exemption:** raw PTY transport stays byte-transparent and is named in
    docs and architecture tests; it is not a Taut-owned text-rendering sink.
16. **Version-floor invariant:** once `taut-summon` imports the new core export,
    its package metadata requires the exact first core version that contains
    the export, and wheel-matrix tests reject an older pairing.

Stop and return for review if implementation requires a new dependency,
changes stored data, adds `.taut.toml` policy, introduces a mutable registry,
or cannot keep source, sdist-built, and installed-wheel behavior identical.

## 9. Rollout and Rollback

Rollout is one coordinated core and Summon release:

1. promote the reviewed spec text without premature implementation mappings;
2. land the public utility, defaults resource, and tests;
3. route core and first-party extension human output through it;
4. raise the Summon core floor and add source, sdist-built, installed-wheel, and
   prior-core rejection evidence;
5. add reciprocal spec/implementation mappings;
6. release only after the ordinary root and Summon gates pass.

Old extensions remain compatible because no existing command or client
interface is removed. The first Taut Summon version that imports
`escape_terminal_text`, and every later extension that uses it, must declare a
Taut version floor containing the export.

Rollback is a code/spec revert. Stored messages need no migration because their
bytes never change. Revert renderer integration, the public export, defaults
resource, tests, and promoted spec wording together. A partial rollback that
removes `defaults.toml` while leaving the public function is invalid and must be
caught by sdist and installed-wheel tests. Roll back the coordinated Summon
import and dependency floor with the core revert; do not leave new Summon code
installable beside a core that lacks the export.

## 10. Proposed Spec Delta

Promotion strategy: **A, in-file active text before implementation-link
claims**.

| Spec file | Strategy | Sections touched |
|-----------|----------|------------------|
| `docs/specs/02-taut-core.md` | A | [TAUT-6.4], [TAUT-8.3], [TAUT-8.6], [TAUT-9] |
| `docs/specs/04-summon.md` | A | [SUM-3], [SUM-7.4], [SUM-13] |

### [TAUT-6.4] replace the current Limits paragraph

> Body size and content limits are SimpleBroker's (10 MB default). Taut adds
> no storage limit of its own; `text` is arbitrary UTF-8 including newlines and
> terminal control characters. Storage, Python API objects, and `--json` output
> preserve that exact content.
>
> Human-readable terminal output is a separate presentation boundary. By
> default, each Taut-owned dynamic text field is passed through the public
> `taut.escape_terminal_text` function before it is composed with trusted
> structural formatting. Renderer-owned line endings are appended only after
> the dynamic field or single-line record body is escaped. The function loads
> its default regex list from the packaged `taut/defaults.toml`. The shipped
> policy selects all C0 controls, DEL, and all C1 controls and renders every
> selected code point as a visible printable-ASCII escape. This includes
> content LF, ESC, CSI/OSC introducers, BEL, carriage return, backspace, tab,
> and their C1 forms. Selected BEL, backspace, tab, LF, vertical tab, form feed,
> and carriage return use `\a`, `\b`, `\t`, `\n`, `\v`, `\f`, and `\r`;
> other selected code points use `\xhh` through U+00FF, `\uhhhh` through
> U+FFFF, and `\Uhhhhhhhh` above U+FFFF, with lowercase hexadecimal digits.
>
> In inherited mode, the public function loads packaged defaults and the
> nearest CWD `.taut.toml` `[terminal_text]` policy. The project table may
> append, replace, or disable patterns. `--db`, `TAUT_DB`, and `db_path=` do
> not alter presentation discovery. Public `additional_patterns` append after
> the effective project policy; public `inherit_defaults=False` bypasses both
> project discovery and packaged-resource access. Every regex operates on the
> original input; overlapping match spans are combined and generated escape
> text is not filtered again. An invalid regex or a matcher that yields an empty
> span from explicit caller input raises `ValueError`; the equivalent ambient
> policy failure raises the fixed `RuntimeError`. A bare string passed as the
> pattern iterable, or any non-string pattern element, raises `TypeError`.
> A missing, malformed, wrong-shaped, or invalid-regex packaged policy raises
> `RuntimeError("terminal output policy is unavailable")`; Taut-owned renderers
> emit that fixed printable-ASCII diagnostic without recursively calling the
> failed policy or silently falling back to raw output.
>
> This is a defense-in-depth output-safety control for accidentally relayed
> untrusted content. It does not authenticate participants, validate message
> meaning, prevent prompt injection, or change the [TAUT-9] trust boundary.
> `--json` remains the machine-consumer path and is never passed through the
> human display transform. Taut-owned command text, diagnostics, and
> non-interactive first-party extension logging use the transform. An explicit
> Summon terminal lease and its raw PTY byte bridge are exempt: attached
> terminal applications retain byte-transparent terminal semantics and may
> emit controls by design. The temporary previous-version Summon compatibility
> bridge can escape non-LF controls in redirected Python text, but it treats
> every LF already emitted by legacy code as a structural line terminator
> because the formatted stream no longer exposes content-field boundaries.

### [TAUT-8.3] insert after the root-package lazy-export paragraph

In the existing exhaustive public-export sentence, replace:

> `TautError`, and `__version__`.

with:

> `TautError`, `escape_terminal_text`, and `__version__`.

> `taut.escape_terminal_text(text: str, *, additional_patterns:
> Iterable[str] = (), inherit_defaults: bool = True) -> str` is the typed public
> terminal-display utility for embedding callers and extensions. Its owner is a
> lightweight core module, not `TautClient`, because client/domain values remain
> exact. In inherited mode, packaged defaults, project patterns, and explicit
> additions apply in that order. `inherit_defaults=False` bypasses both ambient
> and packaged policy; an empty explicit replacement is pass-through.
> Accessing the lazy root export may load only standard-library configuration and
> regex support; it must not import client, state, watcher, command-discovery,
> Summon, PTY, or TUI implementations. Its public failures are the `TypeError`,
> `ValueError`, and fixed-message `RuntimeError` cases defined by [TAUT-6.4].

### [TAUT-8.6] insert after the execution-context stream paragraph

> Core and first-party extension adapters pass dynamic human-output fields or
> single-line record bodies through `taut.escape_terminal_text` before composing
> trusted multi-line structure and appending structural line endings.
> Non-interactive first-party extension logs use the same utility. Third-party
> extensions use the public function when they want Taut's default output-safety
> policy. JSON records are serialized from the original domain values and never
> from escaped display text. Raw PTY byte transport is not a command text
> renderer and remains exempt under [TAUT-6.4].

### [TAUT-9] insert after the one-line threat model

> Terminal escaping under [TAUT-6.4] is a safety default inside this trust
> model, not a stronger trust boundary. It reduces accidental effects when a
> trusted participant relays untrusted content. It does not constrain a
> participant that can edit Taut storage, project files, installed code, or the
> caller-selected rendering policy. Project configuration may deliberately
> disable escaping or install an expensive regex and is therefore trusted.

### [SUM-3] insert after the two-console-surface paragraph

> Both first-party console surfaces use `taut.escape_terminal_text` for
> Taut-owned dynamic human text and diagnostics under [TAUT-6.4]. The temporary
> previous-version compatibility adapter applies the policy to redirected
> Python text on a line-buffered best-effort basis: incoming LF is a structural
> terminator because legacy formatted output no longer exposes content-field
> boundaries. JSON/domain values remain exact.

### [SUM-7.4] insert after the opening PTY-adapter paragraph

> The explicit host terminal lease and attach bridge forward PTY bytes
> unchanged. They are terminal transport, not Taut-owned text rendering, and
> are exempt from [TAUT-6.4]. Sanitizing this byte stream would corrupt the
> hosted terminal protocol.

### [SUM-13] insert after the opening controller paragraph

> Command and standalone-console adapters escape their Taut-owned dynamic human
> text through the core public utility. A host interaction's scoped terminal
> lease remains byte-transparent as specified by [SUM-7.4]; rich hosts must not
> assume attached PTY bytes have passed through the text-rendering safety
> policy.

## 11. Deviation Log

| Spec ref | Planned behavior | Actual behavior | Rationale | Spec proposal |
|----------|------------------|-----------------|-----------|---------------|
| n/a, plan Tasks 2-5 | Accumulate each task's red tests before its implementation task | Execute vertical one-test red-green tracer slices | The required TDD skill rejects horizontal test batches because they test imagined structure; all enumerated contract cases and task gates remain required | n/a, execution order only |
| n/a, plan Task 3 | Add `taut/defaults.toml` with the utility implementation | Add the reviewed defaults resource in the spec-promotion slice; loader/package behavior remains test-first | The documentation path gate rejects an active spec that names a nonexistent package resource. Creating declarative policy data keeps promotion green without implementing the public behavior | n/a, execution order only |
| [TAUT-3.2], [TAUT-6.4], plan 5.1 | Limit extensibility to explicit Python calls; do not use `.taut.toml` | Add a human-owned `[terminal_text]` project policy with explicit precedence, CWD discovery, bounded freshness-aware caching, and storage-selector independence | User clarification showed that “extensible” must include ordinary CLI users, not only extension authors. The original scope argument was an implementation concern, not a sound product boundary | Promoted into the active core spec before completing implementation |

## 12. Dependency-Ordered Tasks

### Task 1: Promote the reviewed spec delta

- Files to touch: `docs/specs/02-taut-core.md`, `docs/specs/04-summon.md`.
- Add this plan under both specs' `## Related Plans` sections.
- Apply the exact text in section 10 using promotion strategy A. Do not add
  implementation mappings yet.
- Record the promotion baseline identifier in section 4.
- Verification: inspect the spec diff and run the repository documentation
  reference/traceability gate named by current release tooling.
- Done signal: the core and Summon governing contracts describe exact-data
  preservation, safe human defaults, trusted overrides, the public function,
  raw PTY exemption, and unchanged trust boundaries without contradiction.
- Stop if review requires a new security boundary or a config contract beyond
  the `[terminal_text]` schema and precedence defined here.

### Task 2: Add failing public-utility and package-resource tests

- Files to add: `tests/test_terminal_text.py`.
- Files to update: `tests/test_public_api.py`, `tests/test_lazy_imports.py`, and
  the narrow installed-wheel probe or checker already used by those tests.
- Write red tests before creating the module or defaults resource.
- Required firing cases:
  1. every C0 code point;
  2. DEL and every C1 code point;
  3. mnemonic and numeric escape spellings;
  4. ordinary ASCII, non-ASCII, emoji, and literal backslash text unchanged;
  5. empty text;
  6. OSC title, OSC 52, CSI, BEL, CR, backspace, tab, and content LF;
  7. additive patterns;
  8. `inherit_defaults=False` replacement and empty pass-through;
  9. overlapping-rule union and generated-output non-recursion;
  10. invalid regex, bare-string iterable, non-string element, and supplied-
      input empty-match rejection;
  11. compilation of every rule before scanning or returning a result;
  12. missing, malformed, wrong-type, and missing-key packaged config failures;
  13. fixed bootstrap diagnostic on policy-load failure, with exit 1 and no
      traceback or recursive policy call;
  14. the malformed-policy path through the Summon logging formatter with
      `logging.raiseExceptions=True`, proving no logging `handleError` traceback;
  15. exact root export, lazy import floor, source-tree resource load, and
      isolated installed-wheel resource load.
  16. complete project-policy precedence, missing/defaulted/unknown keys,
      wrong types, invalid and data-dependent zero-width project regexes;
  17. edit/deletion/nearer-file freshness, bounded cache, nearest-parent and
      no-artificial-depth-cap discovery, `.broker.toml`/`.taut.db` exclusion;
  18. explicit API replacement bypassing malformed ambient and packaged
      policy, plus `--db`/`TAUT_DB` storage-selector independence.
- The real `taut/defaults.toml` must stay real in the main tests. Limited
  temporary-package resources may be injected only for malformed-resource
  error cases; do not mock the successful loader.
- Verification: run the focused files and record the expected red failures.
- Done signal: failures name the missing public function, resource, behavior,
  and wheel data rather than failing for unrelated fixture setup.

### Task 3: Implement the lightweight public utility and defaults resource

- Files to add: `taut/terminal.py`, `taut/defaults.toml`.
- Files to update: `taut/__init__.py`, `pyproject.toml`.
- Use `importlib.resources.files("taut")` and `tomllib`; never resolve the
  resource relative to `cwd` or `__file__` outside the package-resource API.
- Compile rules independently, enumerate non-empty matches against the original
  input, retain at most one live span per matcher, and stream-merge overlapping
  spans before rebuilding output once. Reject zero-length matches before
  returning. Do not concatenate caller regex source into one alternation because
  that changes inline-flag, group, and backreference semantics.
- Make policy-load `RuntimeError` carry one fixed printable-ASCII message. Core
  and extension callers catch `RuntimeError` only around the public helper call
  and may write that fixed message directly; no extension imports a private
  core exception type. This is the only bootstrap-safe exception to the common
  helper.
- Keep the owner module independent from `taut.client`, SimpleBroker,
  `taut.commands`, watcher, and extensions.
- Implement presentation discovery with `pathlib` only: resolve CWD, walk to
  filesystem root, and choose the nearest `.taut.toml`. Do not import a private
  SimpleBroker finder. Re-discover each inherited call and cache parsed policy
  with the bounded file-identity key from section 5.1.
- Include `/taut/**/*.toml` or the exact `/taut/defaults.toml` resource in the
  Hatch build configuration. Prefer the exact file while it is the only TOML
  resource.
- Verification: run the Task 2 tests; build a wheel; inspect the archive for
  `taut/defaults.toml`; run the installed-wheel probe outside the checkout.
- Done signal: the public utility is green in source and installed-wheel use,
  and `import taut` remains lazy.
- Stop if an implementation needs a third-party regex/TOML package, a mutable
  registry, or a hard-coded fallback list.

### Task 4: Add failing human-renderer regression and acceptance tests

- Files to update: `tests/test_cli.py`, `tests/test_command_registry.py`,
  `tests/test_architecture_boundaries.py`, and the smallest relevant Summon
  command, standalone CLI, driver-logging, and compatibility-bridge test files.
- Use real `TautClient`, real SQLite queues, actual command dispatch, and
  captured pipe/StringIO streams. Never attach hostile probe output to a live
  terminal.
- Cover these distinct source and sink pairs:
  1. normal `taut say` text rendered by `log`, `read`, and live `watch`;
  2. forged envelope sender and text;
  3. foreign broker message body;
  4. known notification actor and thread;
  5. foreign notification raw body;
  6. member persona in `who` and `whoami`;
  7. database target, created identity, identity candidates, explain details,
     thread display labels, unread/list rows, and rename output;
  8. argparse errors containing caller argv;
  9. installed command summaries, registry diagnostics, selected-command load
     diagnostics, dynamic warnings, and execution errors;
  10. first-party Summon command result/warning text;
  11. standalone `taut-summon` member, session, status, detail, database, and
      operation-error text;
  12. non-interactive driver logging of assistant text;
  13. legacy compatibility-bridge Python text output.
- Prove that content LF renders visibly and cannot create an extra physical
  message row. Allow only renderer-owned structural LF in captured output.
- Parse JSON and assert exact original values for representative message,
  notification, foreign, and persona cases.
- Include a capture-level OSC 52/title/CSI probe and scan output for literal
  ESC, BEL, C1, CR, backspace, and tab.
- Add a raw-PTY exemption test proving bytes written through the explicit
  terminal lease remain byte-identical. That test is an exemption proof, not a
  claim that attached PTY output is sanitized.
- Verification: run the focused tests and record their expected red failures.
- Done signal: tests fail at the current direct-write seams and not because the
  control-bearing probe reached a terminal.

### Task 5: Route human output through one shared escape seam

- Files to update: `taut/commands/_rendering.py`,
  `taut/commands/_dispatch.py`, `taut/commands/_protocol.py`,
  `taut/commands/_summon_compat.py`,
  `extensions/taut_summon/taut_summon/cli.py`, relevant files under
  `extensions/taut_summon/taut_summon/commands/`, and the narrow Summon logging
  configuration owner.
- Add one private core line writer that escapes a complete record body and then
  appends the renderer's structural newline. Make human writes in
  `_rendering.py` converge on it; keep `write_json` separate and exact.
- Use the public `taut.escape_terminal_text` implementation, not a private
  wrapper with its own patterns.
- Escape sender values before calculating display width. Do not compute column
  width from raw control-bearing strings and escape only afterward.
- Escape dynamic fields before composing trusted multi-line usage/help
  structure. Do not pass an assembled multi-line diagnostic through the helper,
  because that would turn renderer-owned structural LF into content escapes.
- Route argparse, registry, selected-command, and execution-error dynamic fields
  through the public function. Static usage/help grammar may remain direct.
- Update first-party Summon command adapters, standalone CLI printers, and
  non-interactive logging. Use a formatter or handler that escapes the final
  dynamic log message while preserving trusted timestamp/logger/level framing.
  The formatter/handler itself must catch policy-load `RuntimeError` and return
  the fixed bootstrap diagnostic; do not let Python logging call `handleError`
  and emit its own traceback. Do not add a Summon-specific regex list.
- Give the legacy compatibility bridge a core-owned line-buffering text proxy
  with this exact terminator rule: buffer text until LF, escape the preceding
  segment, then re-emit one structural LF; on `flush()` or bridge exit, escape
  and emit any unterminated suffix. Because legacy formatted output has already
  lost field boundaries, an incoming LF is always treated as structure and
  cannot be promised as a visible content `\\n`. Raw fd-based PTY writes
  intentionally bypass the proxy.
- Add a required architecture/source gate that inventories first-party `.write`,
  `print`, argparse-error, and logging sinks. Its explicit allowlist may contain
  JSON serialization, trusted static structure, the common escaped writers, the
  fixed policy-bootstrap diagnostic, and the raw PTY byte bridge. New dynamic
  text sinks must fail until routed or explicitly reviewed.
- Verification: run Task 4 tests, then all core CLI and command-registry tests
  and the touched Summon test file.
- Done signal: all listed surfaces are green, JSON remains exact, and a source
  scan finds no second control-character regex list.
- Stop if a surface cannot use the common function without changing its public
  output shape beyond visible escaping.

### Task 6: Apply adversarial size and performance probes

- Files to update: `tests/test_terminal_text.py`; add a slow marker only if the
  ordinary suite cannot carry the maximum-size case within its budget.
- Exercise:
  1. a 10 MB printable body with no matches;
  2. a 10 MB control-heavy body whose escaped output expands substantially;
  3. alternating matched and unmatched code points;
  4. an extension regex that matches a multi-code-point substring;
  5. overlapping extension regexes whose matched span union is escaped once;
  6. a zero-width lookaround rejected without any output write.
- Assert exact output and completion under the repository's existing test
  timeout. Do not add a brittle sub-second wall-clock threshold. Record an
  informational local timing for the two 10 MB probes so later regressions have
  a baseline.
- Done signal: maximum valid input is linear in observed behavior and does not
  allocate per-character regex objects, run a Python-level pattern loop, or
  retain millions of match-span tuples. The merge holds at most one live span
  per matcher plus output proportional to the returned string.
- Stop if the default 10 MB case approaches the test timeout or memory use is
  an uncontrolled multiple of required output size.

### Task 7: Align the first-party extension floor and prove both artifacts

- Files to update: `extensions/taut_summon/pyproject.toml`, root
  `pyproject.toml`, `uv.lock`, `CHANGELOG.md`,
  `tests/test_project_metadata_consistency.py`,
  `tests/test_core_summon_wheel_matrix.py`, and release metadata/checker tests
  that encode the paired floor.
- Determine the coordinated patch version from current metadata immediately
  before this task. If the released/current version remains 0.6.2, the feature
  version is 0.6.3. If another release landed first, use the next patch version
  and record the new baseline rather than reusing 0.6.3.
- Raise `taut-summon`'s `taut>=...` dependency to the exact first core version
  that exports `escape_terminal_text`. Raise the root development Summon floor
  and regenerate the lock consistently.
- Extend the existing wheel-matrix resolver proof so the new Summon paired with
  the immediately prior core is rejected, while the coordinated pair installs
  and runs the public helper path.
- Build both wheel and sdist. Inspect both archives for `taut/defaults.toml`.
  Extract the sdist outside the checkout, build its wheel, install that wheel in
  an isolated environment, and run the same resource/function probe. Direct
  source-tree and direct-wheel success do not substitute for the sdist proof.
- Update the changelog with the safety-control, public API, config resource,
  exact-data preservation, trust-boundary qualification, and Summon floor.
- No tag, push, publication, or release is authorized by this plan.
- Done signal: old-core/new-Summon resolution fails for the intended floor,
  coordinated artifacts pass, and both published artifact forms carry a usable
  defaults resource.
- Stop if version preparation conflicts with another in-flight coordinated
  release; rebase the metadata task and its exact floor before continuing.

### Task 8: Align documentation, extension guidance, and traceability

- Files to update: `README.md`, `docs/implementation/04-taut-architecture.md`,
  `docs/implementation/06-command-extensions.md`,
  `docs/specs/02-taut-core.md`, `docs/plans/README.md`, and this plan.
- README must explain that exact stored/JSON content and safe human display are
  separate, and that the safety default does not change the filesystem/database
  trust model.
- Architecture docs must name `taut/terminal.py` as the presentation utility,
  `taut/defaults.toml` as the default policy owner, and
  `_rendering.py` as the core integration seam.
- Extension docs must show the public import and explain extension/replacement
  arguments. State that extension patterns are trusted policy and can cause bad
  rendering or poor performance if written badly.
- Add implementation mappings and reciprocal backlinks only now that the code
  and tests exist. Update the repository map if its file inventory requires the
  new public module/resource.
- Evaluate whether implementation exposed a durable lesson. Record one only if
  it generalizes beyond this change.
- Done signal: a zero-context extension author can use the helper without
  importing private modules or misunderstanding it as a sandbox.

### Task 9: Run final verification and independent implementation review

- Run the focused safety, CLI, public API, command registry, lazy import,
  architecture, and Summon suites.
- Run root ruff, formatting check, mypy, documentation reference/traceability,
  packaging, and installed-wheel gates through the current canonical release
  command rather than inventing parallel commands.
- Run a final captured-output probe containing OSC title, OSC 52, CSI, BEL,
  C0, DEL, C1, embedded LF, a forged sender, a foreign message, a foreign
  notification, and persona text. Record bytes/repr only; never print raw probe
  output to a terminal.
- Have a separate reviewer inspect the final diff against promoted [TAUT-6.4],
  [TAUT-8.3], [TAUT-8.6], and [TAUT-9], with special attention to missed human
  sinks and accidental JSON/storage mutation.
- Reconcile every review finding or record an explicit disposition. Re-run
  affected gates after corrections.
- Record changed files, exact commands, observed results, residual risks,
  promotion baseline, and deviation-log status.
- Do not claim ready to land until the user has authorized and the finished
  slice is committed; verify the commit with `git log`.

## 13. Testing Plan

Red-green TDD is mandatory for Tasks 2 through 5. No exception is planned.

### 13.1 Unit and public-contract proof

- `tests/test_terminal_text.py`: config loading, pattern semantics, escape
  spelling, error cases, extension/replacement behavior, one-pass behavior,
  maximum-size probes.
- `tests/test_public_api.py`: exact `__all__`, lazy root export, owning module,
  typing-visible object identity.
- `tests/test_lazy_imports.py`: importing/accessing the helper does not load
  client, state, watcher, command discovery, SimpleBroker, Summon, PTY, or TUI.

### 13.2 Real rendering proof

- `tests/test_cli.py`: real SQLite, real envelopes/notifications, real command
  dispatch, pipe/StringIO capture, exact JSON parseback.
- `tests/test_command_registry.py`: escaped dynamic command errors and public
  extension usage through injected streams.
- `tests/test_architecture_boundaries.py`: executable sink inventory, with raw
  PTY and fixed policy-bootstrap diagnostics as narrow named exceptions.
- touched Summon tests: command adapters, standalone CLI, non-interactive
  assistant logging, compatibility redirection, and raw-PTY exemption behavior.

Do not mock `escape_terminal_text`, `_rendering.py`, `TautClient`, queue writes,
or JSON serialization in the end-to-end proof. Mocking an installation resource
is permitted only for explicit malformed-resource unit tests.

### 13.3 Packaging proof

- Build and inspect the actual wheel and sdist for `taut/defaults.toml`.
- Install it into an isolated environment whose `cwd` is outside the checkout.
- Import `escape_terminal_text`, exercise default and replacement policies, and
  assert the loaded module/resource paths come from the installed environment.
- Extract the sdist outside the checkout, build a wheel from that extracted
  source, and repeat the isolated probe. This proves the sdist is usable, not
  merely that its tar member list contains the resource.
- Exercise the existing core/Summon resolver matrix with the new extension
  floor: new Summon plus prior core must fail, coordinated artifacts must pass.

### 13.4 Non-regression proof

- Existing plain human rendering stays unchanged for text not selected by the
  policy, except where raw content LF/tab/control behavior intentionally becomes
  visible escaping.
- Existing JSON fixtures and shapes remain byte/parse compatible except no
  intended JSON change should appear at all.
- Existing client, envelope, notification, watcher, and PostgreSQL behavior
  remain unchanged. The change is backend-independent and does not require a
  dedicated PostgreSQL behavior matrix.

## 14. Verification and Gates

Focused commands, adjusted only if the canonical runner changes before
implementation:

```text
uv run --extra dev pytest tests/test_terminal_text.py tests/test_public_api.py tests/test_lazy_imports.py -n 0 -q
uv run --extra dev pytest tests/test_cli.py tests/test_command_registry.py -n 0 -q
uv run --extra dev pytest extensions/taut_summon/tests/<touched-command-and-cli-tests>.py -n 0 -q
uv run --extra dev pytest tests/test_architecture_boundaries.py tests/test_docs_references.py -n 0 -q
uv run --extra dev pytest tests/test_project_metadata_consistency.py tests/test_core_summon_wheel_matrix.py -n 0 -q
uv run --extra dev ruff check taut tests extensions/taut_summon
uv run --extra dev ruff format --check taut tests extensions/taut_summon
uv run --extra dev mypy taut tests extensions/taut_summon/taut_summon extensions/taut_summon/tests
uv build
```

The implementer must replace the Summon placeholder with the exact touched test
files before execution. Use the current release precheck/build and paired
artifact commands for the final full gate; do not rely only on the illustrative
commands above. Record explicit wheel, sdist, and wheel-built-from-sdist probes.

Final success requires:

- all default C0/DEL/C1 contract elements have firing tests;
- all enumerated human source/sink pairs have firing tests;
- no raw hostile controls appear in captured human output;
- exact values survive storage, client objects, and parsed JSON;
- source and installed-wheel resource behavior match;
- the source distribution contains the resource and can build an independently
  working wheel;
- the first-party Summon floor rejects the prior core and accepts the
  coordinated core;
- maximum-size probes complete within existing timeout budgets;
- docs preserve the [TAUT-9] trust model and call this a safety control;
- spec mappings and reciprocal backlinks pass the repository traceability gate;
- independent review is incorporated or explicitly answered.

Post-release success signal: a captured `taut log`, `read`, `watch`, `inbox`,
and `who` probe shows visible escapes and no raw C0/DEL/C1 dynamic content,
while the paired `--json` probe parses back to the exact originals. No telemetry
or persistent logging is added for this feature.

## 15. Independent Review Loop

Plan review should use a separate agent from the authoring pass. The reviewer
must read:

- this entire plan, including `## Proposed Spec Delta`;
- `README.md` trust-boundary FAQs;
- `docs/specs/02-taut-core.md` [TAUT-6.4], [TAUT-8.2], [TAUT-8.3],
  [TAUT-8.6], and [TAUT-9];
- `taut/commands/_rendering.py`, `taut/commands/_dispatch.py`,
  `taut/commands/_protocol.py`, `taut/commands/_summon_compat.py`,
  `taut/__init__.py`, both package manifests, standalone Summon CLI and driver
  logging, the raw PTY bridge, and direct first-party extension writes.

Review prompt:

> Read the terminal output safety plan and its proposed spec delta. Examine the
> current code and trust model. Look for missed terminal sinks, accidental
> storage/JSON mutation, ambiguous config semantics, regex performance traps,
> packaging omissions, public API layering errors, or claims that turn a safety
> control into a security boundary. Do not implement anything. Could you
> implement this confidently and correctly after promotion? Return concrete
> blockers and lower-severity improvements separately.

The author must disposition each point by changing the plan, explaining why the
current design remains preferable, or marking it out of scope with reasons. Any
answer of "not confidently implementable" blocks implementation.

Implementation review repeats after the renderer-integration slice and before
completion, preferably with a different agent family from the implementer.

## 16. Out of Scope

- Message rejection, storage sanitization, envelope changes, or message-size
  changes.
- Authentication, authorization, signatures, encryption, sender attestation,
  or enforcement of an external tool sandbox.
- Prompt-injection detection or semantic content moderation.
- A new config filename, environment variable, CLI flag, named policy profile,
  polling watcher, or process-global plugin registry. Next-call file freshness
  is part of the contract; proactive filesystem watching is not.
- Terminal-emulator capability detection or per-terminal OSC allowlists.
- Escaping or altering bytes inside an explicit Summon terminal lease or raw PTY
  bridge. Those paths remain byte-transparent and are documented exceptions.
- HTML, Markdown, shell, SQL, log-forensics, bidi, homoglyph, or confusable-text
  sanitization beyond caller-added regexes.
- A reversible display encoding or changes to NDJSON's `ensure_ascii=False`.
- Refactoring unrelated renderer formatting, command architecture, watcher
  lifecycle, or backend code.

## 17. Fresh-Eyes Review Checklist

Before implementation starts, verify that a zero-context engineer can answer:

- what exact characters the default policy selects;
- how each selected code point appears;
- why content LF is escaped but structural LF is preserved;
- how humans and extensions add, replace, or disable patterns;
- why the policy belongs in `.taut.toml` but still not on `TautClient`;
- how source, sdist-built, and direct-wheel resource loading is proved;
- which human sinks must change and which JSON paths must not;
- why standalone text logging is covered while raw PTY bytes are exempt;
- how a policy-load failure reports itself without recursively calling the
  failed policy;
- how the 10 MB path avoids a Python pattern loop per character and an
  unbounded match-span list;
- why trusted configurability does not contradict safe defaults;
- how to roll back without a data migration.

If any answer requires inference outside the named files, tighten this plan
before code.

## 18. Plan Hardening Checklist

- [x] Invariants and non-goals are named before tasks.
- [x] Exact-data and human-rendering boundaries are separated.
- [x] Trust model and external prompt-injection scenario are explicit.
- [x] Core and extension paths share one public function.
- [x] Project and public config precedence, discovery, freshness, and
  extension/replacement semantics are explicit.
- [x] Stop-and-re-evaluate gates are included.
- [x] Anti-mocking guidance names the real seams.
- [x] Contract, adversarial, maximum-size, sdist, packaging, and installed-wheel
  tests are specified.
- [x] Fatal config failures and successful-storage/render-failure priority are
  explicit.
- [x] Rollout, rollback, observability, and lack of one-way doors are explicit.
- [x] Required reading includes comprehension questions.
- [x] Independent plan and implementation reviews are required.

## 19. Plan Review Record

Independent reviewer: `/root/terminal_plan_review`, 2026-07-14.

Initial verdict: not confidently implementable until four blockers were
resolved.

| Finding | Disposition |
|---------|-------------|
| Spec promised every dynamic record but the inventory omitted argparse, registry/help, additional core fields, standalone Summon, driver logs, compatibility output, and raw PTY semantics | Incorporated. Tasks and tests now enumerate Taut-owned text sinks; raw PTY transport is an explicit byte-transparent exemption. |
| Policy-load failure could recurse through the failed policy in generic error rendering | Incorporated. The helper raises `RuntimeError` with one fixed printable-ASCII message; callers catch it only around the helper, and the logging formatter handles it internally so `handleError` cannot emit a traceback. |
| First-party Summon would import a new core export without raising its core dependency floor | Incorporated. Task 7 owns the coordinated version floor, lock, changelog, and prior-core rejection matrix. |
| The requested sdist outcome had only wheel proof | Incorporated. Task 7 and section 13.3 require sdist archive inspection plus an isolated wheel build and function/resource probe from extracted sdist. |
| Bare-string/non-string pattern inputs and empty-match semantics were ambiguous | Incorporated with explicit `TypeError` rules and supplied-input empty-span semantics. |
| Span-merge memory bound was prose-only | Incorporated as one live span per matcher, O(pattern-count) merge state, and maximum-size evidence. |
| Direct sink architecture test was optional | Incorporated as a required executable sink inventory with narrow named exceptions. |
| Multi-line structural formatting could be escaped accidentally | Incorporated. Dynamic fields are escaped before trusted multi-line composition; structural LF is appended afterward. |
| Post-promotion review found [TAUT-8.3]'s exhaustive export list omitted the newly declared root function | Incorporated in both the plan delta and promoted spec before implementation completion. |

Post-disposition re-review: approved by `/root/terminal_plan_review` on
2026-07-14. The reviewer stated that the plan is confidently implementable
after the spec-promotion slice. Residual improvements were incorporated:

- corrected Summon references to [SUM-2], [SUM-3], [SUM-7.4], and [SUM-13],
  with exact proposed deltas and a required Summon-spec backlink;
- made logging policy failure bootstrap-safe inside the formatter/handler;
- removed any requirement for extensions to import a private core exception;
- specified the legacy bridge's LF terminator rule and limited its guarantee to
  best-effort line-buffered text escaping.

Human-config correction review: `/root/terminal_plan_review`, 2026-07-14.
The reviewer required the complete table schema, an exact precedence table,
CWD/storage-selector independence, explicit presentation discovery, distinct
ambient versus caller failures, and freshness-aware bounded caching. All six
points are incorporated in sections 5.1, 7, 8, 10, 12, 16, and 18 and in the
promoted [TAUT-3.2], [TAUT-6.4], [TAUT-8.3], and [TAUT-9] text.

Integrated implementation re-review: `/root/terminal_plan_review`,
2026-07-14. The first pass found three behavior defects: generated sender
escapes could be scanned a second time, a data-dependent policy failure in a
command summary could be mislabeled as an extension load failure, and a live
watch policy failure could enter the poison-message retry path. Each defect
received a failing test before its fix. Re-review approved all three fixes.
The reviewer then requested direct proof that a post-commit timestamp-render
failure does not roll back `say`; that firing test passes. A final author pass
also found and test-first fixed a redundant human-policy preflight in direct
`watch --json`. The reviewer inspected both final additions and approved the
implementation with no remaining blocker.

## 20. Implementation Execution Log

### 20.1 Required-reading comprehension gate

1. Storage, client models, and JSON preserve exact controls because they are
   domain/wire values. Only a human terminal renderer has the presentation
   context that justifies escaping.
2. `log`, `read`, and `watch` converge on `emit_messages`; `inbox` and watch
   notifications converge on `emit_notifications`; `who`/`whoami` converge on
   `emit_members`. Additional text sinks exist in argparse protocol errors,
   dispatcher help/errors, standalone Summon prints, Summon logging, and the
   previous-version compatibility redirect.
3. `TautClient` is the wrong owner because its API must return exact domain
   values independent of presentation. The lightweight root utility is shared
   by embedding and extension renderers without mutating client state.
4. [TAUT-9] trusts storage/project/install owners, so explicit replacement or
   disablement does not cross Taut's boundary. Safe defaults still reduce
   accidental relay of controls from untrusted content.
5. Installed code locates `taut/defaults.toml` through
   `importlib.resources.files("taut")`; source, direct wheel, and
   wheel-built-from-sdist probes must run outside the checkout.
6. LF inside a dynamic value is content and becomes visible `\\n`. A renderer
   appends its trusted structural LF only after escaping the field or one-line
   body. Legacy formatted output is the documented exception because field
   boundaries are already lost.
7. Each regex scans the original input. A bounded k-way merge unions spans so
   generated escape bytes never become input to later patterns and caller
   regex groups/flags/backreferences retain normal `re` semantics.
8. Taut-owned text logs are presentation records. Raw PTY bytes implement an
   attached terminal protocol and must remain byte-transparent.
9. A policy-load `RuntimeError` carries one fixed printable-ASCII message.
   Callers catch it only around the helper; the logging formatter handles it
   internally so error reporting never re-enters the failed policy.

### 20.2 Execution checkpoints

- Spec-promotion baseline: `ce2bbb1` plus the uncommitted core/Summon spec diff
  recorded in section 4.
- Release `88f1b9a1` landed during implementation with coordinated version
  0.6.3; this feature therefore uses the next patch version, 0.6.4.
- Utility slice: implemented and independently approved. The public lazy
  function, packaged policy, bounded original-input span merge, type/error
  contract, maximum-size probes, and direct-wheel resource probe are green.
- Human project-config correction: implemented test-first with full precedence,
  nearest-CWD discovery, edit/deletion/nearer-file freshness, bounded cache,
  `--db`/`TAUT_DB` independence, fail-fast human preflight, and successful JSON
  independence. Focused correction tests are green.
- Renderer/Summon slice: implemented. Integrated review found and test-first
  fixes now cover generated-escape non-recursion in message rows,
  data-dependent policy failures during command-parser construction, and
  watch-time policy failures as terminal delivery failures with no cursor
  advance. Re-review approved the fixes. Post-commit durability and JSON-only
  watch policy independence also have direct firing tests.
- Metadata/artifact slice: coordinated 0.6.4 metadata is implemented. Direct
  wheel, extracted-sdist-to-wheel, installed-resource, resolver-rejection, and
  coordinated core/Summon wheel-matrix proofs pass.
- Release-hardening review found that process-global `logging.basicConfig`
  could leave a host's preconfigured raw handler in control. A failing public
  command test reproduced the control-byte leak; the foreground adapter now
  owns a package-scoped non-propagating `taut_summon` handler and preserves the
  host root logger.
- Final verification and review: all scoped gates pass and independent review
  approved the final diff. The owner subsequently authorized commit and 0.6.4
  release subject to the ordinary release gates.

### 20.3 Verification evidence

Observed passing commands on 2026-07-14:

```text
uv run --extra dev pytest -n 0 -q
uv run --extra dev pytest -q -n 0 extensions/taut_summon/tests/test_summon_cli.py::test_native_summon_command_owns_safe_logging_without_replacing_host_handlers
uv run --extra dev pytest -q -n 0 extensions/taut_summon/tests -m 'not requires_live_harness and not requires_local_llm'
uv run --extra dev pytest -q -n 0 tests/test_terminal_text.py tests/test_cli.py tests/test_architecture_boundaries.py
uv run --extra dev pytest -q -n 0 tests/test_docs_references.py tests/test_project_metadata_consistency.py tests/test_core_summon_wheel_matrix.py tests/test_lazy_imports.py
uv run --extra dev ruff check taut tests bin extensions/taut_pg/taut_pg extensions/taut_pg/tests bin/pytest-pg extensions/taut_summon/taut_summon extensions/taut_summon/tests
uv run --extra dev ruff format --check taut tests bin extensions/taut_pg/taut_pg extensions/taut_pg/tests bin/pytest-pg extensions/taut_summon/taut_summon extensions/taut_summon/tests
uv run --extra dev mypy taut tests bin/release.py bin/release-artifact.py bin/require-green-workflows.py --config-file pyproject.toml
uv run --extra dev mypy taut/_scripts.py extensions/taut_pg/taut_pg extensions/taut_pg/tests extensions/taut_pg/tests/conftest.py --config-file pyproject.toml
uv run --extra dev mypy extensions/taut_summon/taut_summon extensions/taut_summon/tests extensions/taut_summon/tests/conftest.py --config-file pyproject.toml
uv run python bin/build-and-check-release-wheels.py
git diff --check
```

The full non-live Summon run excludes the separate live-harness and local-LLM
release lanes. This change does not alter their raw PTY boundary; touched PTY,
driver, compatibility, and CLI tests pass. No live PostgreSQL lane was added
for this backend-independent presentation change. The source-distribution test
builds an sdist, extracts it outside the checkout, builds and installs its
wheel, and verifies the packaged policy there. The actual release-wheel matrix
also rejects new Summon with the prior core and accepts the coordinated 0.6.4
pair.
