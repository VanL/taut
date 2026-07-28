# First-Class Direct-Message Navigation Plan

Date: 2026-07-28

Status: completed. The independently reviewed contract delta and every planned
behavior/documentation slice are complete. The repository owner authorized a
targeted commit on 2026-07-28.

Plan type: implementation with coordinated identity/addressing, core, CLI, and
MCP spec revision.

Class: 5. This adds intended public behavior to existing CLI, Python, watcher,
and MCP surfaces. It broadens accepted conversation selectors and adds a
direct-message directory mode. It is also risky under [DOM-5] because it
changes public CLI and MCP schemas and puts an identity-based confidentiality
check in front of previously channel-only history operations.

Owner: the implementing engineer owns spec promotion, the shared selector
boundary, core and adapter changes, real-backend proof, documentation, and
review evidence. The repository owner owns commit, version selection, release,
and publication.

## 1. Goal

Make every durable direct-message conversation explicitly reopenable by either
of these identity-scoped selectors:

```text
@current-name-or-alias
dm.d_<stable-id>
```

The first is convenient and resolves at invocation time. The second is the
existing deterministic internal queue name and remains stable across both
participants changing names.

The initial user-facing operations are:

```text
taut log @claude
taut read @claude
taut watch @claude
taut log dm.d_<stable-id>
taut read dm.d_<stable-id>
taut watch dm.d_<stable-id>
taut list --dms
```

The same selection semantics must be available through `TautClient` and the
existing MCP tools. The future TUI consumes the public typed client directory
and history/watch methods under [TAUT-12.4]; this plan does not create a TUI.

This is an addressing and directory feature. It does not create a new history
store, rename the existing DM queue scheme, persist broker aliases, or add
presence state.

## 2. Decided Contract

### 2.1 Selector classes and naming

- Keep [IAN-6.4]'s existing deterministic queue name unchanged:
  `dm.d_` plus 26 lowercase base32 characters derived from the sorted stable
  member-id pair.
- A direct-message route selector is `@NAME_OR_ALIAS`, using the existing
  member route namespace and normalization in [IAN-4].
- A stable direct-message selector matches exactly
  `^dm\.d_[a-z2-7]{26}$`.
- Broker `@alias` records are not used. They are global queue aliases and
  cannot express "this name as seen by this acting member." Resolution remains
  in Taut's identity/addressing layer.
- `say @name` keeps its current create-on-first-contact behavior.
  `say dm.d_*` is deliberately not added. Stable handles are conversation
  navigation handles, not a second send-address form. Sending to a person
  continues to use the current identity route.
- `leave`, `join`, `reply`, `rename`, and `who THREAD` do not gain DM
  selectors in this feature.

### 2.2 One actor-aware resolution path

Add one private client-owned resolver that accepts a selector and an already
resolved acting `MemberRow`, and returns one canonical registered chat thread.
`read`, `log`, `watch`, and the DM directory must not each reimplement the
checks.

For `@route`, the resolver:

1. resolves the route through Taut's current member-name/alias table;
2. rejects self-selection as an ordinary absent-conversation result;
3. derives the existing queue with `addressing.dm_queue_name(actor_id,
   target_id)`;
4. validates the registered row, participant metadata, and memberships below;
5. returns the canonical `dm.d_*` name.

For a stable `dm.d_*` selector, the resolver reads that exact registry row and
validates it without searching all DMs or reverse-hashing the name.

A valid accessible DM must have all of these properties:

- one registered thread row with `kind == "dm"`;
- exactly two distinct valid member ids in `meta.members`;
- the acting member is one of those ids;
- the registered name equals `dm_queue_name(member_a, member_b)`;
- both participant memberships exist for that registered thread; and
- both member rows still exist so the directory and human label do not invent
  identity.

Missing, malformed, nonparticipant, or pair/name-mismatched state fails closed.
It must not expose the other participant, registry metadata, queue contents, or
whether another pair owns the supplied handle. Every syntactically valid DM
selection miss, including unknown route, self route, known route without an
existing DM, absent stable handle, corrupt state, and another pair's handle,
uses one content-free adapter message in the existing not-found/empty class and
CLI exit 2. Malformed syntax remains a validation error.

Resolution is observational. `log`, `read`, `watch`, and `list --dms` must not
create or heal a member, claim, route, queue, thread row, membership,
notification, or DM. The ordinary existing-member activity behavior of
`read`, `watch`, and `list` remains. DM `log` uses read-only member resolution
so the operation stays cursor-neutral and activity-neutral; channel and
subthread `log` retain their current no-identity path.

### 2.3 Rename and route-reuse behavior

`@name` means the member currently owning that route when the invocation
starts. Taut resolves it once:

- an in-flight `watch @name` stays on the resolved stable DM after either
  participant renames;
- a later `@name` invocation follows the route's then-current owner;
- old names do not keep routing after rename unless a separately managed Taut
  member alias exists, per [IAN-4.4];
- if an old name is later assigned to another member, it addresses that new
  member and therefore a different deterministic pair;
- a current member route with no existing conversation returns not found and
  creates nothing; and
- the stable `dm.d_*` handle remains the reopenable path when names have
  changed or routes have been reused.

### 2.4 History, unread, and live watch

- `log SELECTOR` returns decoded Taut history from the canonical DM queue and
  never moves a cursor. Existing `--since` and `--limit` semantics are
  unchanged.
- `read SELECTOR` returns only unread rows from the selected existing DM and
  advances only its existing membership cursor through the returned page.
  An empty or caught-up DM retains the existing empty result.
- `watch SELECTOR...` resolves every supplied selector once before constructing
  the watcher. It deduplicates selectors that resolve to the same canonical
  queue. Input order does not define watcher scheduling order.
- An explicit watch requires the resolved existing membership. It does not
  create a DM. An existing empty DM is watchable and will receive later
  messages on its stable queue.
- Bare `read` and bare `watch` keep their current all-membership behavior.
- Watch membership refresh remains dynamic for the selected canonical queues.
  Route tables are not re-resolved during the run.

Human message headings for valid DMs use `DM with <other current display
name>`. Python, JSON, and MCP message objects keep the canonical `dm.d_*`
value in `thread`. The existing `Message` shape does not gain display metadata.

### 2.5 Actor-scoped DM directory

Add:

```python
TautClient.list_direct_messages() -> list[Thread]
```

and:

```text
taut list --dms
```

The directory:

- resolves one existing acting member;
- considers only that member's current DM memberships;
- applies the same registry, deterministic-name, participant, membership, and
  member-row validation as explicit selection;
- includes caught-up and empty registered DMs, not only unread DMs;
- returns the existing `Thread` value with canonical `name`, `kind == "dm"`,
  both stable participant ids in `members`, current human `display_name`,
  unread state/count, and latest pending `last_ts`;
- sorts by `last_ts` descending, puts `None` last, and uses canonical thread
  name as the deterministic tie break;
- returns the existing empty-result class, and CLI exit 2, when no valid
  accessible DM exists.

`--dms` and `--all` are mutually exclusive parser options. Bare `list` and
`list --all` retain their current behavior and ordering.

No new durable "DM index" is added. The directory is derived from existing
membership and thread-registry state. This is sufficient to retain empty DMs
because [IAN-6.4] already keeps those rows and memberships after physical
message deletion.

### 2.6 Notification actions

Now that stable DM handles are valid navigation selectors:

- a direct-message mention renders
  `inspect: taut log dm.d_<stable-id>`;
- `dm_started` renders `read: taut read dm.d_<stable-id>`;
- channel/subthread mention and reply actions are unchanged;
- JSON notification fields are unchanged.

The DM actions use the pointer's stable source thread, not a mutable `@name`.
Choosing and constructing the DM inspect/read action uses only the pointer's
thread string and stable namespace grammar. That path must not call
`list_threads()`, resolve identity, inspect the registry, or read the source
queue. Existing channel mention reply-suffix eligibility and uniqueness probes
remain unchanged.

### 2.7 MCP surface

The fixed manifest remains 18 tools. No `watch` MCP tool and no new DM-specific
tool are added.

