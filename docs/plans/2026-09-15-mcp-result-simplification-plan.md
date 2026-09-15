# MCP Result Simplification Plan

Status: active — plan drafted 2026-09-15; fresh-eyes plan review returned
BLOCKED on the size estimate and five slice-instruction defects, all
incorporated below (see Review Log); two bounded Codex attempts produced no
verdict. Owner chose to omit `outputSchema` on 2026-09-15; this revision
resolves that branch and the three subsequent Codex review findings.
Implementation started 2026-09-15; slice evidence is recorded below.
Class: 5 (spec-changing). [DOM-5] risky trigger fires: this changes the
public MCP result contract, so the hardening-plans checklist applies. Plan
type: implementation with spec revision. Promotion strategy: A (in-file
spec edit lands first, code slices follow against the promoted text).

Owner: implementing engineer. The repository owner made the product decision
on 2026-09-15: MCP tool results should look like the CLI's `--json` output,
the result envelope's derived and static fields go away, parameter prose
should be as terse as CLI help, and `outputSchema` stays omitted. Closed
result schemas remain test-only oracles.

## Goal

Replace the six-field MCP result envelope with the CLI's record stream
wrapped in the one object MCP requires, move the three static guidance texts
into their tool descriptions, cut every parameter description to CLI-help
terseness, and keep `outputSchema` omitted, with a 21,000-byte serialized
`tools/list` manifest ceiling.

## Source documents

Surfaces consulted for this plan (declared per `docs/agent-context/README.md`):
`AGENTS.md`; `docs/program-theory.md` [THEORY-1] and [THEORY-4] item 1
("record-oriented CLI commands expose `--json`; rich terminal and protocol
surfaces use their own native machine or human transport");
`docs/agent-context/decision-hierarchy.md`;
`docs/agent-context/runbooks/writing-plans.md` §4b–§4d;
`docs/agent-context/runbooks/hardening-plans.md`;
`docs/agent-context/runbooks/review-loops-and-agent-bootstrap.md` §2;
`docs/specs/05-taut-mcp.md` [MCP-5], [MCP-6], [MCP-9], [MCP-12];
`docs/specs/02-taut-core.md` [TAUT-8.2] (record field sets);
`docs/implementation/07-taut-mcp-architecture.md`; the 0.9.7 CHANGELOG entry
that removed `outputSchema`; and the measurements below.

## Evidence

Measured on the v0.9.7 tree (compact JSON, `separators=(",", ":")`):

| Manifest component | v0.9.6 bytes | v0.9.7 bytes |
|--------------------|-------------:|-------------:|
| `inputSchema` (21 tools) | 24,562 | 24,562 |
| of which parameter description prose | 18,560 | 18,560 |
| of which structure (types, required, patterns) | 6,002 | 6,002 |
| `outputSchema` (21 tools) | 43,874 | 0 |
| tool descriptions | 3,863 | 3,863 |
| annotations | 1,874 | 1,875 |
| whole `tools/list` | 75,888 | 31,679 |

For scale, the CLI's own `--help` output for the same 18 commands totals
15,134 bytes. The manifest's prose (tool descriptions plus parameter
descriptions) is 22.4 KB today: parameter descriptions are paragraphs of
agent guidance where argparse help is one short sentence.

The removed 44 KB of output schemas was 21 inlined copies of the same
six-field envelope (about 1.7 KB each) plus the record schema. With the
envelope gone and every `description` key removed, the nine closed record
schemas total 5,468 bytes, but MCP has no cross-tool `$defs`, so inlining
them into 21 tools (`message` seven times, `member` and `workspace` three
times each, `thread` twice) plus a 174-byte wrapper per tool costs
14,357 bytes. Types-only schemas would save only 3.8 KB of that and give up
the closed-shape guarantee, so the choice is closed schemas or none.

Measured floors after this plan:

| Shape | Approx bytes |
|-------|-------------:|
| terse parameter prose, no `outputSchema` | 17,000 |
| terse parameter prose, closed `outputSchema` | 31,500 |

Of the envelope fields: `empty` equals `records == []`; `record_type` is
fixed per tool by the [MCP-6] table; `workspace` echoes the caller's input
except on `attach_workspace`, whose record already carries it; `guidance`
has three codes in the whole server, each a constant string attached to one
condition the client can already see; `warnings` is the one field with a job
because MCP has no stderr, and it is empty on nearly every call.

## Owner decision: omit `outputSchema` (2026-09-15)

The owner chose omission, in this order of weight:

1. No demonstrated agent-facing benefit or host requirement justifies the
   measured 14,357-byte addition. The intended teaching surface is tool and
   parameter descriptions. The installed SDK can validate declared output
   schemas, but that capability does not establish a shipped-host need.
   Host rendering and reliance claims have not been surveyed across all
   hosts; this decision does not depend on a universal claim about them.
2. This retains 0.9.7's approach and mirrors the CLI's model: the public
   contract lives in the specs and tests validate real results against
   closed schemas; no machine-readable output schema is advertised.
3. Adding schemas later is an isolated, additive change. Advertising them
   now creates a public dependency whose later removal needs a contract
   change and changelog entry.

The tradeoff is explicit: clients get no advertised result schema for
runtime validation. The test oracle and real-result validation stay in
place. Reconsider only when a concrete client requirement earns the cost.
The ceiling is 21,000 bytes. There is no alternative execution branch.

## Revision scope

This is an owner-directed Class 5 plan revision within the existing dated
plan, not implementation or spec promotion. The pre-revision review found
three execution defects: a premature mapping link, an inconsistent omit
branch, and old schema assertions left past their migration slice. This
revision addresses all three. Verification is document gates, inspection
of retained executable seams, and an independent scoped review. No runtime
behavior changes in this revision.

## Context and key files

Read these before editing. Anchors are symbol names; line numbers drift.

- `extensions/taut_mcp/taut_mcp/_tools.py` — manifest owner.
  `ToolDefinition.to_mcp()` builds each `types.Tool` with `input_schema=`
  only and adds a `"$schema"` key; the 21-entry `RECORD_TYPE_BY_TOOL` and
  `DOMAIN_TOOL_NAMES`; the parameter description constants
  (`ATTACH_WORKSPACE_DESCRIPTION`, `WORKSPACE_DESCRIPTION`,
  `DETACH_WORKSPACE_DESCRIPTION`, `TOKEN_DESCRIPTION`, `CHANNEL_DESCRIPTION`,
  `CHANNEL_PROPERTY_DESCRIPTION`, `CHAT_DESCRIPTION`, `CHAT_OR_DM_DESCRIPTION`,
  `READ_THREAD_DESCRIPTION`, `LIMIT_DESCRIPTION`,
  `EXACT_MESSAGE_ID_DESCRIPTION`, `REACTION_DESCRIPTION`) plus inline
  description strings inside `TOOL_DEFINITIONS` for `persona`, `name`,
  `target`, `text`, `topic`, `since`, the six `search` selectors, `reindex`,
  and `list.all`/`list.dms`; `MESSAGE_ID_PATTERN`. `_tools.py` imports
  `jsonschema` and `mcp` but not `taut`; nothing pins that today (see
  invariant 6).
- `extensions/taut_mcp/taut_mcp/_commands.py` — child-side dispatcher.
  Carries a second, 18-entry `RECORD_TYPE_BY_TOOL`; `execute_command`
  returns `CommandRecords(record_type, records)`; `record_object` serializes
  each domain object with 19-digit string timestamps.
- `extensions/taut_mcp/taut_mcp/_workspace_reactor.py` —
  `WorkspaceCommandOutcome` carries `record_type` and is constructed in two
  places (the `_execute_command` success path and the control-drain canceled path);
  caught ordinary-error branches assign `command_record_type = RECORD_TYPE_BY_TOOL[...]`.
