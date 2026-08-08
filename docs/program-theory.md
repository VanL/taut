# Taut Program Theory

Status: Active — ratified by the owner 2026-08-07 after independent
semantic review (ADOPT-WITH-EDITS; all ten edits applied).
Crystallized 2026-08-07 from the README (the declared product
contract), the [TAUT-*]/[IAN-*]/[SUM-*]/[SRCH-*] specs, plans,
lessons, and owner dialogue. Owner answers of 2026-08-07 resolved the
simplicity metric, founding account, contract mechanism, and the five
adopted durable alternatives in [THEORY-5]. Later revisions gate on
the human owner.
Owner: Taut product owner
Boundary: Conceptual identity and design judgment, not exact current
behavior. The winning product contract owns exact behavior; until
[THEORY-7]'s registry exists, the README is the contract of record.
Verification: Owner and independent semantic review; consistency with
the README and the exact owning product-spec sections named in
[THEORY-3].
Required action: Read before product-scope judgment (audits, reviews,
feature-fit and design opinions) and before changing a core concept,
durable principle, or non-goal; conform or propose a revision.

"Program theory" follows Peter Naur's "Programming as Theory Building"
(1985): this file is the current externalized account of what kind of
system Taut is, not a substitute for possessing that model in
practice. The definitional primer lives in the agent-theory hub
(cited by name; this file describes Taut, not the concept).

---

## Purpose and desired feel [THEORY-1]

Taut is **Slack in your terminal, for you and your agents**: channels,
threads, history, unread counts, and live following for participants
who already share a machine — a human in one terminal, coding agents
in others, a cron job that should be able to speak up. They can all
run a CLI and share a filesystem; what they lack is a way to talk.

It should feel like:

- **installable with pipx, deletable with rm** — no server, no
  daemon, no dotfiles, no accounts; `taut init` creates one file and
  that file is the entire installation,
- **honest plumbing** — `.taut.db` is a standard SimpleBroker
  database; `broker -f .taut.db list` works; nothing is hidden,
- **loud about its weak trust model** — saying it loudly is part of
  the design, not an apology,
- **equally usable by a person at a prompt and a script in a loop** —
  every command has `--json`; agents join with three shell commands
  and zero setup.

