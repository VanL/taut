# MCP dependency ceiling removal

Date: 2026-10-28. Status: active. Class 5, with hardening: [MCP-3] defines dependency bounds and the change widens the published compatibility surface. Source: explicit owner request to remove ceilings; baseline `docs/specs/05-taut-mcp.md` [MCP-3], `extensions/taut_mcp/pyproject.toml`, and its uv lock. Consulted program theory, agent context, hierarchy, principles, engineering principles, hardening and review runbooks, and lessons.

## Goal and spec delta

Remove the `<3` MCP SDK and `<5` jsonschema caps without changing the minimums, package names, internal package pin, or transport behavior. In [MCP-3], replace the two range literals with `mcp>=2.0.0` and `jsonschema>=4.26.0`; replace the stale lock-version claim and major-ceiling rationale with an explicit statement that no upper bounds are declared and future major versions are not yet qualified. Remove the later sentence requiring review of a changed declared ceiling; this owner-directed change receives compatibility review here. Promotion follows owner direction; code and spec change together. Current stable SDK and jsonschema lock resolutions stay real, not mocked. Future major compatibility is not implied by current test evidence.

## Hardening and sequence

The published constraints are externally visible; the lock is a repository development artifact and cannot constrain consumers. Wider bounds can allow a future incompatible upstream release. Before release, rollback is a revert; after publication, metadata cannot be edited and correction requires a new release or yank. Unlocked CI can pick up a future incompatible major before the retained lock changes. No persistent state migration, asynchronous behavior change, or one-way door is introduced. Do not change MCP behavior, all package minimums, or internal exact version constraints. No new dependencies.

1. Independently review this plan and spec delta before editing. Stop on blocker.
2. Edit [MCP-3] and the MCP extension's dependency ranges, update both root and extension uv locks using uv 0.13.6. Stop if resolution changes unexpectedly.
3. Run `uv lock --check` for the root and extension, actual installed MCP tests, and documentation checks; also freshly resolve the uncapped dependencies to check for a current new major. Run build and inspect wheel METADATA to verify both lower bounds and no upper caps. Keep real SDK and schema validators, no mocks of dependency boundaries. Test-first exception: one-time built-wheel metadata inspection is the substitute proof for this declarative packaging change; no permanent test that pins the dependency metadata is added. Observe hosted CI before merge. Future SDK majors remain an explicit untested risk.
4. Review implementation independently, record findings and verification. Keep this plan active while CI is pending; close its index row when the work is fully qualified.

Out of scope: removal of internal exact package pins, dependency behavior rewrites, release publication, or speculative upstream major compatibility changes.

Pre-implementation review: Claude returned no blocker and four P2s; all accepted above: refresh both locks, remove the separate ceiling review sentence, drop the stale assertion that minima equal locked versions, and name the test-first exception and wheel metadata substitute. The review also identified post-publication rollback limits and unlocked CI risk, recorded above. Grok review could not start because its sandbox failed; Claude containment was not independently reprobed.

Verification: uv 0.13.6 `lock --check` passes for root and MCP extension. An uncapped index resolution selects MCP 2.3.0 and jsonschema 4.26.0. The built wheel's `Requires-Dist` entries are exactly `mcp>=2.0.0` and `jsonschema>=4.26.0`, with no upper bounds. MCP extension pytest passed on macOS/Python 3.14, with ten PostgreSQL tests skipped for lack of DSN. Plan-index and documentation-path checks pass. Hosted CI and final independent review remain pending.
