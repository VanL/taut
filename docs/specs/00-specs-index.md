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
2. `02-taut-core.md` - the taut core product spec: storage model,
   thread semantics, message envelope, read model, CLI/API/watcher surfaces,
   and trust model
3. `03-identity-addressing-notifications.md` - stable member identity,
   mutable names, reserved alias storage, `@name` direct messages, special
   queue namespaces, notification inboxes, and channel rename semantics
4. `04-summon.md` - the summon extension spec: hosting an existing agent
   harness as an ordinary workspace member — injection ears, CLI mouth,
   provider adapters, session ledger, control plane, persona, and
   conformance suite

## Naming

- Use stable filenames.
- Numbered prefixes are recommended when the corpus is expected to grow.
- Prefer concise, descriptive titles over ticket-like names.

## Related Surfaces

- `docs/plans/` for execution
- `docs/implementation/` for rationale and repository maps
- `skills/` for reusable workflow instructions