"Simple" for Taut means **a small use surface and operational model**
— no server, no required daemon, no config, one file — not a small
source count. Cohesive internal machinery is justified when it
protects that external model. (Owner-ratified 2026-08-07, adopting
SimpleBroker's revised account of the same word.)

## Whole-system mental model [THEORY-2]

A **workspace is its storage**: one SQLite file by default, a
configured Postgres schema via `taut-pg`. Storage access *is*
membership — everyone who can write the storage is root of the chat,
and the boundary (a `chmod`, a group, a database grant) is chosen by
the operator, never managed by Taut.

On top of that storage, Taut owns chat semantics; SimpleBroker owns
durable queue mechanics underneath; the participants own what the
messages mean.

- **The queue is the history.** Ordinary readers peek; "read" means
  "move my bookmark" (a per-member cursor in a sidecar table), and
  unread is "anything after my bookmark". Authors may delete their own
  messages; nothing else consumes history. (Pointing a vanilla
  `broker read` at a chat queue consumes it — tolerated, not
  protected.)
- **Notification inboxes are the deliberate exception**: consumable
  pointers for mentions, replies, new DMs, and reactions. Claims
  drain them; two sessions of one member share one inbox; a crashed
  claim can lose a pointer; a pointer can outlive a deleted message.
  Taut does not cascade or repair — the single-directory model is
  intended.
- **Identity is a stable opaque member id.** Names are mutable display
  labels; messages freeze the sender name at write time; machine
  consumers use `from_id`. The selector-free path derives an identity
  claim from process evidence — deterministic and inspectable
  (`whoami --explain`), never authenticated.
- **Extensions widen the same model rather than adding a second one**:
  `taut-pg` swaps the storage substrate under identical commands;
  `taut-summon` hosts an existing agent harness as an ordinary
  workspace member (ears, mouth, adapters, session ledger, control
  plane, persona); `taut-mcp` exposes the workspace to MCP clients.

## Core concepts and ownership [THEORY-3]

| Concept | Meaning | Conceptual owner | Exact current contract owner |
|---------|---------|------------------|------------------------------|
| Workspace | The storage (file or schema); access to it is membership | Core; operator chooses the boundary | [TAUT-2], [TAUT-3.1], [TAUT-9] |
| Member | Stable opaque id owning memberships, cursors, DMs, notifications | Core identity model | [IAN-2.1], [IAN-3] |
| Name | Mutable display label, frozen into messages at write | Core | [IAN-2.2], [IAN-4] |
| Identity claim | Deterministic hash of agent-process, human-session, or continuity-token evidence; maps to a member and identifies, never authenticates | Core | [IAN-2.3], [IAN-3.2]–[IAN-3.3] |
| Channel / thread | Queues whose content is the history; readers peek | Core | [TAUT-2], [TAUT-4], [TAUT-7] |
| Direct message | Stable member-id pair queue reopened by name or handle | Core | [IAN-5.3], [IAN-6.4] |
| Bookmark / unread | Per-member cursor; unread = past the bookmark | Core read model | [TAUT-7.2], [TAUT-7.3] |
| Notification inbox | Consumable pointers; claimed, drainable, unrepaired | Core | [IAN-2.5], [IAN-6.5], [IAN-7] |
| Durable queue mechanics | Queue ordering, persistence, and activity-wait primitives | SimpleBroker (upstream; not re-specified here) | SimpleBroker's own contracts |
| Live chat watcher | Burst-then-backoff following of joined threads | Core (scheduling base attributed to Weft) | [TAUT-8.4] |
| Summoned member | A hosted harness acting as an ordinary member | Summon; the member model stays core's | [SUM-2], [SUM-4] |
| Terminal escape policy | Display-time safety control against accidental relay; `.taut.toml` is the operator policy input | Core presentation | [TAUT-6.4] |

## Durable principles [THEORY-4]

1. **Humans and agents are both first-class.** Every surface serves
   both; `--json` is not an afterthought.
2. **Zero configuration by default; explicit, project-visible doors
   otherwise.**
3. **Storage access is the only boundary.** Identity claims make
   attribution frictionless and inspectable, never impossible to
   spoof; `--as` requires no proof, and that is stated, not patched.
4. **Presentation filtering prevents accidental relay; it is not
   authentication or authorization.**
5. **Plumbing stays inspectable.** SimpleBroker underneath is a
   feature, not an implementation detail to hide.

## Non-goals [THEORY-5]

- **Not for untrusted users, compliance, or anything Slack is
  actually for.** One trust domain; in-the-moment coordination.
- **Not an authentication or authorization system.** Taut coordinates
  inside a trust domain; it does not establish one. Every participant
  could already do worse than lie in chat — they run code on your
  machine, as you.
- **No user-managed service lifecycle; no server, no accounts.** The
  durable invariant is out-of-the-box operation without a
  user-managed service lifecycle, not today's literal zero-process
  realization. Today, `taut watch` and Summon are foreground
  processes, and Taut has no process when neither is active. A
  demand-started, self-managed process with explicit readiness,
  status, stop, and bounded idle-exit semantics could evolve (see
  A4). Rejected today: a resident service required for typical use,
  or a detached process without that lifecycle contract.
- **No repair of dangling notification pointers** — the
  single-directory model accepts the loss.
- **No hiding of the broker substrate.**

### Adopted durable alternatives (owner-ratified 2026-08-07)

Five records, admitted selectively (likely recurrence, material
investigation cost, hidden constraint exposed, or harm from blind
retry). Format stays prose-with-fields until this repository adopts a
formal record grammar. Architecture- and contract-scope records
(per-call read limit, vendor-whole vs contract-copy, extension
packaging, process-evidence mechanics, the `taut-chat` naming) are
routed to their owning specs and implementation docs, not here.

**A1 — Notification inboxes stay consumable pointers.** Rejected:
treating claim-on-read as delivery loss and adding per-device state or
cascade-repair. An external review filed it as a code defect; the
rebuttal (pointer loss ≠ delivery loss) was scored 10/10 and the
remedy was documentation (multi-factor remediation plan, findings
A5/B10/C9, disposition `intentional`). Blindly "fixing" it converts
the single-directory model into per-device state. Reconsider when:
pointer loss ever costs a *message* (chat history also gone), or
multi-session-per-member (MCP + CLI + summon concurrently) becomes
the normal deployment shape rather than the exception.

**A2 — Cross-backend search uses native analyzers, not hashed ASCII
token carriers.** Rejected after adoption: exact cross-backend result
parity via SHA-256 ASCII carriers (accepted from review finding F1,
promoted to spec, then owner-reversed the same day — "exact result
equality made search an authoritative computation, hid useful
built-in analysis behind opaque carriers, and was not required for
Taut's API contract"; the deviation is recorded inline at
[SRCH-2.3]). The parity argument is technically correct and will be
re-derived; this record preempts it. Reconsider when: a user-visible
workflow depends on identical hit sets across backends, or search
output is treated as authoritative state rather than a retrieval aid.

**A3 — No authentication layer; storage access is membership.**
Rejected repeatedly: authorization layers, control-evidence-as-auth,
and the continuity-token-as-secret classification (each re-defended
rather than patched; the token-as-secret drift produced its own
lesson about overclaiming posture and low-locality scrubbing code).
Auth is a non-goal, not deferred ambiguity ([TAUT-9]; README, "Why no
auth, signing, or encryption?": "it would be theater"). Reconsider
when: a shared-Postgres deployment needs per-principal write policing
that the database's own grants cannot express — at which point revise
this account rather than bolting on signing.

**A4 — No daemon *required* for typical use.** The durable invariant
is out-of-the-box operation without a user-managed service lifecycle,
not today's literal zero-process realization. Today, `taut watch` and
Summon are foreground processes, and Taut has no process when neither
is active ([TAUT-2], end-to-end per [SUM-*]). A demand-started,
self-managed process with explicit readiness, status, stop, and
bounded idle-exit semantics could evolve (weft's manager model; in
the extreme, taut services on weft's heartbeat/TaskMonitor model).
Rejected today: a resident service required for typical use, or a
detached process without that lifecycle contract. Reconsider when —
two conditions, in order, neither speculative: (1) a manager-like
self-managed service has actually evolved, and (2) a distinct use
case with concrete external pull exists for externally-managed
operation (the `weft manager serve` shape — systemd/launchd
ownership, forced no-idle-exit). "We could build this" does not
qualify. (Owner-refined 2026-08-07.)

**A5 — Cursor advancement follows the committed message, last and
best-effort.** Rejected after adoption: treating cursor advancement
as part of the authoritative-sidecar-first phase. The valid order
remains authoritative registry/membership state → message insert →
writer cursor advance. Foundation round 1 established the first
phase; round 3 C7 removed the cursor from it because
cursor-before-insert could skip concurrent messages after a crash;
re-litigated once more as finding A2 (pre-write probe replaced with a
bounded post-write probe, [TAUT-7.4]). The queue-is-history inversion
survives only with this ordering. Reconsider when: a storage backend
offers a transaction that makes message-insert and cursor-advance
atomic across both tables with no crash window — and even then, the
probe discipline is re-derived, not assumed.

## Tensions and falsifiers [THEORY-6]

- **Summon widens what storage write access can cause** (a remote
  Postgres writer can influence tools on a harness host). If real
  deployments start needing per-principal write policing, the
  storage-access-is-membership equation is under pressure — the answer
  is operator-side grants or constrained tools, and if that stops
  sufficing, this account must be revised rather than quietly
  patched.
- **README-as-contract**: the README declares itself the intended
  product contract, written first. If specs and README drift into
  divergent normative claims for the same behavior, the
  single-contract model has failed — resolve by ceding the section
  through [THEORY-7]'s registry, not by parallel authority.
- **Unread-model economy**: if answering "what's new for me"
  correctly requires state beyond one per-member cursor and queue
  order, or an observed workspace shows cursor-based unread lookup
  must scan total history, the queue-is-history inversion needs
  reexamination.

No additional lived-use falsifier is recorded yet: the owner reports
none has presented itself (owner statement 2026-08-07). Falsifiers
are first-class when real, not a quota — the next genuine surprise
that does not fit this account is the candidate.

## Founding continuity [THEORY-7]

**Taut was theory-first before the name existed**: the owner wrote
the README — the full intended product contract — before any spec
and before any code (owner statement 2026-08-07). The alpha README is
therefore both the founding statement and the first externalized
account of this theory; the specs grew out of it, not the reverse.
Built on SimpleBroker's durable queues by design ("SimpleBroker all
the way down").

**Contract mechanism (owner-ratified 2026-08-07):** Taut adopts the
product-section registry mechanism — a per-section table naming the
winning contract (README section or spec) for each behavior area, as
practiced in SimpleBroker. Until the registry exists, the README
remains the contract of record as declared in its own header;
creating `docs/specs/product-section-registry.md` and re-homing the
README's contract sections to their owning specs is the named
follow-up work.

## Revisions [THEORY-8]

(None yet — this is the initial ratified account. Revisions append
here as [REV-THEORY-NNN] records.)
