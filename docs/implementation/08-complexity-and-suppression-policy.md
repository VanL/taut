# Complexity and Suppression Policy

## Purpose

Taut enables Ruff `C901` at McCabe complexity 10 across every first-party
Python source. The score is an audit signal. It does not override cohesion,
failure locality, transaction ownership, or real-process proof.

The governing contract is [DOM-10.2] and [DOM-10.2.1] in
`docs/specs/01-development-documentation-operating-model.md`.

## Ownership and boundaries

The root and MCP Ruff configurations explicitly select the reviewed rule
families. All four development manifests pin the same Ruff version. Root CI
owns repository-wide `ruff check .` and suppression reconciliation; PG and MCP
jobs keep their scoped extension checks as independent environment proof.
Formatting retains its prior explicit paths.

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

The repository has no root lockfile. Unlike SimpleBroker, the canonical command
therefore uses `uv run --extra dev`, not `--frozen --no-sync`. Exact manifest
pins, the two existing extension locks, and policy tests comparing the running
root and MCP binaries to the pin provide the reproducibility proof.

## Required workflow

Normal review runs:

```bash
uv run --extra dev ruff check .
uv run --extra dev python bin/ruff_suppression_index.py --check
```

After explicit human approval changes a human-owned field or source pointer,
regenerate only the derived block and immediately recheck:

```bash
uv run --extra dev python bin/ruff_suppression_index.py --write
uv run --extra dev python bin/ruff_suppression_index.py --check
```

Never use a threshold increase, per-file ignore, blanket file directive, or
baseline allowlist to absorb a new finding. Refactor at a real ownership seam
or add a reviewed narrow group with firing behavioral proof.