- Existing `log.thread` and `read.thread` accept a channel, one-level
  subthread, `@name-or-alias`, or stable `dm.d_*` selector.
- Existing `list` gains optional `dms: boolean = false`.
- `all=true` and `dms=true` are rejected by schema or command validation before
  child dispatch.
- `list(dms=true)` calls `TautClient.list_direct_messages()`.
- Message and thread result schemas do not change.
- `log` remains `readOnlyHint=true`: DM actor resolution is read-only and the
  operation changes neither activity nor cursor.
- Recovery guidance may recommend `list(dms=true)` to recover stable handles
  and `log` to inspect DM history without moving a cursor.
- Started `read` cancellation remains outcome-uncertain, but the spec no
  longer claims DM history is unrecoverable. A later cursor-neutral DM `log`
  can inspect history; `list(dms=true)` can inspect unread state. Neither
  reveals which page was delivered before transport loss.

At the current baseline, core and MCP are both versioned `0.8.0`, MCP already
requires `taut>=0.8.0`, and no `v0.8.0` tag exists. The coordinated change may
use that existing floor only if it lands before the first 0.8.0 tag. If
0.8.0 is tagged first, implementation must stop, select the next coordinated
version with the repository owner, and raise the MCP core floor before
publication.

### 2.8 TUI boundary and non-presence rule

There is no implemented first-party TUI to change. The typed
`list_direct_messages()`, selector-aware `read()`/`log()`, and canonicalized
`watch()` are the public seams the future TUI must consume under [TAUT-12.4].
The TUI must not derive queue names itself or query private state.

Connected/recently-active state is a separate feature. This plan does not:

- infer "departed" from inactivity;
- add leases, heartbeats, timeouts, or cleanup;
- change `last_active_ts` or computed `presence`;
- make a running TUI, live watch, or MCP server advertise a connection; or
- hide DM history because the other participant is inactive.

Durable access is based on stable membership and validated registry state, not
liveness.

## 3. Source Documents

- `docs/specs/01-development-documentation-operating-model.md`
  [DOM-4]–[DOM-6], [DOM-10]–[DOM-12], [DOM-15]
- `docs/specs/02-taut-core.md`
  [TAUT-7.1]–[TAUT-7.4], [TAUT-8.1]–[TAUT-8.4], [TAUT-10],
  [TAUT-11], [TAUT-12.4], [TAUT-12.5]
- `docs/specs/03-identity-addressing-notifications.md`
  [IAN-2], [IAN-4], [IAN-5], [IAN-6.4], [IAN-7], [IAN-8]
- `docs/specs/05-taut-mcp.md`
  [MCP-3], [MCP-5], [MCP-6], [MCP-9]–[MCP-12]
- `docs/implementation/04-taut-architecture.md`
- `docs/implementation/06-command-extensions.md`
- `docs/implementation/07-taut-mcp-architecture.md`
- `docs/agent-context/runbooks/writing-plans.md`
- `docs/agent-context/runbooks/writing-specs.md`
- `docs/agent-context/runbooks/hardening-plans.md`
- `docs/agent-context/runbooks/testing-patterns.md`
- `docs/agent-context/runbooks/adversarial-acceptance-probes.md`
- `docs/agent-context/runbooks/maintaining-traceability.md`
- `docs/agent-context/runbooks/review-loops-and-agent-bootstrap.md`

## 4. Spec Baseline and Promotion Strategy

Original spec baseline: committed `HEAD`
`788cdd3884c29a68753e8ba9e244907d4e1a4455` plus the then-current worktree.
The governing spec files were clean relative to that commit.

Implementation-start baseline:
`3706d732db13f0ec7265d9b7e4e77601793d7a55`. The intervening committed
coalescing work did not change any of the three governing product specs.

Promotion strategy: **A, in-file text-first edits**.

The exact proposed text in section 6 was reviewed and then applied to the three
active spec files with reciprocal Related Plans links. Behavior code may cite
the promoted sections after the Slice 0 documentation checks and independent
promotion review recorded below pass.

Promotion baseline: implementation-start commit
`3706d732db13f0ec7265d9b7e4e77601793d7a55` plus the uncommitted promoted
diff in `docs/specs/02-taut-core.md`,
`docs/specs/03-identity-addressing-notifications.md`, and
`docs/specs/05-taut-mcp.md`.

No status reclassification is needed because all three specs are already
active. The plan remains the historical rationale after promotion; the spec
tree becomes the single contract.

## 5. Current Structure and Hidden Couplings

### 5.1 Address parsing and queue identity

`taut/addressing.py::parse_target()` currently recognizes `@name`, channels,
and one-level subthreads. It treats a dotted `dm.d_*` value as a malformed
subthread. `dm_queue_name()` already implements the required stable pair hash.

Required action: add an operation-aware DM-selector parser or validator without
making every existing thread argument accept DMs. Do not weaken channel or
subthread validation globally.

### 5.2 Messaging and member resolution

`taut/client/_messaging.py::_say_dm()` already resolves `@route`, derives the
stable name, validates/creates registry state, installs permanent
memberships, and writes the first-contact notification. Its creation path must
not become the navigation resolver: history navigation is read-only and must
never create a conversation.

`read_unread()` and `log()` currently have separate channel/subthread
validation. `log()` does not resolve an actor at all. The new private
selection helper belongs on the shared client layer and accepts an explicit
actor so call sites control activity semantics. It must reuse
`dm_queue_name()` and Taut state queries, not `_say_dm()` and not broker alias
resolution.

### 5.3 Thread listing and rendering

`taut/client/_threads.py::list_threads()` has two established modes:
unread-aware memberships and global registered threads. It raises when the
ordinary member view has no unread rows. Reusing it for `--dms` would either
hide read conversations or change bare-list semantics.

Required action: add `list_direct_messages()` as a distinct typed query and
reuse `_thread_from_row()` only after actor-scoped DM validation. Keep the
existing `Thread` model and JSON shape.

`taut/commands/_rendering.py::emit_messages()` currently sees only `Message`
objects and prints their canonical thread name as the heading. The
implementation needs an optional canonical-thread-to-human-label mapping, or
an equivalent shared renderer seam, supplied by the client/adapter. It must
not mutate `Message.thread` or change JSON.

### 5.4 Watcher canonicalization

`TautClient.watch()` passes raw filters to `TautWatcher`. The watcher matches
exact canonical membership names and owns live membership refresh. Selector
resolution belongs before runtime/watcher construction on the client owner
thread. The watcher should continue to know only canonical queue names.

Do not re-resolve routes from the watcher loop. That would silently retarget a
running session after rename/reuse and would mix state access into the
reactor.

### 5.5 MCP fixed manifest and package floor

`extensions/taut_mcp/taut_mcp/_tools.py` explicitly rejects DM selectors in
`read`/`log` descriptions and patterns. `_commands.py` dispatches the fixed
surface through child-owned clients. `server.py` and [MCP-9] repeat the current
bare-read-only recovery guidance.

The tool count remains fixed at 18, but schema snapshots, descriptions,
command input models, dispatch, structured-content tests, cancellation
guidance, and instructions must move together. The current untagged 0.8.0
version/floor relationship is a rollout condition, not a reason to skip
compatibility checks.

### 5.6 Confidentiality and corrupt state

A stable queue name is not authority. An attacker may guess or copy another
pair's handle. Every explicit selector and directory row must be checked
against registry metadata, deterministic name, member rows, and memberships
before any queue peek or watcher construction.

Candidate scoping is the privacy boundary: never open the supplied DM queue
first and check the decoded body later. Content-free not-found behavior must
be byte-equivalent for an absent handle and another pair's real handle at CLI
and MCP adapters.

### 5.7 Comprehension gate

Before production edits, the implementer must answer:

1. Why can SimpleBroker's global `@alias` namespace not represent
   actor-relative member routing?
2. Why must `@name` resolve once while a stable handle survives later route
   changes?