- `extensions/taut_mcp/taut_mcp/_process_reactor.py` — result assembly.
  `workspace_result(records, *, workspace, warnings)` and
  `command_result(*, name, record_type, records, warnings, workspace)` build
  the envelope; `READ_GUIDANCE`, `MESSAGE_NOT_DELETED_GUIDANCE`,
  `MESSAGE_REACTION_NOT_SENT_GUIDANCE`; `list_workspaces` produces the only
  process-level warning. Two runtime couplings to the envelope live here:
  `execute_tool` guards with `if name not in RECORD_TYPE_BY_TOOL` using the
  18-entry `_commands` map as the set of CLI-shaped tools, and then reads
  `ensured.get("workspace")` from the top level of the ensure payload and
  asserts it is a string.
- `extensions/taut_mcp/taut_mcp/server.py` — `_result(payload)` wraps any
  payload as `structured_content` plus one `TextContent` of
  `canonical_json(payload)`; no envelope knowledge, no change. Its
  `INSTRUCTIONS` string mentions none of `guidance`, `empty`, `record_type`.
- `extensions/taut_mcp/tests/_result_schemas.py` — test-side oracle:
  `RECORD_SCHEMAS` (nine record types, with descriptions),
  `result_schema(record_type)`, `result_schema_for_tool`.
- Tests touching the envelope or `output_schema`:
  `extensions/taut_mcp/tests/test_tools.py` (`_assert_result`;
  `test_manifest_omits_output_schema_and_results_stay_closed`; literal
  description asserts in `test_exact_message_tool_manifest_contract` and the
  `message_react` and `search` contract tests; the sha256 manifest hash in
  `test_exact_tool_manifest_snapshot`, which covers name, description,
  inputSchema, and annotations and excludes outputSchema; the exact guidance
  tests around `test_empty_reaction_result_has_content_free_guidance`),
  `test_stdio_server.py` (the `call()` helper inside
  `test_stdio_all_cli_shaped_tools_return_schema_valid_canonical_results`,
  the `assert all(tool.output_schema is None ...)` line, the literal
  envelope dicts for search, attach, detach, and `list_workspaces`, the
  `guidance` asserts after `message_delete` and `read`, and the direct
  `detach_workspace`/`list_workspaces` calls in
  `test_broken_stdout_after_initialize_is_a_clean_transport_exit`),
  `test_process_reactor.py` (about fifteen `["workspace"]` reads from the
  envelope top level), `test_resource.py` (about twelve `["workspace"]` reads
  and one `record_type == "notification"`), `test_pg_conformance.py`,
  `test_channel_tools.py`, `test_dual_era_contract.py`.
- `docs/specs/05-taut-mcp.md` — [MCP-6] defines the envelope; [MCP-5]
  carries the exact tool-description table, the parameter-description table,
  and the `say.target` paragraph that names the empty envelope; [MCP-10]
  and [MCP-12] restate envelope literals and the guidance rule.
- `docs/implementation/07-taut-mcp-architecture.md` — the ownership table
  still says `_tools.py` owns "output schemas" (stale since 0.9.7) and a
  paragraph says "Closed output schemas require 19-digit strings". The phrase
  "result envelopes" in "One SDK server, two wire eras" refers to the SDK's
  protocol envelopes and is correct as is.

The `taut://notifications/current` resource ([MCP-7]) has its own shape and
is not part of this change.

## Invariants and constraints

These must remain true after every slice:

1. Every successful tool returns `structuredContent` that is a JSON object
   (MCP requires an object, never a bare array), and the single text content
   block is its canonical JSON serialization ([MCP-6] "Canonical JSON").
2. Record field sets and values are unchanged: [TAUT-8.2] and [IAN-7.2]
   records, the closed `deletion`, `reaction`, `channel`, `thread`,
   `search_hit`, and `workspace` shapes, and 19-digit string timestamps
   everywhere [TAUT-3.5] applies.
3. A single logical result is still a one-record array; an ordinary empty or
   not-found outcome is a successful result with an empty array, never a
   tool error.
4. Notification warnings precede search warnings, both channels are cleared
   before every domain command, and no warning leaks into the next call.
   `list_workspaces` still surfaces the fixed stalled-reservation warning.
5. Tool errors are unchanged: `isError: true`, one text block, no
   `structuredContent`.
6. `_tools.py` and the new `_results.py` import nothing from `taut` or from
   `taut_mcp._commands`. Nothing pins this today; Slice 2 adds a subprocess
   probe to `test_results.py` so it stays pinned.
7. Tool names, input schemas' types, patterns, bounds, and required lists,
   annotations, and the 21-tool count are unchanged. Only description prose
   and the `$schema` key change in `inputSchema`.
8. No dual-era result shape. One contract, promoted before code.

Hidden couplings:

- `execute_tool` in `_process_reactor.py` reads the canonical workspace from
  the ensure payload's top-level `workspace` key. After Slice 3 that key no
  longer exists; Slice 3 changes the read to the record.
- `execute_tool` uses the 18-entry map as a membership test for CLI-shaped
  tools. Consolidating to the 21-entry map without changing the guard would
  admit the three lifecycle tools into child dispatch; Slice 2 switches the
  guard to `DOMAIN_TOOL_NAMES` and adds a firing test.
- `outputSchema` remains absent. `ClientSession` therefore does not validate
  the application result shape automatically; retain explicit validation
  against the test oracle in stdio tests, including lifecycle results.
- `record_type` has no runtime consumer once the envelope is gone; the
  shared map stays as a test-oracle selector and tool-coverage contract.

## Decisions

### One result shape, mirroring the CLI

Every tool returns:

```json
{"records": [ ...records... ]}
```

with an optional second key, `"warnings": [ ...strings... ]`, present only
when at least one warning exists. There is no `empty`, `record_type`,
`guidance`, or `workspace` key. The CLI prints one record per line and puts
warnings on stderr; this is that stream wrapped in the one object MCP
requires, with `warnings` as the stderr analogue. Agents read
`payload.get("warnings", [])`.

Rejected: returning the bare record for single-record tools. Eight of the
fourteen single-record tools have a documented empty outcome (`say` on a
stable-handle miss, `channel_show`, `channel_topic`, `message_show`,
`message_delete`, `message_react`, `detach_workspace`), which would force a
second shape for empty. One rule is worth one extra level of nesting.

Rejected: per-tool array names (`messages`, `members`). Seven names for one
rule; agents learn `records` once.

### Guidance becomes description

The three guidance texts move into the descriptions of `read`,
`message_delete`, and `message_react` (exact strings in the delta).
Descriptions are read once at discovery; results never carry prose. The
[MCP-9] instructions already state the cursor and blind-retry rules (items
10, 13, 14) and need no change; the absorbed sentences add no rule.

### Parameter prose at CLI-help terseness

Every input property description becomes one short sentence, as argparse
help is. Grammar, reserved names, and range rules that a schema `pattern`,
`enum`, `minimum`, or `maxLength` already enforces are not restated in
prose. Cross-tool remarks ("used by X and Y") are dropped: the property
lives on the tool it describes. The long workspace-resolution guidance
stays only on `attach_workspace.workspace` and in [MCP-9] items 2 and 3.
The exact table is in the delta.

### Closed schemas stay in the test oracle

`extensions/taut_mcp/tests/_result_schemas.py` retains all nine
`RECORD_SCHEMAS` entries, including their descriptions and constraints.
Only `result_schema(record_type)` changes to the closed `records` plus
optional `warnings` wrapper. `result_schema_for_tool` stays available.
No schema moves into production and no tool advertises `outputSchema`.

Remove `$schema` from input schemas only. The test oracle may retain its
explicit Draft 2020-12 declaration; it contributes no manifest bytes.

### One owner for shared result plumbing

New module `extensions/taut_mcp/taut_mcp/_results.py` owns
`MESSAGE_ID_PATTERN`, the 21-entry `RECORD_TYPE_BY_TOOL`, `DOMAIN_TOOL_NAMES`,
and `tool_result(records, *, warnings)`. It imports only the standard
library. `_tools.py`, `_commands.py`, and `_process_reactor.py` import from
it; the duplicate 18-entry map in `_commands.py` is deleted. The test oracle
uses that shared map while retaining ownership of schemas. Real-result
validation and independent exact-dict assertions preserve the closed record
contract without adding a runtime schema dependency.

