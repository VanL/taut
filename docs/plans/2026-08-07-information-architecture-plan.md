# Information Architecture Plan (Diataxis Cutover)

Status: completed — all seven slices executed. Slice 1 pinned the
baseline at `2313c3c`; slices 2–7 ran 2026-08-08 (equivalence ledger,
registry + [DOM-10.1] promotion with red-first probes, README
extraction with per-block ledger, kernel/llms.txt/docs-README
surfaces, full gates + rendered-link inspection, and the
different-family completion review with all findings applied or
answered below).
Class: 5+P — creates `docs/specs/product-section-registry.md`, amends
[DOM-10.1]'s enumerated source sets, and restructures the README (the
contract of record). Effective: class 5 plus pre-landing
different-family review.
Hardening: N/A — no [DOM-5] risky trigger fires (docs only).
Plan type: implementation with spec revision — promotion strategy A
(registry and [DOM-10.1] text land first without link claims; gates
and consumers bind in later slices).

## Goal

Diataxis cutover following SimpleBroker's worked example, right-sized
to this repository (841-line README, existing canonical specs,
existing extension READMEs): create the product-section registry
([THEORY-7]); cede README authority to the owning specs only through
a blocking two-way equivalence audit; slim the README's how-to weight
into the minimal set of new homes; add the agent kernel, `llms.txt`,
and the layered `docs/README.md` ownership statement; widen the
[DOM-10.1] gates over every new surface red-first.

## Spec Baseline

- `2313c3c` (2026-08-07) — dump/load landed (its 9410b6b), first
  sweep complete (its a86d669), tree clean. Spec 08
  `08-persistence-io.md` [PIO-1] through [PIO-11] stable. All
  registry row codes in D1 re-verified present at this pin
  (24/24). Mid-flight claims are against this identifier.

## Source Documents

- `docs/program-theory.md` [THEORY-6], [THEORY-7]
- `docs/specs/01-development-documentation-operating-model.md`
  [DOM-2], [DOM-6], [DOM-10.1]
- `docs/specs/02-taut-core.md` … `06-search.md`, and `08-*` ([PIO-*])
  once landed — the owning contracts
- `README.md`; `extensions/taut_pg/README.md`,
  `extensions/taut_summon/README.md` (existing extension homes —
  round-1 F8)
- `tests/test_docs_references.py` AND `tests/test_cli_claims.py` —
  the two separate gate-grammar sources ([DOM-10.1]; round-1 F4)
- `docs/implementation/04-taut-architecture.md` (names the README
  Development section as the canonical local verification block —
  round-1 F6)
- Worked example (foreign, by name): SimpleBroker's registry, layered
  docs/README, kernel, llms.txt — including its late-caught PyPI
  link defect (round-1 F10)

## Invariants and constraints

- **Authority cedes only through the equivalence ledger.** For each
  concern family, a blocking two-way audit: every README normative
  promise in that family is located in the cited spec section (or
  the row stays `readme-only`, or a deviation row records the gap).
  No promise silently becomes canonical (F3).
- **Extraction ledger, one row per removed block** (F7): source span,
  exact destination or surviving duplicate, hazard/required-action
  preserved, pointer and gate retargets, commit, reviewer. Reviewed
  against the extraction diff before the next slice.
- **The README stays the recognizable product statement**; Identity
  Trick and Trust Model stay, bound with spec links. The
  **Development section stays intact** — it is the canonical local
  verification block per implementation doc 04; no CONTRIBUTING
  split in this plan (F6).
- **README routes that must work on PyPI use absolute GitHub URLs**,
  and completion includes a rendered-link inspection of the package
  long description (F10 — the defect that escaped SimpleBroker's
  cutover until completion review).
- **One home per recipe** (F8): the **agent kernel owns
  agent-executable recipes** — no `working-with-agents.md` guide;
  extension depth routes to the **existing extension READMEs**, not
  new pg/summon guides; no `design-notes.md` — Weird-but-Aren't
  entries stay in the README, each gaining its owning
  theory/spec link; a configuration guide is added only if
  implementation shows a genuinely cross-cutting task not owned by
  an extension README or spec (default: not).
- [DOM-10.1] widening updates **both** pytest source lists and both
  source-membership tests; the `bin/` scripts import those contracts
  and need no edit (F4).
- No new normative claims beyond the registry/ownership rules this
  plan explicitly creates (F1 wording corrected).