3. Which navigation operations may touch activity, and why must DM `log` not?
4. Why must another pair's valid stable handle be rejected before queue peek?
5. Why can `list_threads()` not simply grow a filter without changing bare
   unread behavior?
6. Why does an empty registered DM remain listable and watchable?
7. Where are raw selectors canonicalized before `TautWatcher` sees them?
8. What can a future TUI consume without importing private modules?
9. Why is a connection timeout not evidence that a member has departed?
10. What version/floor action becomes mandatory if `v0.8.0` appears first?

Stop and revise the plan if DM queue naming, permanent membership retention,
member-route uniqueness, cursor high-water semantics, or the future-TUI public
boundary changes before implementation.

## 6. Proposed Spec Delta

Promotion strategy: **A**. Apply the following exact normative text, adjusted
only for surrounding Markdown flow and cross-reference placement.

### 6.1 `docs/specs/03-identity-addressing-notifications.md`

Replace [IAN-5.1]'s address table and following paragraph with:

```markdown
### [IAN-5.1] Command address classes

Taut conversation arguments use these shapes:

| Input shape | Meaning |
|---|---|
| `general` | channel `general` |
| `#general` | channel `general`, accepted for familiarity but usually needs shell quoting |
| `general.<message_id>` | sub-thread under channel `general` |
| `@claude` | direct message with the member currently named `claude`, or aliased `claude` if a Taut member alias exists |
| `dm.d_<26-lowercase-base32-chars>` | one existing stable direct-message conversation, subject to actor access checks in [IAN-5.3] |

Not every command accepts every class. `say` accepts channels, subthreads, and
`@name-or-alias`; it does not accept a stable `dm.d_*` handle. `read`, `log`,
and `watch` accept their existing channel/subthread forms plus both DM selector
forms. `join`, `leave`, `reply`, `rename`, and `who THREAD` retain their
existing narrower contracts.

Documentation should prefer bare channel names in shell commands because an
unquoted leading `#` can be interpreted as a shell comment. Human rendering may
show channels as `#general`.
```

Insert after [IAN-5.2]:

```markdown
### [IAN-5.3] Direct-message conversation selection

A DM route selector is `@` plus a valid current member name or Taut member
alias. It resolves once at invocation time relative to the acting member, then
derives [IAN-6.4]'s deterministic queue from the two stable member ids. A
running watch stays on that canonical queue after either member renames.
Later invocations follow the then-current route owner. Old names do not remain
routes unless retained through the Taut member-alias model in [IAN-4].

A stable DM selector matches exactly `^dm\.d_[a-z2-7]{26}$`. The selector is
authority only when the registered row is a DM with exactly two distinct valid
member ids, its name equals [IAN-6.4]'s derivation for that pair, the actor is
one participant, both member rows exist, and both participant memberships
exist. Missing, malformed, mismatched, self, nonparticipant, or inaccessible
selection returns one content-free not-found/empty result without exposing
another participant, registry metadata, queue contents, member-route
existence, or whether another pair owns the supplied handle. Malformed selector
syntax remains a validation error.

Navigation never creates or heals a member, identity claim, route, queue,
thread, membership, notification, or DM. A valid current route with no
existing DM is not found. SimpleBroker queue aliases do not participate in DM
selection because their namespace is global rather than actor-relative.
```

Replace the human-rendering/action paragraphs in [IAN-6.4] with:

```markdown
Actor-scoped human renderers label a valid direct-message conversation
`DM with <other current display name>`. Human `read`, `log`, and `watch`
message headings, bare joined `list`, and `list --dms` use that label. JSON,
Python, and MCP message surfaces keep the internal `dm.<dm_id>` queue name in
`thread`; list/thread metadata also exposes participant member ids under
[TAUT-8.2].

The pre-existing global `list --all` diagnostic view retains its current
membership-independent rendering: a valid DM may show all current participant
names, and missing or malformed participant metadata renders
`DM <internal-thread> (participants unavailable)`. It invents no identity or
extra warning. Actor-scoped `list --dms` excludes malformed or inaccessible
rows.

Human notification actions are type-specific. A channel or subthread mention
renders `taut log <source-thread>`; a direct-message mention renders
`taut log <stable-dm-thread>`. A mention includes the shortest unique
source-message suffix usable with `taut reply` only when the source is a
top-level channel and the recipient is a member (full id on ambiguity). A
reply pointer renders `taut log <child-thread>`; `dm_started` renders
`taut read <stable-dm-thread>`, and no invented reply id. Choosing and
constructing a DM action uses the pointer's stable source thread and performs
no identity, list, registry, or source-queue lookup. Existing channel mention
reply-suffix eligibility and uniqueness probes are unchanged. `log` remains
membership-independent for channels/subthreads but is participant-scoped for
DMs under [IAN-5.3]. All render local `HH:MM`. JSON timestamps and names do not
change.
```

Add to [IAN-9]'s required coverage:

```markdown
- `@name-or-alias` DM navigation resolves relative to the actor and creates no
  conversation; valid stable handles survive rename, while later route reuse
  follows the new owner
- stable handles are rejected before queue access for nonparticipants,
  malformed registry metadata, pair/name mismatch, missing members, or missing
  participant memberships, with absent and inaccessible adapter output
  indistinguishable
- actor-scoped DM directory results include read and empty valid DMs, exclude
  malformed/inaccessible rows, and sort by newest surviving row with empty
  conversations last
```

### 6.2 `docs/specs/02-taut-core.md`

Insert after [TAUT-7.7]:

```markdown
### [TAUT-7.8] Direct-message navigation and directory

`read`, `log`, and explicit `watch` accept [IAN-5.3]'s `@name-or-alias` and
stable `dm.d_*` selectors. Taut canonicalizes each selector through one shared
actor-aware client path before queue access. `@route` resolves once per
invocation. Explicit watch filters are canonicalized and deduplicated
before `TautWatcher` construction; input order does not define scheduling
order. The watcher sees only canonical membership names and never re-resolves
routes.

Selection requires an existing valid actor-accessible DM and performs no
creation or repair. `read` advances only the selected existing membership
cursor through returned rows. `log` moves no cursor and uses read-only actor
resolution, so DM log also leaves member activity unchanged. An existing empty
DM is a valid directory/watch target; `read` and `log` still return their
ordinary empty result until rows exist. Bare read/watch behavior is unchanged.

`TautClient.list_direct_messages() -> list[Thread]` returns every valid
registered DM reachable through the acting member's current memberships,
including caught-up and empty conversations. It applies [IAN-5.3]'s full
validation, returns the existing `Thread` shape, sorts nonempty conversations
by descending `last_ts`, puts `last_ts is None` last, and breaks ties by
canonical thread name. No valid result raises the ordinary empty result. The
query derives its result from existing registry and membership state and adds
no durable index.

Human DM headings use [IAN-6.4]'s current-name label. Machine message records
retain the canonical stable queue in `thread`.
```

Replace the affected [TAUT-8.1] rows with:

```markdown
| `read [THREAD_OR_DM]` | Show unread (all joined threads when bare, grouped), advance each selected cursor through displayed messages. An explicit DM may be `@name-or-alias` or a stable `dm.d_*` handle and must already be accessible under [IAN-5.3]. Reads are paged at up to 1,000 unread messages per thread; rerun until exit 2 to drain. Subthreads retain implicit-join behavior. | 0 showed messages; 1 error; 2 nothing unread / unrecognized member / not a member or accessible conversation |
| `log THREAD_OR_DM [--since TS] [--limit N]` | Show cursor-neutral history. A DM may be `@name-or-alias` or a stable `dm.d_*` handle and requires actor access under [IAN-5.3]. `--limit N` selects the most recent N messages after `--since`, rendered chronologically. | 0; 1 error; 2 empty / unrecognized member / inaccessible conversation |
| `list [--all | --dms]` | Bare: joined threads with unread state. `--all`: every registered thread. `--dms`: every valid actor-accessible DM, including read and empty conversations, in [TAUT-7.8] order. The two flags are mutually exclusive. | 0; 2 when the selected actor-scoped view is empty |
| `watch [THREAD_OR_DM ...]` | Live-follow selected existing memberships plus the acting member's notification inbox. DM filters may be `@name-or-alias` or stable handles; they resolve once and deduplicate before watcher construction. Bare watch retains dynamic all-membership behavior. | 0 on clean stop; 1 error; 2 unrecognized member / explicit thread or DM miss |
```

Add to [TAUT-8.2]:

```markdown
- Human message headings for a valid DM are
  `DM with <other current display name>`. Message JSON remains unchanged and
  keeps the stable internal queue in `thread`.