### Size budget is a gate, set from measurement

A test serializes the tool manifest compactly and asserts a total of at most
21,000 bytes, against the estimated 17,000-byte result. This is a wire-size
budget, not a claim about model-visible token usage. The test prints the
per-field byte breakdown on failure. If the measured total after Slice 6
exceeds the ceiling, stop and report the breakdown; do not cut record fields,
tool descriptions, or schema constraints to fit. Test-only schema changes
cannot reduce this manifest.

### Versioning

This breaks the wire result shape. `taut-mcp` is pre-1.0; the change ships
as `taut-mcp` 0.10.0 with a CHANGELOG entry under `## Unreleased` naming the
old and new shapes. No compatibility shim, no dual shape, no negotiation.
The core package is untouched.

## Spec baseline

- `c24cec07e426227454d6aff949e8752835a87965` (main, two commits after tag
  `v0.9.7`; `e43809b` added the inbox-claim sentence to the [MCP-5]
  annotations paragraph, after this plan's anchor, and every delta anchor
  was re-verified to match exactly once at this SHA) —
  `docs/specs/05-taut-mcp.md`, `docs/specs/02-taut-core.md` [TAUT-8.2].
- Promotion baseline identifier: `801554c`.

## Proposed spec delta

Promotion strategy:

| Spec file | Strategy | Sections touched |
|-----------|----------|------------------|
| `docs/specs/05-taut-mcp.md` | A — in-file edit, text before link claims | [MCP-5] annotations paragraph, `read` rationale paragraph, `say.target` paragraph, parameter table, tool-description table (3 rows); [MCP-6] envelope, guidance, warnings, and example literals; [MCP-10] one sentence; [MCP-12] four bullets; Implementation Mapping; Related Plans |

Each item quotes the current anchor text and gives the exact replacement.
Anchors that span a line wrap in the file are quoted unwrapped; match on
the words, not the line breaks.

### [MCP-6] — replace the opening paragraph

Anchor: the paragraph beginning "Successful tools return `structuredContent`
conforming to the fixed result envelope" through "…or the MCP-owned workspace
lifecycle record:" (immediately before the `record_type` table).

> Successful tools return `structuredContent` that mirrors the CLI's `--json`
> output: the record stream the CLI would print, wrapped in the one object MCP
> requires. The object is `{ "records": array }` plus an optional
> `"warnings": array` of strings that is present only when at least one
> warning exists. There is no other top-level field. A single logical result
> is still a one-record array, and an ordinary empty or not-found outcome is
> `{ "records": [] }`. The text content block is the canonical JSON
> serialization of `structuredContent`, for clients that do not consume
> structured output.
>
> The manifest carries input schemas only: `tools/list` omits `outputSchema`.
> Closed result shapes are enforced by validating real tool results against
> closed result schemas in the test suite. Each tool returns one fixed
> record shape, corresponding to the [TAUT-8.2] record or the MCP-owned
> workspace lifecycle record; the record type is fixed per tool and is not
> carried in the result:

The table that follows keeps its rows; rename its middle column header
from `record_type` to `Record schema`.

### [MCP-6] — replace the guidance paragraphs

Anchor: from "`guidance` is an ordered array of objects with exactly `code`,
`message`, and `action` string fields." through "…is not a warning,
authorization signal, or claim that response delivery proves whether the
operation committed."

> Results carry no prose. The effect disclosures that earlier releases
> returned as a `guidance` array are part of the [MCP-5] descriptions of
> `read`, `message_delete`, and `message_react` and of the [MCP-9]
> instructions. An empty `message_delete` or `message_react` result is
> `{ "records": [] }` and reveals nothing about why.

### [MCP-6] — replace the missing-detach literal

