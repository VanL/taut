# Complexity and Suppression Policy

## Purpose

Taut uses Ruff's stable defaults plus the reviewed `E`, `W`, `F`, `I`, `B`,
`C901`, `C4`, and `UP` families across every first-party Python source. `C901`
stays at McCabe complexity 10. Lint findings are audit signals; they do not
override cohesion, failure locality, transaction ownership, resource lifetime,
public error shape, or real-process proof.

The governing contract is [DOM-10.2] and [DOM-10.2.1] in
`docs/specs/01-development-documentation-operating-model.md`.

## Ownership and boundaries

The root, MCP, and TUI Ruff configurations (`pyproject.toml`,
`extensions/taut_mcp/pyproject.toml`, and `extensions/taut_tui/pyproject.toml`)
all target Python 3.12 (`target-version = "py312"`), retain Ruff's stable
defaults through `extend-select`, and add the same reviewed families. All three
ignore only `E501` and `B008`; preview rules remain opt-in. Development
manifests declare a Ruff range (`ruff>=0.17.4`) whose minimum tracks their
owning retained lock selection. `tests/test_ruff_policy.py` derives the
effective reviewed rule set dynamically from the pinned Ruff binary's isolated
default rule set (`ruff check --isolated --show-settings`) unioned with those
reviewed families minus the declared global ignores, and proves all three real
configurations expose that exact rule set without maintaining a static rule
snapshot file. Root CI owns repository-wide `ruff check .` and suppression
reconciliation; PG and MCP jobs keep their scoped extension checks as
independent environment proof. Formatting retains its prior explicit paths.

The source directive owns only rule codes and a stable group pointer. The human
DOM-10.2.1 table owns approval, cardinality, protected invariant, real proof,
and rejected alternatives. `bin/ruff_suppression_index.py` owns derived
evidence only. It runs Ruff as `sys.executable -m ruff`, the interpreter's
pinned package, never a `ruff` found on `PATH`: a stale global binary has
different stable defaults and reports false policy mismatches. Its spec-owned global raw-diagnostic inventory is the sole
approved aggregate by rule code; policy tests invoke the checker rather than
copying those counts or the live and retired group-ID census into Python.
Reviewers consult Git history before assigning a group ID that could have been
retired.

## Symbol identity and raw identity

The generated index renders `path::qualified_symbol`, using the outermost
enclosing function and class qualification. This survives ordinary line
movement and exposes migration between owners. Ruff's physical `noqa_row`
remains the internal identity used to reconcile each raw diagnostic with its
source directive.

Removing and adding the same rule within one qualified symbol can remain
invisible when both site set and cardinality are unchanged. This residual is
accepted and must not be described as line-level identity.

## Failure and write behavior

Check mode never writes. Write mode validates Ruff discovery, source syntax,
directives, groups, counts, raw diagnostics, global inventory, and marker
layout before it creates a same-directory temporary file and atomically
replaces the target (retrying transient `PermissionError` up to 10 times with a
10 ms sleep for Windows file-sharing locks). Only the generated block may
change. Policy mismatches exit 1;
anticipated tool, decoding, source-read, and replacement failures exit 2 with
one diagnostic and no traceback; unexpected defects retain their traceback.

The repository retains root, Summon, MCP, and TUI lockfiles; the PostgreSQL
extension has no separate lock and follows the root development resolution.
Commands that verify an already prepared development or
release environment use `uv run --no-sync`: they must not resolve dependencies,
join an ambient parent workspace, or rewrite lock state. Manifest ranges state
the current minimum; retained locks provide reproducibility. Ruff policy tests
exercise the installed locked tool's rule inventory and behavior without
repeating its selected version.

## Required workflow

Normal review runs:

```bash
uv run --no-sync --extra dev ruff check .
uv run --no-sync --extra dev python bin/ruff_suppression_index.py --check
```

After explicit human approval changes a human-owned field or source pointer,
regenerate only the derived block and immediately recheck:

```bash
uv run --no-sync --extra dev python bin/ruff_suppression_index.py --write
uv run --no-sync --extra dev python bin/ruff_suppression_index.py --check
```

Never use a threshold increase, per-file ignore, blanket file directive, or
baseline allowlist to absorb a new finding. Refactor at a real ownership seam
or add a reviewed narrow group with firing behavioral proof.

When the locked Ruff selection changes, review the stable-default delta when
upgrading Ruff. Re-run normal Ruff and the raw `--ignore-noqa` audit, re-evaluate every
affected suppression rather than grandfathering it, update all three Ruff
configurations together, and regenerate the derived index only after explicit
approval of any changed human-owned registry field.