- `list --dms` emits the existing list object shape. Every result has
  `kind == "dm"` and includes both stable participant ids in `members`.
```

Add to [TAUT-8.3]:

```markdown
The DM-directory signature is
`TautClient.list_direct_messages() -> list[Thread]`. Existing
`TautClient.read()`/`read_unread()` and `TautClient.log()` string parameters
accept [TAUT-7.8]'s DM selectors where the CLI does. `TautClient.watch(...,
threads=list[str] | None)` canonicalizes explicit DM selectors before creating
`TautWatcher`. These methods share one private actor-aware selector boundary;
adapters and the future TUI must not derive DM queue names or inspect private
state.
```

Add to [TAUT-8.4]:

```markdown
Explicit watcher filters are canonical registered membership names by the time
they reach `TautWatcher`. Public client construction resolves
[TAUT-7.8]'s DM selectors once and deduplicates aliases of the same canonical
queue. Input order does not define watcher scheduling order. Membership refresh
remains dynamic, but route ownership is not re-evaluated during the run.
```

Add to [TAUT-10]:

```markdown
- Every syntactically valid DM selection miss, including unknown route, self
  route, known route without an existing conversation, absent handle,
  inaccessible handle, and failed registry/pair/member/membership validation,
  uses one content-free not-found/empty adapter result and CLI exit 2. These
  cases expose no member-route, participant, content, or conversation-existence
  distinction.
- `list --all --dms` is a usage error and exits 1 before client construction.
```

Add to [TAUT-11]:

```markdown
- DM selector and directory contracts run against real Taut state plus real
  SimpleBroker queues on SQLite and PostgreSQL. Tests must prove that
  inaccessible selectors are rejected before queue peek/watcher construction
  and that navigation creates no state. Mock-only resolver or schema tests are
  insufficient.
```

Add to [TAUT-12.4]:

```markdown
The future TUI obtains its DM directory from
`TautClient.list_direct_messages()` and opens history/live views through the
public selector-aware client/watcher boundary. It does not derive deterministic
queue names, resolve routes, or inspect registry/membership tables itself.
```

### 6.3 `docs/specs/05-taut-mcp.md`

Replace the affected [MCP-5] tool descriptions with:

```markdown
| `read` | Return oldest unread messages and advance each selected cursor through its returned page. `thread` may select a channel, subthread, `@name-or-alias` DM, or stable `dm.d_*` conversation. Omit it for all joined chat threads. | false | true | false | true |
| `log` | Inspect cursor-neutral history for a channel, subthread, or existing actor-accessible DM selected by `@name-or-alias` or stable `dm.d_*` handle. | true | false | true | true |
| `list` | List ordinary joined/unread threads, every registered thread, or every valid actor-accessible DM. `all` and `dms` are mutually exclusive. Resolving the existing member for actor-scoped list modes may update activity. | false | false | false | true |
```

Replace the current [MCP-5] recovery paragraph beginning
`After an uncertain read` and ending `not a recovery guarantee` with:

```markdown
After an uncertain `read`, the caller first uses `list`; it never blindly
repeats a read. `list` with `dms=true` recovers the attached member's durable DM
directory and stable handles. `log` reconstructs channel, subthread, or
actor-accessible DM history without another cursor or activity move. It cannot
prove which returned page reached the host before cancellation or transport
loss. `show_message` remains useful only when an exact id is already known and
retains its cursor effect. These are inspection and recovery aids, not a
delivery guarantee.
```

Replace, and do not retain, the rejecting `chat thread`, `read.thread`, and
`all` rows in [MCP-5]'s property table. Use these exact rows and add `dms`:

```markdown
| chat `thread` | Taut channel or one-level subthread. A subthread is `<channel>.<19-digit-parent-message-id>`. | `leave` and `who` accept only this narrow form. |
| chat-or-DM `thread` | Taut channel, one-level subthread, `@name-or-alias`, or stable `dm.d_<26-lowercase-base32-chars>` selector. | `log` accepts all forms and applies actor access checks to DMs. |
| `read.thread` | Optional chat-or-DM selector. Null or omitted reads every joined chat thread. | Explicit DM selection requires an existing accessible conversation and advances only its returned page. |
| `all` | When true, list every registered Taut thread. | Defaults to false; mutually exclusive with `dms`. |
| `dms` | When true, list every valid actor-accessible DM, including read and empty conversations. | Defaults to false; mutually exclusive with `all`. |
```

Replace the affected [MCP-5] input table rows:

```markdown
| `read` | `workspace: string`, `thread: string or null`, `limit: integer` | `workspace` | default limit 100; range 1..1,000; explicit DM selectors follow [TAUT-7.8]; null/omitted keeps bare joined-thread behavior; each selected queue has its own limit and cursor advance |
| `log` | `workspace: string`, `thread: string`, `since: string, integer, or null`, `limit: integer` | `workspace`, `thread` | default limit 100; range 1..1,000; DM log is actor-scoped, cursor-neutral, and activity-neutral |
| `list` | `workspace: string`, `all: boolean`, `dms: boolean` | `workspace` | both default false; `all && dms` is rejected before child dispatch; `dms=true` calls `TautClient.list_direct_messages()` |
```

Add to [MCP-5] behavior:

```markdown
The fixed manifest remains exactly 18 tools. `read.thread` and `log.thread`
schemas accept the existing channel/subthread grammar, the [IAN-4] `@` route
grammar, and exact stable-DM grammar `^dm\.d_[a-z2-7]{26}$`. A malformed
selector is rejected by schema before child dispatch. A well-formed absent or
inaccessible DM maps to the same content-free typed empty result as every other
well-formed DM miss, without route, participant, or existence detail. `log`
retains `readOnlyHint=true` and `idempotentHint=true`; its DM identity selection
uses core's read-only resolver.
```

Replace [MCP-6]'s exact `read_cursor_advanced` guidance object with:

```markdown
`{ "action": "Use log for non-consuming channel, sub-thread, or accessible direct-message rereads. After an uncertain read, inspect list before retrying.", "code": "read_cursor_advanced", "message": "Read cursors advanced through the returned records; no message history was deleted." }`
```

The canonical guidance constant, connection-reactor result path, server
instructions, and exact snapshot tests must use this same string. No active
adapter text may retain the old `Direct messages have no public log operation`
claim.

Replace [MCP-9] instruction item 10 with:

```markdown
10. Prefer `read` with one explicit selector when only one conversation is
    intended. Use `list` with `dms=true` to discover the attached member's
    durable DM conversations and stable handles. Use `log` for cursor-neutral
    channel, subthread, or DM history. After an uncertain `read`, inspect
    `list` and the selected conversation with `log` before retrying. A later
    log can recover history but cannot prove which read page reached the host.
```

Replace the started-read cancellation clause in [MCP-11]/[MCP-12] with:

```markdown
- cancellation after started explicit and bare `read` calls discards the
  response but may advance one or several selected cursors; later `list`
  (including `dms=true`) and cursor-neutral `log` recover current unread state
  and history for channels, subthreads, and accessible DMs, but cannot prove
  which returned page reached the host; blind retry remains unsafe
```

Replace [MCP-12]'s existing `read schema and cursor proof` bullet in full with:

