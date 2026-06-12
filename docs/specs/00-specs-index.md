# Specs Index

This directory contains the repository's source-of-truth specs for intended
behavior.

Use this numbered index as the canonical starting point for specs. Keep
`README.md` as a thin pointer so directory browsing and numbered read order
stay aligned instead of competing.

## Rules

- Specs define intended behavior, invariants, and verification expectations.
- Specs use stable reference codes so plans and code can cite exact
  requirements.
- Specs backlink related plans under `## Related Plans`.
- If behavior changes materially, update the spec before or with the code.

## Recommended Starting Points

1. `01-development-documentation-operating-model.md`
2. `02-taut-core.md` — the taut v0.1 product spec: storage model,
   identity and fingerprinting, message envelope, read model, CLI/API/
   watcher surfaces, and trust model

## Naming

- Use stable filenames.
- Numbered prefixes are recommended when the corpus is expected to grow.
- Prefer concise, descriptive titles over ticket-like names.

## Related Surfaces

- `docs/plans/` for execution
- `docs/implementation/` for rationale and repository maps
- `skills/` for reusable workflow instructions