Anchor: "missing detach returns `{ "empty": true, "guidance": [],
"record_type": "workspace", "records": [], "warnings": [], "workspace": null }`."

> missing detach returns `{ "records": [] }`.

### [MCP-6] — warnings sentence

Anchor: "Its completion returns both channels in deterministic
notification-then-search order, even when search otherwise returns no
records, and no warning leaks into the next call."

> Its completion returns both channels in deterministic
> notification-then-search order as the `warnings` array, which is omitted
> when both channels are empty, and no warning leaks into the next call.

### [MCP-6] — empty search sentences

Anchor: "Empty search returns the ordinary envelope with
`record_type: "search_hit"`, `records: []`, and `guidance: []`."

> Empty search returns `{ "records": [] }`.

Anchor: "returns the empty `search_hit` success envelope above; it is not a
tool error."

> returns the empty `search_hit` result above; it is not a tool error.

### [MCP-6] — empty-result sentence

Anchor: "The ordinary Taut empty/not-found outcome is a successful MCP result
with `empty: true`; it is not a protocol error."

> The ordinary Taut empty/not-found outcome is a successful MCP result with
> `"records": []`; it is not a protocol error.

### [MCP-6] — channel metadata literal and the three guidance mentions

Anchor: "returns exactly `{ "empty": true, "guidance": [], "record_type":
"channel", "records": [], "warnings": [], "workspace": "<canonical>" }`."

> returns exactly `{ "records": [] }`.

Anchor: "return byte-equivalent empty `deletion` results with the
content-free guidance above;" → "return byte-equivalent empty `deletion`
results;".

Anchor: "returns the same empty `message` result with `guidance: []`;" →
"returns the same empty `message` result;".

Anchor: "return byte-equivalent empty `reaction` results with the
content-free guidance above." → "return byte-equivalent empty `reaction`
results."

### [MCP-5] — `say.target` paragraph (stable-handle miss)

Anchor: "normalized to the ordinary empty `message` envelope: `empty=true`,
`record_type="message"`, empty `records`, `guidance`, and `warnings`, plus
the canonical workspace."

> normalized to the ordinary empty `message` result `{ "records": [] }`.

### [MCP-5] — annotations paragraph

Anchor: "are disclosed by description and structured guidance, not by the
destructive flag." → "are disclosed by description, not by the destructive
flag."

### [MCP-5] — `read` rationale paragraph

Anchor: "and its description plus the structured cursor guidance disclose the
consumption so a host that pre-approves non-destructive tools still shows the
agent the effect." → "and its description discloses the consumption so a host
that pre-approves non-destructive tools still shows the agent the effect."

### [MCP-5] — parameter description table (replace whole)

Anchor: the paragraph beginning "Every input property has a nonempty
normative `description`." through the end of the table that follows it
(the last row today is `topic`; replace every row, including any after it).

> Every input property has a nonempty normative `description` of one short
> sentence, in the register of CLI help. Rules that the schema already
> enforces (`pattern`, `enum`, `minimum`, `maximum`, `maxLength`) are not
> restated in prose. Schema snapshot tests include these descriptions.
> Input schemas carry no `$schema` key.
>
> | Property | Exact description |
> |----------|-------------------|
> | `attach_workspace.workspace` | Absolute local directory of an existing Taut project; the result carries its canonical identifier. |
> | `detach_workspace.workspace` | Canonical workspace identifier from attach_workspace or list_workspaces. |
> | CLI-shaped `workspace` | Canonical workspace identifier, or the absolute local directory of an existing Taut project. |
> | `token` | Existing Taut continuity token for this workspace; never returned and never invented. |
> | `join.thread`, `reply.thread`, `channel_rename.old_name`, `channel_rename.new_name` | Top-level Taut channel name. |
> | `channel_show.channel`, `channel_topic.channel` | Top-level Taut channel name. |
> | `leave.thread`, `who.thread` | Taut channel, or a `<channel>.<19-digit-message-id>` subthread. |
> | `log.thread` | Channel, subthread, `@name-or-alias` DM, or stable `dm.d_*` handle. |
> | `read.thread` | Optional channel, subthread, `@name-or-alias` DM, or stable `dm.d_*` handle; omit for every joined thread. |
> | `join.persona` | Optional persona text for this member; null leaves it unchanged. |
> | `set_name.name` | New display name for this member. |
> | `say.target` | Channel, subthread, `@name-or-alias` DM (may create one), or stable `dm.d_*` handle (existing conversation only). |
> | `text` | Nonblank message text. |
> | `channel_topic.topic` | Channel topic of at most 500 characters with no line breaks, or null to clear it. |
> | `message_show.msg_id`, `message_delete.msg_id`, `message_react.msg_id` | Exact 19-digit Taut message id, as a string. |
> | `reply.msg_id` | Parent message id, or a unique suffix of at least 4 digits among the channel's most recent 1000 ids. |
> | `message_react.reaction` | Configured reaction slug. |
> | `read.limit` | Maximum records per selected thread, 1 through 1000; default 100. |
> | `inbox.limit` | Maximum notifications, 1 through 1000; default 1000. |
> | `log.limit` | Maximum most-recent messages, 1 through 1000; default 100. |
> | `search.limit` | Maximum hits, 1 through 1000; default 50. |
> | `log.since` | Exclusive lower bound: ISO 8601, Unix time, or 19-digit message id; null for none. |
> | `search.query` | Nonblank search text. |
> | `search.channels` | Channel names to search; empty means every registered channel. |
> | `search.direct_messages` | `@name-or-alias` or stable `dm.d_*` DM selectors to search. |
> | `search.all_direct_messages` | Search every accessible DM. |
> | `search.from_member` | Author name or alias filter; null for none. |
> | `search.kinds` | Message kinds to include; empty means all. |
> | `search.before` | Exclusive upper 19-digit message-id bound; null for none. |
> | `search.reindex` | Rebuild the search index before querying. |
> | `list.all` | List every registered thread; exclusive with dms. |
> | `list.dms` | List every accessible DM; exclusive with all. |

### [MCP-5] — tool-description table, three rows

Replace the `read` description cell with:

> Return oldest unread messages and advance each selected cursor through its returned page. `thread` may select a channel, subthread, `@name-or-alias` DM, or stable `dm.d_*` conversation. Omit it for all joined chat threads. Cursors advance only through the returned records and no message history is deleted; use log for cursor-neutral rereads, and after an uncertain read inspect list before retrying.

Replace the `message_delete` description cell with:

> Physically and irreversibly delete one exact ordinary message authored by this member, including after leaving its thread. It does not cascade to notifications, sub-threads, memberships, cursors, or thread registry state and is not recall. An empty result means no matching deletable own message was found; verify the full 19-digit message id and current author identity before retrying.

Replace the `message_react` description cell with:

> Send one configured reaction to the current audience of an exact ordinary message, excluding this member. Validates against the workspace's attachment-time reaction vocabulary, advances this member's high-water cursor through the target, then attempts one atomic best-effort notification broadcast to every requested inbox. Repeating may deliver duplicates. An empty result means no reactable message with a current recipient was found; verify the full 19-digit message id, current membership, and that another current thread member exists before retrying.

### [MCP-10] — delete scan sentence

Anchor: "every ineligible target uses the same content-free empty result and
guidance as an absent target." → "every ineligible target uses the same empty
result as an absent target."

### [MCP-12] — four bullets

Anchor (snapshot bullet): "…including every property description, the common
`guidance` field and guidance-entry schema, rejection of additional
properties, and canonical text/structured parity;" →
"…including every property description, the `records`/optional-`warnings`
result object, omission of `outputSchema`, rejection of additional
properties, a serialized tool-manifest size ceiling of 21,000 bytes, and
canonical text/structured parity;".

Anchor (`message_delete` snapshot bullet): "both record-type maps and command
union agree" → "the record-type map and command union agree".

Anchor (delete bullet): "Empty `message_delete` returns exactly one
content-free `message_not_deleted` guidance entry; empty `message_show` and
every unaffected successful tool retain their declared guidance." → "Empty
`message_delete` returns `{ "records": [] }`; empty `message_show` and every
unaffected successful tool return the same shape."

Anchor (read bullet): the bullet beginning "every successful nonempty `read`
returns exactly one `read_cursor_advanced` guidance entry" through "canonical
text and structured content agree." →

> every successful `read` returns only `records` (plus `warnings` when
> present); canonical text and structured content agree.

The rest of that bullet ("Real-state inspection proves…") is unchanged.

### Implementation Mapping (Slice 2, after the module exists)

Do not apply this item in Slice 1. Replace the [MCP-5]–[MCP-6] row's owner cell with:
`extensions/taut_mcp/taut_mcp/_tools.py`,
`extensions/taut_mcp/taut_mcp/_results.py`,
`extensions/taut_mcp/taut_mcp/_commands.py`,
`extensions/taut_mcp/taut_mcp/server.py`.

### Related Plans

Add at the top of the list:

> - `docs/plans/2026-09-15-mcp-result-simplification-plan.md` — replaces the
>   six-field result envelope with the CLI-shaped `records` object, moves
>   guidance into descriptions, cuts parameter prose to CLI-help terseness,
>   and caps manifest size.

## Deviation Log

| Date | Slice | Deviation | Reason | Spec edit |
|------|-------|-----------|--------|-----------|
| 2026-09-15 | Slice 1 | Split reply message-id prose from exact-id tools | Existing reply schema accepts suffixes; generic exact-id prose contradicted invariant 7 | [MCP-5] proposed parameter table corrected before promotion |
| 2026-09-15 | Plan revision, before Slice 1 | Omit `outputSchema`; retain schemas and explicit validation in tests; remove former Slice 5; fix mapping and test migration order | Owner decision and subsequent Codex findings F1–F3 | Proposed [MCP-6]/[MCP-12] delta updated; governing spec not yet changed |

## Required reading and comprehension check

Before Slice 2, the implementer reads [MCP-6] as promoted,
`_process_reactor.py::command_result` and `::execute_tool`,
`_workspace_reactor.py::_execute_command`, and answers in the handoff:

1. Which tool produces a warning that does not come from a `TautClient`
   warning list, and where must it still appear after this change?
   (Answer: `list_workspaces`, stalled-reservation warning, in `warnings`.)
2. Why must `_results.py` import neither `taut` nor `taut_mcp._commands`?
   (Answer: `_commands` pulls `taut.client`; the manifest must stay
   importable without the client, and Slice 2's subprocess probe pins it.)
3. After Slice 3, where does `execute_tool` get the canonical workspace?
   (Answer: `ensured["records"][0]["workspace"]`, the attach record.)

## Slices

Dependency order. Each slice is one commit that leaves the MCP lane green.
Run the per-slice gate before moving on.

### Slice 0 — independent plan review

Initial review and owner decision recorded 2026-09-15 (see Review Log and
Deviation Log). Verify this revision with a scoped independent review and
disposition its findings before Slice 1.

### Slice 1 — spec-promotion slice

Files: `docs/specs/05-taut-mcp.md` only.

1. Apply the proposed behavior text and Related Plans item verbatim. Defer
   the Implementation Mapping item to Slice 2, when `_results.py` exists.
   This preserves strategy A and the path-existence gate.
2. Run `uv run pytest tests/test_docs_references.py -q -n 0` and
   `uv run python bin/check-doc-paths`.
3. Commit: `Promote CLI-shaped MCP result contract`.
4. Record the commit SHA as the promotion baseline identifier in "Spec
   baseline" above.

Stop gate: if applying an item requires touching a sentence not listed in
the delta, stop and add it to the delta first; do not improvise spec text.

### Slice 2 — `_results.py` owns the result contract (green)

Files: create `extensions/taut_mcp/taut_mcp/_results.py`; modify
`extensions/taut_mcp/taut_mcp/_tools.py`,
`extensions/taut_mcp/taut_mcp/_commands.py`,
`extensions/taut_mcp/taut_mcp/_process_reactor.py`; create
`extensions/taut_mcp/tests/test_results.py`. Keep
`extensions/taut_mcp/tests/_result_schemas.py` and every test import of it
untouched in this slice so the suite stays green; Slice 3 updates only its
result wrapper. Also modify `docs/specs/05-taut-mcp.md` to apply the deferred
Implementation Mapping item after creating `_results.py`.

Red test first, `extensions/taut_mcp/tests/test_results.py`:

```python
from __future__ import annotations