```markdown
- `read` schema and cursor proof: omitting `limit` passes 100 to core;
  explicit 1 and 1,000 are accepted; 0 and 1,001 are rejected by schema
  validation before child dispatch; and 250 unread rows in one explicit
  thread read with limit 100 produce exact oldest-first pages of 100, 100,
  and 50 with the cursor at the last returned row and no gap or duplicate.
  Omitted and null `thread` both pass `None`, return unread rows from two
  joined channels and one direct-message queue, and apply the limit to each
  queue independently; a limit-1 bare read may therefore return three rows
  and advances each cursor only through its one returned row. Explicit valid
  `@name-or-alias` and stable `dm.d_*` selectors are accepted for existing
  actor-accessible DMs, while malformed selectors are rejected before child
  dispatch and `say @name` remains valid. Inspection and a forwarding spy
  prove the handler passes the chosen thread and limit to `TautClient.read()`
  and never fetches a larger page then slices the result. The real
  broker/client/state pagination and DM-selection proof runs on SQLite and
  PostgreSQL.
```

Add these further bullets to [MCP-12]'s executable proof list:

```markdown
- explicit `read` and `log` accept both DM selector forms and reject malformed,
  absent, corrupt, and nonparticipant handles without queue access or content
  leakage; route rename/reuse and stable-handle behavior match core
- `list(dms=true)` includes unread, caught-up, and empty valid DMs in core
  order, emits the existing thread schema, rejects `all=true` before child
  dispatch, and creates no state
- the manifest remains 18 tools, `log` stays read-only annotated, and schema,
  dispatch, instructions, cancellation recovery, SQLite, and PostgreSQL proofs
  move together
```

Each spec's Related Plans section gains a backlink to this file.

## 7. Invariants and Constraints

### 7.1 Must change

- Explicit read/log/watch accept current member routes and stable existing DM
  handles through one actor-aware resolver.
- Valid stable handles survive participant renames.
- Users and agents can enumerate all durable accessible DMs, including read
  and empty conversations.
- Human DM history headings and notification actions stop presenting opaque
  or unusable navigation.
- Python and the existing MCP tools expose the same operation semantics.

### 7.2 Must not change

- [IAN-6.4]'s queue naming/hash algorithm or existing queue names.
- `say @name` first-contact creation, deterministic reuse, permanent
  memberships, or `dm_started` one-time behavior.
- Sender snapshots, rename rules, name/alias uniqueness, or the rule that old
  names are not automatically retained.
- Bare read/watch, channel/subthread cursor rules, log `--since`/`--limit`,
  or high-water semantics.
- Existing `Message` and `Thread` field sets or message/thread JSON shapes.
- Global `list --all` behavior, despite its distinct diagnostic use.
- Watcher scheduling, queue modes, native waiter use, membership refresh, or
  notification claiming.
- MCP attachment, fixed-tool lifecycle, busy/cancellation machinery, resource
  semantics, or tool count.
- SimpleBroker schema, queue aliases, private tables, or dependency floors.
- Presence, activity timeout, member retirement, cleanup, or TUI process
  lifecycle.

### 7.3 Anti-mocking rules

- Resolver confidentiality, no-creation, empty-DM, cursor, and ordering tests
  use real `TautClient`, Taut state, and SimpleBroker queues on SQLite.
- The shared backend contract runs on real PostgreSQL through `bin/pytest-pg`.
- Do not mock queue peek, registry rows, memberships, member routes,
  `_thread_from_row()`, or watcher construction for integration acceptance.
- Narrow spies/fault doubles may prove validation ordering, that an
  inaccessible handle never opens a queue, or that duplicate filters
  canonicalize before watcher construction. They do not replace real-state
  tests.
- CLI tests use the real parser/dispatcher and renderer.
- MCP tests use the fixed manifest and real workspace-reactor command path.
  Schema snapshots alone are insufficient.
- Rename/reuse fixtures are built through public client operations and state
  APIs already used by production. Do not synthesize a second queue naming
  implementation in tests.

## 8. Dependency-Ordered Implementation Tasks

### Slice 0: Promote and verify the contract

Owner: spec/core implementer.

Boundary: active specs, Related Plans links, and this plan only.

Actions:

1. Apply section 6 to the three active specs with stable reference codes.
2. Remove or replace every statement that says bare read is the only DM
   history path or that opaque DM names cannot be logged.
3. Add reciprocal plan links.
4. Run docs references, plan-index validation, and whitespace checks.
5. Record the promotion baseline here.
6. Obtain independent confirmation that no contradictory DM access contract
   remains before behavior code starts.

Verification:

```bash
uv run --extra dev pytest tests/test_docs_references.py -q -n0
bin/check-plan-status-index
git diff --check
```

Stop gate: no code implementation against plan-only text.

### Slice 1: Add red addressing and resolver contracts

Owner: core implementer.

Boundary: `taut/addressing.py`, one shared client resolver seam, and focused
tests. No adapter changes.

Actions:

1. Add exact route/stable-selector parser tests without broadening unrelated
   command validators.
2. Add red tests for current route, alias route, rename, route reuse, stable
   handle, self, no-existing-DM, malformed metadata, pair/name mismatch,
   missing member/membership, absent handle, and another pair's real handle.
3. Prove every navigation miss creates no member/claim/activity/thread/
   membership/queue/notification state.
4. Implement one private resolver that accepts an explicit actor and returns
   canonical validated DM context needed by history, directory, labels, and
   watcher setup.
5. Prove another pair's handle is rejected before `queue()` or watcher runtime
   construction.

Red gate: the focused tests must fail because the selector/resolver behavior
does not exist, then pass after the smallest implementation.

Review gate: independent slice review checks operation-aware parsing,
validation order, confidentiality, and absence of `_say_dm()` reuse.

### Slice 2: Add core history and directory behavior

Owner: core implementer.

Boundary: `taut/client/_messaging.py`, `taut/client/_threads.py`, public
facade/type contracts, shared backend tests.

Actions:

1. Extend `read_unread()`/`read()` and `log()` through the shared resolver.
2. Preserve read activity/cursor behavior and make DM log actor/activity/
   cursor neutral.
3. Add `list_direct_messages()` with full validation, read/empty inclusion,
   stable sorting, and existing `Thread` values.
4. Keep bare list/all-list behavior byte-for-byte where unaffected.
5. Add SQLite shared-contract tests for all valid/invalid branches, sole-row
   deletion, caught-up DMs, concurrent latest-row staleness convergence, and
   name changes.
6. Run the same public contract on PostgreSQL.

Verification:

```bash
uv run --extra dev pytest tests/test_addressing.py tests/test_client.py tests/test_shared_contract.py -q
uv run --extra dev bin/pytest-pg --fast
```

Review gate: no queue alias, new index, state schema, or alternate hash
implementation; no activity write from DM log.

### Slice 3: Canonicalize watch selectors

Owner: watcher/core implementer.

Boundary: `TautClient.watch()`, existing watcher construction, watcher tests.

Actions:

1. Resolve explicit filters on the client owner thread before runtime
   construction.
2. Preserve ordinary canonical channel/subthread filters.
3. Deduplicate route/handle aliases of one DM before watcher construction;
   input order does not define scheduling order.
4. Keep bare dynamic membership behavior and notification-inbox inclusion.
5. Prove rename during watch does not retarget, later invocation follows the
   new route, empty DM is watchable, and invalid/nonparticipant selectors
   construct no runtime/queue.
6. Keep deterministic test barriers. Do not use timing sleeps for retarget or
   membership races.

Verification:

```bash
uv run --extra dev pytest tests/test_watcher.py tests/test_client.py -q
```

Review gate: `TautWatcher` continues to consume canonical names only and owns
no identity/state resolver.

### Slice 4: Add CLI parsing, labels, and actions

Owner: CLI implementer.

Boundary: list/read/log/watch adapters, shared rendering, notification actions,
CLI/registry/help tests.

Actions:

1. Add mutually exclusive `list --dms` and `--all`.
2. Update positional help to name accepted selector forms.
3. Route `--dms` to `list_direct_messages()` without changing bare list.
4. Supply human DM heading labels without changing `Message.thread` or JSON.
5. Render stable DM mention and `dm_started` actions purely from the pointer's
   thread string. Remove the existing `list_threads(all_threads=True)` DM-kind
   lookup and add a no-client/state-access proof for DM action selection.
   Preserve the separate existing channel mention reply-suffix probes.
