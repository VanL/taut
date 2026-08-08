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
5. `05-taut-mcp.md` - the optional MCP extension spec: stdio lifecycle,
   dynamic workspace attachment, per-workspace identity, explicit CLI-shaped
   tools, the aggregate read-only notifications resource, edge hints, host
   adapters, and conformance
6. `06-search.md` - cursor-neutral full-text message search, canonical query
   semantics, visible scope, derived indexing, deferred work, recovery,
   reconciliation, and SQLite/PostgreSQL parity
7. `07-agent-theory-and-program-theory.md` - definitional reference:
   what Agent Theory and program theory mean; read when the terms are
   unfamiliar or before revising `docs/program-theory.md` (adopted from
   the agent-theory hub @ `0423923`)
8. `08-persistence-io.md` - actor-free composite workspace dump/load,
   logical sidecar records, extension contribution, quiescence, exact-id
   restoration, and fail-closed recovery
9. `product-section-registry.md` - the mechanical authority table naming
   the winning contract (README section or spec) for each product
   behavior family, with the promise-granular conflict and promotion
   rules

## Naming

- Use stable filenames.
- Numbered prefixes are recommended when the corpus is expected to grow.
- Prefer concise, descriptive titles over ticket-like names.

## Related Surfaces

- `docs/plans/` for execution
- `docs/implementation/` for rationale and repository maps
- `skills/` for reusable workflow instructions