import subprocess
import sys

from taut_mcp._results import (
    DOMAIN_TOOL_NAMES,
    RECORD_TYPE_BY_TOOL,
    tool_result,
)
from taut_mcp._tools import TOOLS


def test_every_tool_has_a_record_type() -> None:
    assert set(RECORD_TYPE_BY_TOOL) == {tool.name for tool in TOOLS}
    assert DOMAIN_TOOL_NAMES == frozenset(RECORD_TYPE_BY_TOOL) - {
        "attach_workspace",
        "detach_workspace",
        "list_workspaces",
    }


def test_tool_result_omits_warnings_when_empty() -> None:
    assert tool_result([]) == {"records": []}
    assert tool_result([{"a": 1}], warnings=()) == {"records": [{"a": 1}]}
    assert tool_result([], warnings=("w",)) == {"records": [], "warnings": ["w"]}


def test_results_and_tools_import_without_the_client() -> None:
    probe = (
        "import sys, taut_mcp._results, taut_mcp._tools;"
        "print(sorted(m for m in sys.modules if m.startswith(('taut.', 'taut_mcp._commands'))))"
    )
    completed = subprocess.run(
        [sys.executable, "-c", probe], capture_output=True, text=True, check=True
    )
    assert completed.stdout.strip() == "[]"
```

Run: `uv run --project extensions/taut_mcp --extra dev pytest extensions/taut_mcp/tests/test_results.py -n 0 -q`
Expected: ImportError on `taut_mcp._results`.

Implementation, `extensions/taut_mcp/taut_mcp/_results.py`:

```python
"""Shared result plumbing: record types and the result object.

Governed by [MCP-6]. Imports only the standard library so the manifest stays
importable without the Taut client.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

MESSAGE_ID_PATTERN = r"^[0-9]{19}$"

RECORD_TYPE_BY_TOOL: dict[str, str] = {
    "attach_workspace": "workspace",
    "detach_workspace": "workspace",
    "list_workspaces": "workspace",
    "join": "message",
    "leave": "message",
    "set_name": "member",
    "say": "message",
    "reply": "message",
    "message_show": "message",
    "message_delete": "deletion",
    "message_react": "reaction",
    "read": "message",
    "inbox": "notification",
    "log": "message",
    "search": "search_hit",
    "list": "thread",
    "channel_show": "channel",
    "channel_topic": "channel",
    "channel_rename": "thread",
    "who": "member",
    "whoami": "member",
}
DOMAIN_TOOL_NAMES: frozenset[str] = frozenset(RECORD_TYPE_BY_TOOL) - {
    "attach_workspace",
    "detach_workspace",
    "list_workspaces",
}


def tool_result(
    records: Sequence[dict[str, Any]],
    *,
    warnings: Sequence[str] = (),
) -> dict[str, Any]:
    """Build the one [MCP-6] result object; ``warnings`` appears only if nonempty."""

    payload: dict[str, Any] = {"records": list(records)}
    if warnings:
        payload["warnings"] = list(warnings)
    return payload
```

Then:

- `_tools.py`: delete its `MESSAGE_ID_PATTERN`, `RECORD_TYPE_BY_TOOL`, and
  `DOMAIN_TOOL_NAMES` definitions and add
  `from ._results import DOMAIN_TOOL_NAMES, MESSAGE_ID_PATTERN, RECORD_TYPE_BY_TOOL`
  so existing test imports from `_tools` keep working.
- `_commands.py`: delete the 18-entry `RECORD_TYPE_BY_TOOL`; import it from
  `._results`. `execute_command` still returns `CommandRecords` here.
- `_process_reactor.py`: change the `execute_tool` guard to
  `if name not in DOMAIN_TOOL_NAMES:` (import from `._results`) and add to
  `extensions/taut_mcp/tests/test_process_reactor.py` a firing test that
  `await reactor.execute_tool(workspace, token, "attach_workspace", {})`
  raises `AssertionError` matching `unregistered ordinary tool`. Parameterize
  over all three lifecycle names (`attach_workspace`, `detach_workspace`,
  `list_workspaces`), using the existing reactor setup in that test file.

Gate:

```bash
uv run --project extensions/taut_mcp --extra dev pytest extensions/taut_mcp/tests -m "not pg_only" -n 0 -q
uv run --project extensions/taut_mcp --extra dev mypy extensions/taut_mcp/taut_mcp extensions/taut_mcp/tests --config-file extensions/taut_mcp/pyproject.toml
```

Also run the two document gates from Slice 1 after applying the mapping.

Stop gate: if `_results.py` needs anything from `taut` or `taut_mcp._commands`,
or gains record schemas, stop; it owns only lightweight shared plumbing.

Commit: `Centralize shared MCP result plumbing`.

### Slice 3 — results are `records` plus optional `warnings`

Files: `extensions/taut_mcp/taut_mcp/_process_reactor.py`,
`extensions/taut_mcp/taut_mcp/_workspace_reactor.py`,
`extensions/taut_mcp/taut_mcp/_commands.py`; update
`extensions/taut_mcp/tests/_result_schemas.py`; the test modules listed in
"Context and key files".

Red tests first. Replace `_assert_result` in `test_tools.py` with:

```python
def _assert_result(
    payload: dict[str, Any],
    *,
    record_type: str,
    warnings: list[str] | None = None,
) -> None:
    if warnings:
        assert payload["warnings"] == warnings
    else:
        assert "warnings" not in payload
    validate(instance=payload, schema=result_schema(record_type))
```

and update its call sites (drop the `workspace=` and `guidance=` keywords).
Keep every test import of `result_schema`/`result_schema_for_tool` from
`_result_schemas`. In that oracle, preserve all nine record schemas and
helpers unchanged, import `MESSAGE_ID_PATTERN` and `RECORD_TYPE_BY_TOOL`
from `taut_mcp._results`, and replace `result_schema` with:

```python
def result_schema(record_type: str) -> dict[str, Any]:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "additionalProperties": False,
        "properties": {
            "records": {"items": RECORD_SCHEMAS[record_type], "type": "array"},
            "warnings": {"items": {"type": "string"}, "minItems": 1, "type": "array"},
        },
        "required": ["records"],
        "type": "object",
    }
```

Update the oracle docstring to describe the new wrapper. Keep
`result_schema_for_tool` unchanged. In `test_tools.py`, update
`test_manifest_omits_output_schema_and_results_stay_closed` and the search
schema test now: replace accesses to `properties.record_type` with exact
wrapper-key/required assertions; retain the assertions that `output_schema`
is `None` and `outputSchema` is absent. Keep record-schema literal assertions,
including descriptions, since those record schemas are unchanged. Change
its `RECORD_TYPE_BY_TOOL` import from `_commands` to `_results`. Update the
direct `execute_command` tests in both `test_tools.py` and
`test_channel_tools.py` to consume tuples and drop `.record_type` assertions;
retain record-value checks. Remove obsolete test-side guidance constants
when their last references disappear.

Add oracle tests enumerating all nine record types: check schema validity,
validate empty and warned results, and reject unknown top-level fields and
`warnings: []`. Assert that map values cover precisely the oracle's nine
record types. Keep explicit `validate(...)` calls and schema maps in stdio
tests, including attach and search. Validate direct detach/list results
against `result_schema_for_tool` where they bypass the helper; do not route
them through `call()`, which injects workspace/token arguments they reject.
Keep canonical text/structured parity assertions.

Rewrite `test_empty_reaction_result_has_content_free_guidance` and the
matching `message_delete` test to assert `{"records": []}` and
rename them `test_empty_reaction_result_is_records_only` and
`test_empty_deletion_result_is_records_only`. In `test_stdio_server.py`,
replace every literal envelope dict with the `records`-only form (search
empty → `{"records": []}`; attach → `{"records": [record]}`; detach missing
→ `{"records": []}`; `list_workspaces` with a stalled reservation →
`{"records": [...], "warnings": ["stalled attachment reservation exists;
restart taut-mcp to clear"]}`), delete the two `guidance` assertions after
`message_delete` and `read`, and replace them with
`assert repeated_delete == {"records": []}` and
`assert set(unread) == {"records"}`. Every top-level `["workspace"]` read
from a tool result in `test_process_reactor.py`, `test_resource.py`,
`test_pg_conformance.py`, `test_dual_era_contract.py`, and
`test_stdio_server.py` (find them with
`grep -n '\["workspace"\]' extensions/taut_mcp/tests/*.py`) becomes a read
from the attach record: add to `extensions/taut_mcp/tests/conftest.py`

```python
def canonical_of(payload: dict[str, Any]) -> str:
    """Canonical workspace from an attach/ensure result's first record."""

    return cast(str, payload["records"][0]["workspace"])