6. Test human, JSON, quiet, global-option placement, `--`, help, and exact
   0/1/2 exit classes.
7. Apply the adversarial parser probes in section 9.

Verification:

```bash
uv run --extra dev pytest tests/test_cli.py tests/test_command_registry.py tests/test_terminal_text.py -q
```

Review gate: the adapter stays thin and does not query private state or derive
queue names.

### Slice 5: Update the fixed MCP surface

Owner: MCP implementer.

Boundary: MCP tool schemas/descriptions, input/dispatch models, instructions,
cancellation guidance, and extension tests. Tool count remains 18.

Actions:

1. Add the exact selector grammar to `read.thread` and `log.thread`.
2. Add `list.dms` and pre-dispatch mutual exclusion with `all`.
3. Dispatch DM directory through the public core method.
4. Preserve message/thread record schemas and `log` annotations.
5. Replace all bare-read-only DM guidance in `_tools.py`, `server.py`, specs,
   README, and tests.
6. Prove attached-workspace isolation, busy/rate-limit/cancellation behavior,
   content-free misses, and no parent-thread client access.
7. Before package completion, assert the 0.8.0 tag/floor rollout condition in
   section 2.7. Stop for version selection if it no longer holds.
8. Run real SQLite and PostgreSQL extension behavior.

Verification:

```bash
uv run --directory extensions/taut_mcp --extra dev pytest -q
uv run --extra dev bin/pytest-pg --fast
```

The PostgreSQL MCP lane must also pass in its repository-owned live-DSN
workflow; a local no-DSN skip is not backend evidence.

Review gate: exactly 18 tools, closed schemas, unchanged reactor ownership,
honest cancellation recovery, and a compatible core floor.

### Slice 6: Reconcile public and implementation documentation

Owner: implementing engineer.

Boundary: README, implementation maps, plan evidence, and durable lessons only
if a reusable correction was discovered.

Actions:

1. Update README command/API/MCP examples with explicit DM navigation and
   `list --dms`.
2. Update `docs/implementation/04-taut-architecture.md` with resolver
   ownership, confidentiality checks, directory derivation, and rendering
   boundary.
3. Update `docs/implementation/07-taut-mcp-architecture.md` with broadened
   existing-tool behavior and unchanged manifest/lifecycle.
4. Update `docs/implementation/06-command-extensions.md` only if its future
   TUI boundary needs the new public method named.
5. Reconcile spec, plan, implementation docs, code references, and tests into
   a closed traceability chain.
6. Run a repository-wide search proving the old "DM only via bare read"
   limitation is gone from active docs and code.

Verification:

```bash
rg -n "only public direct-message read path|only public DM|cannot inspect direct messages|opaque internal DM queue names are not valid|Explicit .*dm.* thread inputs are rejected" README.md docs/specs docs/implementation taut extensions tests
uv run --extra dev pytest tests/test_docs_references.py -q -n0
bin/check-plan-status-index
git diff --check
```

The `rg` command must return no active contradictory claim; historical plan
records may be explicitly exempted.

### Slice 7: Full verification and completed-work review

Owner: implementing engineer; review by a different agent family.

Actions:

1. Run focused and full core, PostgreSQL, CLI, watcher, MCP, docs, type, lint,
   format, build, and installed-artifact gates.
2. Run every enumerable probe in section 9.
3. Run independent completed-work review on the full diff and evidence.
4. Incorporate or explicitly answer every finding.
5. Record exact commands/results and residual risk in this plan.
6. Leave commit, release, tag, and publication to the repository owner.

Minimum final commands:

```bash
uv run --extra dev pytest -q
uv run --extra dev bin/pytest-pg
uv run --directory extensions/taut_mcp --extra dev pytest -q
uv run --extra dev ruff check .
uv run --extra dev ruff format --check .
uv run --extra dev mypy taut
uv run --directory extensions/taut_mcp --extra dev mypy taut_mcp
uv build
uv build --directory extensions/taut_mcp
bin/check-plan-status-index
git diff --check
```

Use the repository's canonical installed-wheel and release-precheck commands
from the current README/[TAUT-12.5] at implementation time. Do not copy a stale
release command into this plan as authority.

## 9. Test Diagram and Adversarial Acceptance Probes

| Flow or branch | Required firing proof |
|---|---|
| Selector grammar | valid mixed-case `@Name`, Taut alias, and exact lowercase base32 stable handle accepted where specified; missing `@` name, empty `@`, bad route chars, wrong DM prefix/length/alphabet/case, extra dots, whitespace, signs, and non-string Python values fail before state/queue access |
| Operation scope | read/log/watch accept both DM forms; say accepts only `@route`; join/leave/reply/rename/who retain their narrow forms |
| Current route | current name and alias derive the existing pair; known member with no DM, self route, and unknown route return the same content-free empty/not-found adapter result and create nothing |
| Rename/reuse | stable handle and an already-running watch stay on original pair; old name stops routing after rename absent alias; later reused name addresses the new pair |
| Registry validation | kind mismatch, wrong cardinality, duplicate ids, invalid id, missing actor, deterministic-name mismatch, missing member row, and either missing membership all fail closed before queue peek/watch |
| DM miss privacy | unknown/self/no-conversation routes, another pair's real handle, corrupt state, and an absent handle produce byte-identical content-free CLI/MCP results; no body, member, route, metadata, queue existence, warning, or log leak |
| No creation | every navigation/list miss leaves members, claims, activity where promised, registry, memberships, queues, notifications, and cursors unchanged |
| Log | route and handle return the same decoded chronological history; since/limit unchanged; cursor and actor activity unchanged; empty DM returns empty |
| Read | route and handle return the same oldest unread page; only selected cursor advances to last returned row; caught-up/empty returns empty; bare read unchanged |
| Watch canonicalization | route/handle duplicates produce one watched queue; input order makes no scheduling claim; empty existing DM starts; invalid selector builds no runtime; rename does not retarget; notification inbox remains |
| Directory contents | unread, caught-up, sole-row-deleted/empty, and renamed DMs appear; invalid/cross-pair/non-DM memberships do not; no-DM result is empty |
| Directory ordering | newest first; equal `last_ts` uses canonical name; `None` last and canonical among empties; one-call latest-row race may be stale but next call converges |
| Directory shape | existing `Thread` and list JSON fields only; `kind=dm`; canonical thread and exact two member ids; current human label; no connection/departure field |
| Human history | explicit and bare DM read/log/watch headings use current label; malformed global list-all fallback stays content-safe; JSON keeps canonical queue |
| Notification actions | DM mention uses stable log action; DM-started uses stable read action; DM action selection performs no client, identity, registry, list, or queue lookup; existing channel mention reply-suffix probes and channel/subthread/reply/reaction output remain unchanged |
| CLI parser | `list --all --dms` exits 1 before client; selector-like options after `--` stay positional; missing/extra args, help, globals before/after verb, human/JSON/quiet, and exit 0/1/2 fire |
| Python API | documented methods/signatures and existing values are exported/typed; no private resolver exported; non-string behavior is explicit and tested |
| MCP schema | exactly 18 tools; accepted selector union; malformed input rejected before child dispatch; `dms` default false; `all && dms` rejected; all four annotations remain |
| MCP execution | route/handle read/log and DM list use real attached client on child thread; isolation, busy, rate, cancellation, detach, resource snapshot, and structured-text agreement remain |
| Cancellation | started explicit/bare DM read may advance without response; later list/log recover state/history but do not claim delivery knowledge; no blind retry guarantee |
| Backends | the same public core and MCP behavior runs on real SQLite and PostgreSQL |
| Version gate | no `v0.8.0` tag permits current floor; presence of the tag blocks completion until coordinated version/floor update |
| Presence boundary | no new heartbeat, lease, timeout, connected flag, activity mutation, cleanup, or departed inference appears in schema/API/output |