- Owner WIP untouched; shared `docs/plans/README.md` lands via
  synthetic HEAD+mine blob (`git show HEAD:<f>` + own edits →
  `git hash-object -w` → `git update-index --cacheinfo`).

## Proposed Spec Delta (exact text lands at the promotion slice;
drafted here for review — F1)

**D1 — `docs/specs/product-section-registry.md`.** Header: mechanical
authority table, one row per non-overlapping concern family; states
`readme-only` | `draft-spec` | `canonical-spec`; conflict rule
(registered family → canonical spec wins; README restates and
links); promotion rule for future families. Row set (owners corrected
per round-1 F2; exact non-overlapping codes, verified again at the
pinned baseline before promotion):

| Concern | State | Owner |
|---------|-------|-------|
| Storage model, workspace, trust boundary | `canonical-spec` | [TAUT-2], [TAUT-3.1], [TAUT-9] |
| Reactions vocabulary, config, semantics, notification shape | `canonical-spec` | [TAUT-3.2], [TAUT-7.7], [IAN-7] |
| Threads, envelope, read model, write ordering | `canonical-spec` | [TAUT-4], [TAUT-7], [TAUT-10] |
| CLI surface and JSON output | `canonical-spec` | [TAUT-8.1], [TAUT-8.2] |
| Watcher / live following; reactor lifecycle | `canonical-spec` | [TAUT-8.4], [TAUT-8.5] |
| Identity, addressing, names | `canonical-spec` | [IAN-2], [IAN-3], [IAN-4] |
| Direct messages and handles | `canonical-spec` | [IAN-5.3], [IAN-6.4] |
| Notifications and inboxes | `canonical-spec` | [IAN-2.5], [IAN-6.5], [IAN-7] |
| Terminal escape policy | `canonical-spec` | [TAUT-6.4] |
| Extension packaging and release | `canonical-spec` | [TAUT-12.5]; Summon packaging [SUM-3]; MCP packaging [MCP-3] |
| Summon | `canonical-spec` | [SUM-*] (exact sections enumerated at promotion) |
| MCP | `canonical-spec` | [MCP-*] (enumerated at promotion) |
| Search | `canonical-spec` | [SRCH-*] (enumerated at promotion) |
| Persistence / dump-load (composite file contract, dump, load, failure modes) | `canonical-spec` | [PIO-4], [PIO-6], [PIO-7], [PIO-9] (surfaces [PIO-3]; verification [PIO-11]) |
| Install / quickstart / roadmap / Recommended For | human entry, not SoT rows |

No per-row Gate column (F9): global [DOM-10.1] path and CLI-claim
hygiene is stated once outside the table; rows carry an exact
obligation-to-test mapping **only** where a row-specific conformance
suite exists and is named in the owning spec.

