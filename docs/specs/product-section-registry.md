# Product-Section Registry

Status: Active — created by `docs/plans/2026-08-07-information-architecture-plan.md`
under the contract mechanism adopted in `docs/program-theory.md`
(THEORY-7, owner-ratified 2026-08-07). The README declares itself the
product contract; this registry is the mechanical authority table that
cedes README sections to their owning specs, one non-overlapping
concern family per row.

## How to read this table

Each row names one concern family and its **state**. Families are
non-overlapping as *concerns* — every promise has exactly one row whose
concern it states, and that row governs it. Owner sections are not
exclusive to a row: one spec section may serve two families (for
example [IAN-7] carries both the reaction notification shape and the
general inbox contract), and a broad section code does not absorb a
promise that another row's concern names more specifically. States:

- `canonical-spec` — the cited spec sections own the family's exact
  behavior; the README restates and links.
- `draft-spec` — a spec draft exists but has not been promoted; the
  README remains the contract for the family.
- `readme-only` — no spec owns the family; the README section is the
  contract of record.

**Conflict rule.** For a `canonical-spec` family, the owning spec wins
where it speaks, and the README must restate and link rather than
diverge. Ceding is **promise-granular**: a README promise in a
registered family that the owning spec does not state remains
README-owned until the spec absorbs it — registration never silently
converts an unowned promise into spec authority, and never silently
deletes it. The equivalence ledger in the creating plan records the
audited promise-level dispositions at cutover.

**Promotion rule.** A `readme-only` or `draft-spec` family becomes
`canonical-spec` by landing the spec text, re-running the two-way
promise audit for the family, and flipping the row in the same change.
New concern families are added as rows when a new surface ships, with
the same audit.

**Hygiene (global).** Every path and `taut` command claim in this file
and in the surfaces it governs is checked by the [DOM-10.1] gates
(`tests/test_docs_references.py`, `tests/test_cli_claims.py`). Rows do
not carry per-row gates; a row cites a conformance suite only where the
owning spec names one.

## Authority table

| Concern | State | Owner |
|---------|-------|-------|
| Storage model, workspace, trust boundary | `canonical-spec` | [TAUT-2], [TAUT-3.1], [TAUT-3.4], [TAUT-9] |
| Reactions vocabulary, config, semantics, notification shape | `canonical-spec` | [TAUT-3.2], [TAUT-7.7], [IAN-7] |
| Threads, envelope, read model, write ordering | `canonical-spec` | [TAUT-4], [TAUT-6.1], [TAUT-6.3], [TAUT-7], [TAUT-10] |
| CLI surface and JSON output | `canonical-spec` | [TAUT-6.5], [TAUT-8.1], [TAUT-8.2] |
| Watcher / live following; reactor lifecycle | `canonical-spec` | [TAUT-8.4], [TAUT-8.5] |
| Identity, addressing, names | `canonical-spec` | [IAN-2], [IAN-3], [IAN-4], [TAUT-8.2], [TAUT-10] |
| Direct messages and handles | `canonical-spec` | [IAN-5.1], [IAN-5.3], [IAN-6.4], [IAN-9], [TAUT-7.8] |
| Notifications and inboxes | `canonical-spec` | [IAN-2.5], [IAN-6.5], [IAN-7], [TAUT-7.1] |
| Terminal escape policy | `canonical-spec` | [TAUT-6.4] |
| Extension packaging and release | `canonical-spec` | [TAUT-12.5]; Summon packaging [SUM-3]; MCP packaging [MCP-3] |
| Summon | `canonical-spec` | [SUM-1], [SUM-2], [SUM-3], [SUM-4], [SUM-5], [SUM-6], [SUM-7], [SUM-8], [SUM-9], [SUM-10], [SUM-12], [SUM-13]; trust co-owner [TAUT-9] |
| MCP | `canonical-spec` | [MCP-1], [MCP-2], [MCP-3], [MCP-4], [MCP-5], [MCP-7], [MCP-9], [MCP-12] |
| Search | `canonical-spec` | [SRCH-1], [SRCH-2], [SRCH-3], [SRCH-4], [SRCH-5], [SRCH-6], [SRCH-10], [SRCH-11] |
| Persistence / dump-load | `canonical-spec` | [PIO-2], [PIO-3], [PIO-4], [PIO-5], [PIO-6], [PIO-7], [PIO-9], [PIO-10], [PIO-11] |

Install, quickstart, roadmap, and Recommended For are the README's
human entry material, not source-of-truth rows; installation mechanics
(such as pipx usage) are deliberately README-owned how-to content.

## README-owned promises inside registered families

Recorded at cutover (2026-08-08) per the conflict rule; each remains
README-owned until a spec absorbs it. The full audit is in the creating
plan's equivalence ledger:

- the shipped-Postgres trust boundary stated present-tense ("with
  Postgres, the boundary is who can reach and write the configured
  database/schema"): [TAUT-9]'s corresponding sentence still reads
  future-tense ("when a server-backed broker arrives") and is recorded
  stale in the creating plan's deviation log — the README's
  present-tense statement is the accurate account and wins as an
  explicit promise-level exception until [TAUT-9] is realigned
- the no-daemon / no-server / zero-resident-process property as a core
  product statement (natural future home: [TAUT-2])
- live-watch pacing mechanics — WAL concurrency, burst-then-backoff,
  wake on the database change counter (natural home: [TAUT-8.4])
- presence semantics for `taut who` (local liveness vs remote-style
  presence; no spec home today)
- the identity heuristic of looking past shells and wrapper commands,
  and the new-identity candidate diagnostic block (natural home:
  [IAN-3])
- `say @name` as the sole DM creator, stated affirmatively (natural
  home: [IAN-5.3])
- notification claims by `taut watch` stated generically, the
  crash-window framing of pointer loss, and the guarantee that
  ordinary chat activity does not necessarily create a pointer
  (natural home: [IAN-7])
- the pipx installation mechanics and the fact that `taut-pg` installs
  no console script (README how-to)

## Related Plans

- `docs/plans/2026-08-07-information-architecture-plan.md` — creates
  this registry and records the cutover equivalence ledger.