Every syntax class, validation branch, exit class, flag combination, output
field, ordering rule, activity/cursor effect, and listed corrupt-state case
needs a firing test. Table-driven tests are preferred where failures remain
legible.

## 10. Failure Modes and Recovery Registry

| Failure | Observable result | State after failure | Recovery |
|---|---|---|---|
| Malformed selector | validation/usage error; CLI 1 or MCP schema error | no identity, activity, state, queue, or cursor access | correct the selector |
| Unknown route or no existing DM | not found/empty; CLI 2; typed MCP empty | no conversation created | send with `say @current-name` to start a DM, or choose an existing directory entry |
| Stable handle absent/inaccessible/corrupt | uniform content-free not found; CLI 2 | no queue peek or mutation | use `list --dms` / `list(dms=true)`; repair corrupt state separately |
| DM log member cannot resolve | empty/not found | no activity or cursor change | restore identity selection/rejoin, then retry |
| Read response lost/canceled | result absent; cursor may have advanced | selected cursor may reflect returned page | inspect directory unread state and cursor-neutral log; do not blind retry |
| Participant renames during explicit watch | watch remains on original canonical queue | no retarget | stop and invoke a new selector to resolve current routes |
| Route reused by another member | later `@old-name` selects new member's pair | original DM unchanged | use original stable handle from directory/history |
| Sole DM row deleted | directory row remains with `last_ts=None`; log/read empty | registry and memberships persist | watch the empty DM or send via current `@name` |
| Latest-row changes during list | one directory result may be stale | next list recomputes | rerun list |
| Notification pointer names stale actor | stable source action still points to DM | history availability follows normal access | run the stable action as recipient |
| 0.8.0 tagged before landing | compatibility gate fails | no publication under false floor | select next coordinated version and update manifests/locks/docs through release process |
| Backend/sidecar failure | ordinary concise error | no claimed repair | repair backend; retry observational operation |

## 11. Hardening Checklist

Plan-design checks:

- [x] Public contracts, error classes, and non-goals are explicit.
- [x] Stable queue naming is preserved exactly.
- [x] Identity-scoped authority is checked before queue access.
- [x] Actor activity and cursor effects are explicit per operation.
- [x] Rename, route reuse, empty-DM, corrupt-state, and notification couplings
  are explicit.
- [x] Watch canonicalization and owner-thread boundary are explicit.
- [x] Existing models/JSON and fixed MCP tool count are preserved.
- [x] Anti-mocking rules require real SQLite and PostgreSQL.
- [x] No schema migration, cleanup lifecycle, feature flag, or dual write is
  required.
- [x] Rollout order is spec, core, watcher/CLI, MCP, docs, then coordinated
  release only after version-floor verification.
- [x] Before release, rollback is code/spec reversal with no data recovery
  work because no new state is written. After release, old clients remain
  compatible with canonical queue names; reverting only the MCP schema would
  remove convenience without corrupting data.
- [x] The only version one-way gate is publishing a new MCP surface against an
  insufficient core floor. The explicit tag check prevents it.
- [x] Post-release success signals are explicit DM log/read/watch use, DM
  directory nonempty/empty rates, expected typed misses, no cross-pair access,
  unchanged cursor/activity behavior, stable MCP busy/error rates, and no
  watch retarget reports.

Implementation-evidence gates:

- [x] Proposed spec delta promoted and promotion baseline recorded.
- [x] Red tests observed before each behavior slice.
- [x] Every corrupt-state and cross-pair case rejects before queue access.
- [x] Navigation no-creation and DM-log no-activity effects pass.
- [x] Rename/reuse and running-watch behavior pass deterministically.
- [x] Empty/caught-up directory and ordering rules pass.
- [x] CLI parser/exit/output probes pass.
- [x] MCP manifest/schema/dispatch/cancellation probes pass with 18 tools.
- [x] Real SQLite and PostgreSQL shared contracts pass.
- [x] Version/floor gate passes immediately before completion.
- [x] Docs/traceability and stale-limitation search pass.
- [x] Independent completed-work review has no unresolved blocker.

## 12. Rollout, Rollback, and Residual Risk

Rollout is additive to persisted data and uses existing deterministic queues.
Land spec and core behavior first. CLI/watch can then consume the core
resolver. MCP must land only with a core version floor that contains the
behavior. No database migration, data backfill, broker alias installation, or
reindex is required.

Rollback before publication is a coordinated code/spec revert. Existing DM
queues and memberships remain valid because their naming and storage never
changed. After publication, rolling back core while leaving the broadened MCP
schema would be incompatible, so MCP must be rolled back first or together.
Rolling back only CLI/MCP convenience does not damage history.

Residual risks:

- Directory cost is O(current memberships) plus one latest/unread lookup per
  valid DM. This matches current list behavior and needs measurement only if
  real workspaces show material latency.
- Current display names can change between directory rendering and a later
  action. The stable handle prevents retargeting; labels are snapshots.
- A corrupt DM is hidden by the actor-scoped directory rather than repaired.
  That is deliberate fail-closed behavior. A separate diagnostic/repair
  feature may be warranted if corruption is observed.
- `list --all` retains its pre-existing global semantics. This plan does not
  treat it as the user-facing DM directory.

## 13. Out of Scope and Rejected Alternatives

- **SimpleBroker queue aliases:** rejected because aliases are global and
  cannot represent actor-relative member routing.
- **A new queue naming scheme:** rejected because the existing stable pair hash
  already provides the required durable identity and changing it would require
  migration.
- **Persisted per-member DM index:** rejected because memberships plus the
  retained registry already enumerate durable conversations, including empty
  ones.
- **`say dm.d_*`:** rejected for this slice. Sending remains person-addressed
  through the current route; stable handles are for reopening an existing
  conversation.
- **Presence-derived departure:** rejected. Connected/recently-active and
  explicit member retirement require separate lifecycle specs and must not
  gate durable history.
- **TUI implementation:** deferred to the future TUI product spec. This plan
  supplies its public typed core seam.
- **New MCP watch or DM tools:** rejected. Existing read/log/list tools are the
  smaller coherent surface; MCP has no live watch tool.
- **DM leave/delete/archive, group DMs, search, per-message read receipts,
  route-history aliases, auto-repair, cleanup, and storage migration:** out of
  scope.
- Release, tag, commit, or publication work.

## 14. Independent Review Loop

### Plan review

- Reviewer: a review-eligible different model family, invoked read-only.
- Reviewer reads this plan, cited spec sections, address/client/watcher
  boundaries, CLI renderers, MCP schemas/dispatch/instructions, tests, current
  version metadata, and the unrelated dirty-tree diff.
- Required challenge areas: actor-relative authority, route rename/reuse,
  corrupt state, no-creation/activity/cursor effects, empty-DM retention,
  directory ordering, watcher ownership, renderer lookup avoidance, MCP
  annotations/cancellation, version floor, and enumerable proof.
- Verdict: `APPROVED`, `APPROVED WITH CONDITIONS`, or `BLOCKED`.
- Every finding is reproduced and incorporated or explicitly answered in
  section 17 before spec promotion.

### Slice and completed-work review

- Review after spec promotion, resolver/core, watcher/CLI, MCP, and the
  complete diff.
- Supply the plan, promoted baseline, complete slice diff, exact red/green
  commands, and observed output.
- A review inspecting only tests or only production code is insufficient.
- Pre-existing unrelated coalescing changes are out of scope unless this work
  worsens or conflicts with them.
- Completion requires no unresolved blocker and a disposition for every
  suggestion.

## 15. Fresh-Eyes Review

A fresh reader must be able to answer:

1. Which exact strings select a DM, and on which commands?
2. Why is a stable queue handle not sufficient authority by itself?
3. What changes after a member rename or route reuse?
4. Which calls may create a DM and which categorically may not?
5. Which calls move a cursor or activity timestamp?
6. How are all durable DMs listed without new state?
7. Why can an empty DM still be watched?
8. Where does selector resolution stop and watcher ownership begin?
9. What does MCP add without adding a tool?
10. How does the future TUI consume this without private access?
11. Why is connected/departed state absent?
12. What blocks publication if 0.8.0 is already tagged?

