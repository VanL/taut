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

The root and MCP Ruff configurations retain Ruff's stable defaults through
`extend-select` and add the same reviewed families. Both ignore only `E501` and
`B008`; preview rules remain opt-in. All four development manifests pin the
same Ruff version. `tests/fixtures/ruff-enabled-rules.txt` owns the exact
reviewed 453-rule inventory for that version, and `tests/test_ruff_policy.py`
proves both real environments resolve it. Root CI owns repository-wide
`ruff check .` and suppression reconciliation; PG and MCP jobs keep their
scoped extension checks as independent environment proof. Formatting retains
its prior explicit paths.

The source directive owns only rule codes and a stable group pointer. The human
DOM-10.2.1 table owns approval, cardinality, protected invariant, real proof,
and rejected alternatives. `bin/ruff_suppression_index.py` owns derived
evidence only.

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
layout before it creates a same-directory temporary file and calls
`os.replace`. Only the generated block may change. Policy mismatches exit 1;
anticipated tool, decoding, source-read, and replacement failures exit 2 with
one diagnostic and no traceback; unexpected defects retain their traceback.

The repository has no root lockfile. Commands that verify an already prepared
development or release environment therefore use `uv run --no-sync`: they must
not resolve dependencies, join an ambient parent workspace, or write lock state.
Exact manifest pins and the two existing extension locks prove configuration.
The Ruff module in the canonical root pytest interpreter proves its installed
pin; MCP retains a static extension-lock proof rather than a second runtime
binary comparison.

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

When the Ruff pin changes, review the stable-default delta before updating the
fixture. Re-run normal Ruff and the raw `--ignore-noqa` audit, re-evaluate every
affected suppression rather than grandfathering it, update both configurations
together, and regenerate the derived index only after explicit approval of any
changed human-owned registry field.