```

and use it. Delete every `record_type`, `empty`, and `guidance` assertion in
`test_channel_tools.py`, `test_pg_conformance.py`, `test_dual_era_contract.py`,
and `test_resource.py`; where a test asserted a whole envelope, assert the
`records`-only object.

Run the MCP lane; the new assertions must fail against the old envelope:

```bash
uv run --project extensions/taut_mcp --extra dev pytest extensions/taut_mcp/tests -m "not pg_only" -n 0 -q -x
```

Implementation:

- `_process_reactor.py`: delete `workspace_result`, `command_result`,
  `READ_GUIDANCE`, `MESSAGE_NOT_DELETED_GUIDANCE`,
  `MESSAGE_REACTION_NOT_SENT_GUIDANCE`. Import `tool_result` from
  `._results`. Find the call sites with
  `grep -n "command_result(\|workspace_result(" extensions/taut_mcp/taut_mcp/_process_reactor.py`
  and replace each with `tool_result(records, warnings=warnings)`;
  `list_workspaces` passes its stalled-reservation list as `warnings`. In
  `execute_tool`, replace the `ensured.get("workspace")` read and its
  assertion with:

  ```python
  records = ensured["records"]
  if not records or not isinstance(records[0].get("workspace"), str):
      raise AssertionError("successful ensure requires an attach record")
  canonical_workspace: str = records[0]["workspace"]
  ```

- `_workspace_reactor.py`: remove `record_type` from
  `WorkspaceCommandOutcome`; in `_execute_command` delete every
  `command_record_type = ...` assignment and the positional argument in
  both `WorkspaceCommandOutcome(...)` constructions (the success path and
  the control-drain canceled path); drop the unused `RECORD_TYPE_BY_TOOL`
  import. Keep `except EmptyResultError: pass` so the ordinary empty outcome
  still completes successfully after the now-unused assignment is removed.
- `_commands.py`: `execute_command` returns `tuple[CommandRecord, ...]`;
  delete the `CommandRecords` dataclass; callers that read `.records` read
  the tuple. Drop the `RECORD_TYPE_BY_TOOL` import if nothing else uses it.
- `_process_reactor.py`: wherever the completion carried `record_type` from
  the outcome to `command_result`, delete that plumbing.

Gate:

```bash
uv run --project extensions/taut_mcp --extra dev pytest extensions/taut_mcp/tests -m "not pg_only" -n 0 -q
uv run ./bin/pytest-pg --fast extensions/taut_mcp/tests/test_pg_conformance.py
uv run --project extensions/taut_mcp --extra dev mypy extensions/taut_mcp/taut_mcp extensions/taut_mcp/tests --config-file extensions/taut_mcp/pyproject.toml
```

Stop gate: if any code path still needs `record_type` at runtime, stop and
say why before keeping it. The only runtime `workspace` consumer is
`execute_tool`, handled above; if another appears, stop and name it.

Commit: `Return CLI-shaped records from MCP tools`.

### Slice 4 — guidance moves into three descriptions

Files: `extensions/taut_mcp/taut_mcp/_tools.py`,
`extensions/taut_mcp/tests/test_tools.py`.

Red test: add a table-driven description test so every description is
pinned to the [MCP-5] table by value, not only by hash:

```python
EXPECTED_DESCRIPTIONS: dict[str, str] = {
    # one entry per tool, copied from the [MCP-5] description table as
    # promoted in Slice 1; the three changed rows use the promoted text
}


def test_tool_descriptions_match_the_mcp5_table() -> None:
    assert {tool.name: tool.description for tool in TOOLS} == EXPECTED_DESCRIPTIONS
```

Update the literal asserts in `test_exact_message_tool_manifest_contract`
and the `message_react` contract test to the promoted text. Run
`test_tools.py`; expect the new test, the two literal tests, and
`test_exact_tool_manifest_snapshot` (sha256 over name, description,
inputSchema, annotations) to fail.

Implementation: set the three `ToolDefinition` description strings in
`_tools.py` to the promoted text; recompute the sha256 in
`test_exact_tool_manifest_snapshot` and replace the pinned value.

Gate: `uv run --project extensions/taut_mcp --extra dev pytest extensions/taut_mcp/tests/test_tools.py -n 0 -q`.

Stop gate: if the implementer is tempted to add a fourth disclosure sentence
anywhere, stop; only these three carried guidance.

Commit: `Move MCP result guidance into tool descriptions`.

### Slice 5 — removed by the owner decision

No work or commit. The former schema-restoration slice is withdrawn.
Numbering is retained so historical review citations remain meaningful.

### Slice 6 — parameter prose at CLI-help terseness, size ceiling

Files: `extensions/taut_mcp/taut_mcp/_tools.py`,
`extensions/taut_mcp/tests/test_tools.py`.

Red tests, in `test_tools.py`:

```python
CEILING_BYTES = 21_000