Flag any requirement that lacks an owner, boundary, required action,
verification, or firing test.

## 16. Deviation Log

- 2026-07-28: The committed baseline advanced from `788cdd3884c29a68753e8ba9e244907d4e1a4455`
  to `3706d732db13f0ec7265d9b7e4e77601793d7a55` before implementation began
  because unrelated coalescing work landed. A direct diff confirmed no change
  to the three governing product specs, so the reviewed contract was promoted
  without redesign against the later commit.

## 17. Review Findings and Dispositions

Read-only Grok review on 2026-07-28 returned
`APPROVED WITH CONDITIONS`. Its four promotion blockers and two recommended
tightenings were reproduced and incorporated:

| ID | Severity | Disposition |
|---|---|---|
| DMN-F1 | Blocker | Incorporated. Section 6.3 now exactly replaces the remaining MCP-5 bare-read-only recovery paragraph, the rejecting property rows, and MCP-6's exact `read_cursor_advanced` guidance object. |
| DMN-F2 | Blocker | Incorporated. MCP `log` retains both `readOnlyHint=true` and `idempotentHint=true`. |
| DMN-F3 | Blocker | Incorporated. Singular `other` labels are actor-scoped; the existing global `list --all` diagnostic rendering remains explicit and unchanged. |
| DMN-F4 | High | Incorporated with DMN-F1. The old rejecting `chat thread`/`read.thread` rows are replaced, not retained; narrow `leave`/`who` and broad `read`/`log` forms are distinct. |
| DMN-F5 | Medium | Incorporated. Notification actions are pure pointer-string rendering and the plan explicitly removes the current `list_threads(all_threads=True)` lookup. |
| DMN-F6 | Low | Incorporated. Selector dedup remains required, but input order no longer claims watcher scheduling order. |
| DMN-F7 | Low | Strengthened. All syntactically valid DM selection misses use one content-free adapter result, preventing both conversation and member-route existence oracles. |
| DMN-F8 | High | Incorporated after confirmation review. Section 6.3 now replaces MCP-12's old explicit-DM-rejection proof in full while retaining paging, limit, forwarding, and backend evidence. |
| DMN-F9 | Medium | Incorporated after confirmation review. No-lookup language now applies only to DM action classification/construction; existing channel mention reply-suffix state probes remain explicit and unchanged. |
| DMN-F10 | Low | Incorporated after confirmation review. Corrected `deduplicated in before` to `deduplicated before`. |

Final read-only confirmation returned `APPROVED`: no unresolved finding,
F1–F10 adequate, Markdown fences balanced, and spec promotion no longer
blocked by plan-review findings.

The independent Slice 0 promotion review found two high-severity omissions in
the first applied diff: stale MCP cancellation recovery text and an incomplete
Python ownership boundary. Both were corrected. Its confirmation review
returned `APPROVED` with no remaining blocker or high-severity finding.

The independent core-slice review found malformed route-owner leakage plus
claim-owner races in the new non-healing agent-anchor and human-UID identity
paths. Red deterministic tests reproduced all three. The resolver now maps
malformed ids to the uniform DM miss and rechecks claim ownership before
authority or activity selection without healing the claim. The review also
identified missing enumerable and shared-backend tests; those were added. Its
final confirmation returned `APPROVED`.

The independent CLI/watcher-rendering review found that replacing the shared
DM-label mapping during another client operation stranded a running watch on
the old object. An interleaved log-then-new-DM watch test reproduced the
missing label. Operation resets now clear the stable mapping in place. The
reviewer's final confirmation returned `APPROVED`.

The independent MCP review found one proof gap rather than a runtime defect:
the content-free miss test asserted empty records but not byte-equivalent full
adapter results. The test now compares canonical JSON for an absent route and
another pair's real stable handle for both `read` and `log`. The reviewer
confirmed the strengthened proof and returned `APPROVED` with no remaining
finding.

The first completed-work review returned `BLOCKED` on two enumerable proof
gaps, not production defects. The corrupt-state matrix did not fire every
metadata/cardinality/membership branch or prove every corrupt read/log/watch
stopped before queue/runtime construction. The MCP suite also lacked a
DM-specific started-read cancellation and recovery proof. The matrix now has
13 corruption cases and runs read, log, directory, and watch with queue/runtime
failure spies. A deterministic test now covers both explicit and bare
committed DM reads whose MCP result is canceled, followed by
`list(dms=true)` and cursor/activity-neutral `log` recovery. Focused suites
passed, and the reviewer's confirmation returned `APPROVED` with no remaining
finding.

## 18. Verification Record

| Gate | Result |
|---|---|
| Spec baseline | `788cdd3884c29a68753e8ba9e244907d4e1a4455`; active governing spec files clean at plan start |
| Dirty-tree isolation | unrelated coalescing changes identified and preserved |
| Current naming implementation | inspected `taut/addressing.py::dm_queue_name`; plan keeps it unchanged |
| Current release metadata | core/MCP `0.8.0`, MCP `taut>=0.8.0`, latest local tag `v0.7.1` |
| Plan status index | `bin/check-plan-status-index`: passed |
| Documentation references | `uv run --extra dev pytest tests/test_docs_references.py -q -n0`: 10 passed |
| Diff whitespace | `git diff --check`: passed |
| Markdown structure | 66 plan fences, balanced |
| Independent plan review | Grok initial `APPROVED WITH CONDITIONS`; DMN-F1–F10 incorporated; final confirmation `APPROVED` with no unresolved finding |
| Spec promotion | promoted against `3706d732db13f0ec7265d9b7e4e77601793d7a55`; docs references (10 passed), plan index, and diff whitespace passed; independent review found and resolved two high omissions, then returned `APPROVED` |
| Core DM behavior | 31 addressing/core tests initially green; final direct-message matrix 38 passed; direct-message plus identity suite 73 passed before the final proof-only expansion; shared SQLite contract passed; targeted Ruff and mypy passed; independent review findings resolved and final verdict `APPROVED` |
| CLI and watch rendering | focused CLI red/green passed; full selected CLI/registry/terminal/watcher run had one fake-client regression, corrected and rechecked; dynamic watch label interleaving regression passed; targeted Ruff/mypy passed; independent review final verdict `APPROVED` |
| MCP DM behavior | focused red run failed only on the new selector/list/guidance contract; implementation then passed the focused matrix and full non-PostgreSQL extension suite. Exact 18-tool snapshot, stdio framing, closed selector schemas, pre-dispatch `all && dms` rejection, public-client dispatch, and canonical-JSON absent/cross-pair miss equivalence passed. Independent review final verdict `APPROVED` |
| Real PostgreSQL | `uv run --extra dev bin/pytest-pg --fast`: 199 shared plus 14 `taut-pg` tests passed; MCP `test_pg_conformance.py` against a disposable PostgreSQL 18 container: 6 passed, including route/stable DM navigation and directory |
| Documentation reconciliation | README, changelog, repository map, core architecture, command-extension TUI boundary, and MCP architecture updated; stale-limitation search returned no matches; docs references 10 passed; plan index and diff whitespace passed |
| Quality and artifacts | full root suite passed with one expected Windows-only skip; full non-PostgreSQL MCP suite passed with six live-PG skips covered separately; Ruff check, targeted changed-file format check, core/MCP mypy, both builds, metadata consistency (3 passed), and fresh-environment installed-wheel DM-surface smoke passed. Repository-wide format check still names three untouched historical plans; all 36 changed files pass |
| Version/floor gate | core/MCP remain `0.8.0`, MCP requires `taut>=0.8.0`, and local `v0.8.0` plus `taut_mcp/v0.8.0` tag query returned empty |
| Completed-work review | first verdict `BLOCKED` on two proof gaps; expanded corruption/preflight and DM cancellation/recovery tests incorporated; final verdict `APPROVED` with no unresolved finding |
| Behavior implementation | core, CLI/watch, MCP, public/implementation docs, backend proof, artifact gates, and independent review complete; repository owner authorized the targeted commit |