**D6 — [DOM-10.1] delta**: the enumerated source sets (both
`tests/test_docs_references.py` and `tests/test_cli_claims.py`, and
the spec's own enumeration) gain `docs/agent-kernel.md`, `llms.txt`,
and `docs/README.md`; both source-membership tests updated in the
same change. Red-first probes (F5): a path dangler in a genuinely
new source class (`docs/agent-kernel.md`, not under `docs/specs/`),
and an invalid `taut` command claim in the same file for the CLI
list — both watched red, then removed.

## Structure deltas (non-spec)

**D2 — README**: Postgres/Summon installation depth → pointers to the
existing extension READMEs (absolute URLs); MCP subsection: same
treatment (F11 census completion — explicit disposition); Working
With Agents → compact statement + kernel pointer (recipes live in
the kernel only); Weird-but-Aren't stays, entries gain owning links;
Identity Trick/Trust Model bound with links; Recommended For stays
(human entry); Development stays intact; Roadmap stays.
**D3 — `docs/agent-kernel.md`**: agent product-use kernel — the sole
home of agent-executable recipes (join/catch-up/say/read `--json`,
identity and `--as`, DM handles, notification-claim hazard,
vanilla-`broker read` hazard, exit codes); explicitly a view, never
inventing obligations beyond the winning SoT.
**D4 — `llms.txt`**: llmstxt.org link index (absolute URLs).
**D5 — `docs/README.md`**: layered ownership statement (adapted from
SimpleBroker's; surface-role table, duplication-resolution rule,
conflict rule, promotion rule). AGENTS wiring already exists
(newcomer item 1 — F11 no-op removed).

## Equivalence Ledger (Slice 2, 2026-08-08)

Fourteen concern families audited two-way (README promise ↔ owning
spec) by four independent read-only agents with file:line evidence;
~150 distinct promises checked. Family outcomes:

| Family | Outcome |
|--------|---------|
| Reactions | COVERED (16/16 promises spec-stated, no contradictions) |
| Search | COVERED (15/15); [SRCH-N] owner set enumerated for the registry |
| Persistence / dump-load | COVERED (15/15); registry row widened to [PIO-2..7,9,10,11] |
| Terminal escape policy | COVERED (22/22); one wording narrowing fixed README-side |
| MCP | COVERED (18/18); "workspace-scoped" phrasing fixed README-side |
| Extension packaging/release | COVERED except pipx mechanics — classified README how-to (human entry row) |
| Threads/envelope/read model | COVERED; envelope promises owned by [TAUT-6.1]/[TAUT-6.3] (row widened); suffix rule rescoped to `reply` README-side |
| CLI surface and JSON | GAPS fixed README-side: `whoami --json` example lacked the contractual `aliases` field; inbox row understated the four notification types; row widened to [TAUT-6.5] |
| Watcher / live following | COVERED for behavior; burst/backoff + WAL + zero-process idle promises are README-owned (registry carve-out) |
| Identity/addressing/names | GAPS fixed README-side (evidence list aligned to [IAN-3.2]); shells/wrappers heuristic + diagnostic block README-owned; row widened to [TAUT-8.2]/[TAUT-10] |
| DMs and handles | COVERED; row widened to [IAN-5.1]/[IAN-9]/[TAUT-7.8]; sole-creator framing README-owned |
| Notifications/inboxes | GAPS fixed README-side (types list); watch-claims generality, crash framing, no-pointer-for-ordinary-activity README-owned |
| Storage/workspace/trust | COVERED except the [TAUT-9] Postgres-boundary tense (deviation row below); no-daemon headline README-owned; row widened to [TAUT-3.4] |
| Summon | COVERED except the stale codex "named follow-on" roadmap claim, fixed README-side; trust bullets co-owned by [TAUT-9] (row annotated) |

Every README-owned promise inside a registered family is listed in the
registry's "README-owned promises" section — nothing ceded silently
(F3). README-side fixes were applied in the extraction slice with
ledger rows below.

## Extraction Ledger (Slice 4, 2026-08-08)

One row per removed README block; reviewer = the slice-7 completion
review. All destinations verified present before removal.

| Removed block (pre-edit span) | Destination / surviving duplicate | Hazard preserved | Pointer + gate retargets |
|-------------------------------|-----------------------------------|------------------|--------------------------|
| Postgres install + `.taut.toml` config depth (README §Postgres Extension, ~L163–201) | `extensions/taut_pg/README.md` Requirements/Installation/Configuration (verified duplicate incl. the exact toml block) | DSN-secret warning survives verbatim in the pg README (its L56–61) | README keeps compact statement + absolute link; path/CLI gates unchanged |
| Reactions config block (~L203–219) | Compact statement in new §Project configuration; exact contract [TAUT-3.2] (verified, audit family COVERED 16/16) | Restart-after-change requirement kept in the compact statement | Spec link added; no gate retarget |
| Summon usage/example block (~L230–248) | `extensions/taut_summon/README.md` Usage (verified: summon/dismiss/status commands present) + [SUM-3]/[SUM-9] | Trust-boundary bullet stays in README Trust Model (co-owned [TAUT-9]) | Absolute links to extension README + spec + impl docs |
| MCP install/run + dev-checkout block (~L266–279) and tool-name enumeration (~L283–288) | `extensions/taut_mcp/README.md` Install and Run + Tool Notes (verified: pipx, uv checkout lines, `--claude-channel`) + [MCP-3]/[MCP-5] | "wired ≠ published" fact kept compact in README | Absolute links; tool-count phrasing corrected to "20 tools (17 CLI-shaped …)" per audit |
| Working With Agents shell recipes + `CLAUDE.md`/`AGENTS.md` pattern (~L557–576) | `docs/agent-kernel.md` (sole recipe home; pattern block reproduced there verbatim) | rejoin-suggestion recipe, notification-drain and vanilla-`broker read` hazards all present in the kernel | README keeps compact statement + kernel link; kernel added to both [DOM-10.1] source lists (red-first probes recorded below) |

Not removals, applied in the same slice (audit-driven README fixes):
`whoami --json` example gains contractual `aliases`; inbox row and
Weird-entry notification kinds corrected to four types; identity
evidence list aligned to [IAN-3]; `MSG_ID` suffix rule rescoped to
`reply`; codex "named follow-on" replaced with the shipped PTY-hosted
provider statement; conformance-suite wording softened to the spec's
claim; every relative link converted to an absolute GitHub URL (F10);
owning links added to Trust Model, Identity Trick, and every
Weird-but-Aren't entry; Documentation Map updated for the landed
registry, kernel, and llms.txt.

## Deviation Log

| Spec ref | Planned behavior | Actual behavior | Rationale | Spec proposal |
|----------|------------------|-----------------|-----------|---------------|
| [TAUT-9] | Registry cedes the trust-boundary family cleanly | Spec text still frames the Postgres boundary as future ("When a server-backed broker arrives") while `taut-pg` is shipped; README states it present-tense | Spec prose is stale relative to shipped behavior; this plan may not add or revise normative spec text (F1), so the promise stays README-owned via the registry conflict rule | Routed, not pending: a future spec-alignment unit updates [TAUT-9]'s tense; recorded in the registry's README-owned list until then |
| [IAN-3], [IAN-5.3], [IAN-7], [TAUT-2], [TAUT-8.4] | All family promises spec-stated before ceding | Eleven promises have no spec sentence (enumerated in the registry's README-owned section) | Same F1 boundary: absorbing them is future spec work, not registry work | Routed, not pending: each names its natural home in the registry; promotion follows the registry's promotion rule |

## Tasks (dependency-ordered; slices 2+ blocked on the pinned baseline)

1. **Baseline slice** (unblocks the rest): when the dump/load work
   lands, pin the Spec Baseline SHA; re-verify the D1 row set and
   owner codes against it; add the persistence row from landed
   [PIO-*].
2. **Equivalence-ledger slice** (blocking): per concern family, the
   two-way README-promise ↔ spec audit; outcomes recorded per row
   (covered / stays `readme-only` / deviation row). Reviewed before
   promotion.
3. **Spec-promotion slice** (strategy A): land the registry and the
   [DOM-10.1] delta text; both pytest source lists + membership
   tests; red-first probes per D6.
4. **Extraction slice**: D2 README movement with the one-row-per-block
   extraction ledger; absolute-URL policy applied.
5. **New surfaces**: D3 kernel, D4 llms.txt, D5 docs/README.md.
6. Gates: `./bin/check-plan-status-index`, `./bin/check-dom15-fixtures`
   (+ `--self-test`), `python3 bin/coalesce-check`,
   `uv run --no-sync bin/check-doc-paths`,
   `uv run --no-sync bin/check-cli-claims`,
   `uv run --no-sync pytest tests/test_docs_references.py
   tests/test_cli_claims.py tests/test_plan_status_index.py -q`;
   rendered-link inspection of the long description (F10).
7. Scoped completion review (different family); land by file-list
   staging with the synthetic-blob protocol; run-log entry; index
   flip in the landing change.

## Out of Scope

- Any product behavior or CLI change; the dump/load WIP itself; the
  big harvest sweep; promoting future `readme-only` families;
  CONTRIBUTING split (F6); new pg/summon/agent guides (F8);
  rewriting spec content.

## Review Log

| Date | Stage | Reviewer / result | Findings and disposition |
|------|-------|-------------------|--------------------------|
| 2026-08-08 | Slice-7 completion review | codex CLI (two scoped runs after a full-diff timeout; read-only) — run 1 (new surfaces + gates): 3×P1, 2×P2; run 2 (README extraction): 0×P1, 4×P2. All applied or answered: P1 docs-README conflict rule aligned to the promise-granular rule; P1 registry overlap semantics defined explicitly (concern-level non-overlap, shared owner sections; full README-section remap declined as the round-1-approved D1 shape); P1 the stale [TAUT-9] Postgres-tense promise added to the registry's README-owned list as an explicit promise-level exception; P2 same-repo GitHub-URL liveness test added (red-first via mutated URL, then green); P2 kernel gate claim narrowed to grammar-level checking; P2 init-`--json` Postgres contract restated in the pg README; P2 MCP DM-selector/`dms=true` facts restated in the mcp README; P2 [SUM-1] pattern pointer verified to resolve through the retained README section (no spec edit); P2 Documentation Map gains the third extension README. |
| 2026-08-07 | Round-1 plan review | codex CLI (900 s bound, completed in bound) — **BLOCKED**, F1–F11 | All eleven accepted and applied in revision 2: F1 full Class-5 apparatus added (baseline gate, exact delta drafts, strategy A, deviation log; "no new normative claims" corrected); F2 registry owners redrawn non-overlapping with exact codes (CLI → [TAUT-8.1]/[TAUT-8.2]; reactions resolved `canonical-spec` via [TAUT-3.2]/[TAUT-7.7]/[IAN-7]; packaging [TAUT-12.5]/[SUM-3]/[MCP-3]; DM row [IAN-5.3]/[IAN-6.4]; broad core row split); F3 blocking two-way equivalence ledger added as its own slice; F4 both gate-grammar sources named and updated together; F5 probes redesigned (new source class; separate CLI-claim probe); F6 Development section kept intact with the implementation-doc ownership preserved; F7 extraction ledger format specified per removed block; F8 guide set slimmed (kernel owns agent recipes; extension READMEs are the extension homes; no design-notes; configuration guide default-no); F9 per-row Gate column dropped for one global hygiene statement + exact mappings only where real; F10 absolute-URL policy + rendered-link inspection gate; F11 census completed (Recommended For, MCP disposition), AGENTS no-op removed, commands named exactly. **Blocking dependency recorded: slices 2+ wait for the dump/load landing (spec 08 [PIO-*]) — the worktree changed during the review itself.** |

## Execution Log

(append-only)

- 2026-08-08: Slices 2–7 executed in one session. Slice 2: four
  parallel read-only agents audited ~150 README promises across the
  14 families two-way; outcomes in the Equivalence Ledger section.
  Slice 3: registry landed with audit-widened owner rows and
  enumerated [SUM-N]/[MCP-N]/[SRCH-N]/[PIO-N] codes; [DOM-10.1]
  source sets + both pytest source lists + both membership tests
  updated; both red-first probes fired in docs/agent-kernel.md (path
  dangler and `taut frobnicate` claim), watched red, removed.
  Slice 4: extraction per the Extraction Ledger; audit-driven accuracy
  fixes applied; all README links absolute. Slice 5: kernel, llms.txt,
  docs/README layered ownership statement. Slice 6: all named gates
  green (58 sources, 1096 path claims, 238 command claims); GFM
  rendered-link inspection — 72 targets all absolute-or-anchor, 12
  anchors resolve. Slice 7: codex completion review (row above), all
  findings applied or answered; index flipped to completed in the
  landing change. Deviation from the plan's landing protocol: the
  synthetic HEAD+mine blob staging was unnecessary — no concurrent
  session held WIP in the shared files at landing time; ordinary
  staging was used and the tree was clean.

- 2026-08-07: Slice 1 executed. Blocking dependency cleared: dump/load
  landed (9410b6b, plan completed) and the first full coalescing
  sweep ran in the other session (a86d669; the sweep handoff file was
  consumed and deleted as designed). Baseline pinned `2313c3c`; all
  24 D1 registry row codes verified present at the pin; persistence
  row derived from landed [PIO-1..11]. Slices 2–7 unblocked.

- 2026-08-07: Owner-directed README currency pass, executed ahead of
  the blocked structural slices as its own unit (Class 2 against the
  README's own contract intent: reversible, no behavior claims
  changed, verified by the [DOM-10.1] gates — path claims, CLI
  claims 25/25, transcripts byte-untouched). Applied: status block
  brought to published reality (taut-chat on PyPI, CHANGELOG as the
  release record) with the program-theory link added; Table of
  Contents; Features gains the extensions bullet; Roadmap split into
  Shipped (summon, MCP, search — each with its governing spec) /
  In progress (dump-load, owned by its own in-flight work) / Ahead
  (TUI, Redis backend); new Documentation Map section (the
  SimpleBroker "specifications and instructions" analog) naming the
  layered surfaces and noting the registry as planned work. The
  structural extraction, kernel, llms.txt, and registry remain this
  plan's blocked slices.
- 2026-08-07: Diataxis gap flags recorded for future development:
  (tutorial) no learning path beyond Quick Start — a first-workspace
  walkthrough with two agents is the natural piece once the kernel
  exists; (how-to) agent-recipe home is the planned kernel (D3);
  backup/migration how-to arrives with dump-load; a configuration
  how-to (reactions vocabulary, terminal policy, .taut.toml
  discovery) remains default-no per round-1 F8 unless implementation
  shows it cross-cutting; (reference) llms.txt and the registry are
  this plan's D4/D1; (explanation) the former biggest gap —
  conceptual account — is now filled by the Active program theory;
  presence/liveness semantics remain the thinnest explained area.