def test_manifest_size_stays_under_ceiling() -> None:
    dumped = [tool.model_dump(by_alias=True, exclude_none=True) for tool in TOOLS]
    total = len(
        json.dumps(dumped, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    )
    breakdown = {
        field: sum(
            len(json.dumps(tool[field], separators=(",", ":"), ensure_ascii=False).encode("utf-8"))
            for tool in dumped
            if field in tool
        )
        for field in ("description", "inputSchema", "outputSchema", "annotations")
    }
    assert total <= CEILING_BYTES, (total, breakdown)


def test_input_schemas_carry_no_schema_url() -> None:
    for tool in TOOLS:
        assert "$schema" not in tool.input_schema, tool.name


def test_parameter_descriptions_match_the_mcp5_table() -> None:
    expected = {
        # ("tool", "property"): "exact description", one entry per row of the
        # promoted [MCP-5] parameter table, expanded per tool
    }
    actual = {
        (tool.name, name): schema["description"]
        for tool in TOOLS
        for name, schema in tool.input_schema["properties"].items()
    }
    assert actual == expected
```

Implementation in `_tools.py`: replace every description constant and every
inline property description with the promoted table text (one sentence
each, exactly as in the delta). Keep every `pattern`, `enum`, `minimum`,
`maximum`, `maxLength`, `default`, and `not` unchanged. Remove the
`"$schema"` entry from the dict built in `to_mcp()`. Recompute the sha256 in
`test_exact_tool_manifest_snapshot`.

Gate: `test_tools.py` plus the full MCP lane. Record the measured total and
breakdown in this plan's Review Log.

Stop gate: if the measured total exceeds the ceiling, stop and report the
breakdown; the owner decides what else moves.

Commit: `State MCP parameter prose once and cap manifest size`.

### Slice 7 — traceability reconciliation

Files: `docs/implementation/07-taut-mcp-architecture.md`,
`extensions/taut_mcp/README.md` (only if it describes result shape; check
with `grep -n "records\|guidance\|structuredContent" extensions/taut_mcp/README.md`),
`CHANGELOG.md`, `docs/plans/README.md`, this plan.

1. In doc 07: leave "result envelopes" in "One SDK server, two wire eras"
   alone (it means the SDK's protocol envelopes); change "becomes the
   ordinary empty `message` envelope" to "becomes the ordinary empty
   `message` result"; change "returns an empty `search_hit` success
   envelope" to "returns an empty `search_hit` success result"; replace
   "Closed output schemas require 19-digit strings, while the domain
   objects and parent/child IPC remain integer-valued." with "The record
   schemas in the test oracle require 19-digit strings, while the domain
   objects and parent/child IPC remain integer-valued." In the ownership
   table, change the `_tools.py` row to "exact manifest, input validators,
   descriptions, and annotations"; add a row for
   `extensions/taut_mcp/taut_mcp/_results.py` owning "shared record-type map,
   domain-tool set, message-id pattern, and the [MCP-6] result builder";
   identify `extensions/taut_mcp/tests/_result_schemas.py` as the test-only
   closed-schema owner. Add a rationale paragraph explaining the CLI-shaped
   results, guidance in descriptions, terse parameter prose, and the
   owner-approved omission of output schemas with retained test validation.

2. CHANGELOG `## Unreleased`: one entry stating the old six-field object,
   the new `records`/optional-`warnings` object, the `outputSchema`
   decision, the three descriptions that absorbed guidance, the terse
   parameter prose, and the measured manifest size. State it ships as
   `taut-mcp` 0.10.0.
3. Record the promotion baseline, measured sizes, and current dispositions.
   Keep this plan and its index row active until Slice 8 passes; then update
   both to completed in the closeout commit.
4. Run the final gates below.

Commit: `Reconcile MCP result contract docs`.

### Slice 8 — independent review of completed work

Same reviewer stance as Slice 0 against the full diff, using the §4a
scoped-change prompt; disposition every finding before declaring done.
After review passes, update this plan and its index row to completed, rerun
the document gates, and commit the review/closeout record.

## Testing plan

- Harness: the existing MCP test lane. Real stdio server through
  `mcp.client.stdio.stdio_client` and `ClientSession` in
  `test_stdio_server.py`; real SQLite workspaces under `tmp_path`; the real
  PostgreSQL lane for `test_pg_conformance.py`.
- Do not mock: `execute_command`, `TautClient`, the SDK `Server`/`ClientSession`,
  `jsonschema.validate`, or the process/workspace reactors. The contract
  under proof is the wire shape of real results. Explicit test-oracle
  validation is required because no output schema is advertised.
- Contract tests protect: invariant 1 (object with `records`), invariant 3
  (empty is `{"records": []}`), invariant 4 (`warnings` order and omission),
  invariant 5 (errors unchanged), invariant 6 (import boundary probe), the
  per-tool omission of `outputSchema`, retained closed record schemas,
  input `$schema` removal, every tool and parameter description by value,
  and the size ceiling.
- Every enumerable element gets a firing test: all 21 tools omit
  `outputSchema` and real results validate against the test oracle; nine
  record types each validate an empty and a warned result and reject extra
  wrapper fields and empty warnings; 21
  tool descriptions and every parameter description are pinned by value;
  the three lifecycle tools are rejected by `execute_tool`; one size ceiling.
- Error paths: a tool error is unchanged (fatal, `isError`); a warning is
  best-effort data on a successful result and never converts a success into
  an error.

## Verification and gates

Per slice, the commands listed in the slice. Final gates before completion:

```bash
uv run --project extensions/taut_mcp --extra dev pytest extensions/taut_mcp/tests -m "not pg_only" -n 0 -q
uv run ./bin/pytest-pg --fast extensions/taut_mcp/tests/test_pg_conformance.py
uv run pytest tests/test_docs_references.py -n 0 -q
uv run --project extensions/taut_mcp --extra dev ruff check extensions/taut_mcp/taut_mcp extensions/taut_mcp/tests
uv run --project extensions/taut_mcp --extra dev ruff format --check extensions/taut_mcp/taut_mcp extensions/taut_mcp/tests
uv run --project extensions/taut_mcp --extra dev mypy extensions/taut_mcp/taut_mcp extensions/taut_mcp/tests --config-file extensions/taut_mcp/pyproject.toml
uv run python bin/check-doc-paths
uv run python bin/check-plan-status-index
uv run python bin/ruff_suppression_index.py --check
```

Observable success after release: `taut-mcp` 0.10.0's `tools/list` from a
real host serializes under the ceiling; a `say` call returns
`{"records":[{...}]}` with canonical text parity; all 21 listed tools omit
`outputSchema`. Check captured successful results against the test oracle.

## Rollout and rollback

Rollout: one minor release of `taut-mcp` (0.10.0) through the normal
`bin/release.py mcp` path after all slices land on `main`. No storage,
identity, or core change; only the MCP wire shape.

Rollback: revert the code commits (Slices 2–7) as a group and the spec
promotion commit (Slice 1) separately, then release the prior shape as
0.10.1 if 0.10.0 was published. No data migration in either direction.

One-way door: a published 0.10.0 fixes the new shape for any client that
adopted it. The package is pre-1.0 and the change is announced in the
CHANGELOG; no shim is offered. Do not publish until Slice 8 has passed.

## Independent review loop

Reviewer: a different agent family from the author where available (see
`docs/implementation/03-agent-inventory.md`); otherwise a fresh-eyes
repository subagent, recorded as the fallback. Read-only.

Give the reviewer: this plan, the promoted or proposed delta,
`docs/specs/05-taut-mcp.md` [MCP-5], [MCP-6], [MCP-12],
`extensions/taut_mcp/taut_mcp/_process_reactor.py`,
`extensions/taut_mcp/taut_mcp/_tools.py`,
`extensions/taut_mcp/tests/_result_schemas.py`, and
`extensions/taut_mcp/tests/test_stdio_server.py`.

Prompt (plan review, §4 of the review runbook):

> Read the plan and its `## Proposed Spec Delta`. Existence-check every
> named symbol, file, and test against the tree. Look for errors, bad
> ideas, latent ambiguities, and performative overengineering; recommending
> removal counts. Challenge specifically: whether a uniform `records`
> object is the right shape versus bare records; whether any consumer
> still needs `record_type` or `workspace` at runtime; whether the retained
> test oracle and explicit real-result validation cover the new wrapper;
> whether the size ceiling is a contract or ceremony; and whether the
> three absorbed guidance sentences change any [MCP-9] rule. Answer
> PASS or BLOCKED on the two questions: could you implement this
> confidently and correctly as written, and would it degrade the system.

Round-2 after implementation uses the §4a scoped-change prompt over the
full diff.

## Out of scope

- The `taut://notifications/current` resource shape ([MCP-7]).
- Tool names, annotations, input types, patterns, bounds, required lists,
  and the 21-tool count.
- The [MCP-9] instructions text.
- Core `--json` output, `TautClient`, and any storage or identity behavior.
- Advertising `outputSchema`, moving schemas into production, or changing
  record-schema descriptions/constraints or `oneOf` branches.
- Any compatibility shim, dual result shape, or protocol negotiation.

## Fresh-eyes notes

One execution path remains: omit output schemas, retain the closed test
oracle and explicit result validation, and cap the manifest at 21,000 bytes.
Slice 1 promotes behavior text; Slice 2 creates the module before adding
its mapping link; Slice 3 updates the oracle wrapper and all obsolete
wrapper assertions together. Record-schema bodies and descriptions do not
move. Slice 5 is withdrawn. Review-log entries below describe earlier
revisions and are historical, not execution instructions.

## Review Log

| Review | Reviewer / invocation | Verdict | Findings | Disposition |
|--------|-----------------------|---------|----------|-------------|
| Plan fresh-eyes | repository subagent, read-only, 2026-09-15 | BLOCKED (question 1) | F1 size estimate ~7 KB low (measured 42.4 KB with description-free `outputSchema`; ceiling and stop gate unachievable). F2 `execute_tool` reads top-level `workspace` from the ensure payload. F3 `execute_tool` guards with the 18-entry map as the domain-tool set. F4 Slice 2 committed a red suite. F5 detach/list calls cannot route through `call()`. F6 sha256 manifest snapshot unnamed; `read` had no literal pin. F7 two envelope sentences missing from the delta. F8 ~40 top-level `["workspace"]` test reads unlisted. F9 stable-handle sentence is in [MCP-5]. F10 doc 07 "result envelopes" is SDK-owned. F11 import boundary not pinned by `test_lazy_imports.py`. F12 two `WorkspaceCommandOutcome` constructions. F13 "SDK validates every stdio result" overclaims. F14–F16 nits. | All accepted. F1: re-measured (17.0 KB without / 31.5 KB with `outputSchema`), ceilings set at 20,000 / 34,000, decision escalated to the owner, terse prose extended to every parameter (owner direction). F2: Slice 3 reads the attach record; stop gate reworded. F3: guard switched to `DOMAIN_TOOL_NAMES` with a firing test. F4: `_result_schemas.py` retained through Slice 2. F5: manual validation removed instead of extended. F6: hash test named in Slices 4 and 6; table-driven description tests added. F7: two anchors added. F8: files listed, grep and `canonical_of` helper given. F9: relabeled. F10: edit dropped. F11: subprocess probe added; invariant 6 and answer 2 corrected. F12: "both". F13: reworded. F14: `output_schema=`. F15: one dump per tool; set assert dropped. F16: helpers renamed. Reviewer's observations (uniform `records`, optional `warnings`, description-free schemas, ceiling as regression guard, [MCP-9] unchanged) agree with the decisions. |
| Plan different-family | `codex exec -s read-only --json`, attempt 1, timeout 900 s, 2026-09-15 | none | exit 124 (timeout); stderr "Reading additional input from stdin"; no `agent_message` event | Not a verdict. Retried with stdin closed per the bounded-attempts rule. |
| Plan different-family | `codex exec -s read-only --json < /dev/null`, attempt 2, timeout 1800 s, 2026-09-15 | none | exit 1 after 7 events; `rmcp::transport::worker` fatal: HTTP request to a configured MCP endpoint (`local.api.modelmonster.ai:18443`) failed; no `agent_message` | Not a verdict; environment failure recorded in `docs/implementation/03-agent-inventory.md`. Two attempts exhausted; the fresh-eyes review stands as the same-family fallback with this limitation noted. |

| Plan Codex review | Codex desktop, read-only, 2026-09-15 | BLOCKED as reviewed | F1 Slice 1 maps a nonexistent `_results.py`; F2 omit branch leaves schema imports/tests inconsistent and deletes the retained oracle; F3 Slice 3 leaves old wrapper assertions until a later slice. Host-rendering claims exceed verified evidence. | Accepted in this revision: mapping deferred to Slice 2; one omit path with retained oracle and explicit validation; old wrapper assertions updated in Slice 3. Host rationale narrowed to no demonstrated requirement. Record schemas retain descriptions, so their existing literal assertions remain valid. |
| Owner decision | User instruction, 2026-09-15 | Omit `outputSchema` | Agent benefit does not justify bytes; matches CLI/test-oracle model; later addition is cheaper than later removal. | Applied throughout the active plan. Former Slice 5 removed; ceiling 20,000 bytes. Earlier keep-branch dispositions above are superseded. |

| Scoped revision review | Independent repository subagent, 2026-09-15; read-only comparison with pre-revision plan and affected tests | PASS (scoped revision) | F1–F3 resolved. One unused `json` import remained after removal of schema-copy tests. | Removed the import and verified all Python snippets parse after Markdown dedent. Retained oracle, explicit validation, mapping order, Slice 3 assertion migration, and 20,000-byte ceiling verified. This is a scoped revision review, not a new full implementation audit. |

Revision verification (2026-09-15): `uv run pytest tests/test_docs_references.py -q -n 0` (12 passed), `uv run python bin/check-doc-paths` (OK), `uv run python bin/check-plan-status-index` (OK), and `git diff --check` (clean). Python snippets parsed and active omit-path consistency inspected. Changed this plan and its index note only; uncommitted for owner review. Implementation and spec promotion remain pending.

## Execution log

Class 5 implementation authorized by the owner. Starting code baseline: `cca84d1538b7b2a8af6881658815fde4c6f3b9cc`. Shared context, program theory, planning/hardening/testing/adversarial runbooks, lessons, owning spec, architecture note, and agent inventory consulted. Baseline `test_tools.py`: 151 passed. Captured all 21 original tools for final structural comparison.

Slice 1 independent pass found the generic `msg_id` prose would misdescribe `reply` suffix support. Added a dedicated `reply.msg_id` row before promotion; input constraints remain unchanged. Verified against `_tools.py` reply property. This is a correction to the proposed description, not an input-contract change.

Slice 1: promoted spec at `801554c`; 12 doc-reference tests and path gate passed. Comprehension: `list_workspaces` owns the stalled-reservation warning; `_results.py` must stay free of `taut`/`_commands` imports to preserve lazy manifest loading; canonical workspace comes from `ensured["records"][0]["workspace"]`.

Slice 2 deviation: the first full-lane collection exposed an additional map consumer in `server.py`: its import-time assertion compared the old 18-entry command map to `DOMAIN_TOOL_NAMES`. Update it to import the shared 21-entry map and compare to `TOOL_NAMES`; domain dispatch retains its separate 18-name guard and firing tests. No spec behavior changes. The test oracle imports the map/pattern directly from `_results.py` in Slice 2 (wrapper unchanged), avoiding an otherwise unused re-export from `_tools.py`; its test consumers remain unchanged.

Slice 2: red probe failed with missing `_results`; full non-PG MCP lane passed (296 cases), mypy passed (24 files), Ruff and doc gates passed. Independent scoped review PASS; tightened import probe to also reject bare `taut`. Six focused result/lifecycle cases passed after review. No schema or result-shape change in this slice.

Slice 3 review corrections: modern lazy `whoami` returns a member record, so its test derives the canonical path from the known input instead of using `canonical_of`. Added explicit lifecycle oracle validation and canonical-text parity. Red proofs observed both the old CommandRecords tuple mismatch and old-envelope warning-key mismatch before runtime edits.

Slice 3 mechanical documentation delta: Ruff removed the now-unused TRY004 suppression at ProcessReactor.execute_tool because the new combined empty-record/type invariant is not a bare type check. Reduce [RUFF-SUP-073] and the global TRY004 inventory from 12 to 11 and regenerate the owner index, removing that owner. No lint rule or exception policy changes.

Slice 3: 306 non-PG MCP tests passed after corrections; PostgreSQL conformance 7 passed; mypy 24 files, Ruff, document tests and suppression-index gate passed. Independent review found and verified fixes for modern whoami workspace lookup and explicit lifecycle validation, then returned PASS. Closed record schema bodies/descriptions preserved; only result wrapper changes.

Slice 4: exact 21-tool description fixture exposed two pre-existing Markdown-only differences (`say` selectors and `search` reindex flag). Aligned them to the promoted exact table alongside the three guidance-bearing descriptions; no extra disclosure or behavior change. Red description tests failed before edits. All 152 tool tests passed after description/hash updates.

Slice 6 measurement: exact approved prose serializes to 20,514 bytes (description 4,395; inputSchema 12,865; outputSchema 0; annotations 1,875). The 20,000-byte stop gate fires; owner decision requested before proceeding. Structural comparison against all 21 captured baseline tools is identical after removing descriptions and input `$schema`; record schemas remain test-only. All tool tests except the size gate pass.

Owner decision (2026-09-15): raise the manifest ceiling to 21,000 bytes after measured 20,514-byte result; retain all exact approved descriptions. Promoted [MCP-12] ceiling and executable test updated together. The earlier 20,000-byte threshold in historical review entries is superseded.

Slice 6: owner-approved 21,000-byte gate passes at 20,514 bytes, 35.2% below the 31,679-byte baseline. Full non-PG selection excluding the pending size gate passed (308 cases), and the size gate then passed separately after owner approval; PG 7 passed, mypy 24 files, Ruff/check-format, document/reference/path/status and suppression gates passed. All nine RECORD_SCHEMAS definitions are AST-identical to baseline. Final unfiltered lane will run after this commit.
