# Taut

  [![CI](https://github.com/VanL/taut/actions/workflows/test.yml/badge.svg)](https://github.com/VanL/taut/actions/workflows/test.yml)
  [![codecov](https://codecov.io/gh/VanL/taut/branch/main/graph/badge.svg)](https://codecov.io/gh/VanL/taut)
  [![Python versions](https://img.shields.io/badge/python-3.11%20%7C%203.12%20%7C%203.13%20%7C%203.14-blue)](https://github.com/VanL/taut/blob/main/pyproject.toml)

*Slack in your terminal, for you and your agents. No server, no daemon, no
config, no accounts. One SQLite file by default; Postgres when you need it.*

> **Status:** alpha, and real: the core ships on PyPI as
> [`taut-chat`](https://pypi.org/project/taut-chat/) with immutable
> GitHub Releases (see [CHANGELOG.md](https://github.com/VanL/taut/blob/main/CHANGELOG.md) for released
> versions). This README is the product contract, written first on
> purpose — before any spec or code — and kept current against the
> specs below. Per section, the
> [product-section registry](https://github.com/VanL/taut/blob/main/docs/specs/product-section-registry.md)
> names the winning contract (this README or an owning spec).
> The conceptual account of what kind of system Taut is
> lives in [`docs/program-theory.md`](https://github.com/VanL/taut/blob/main/docs/program-theory.md). The core specification lives in
> [`docs/specs/02-taut-core.md`](https://github.com/VanL/taut/blob/main/docs/specs/02-taut-core.md); identity,
> addressing, direct messages, and notifications are specified in
> [`docs/specs/03-identity-addressing-notifications.md`](https://github.com/VanL/taut/blob/main/docs/specs/03-identity-addressing-notifications.md),
> and search in [`docs/specs/06-search.md`](https://github.com/VanL/taut/blob/main/docs/specs/06-search.md).

```bash
$ taut init
$ taut join general
$ taut say general "kicking off the refactor. claude, take the parser."
```

…and in the terminal where your agent is working:

```bash
$ taut join general
$ taut log general           # joining starts you at now — log rewinds
── general ──────────────────────────────────────
  09:13 · van created #general
  09:14 van     kicking off the refactor. claude, take the parser.
  09:15 · claude joined

$ taut say general "claude here. parser tests green in ~20 min."
```

Taut exists for the machine you're already on: you in one terminal, two
coding agents in others, a cron job that should be able to speak up. They
can all run a CLI, they all share a filesystem, and they have no good way
to talk to each other. Taut gives them channels, threads, history, unread
counts, and live following. By default it is backed by a single `.taut.db`
file; with `taut-pg`, the same commands can use a project-configured
Postgres database. Both paths are built on
[SimpleBroker](https://github.com/VanL/simplebroker)'s durable queues.

## Recommended For

- **Talking to your coding agents.** `taut say` and `taut read --json` are
  trivially scriptable; an agent can join, catch up, and reply with three
  shell commands and zero setup.
- **Agents talking to each other.** Two agents in one repo coordinate
  through a channel instead of polling files at each other.
- **Leaving yourself notes that have an audience.** A deploy script that
  posts to `#ops` in your project beats one that echoes into a log nobody
  follows.
- **People who think a chat app should be installable with `pipx` and
  deletable with `rm`.**

**Good for:** one trust domain, in-the-moment coordination — one machine by
default, or a few machines through the Postgres extension.
**Not for:** untrusted users, compliance, anything Slack is actually for.

## Table of Contents

- [Features](#features) · [Installation](#installation) ·
  [Quick Start](#quick-start)
- [The Identity Trick](#the-identity-trick) ·
  [Command Reference](#command-reference) ·
  [Working With Agents](#working-with-agents) ·
  [Python Library](#python-library)
- [Trust Model](#trust-model-read-this-before-filing-the-issue) ·
  [Things That Look Weird but Aren't](#things-that-look-weird-but-arent)
- [Documentation Map](#documentation-map) ·
  [Roadmap](#roadmap) · [Development](#development)

## Features

- **Zero configuration by default** — no server, no daemon, no dotfiles, no
  account. `taut init` creates one file; that file is the entire SQLite
  installation.
- **Humans and agents are both first-class** — every command has `--json`
  (ndjson) output; agents are recognized automatically (see below).
- **Real history** — ordinary reads never consume messages. Reading moves
  *your* bookmark; authors may explicitly delete one of their own messages.
- **Disposable full-text search** — `taut search parser --channel general`
  searches current source history without moving a cursor. SQLite uses its
  built-in FTS5 support; `taut-pg` uses PostgreSQL's built-in text search and
  GIN, with no optional server extension required.
- **Portable workspace dump/load** — `taut system dump --output backup.jsonl`
  writes messages plus authoritative sidecar state; `taut system load` restores
  exact ids into a fresh SQLite or PostgreSQL target.
- **Passive workspace diagnosis** — `taut system doctor` runs six fixed,
  read-only checks over core, broker, extension, and search state without
  claiming work or repairing anything.
- **Unread tracking per participant** — `taut list` shows what's new *for
  you*; exit codes make it shell-composable.
- **Live following** — `taut watch` streams every thread you're in, and
  picks up threads you join while it runs.
- **Durable direct-message handles** — `taut say @claude ...` maps the current
  name to a stable member-id pair queue. `say`, `read`, `log`, and `watch`
  reuse an existing conversation by its exact `dm.d_*` handle; `list --dms`
  discovers every accessible conversation, including read and empty ones.
- **Consumable notifications** — mentions and new DMs can wake the member's
  notification inbox without adding per-device state.
- **Stable member identity** — names can change, but messages, cursors,
  direct messages, and notifications stay tied to an opaque member id.
  Process evidence makes the common case automatic; `whoami --explain`
  keeps it inspectable.
- **SimpleBroker all the way down** — `.taut.db` is a standard SimpleBroker
  database. `broker -f .taut.db list` works. Plumbing is not hidden.
- **Three optional extensions, separately installable** — `taut-pg`
  (same commands on a project-configured Postgres), `taut-summon`
  (host an agent harness as an ordinary workspace member), and
  `taut-mcp` (expose the workspace to MCP clients). Core stays
  dependency-boring without them.

## Installation

The product, import package, and command are still named Taut and `taut`. The
public core distribution is named `taut-chat` because the `taut` PyPI project
name is unavailable.

For command-line use, install the core application with `pipx`:

```bash
pipx install taut-chat
taut --help
```

The pipx environment is consequently named `taut-chat`, even though the
installed executable is `taut`. Optional extensions must be injected into that
environment. To install all three extensions and expose their standalone
commands:

```bash
pipx inject --include-apps taut-chat taut-pg taut-summon taut-mcp
```

This provides `taut` plus the `taut-summon` and `taut-mcp` executables. The
Postgres extension changes the backend available to `taut`; it does not add a
standalone command.

For a Python project or an existing virtual environment:

```bash
uv add taut-chat
# or
python -m pip install taut-chat
```

Add the unchanged extension distribution names when needed:

```bash
uv add taut-chat taut-pg taut-summon taut-mcp
# or
python -m pip install taut-chat taut-pg taut-summon taut-mcp
```

Requirements: Python 3.11+. Runtime dependencies are `simplebroker>=7.0.0`
(which itself has none) and `psutil` for cross-platform process metadata.

### Postgres Extension

`taut-pg` is a separate distribution: the same commands on a
project-configured Postgres database. Install it into the same
environment as `taut-chat` (it brings in `simplebroker-pg` and the
driver dependencies), then select Postgres with a `.taut.toml` in the
project root and run `taut init` normally. `TAUT_DB`, `--db`, and
`db_path=` remain filesystem path selectors; `.taut.toml` is the
Postgres door. Extensions use their own tags (`taut_pg/vX.Y.Z`,
`taut_summon/vX.Y.Z`), so their versions do not generally have to
match the core package version; the first PyPI publication is one
coordinated version across all four distributions.

Requirements, installation, the exact `.taut.toml` shape, and the
credential-handling warning live in the
[taut-pg README](https://github.com/VanL/taut/blob/main/extensions/taut_pg/README.md).

### Project configuration (`.taut.toml`)

A complete project `.taut.toml` also owns the message-reaction
vocabulary: the packaged default is `ack` and `blocked`, a local
`[reactions]` list *replaces* it (unique lowercase ASCII slugs;
`values = []` disables outbound reactions), and each `TautClient`
freezes the resolved list at construction — restart a long-lived
client or MCP attachment after changing the file. The exact contract
is [TAUT-3.2] in the
[core spec](https://github.com/VanL/taut/blob/main/docs/specs/02-taut-core.md);
terminal rendering policy, the other `.taut.toml` table, is covered
under the Trust Model below.

### Summon Extension

`taut-summon` hosts an existing agent harness (Claude Code, or any
interactive agent CLI — the universal PTY adapter hosts named
providers including `claude` and `codex`) as an ordinary workspace
member — no daemon, no bespoke agent protocol. The summon driver feeds
chat into the harness's own live session (its ears), and the agent
speaks by running the ordinary `taut` CLI selected by its continuity
token (its mouth). It ships as a separate package with its own version
tags; installed, it registers native `taut summon` and `taut dismiss`
command adapters that share parser and controller code with the
standalone console. Without the extension, `taut summon` exits 1 with
an install hint.

Installation, usage (`taut summon`, `taut-summon status`,
`taut dismiss`), and the trust boundary live in the
[taut-summon README](https://github.com/VanL/taut/blob/main/extensions/taut_summon/README.md).
The full contract is the
[Summon spec](https://github.com/VanL/taut/blob/main/docs/specs/04-summon.md);
design rationale lives in
[`docs/implementation/05-taut-summon-architecture.md`](https://github.com/VanL/taut/blob/main/docs/implementation/05-taut-summon-architecture.md)
and
[`docs/implementation/06-command-extensions.md`](https://github.com/VanL/taut/blob/main/docs/implementation/06-command-extensions.md).

### MCP Extension

`taut-mcp` is a separate, connection-scoped stdio adapter for MCP
clients. One process serves one MCP connection and can attach up to
eight existing Taut workspaces, each with its own continuity token,
client, and owner thread. The manifest contains exactly 21 tools —
18 CLI-shaped, workspace- and token-scoped, plus three
process-lifecycle tools — and the repeatable
`taut://notifications/current` resource, which reports notification
pointers only; reading it does not claim them or advance chat cursors.
The package is wired into the coordinated PyPI and immutable GitHub
Release path; that configuration does not itself mean a release has
been published.

Installation, running from a checkout, and host notes (including the
experimental `--claude-channel` wake cue) live in the
[taut-mcp README](https://github.com/VanL/taut/blob/main/extensions/taut_mcp/README.md).
The full contract is the
[MCP spec](https://github.com/VanL/taut/blob/main/docs/specs/05-taut-mcp.md);
design rationale lives in
[`docs/implementation/07-taut-mcp-architecture.md`](https://github.com/VanL/taut/blob/main/docs/implementation/07-taut-mcp-architecture.md).

## Quick Start

```bash
# One-time, per project (like git init)
$ cd ~/myproject
$ taut init

# Channels are created by joining them
$ taut join general
$ taut channel topic general "General project coordination"
$ taut say general "anyone awake?"

# …an agent in another terminal joins and answers…

# What's new for me? (exit 2 when nothing — composable in scripts)
$ taut list
general  2 unread
$ taut read general
── general ──────────────────────────────────────
  09:15 · claude joined
  09:15 claude  yes. what broke?

# Log doesn't move your bookmark; explicit author deletion is the exception
$ taut log general --since 2026-06-12

# Follow everything you're in, live
$ taut watch

# Threads branch off a message, Slack-style (-t shows message ids)
$ taut log general -t --limit 1
── general ──────────────────────────────────────
  1837025672140161024  09:15 claude  yes. what broke?
$ taut reply general 0161024 "moving this to a thread"
```

Pipes work where you'd expect:

```bash
$ make test 2>&1 | tail -20 | taut say ci -
$ taut read --json | jq -r 'select(.kind=="message") | .text'
```

Workspace maintenance is actor-free. Stop writers, watchers, Summon drivers,
and foreign broker consumers for the full operation:

```bash
$ taut system dump --output backup.taut.jsonl
$ taut system load --input backup.taut.jsonl --dry-run
$ taut system load --input backup.taut.jsonl   # fresh target only
```

The sibling doctor is passive and does not require a maintenance window:

```bash
$ taut system doctor
```

Its snapshot can become stale immediately. A healthy report does not certify
quiescence or make dump/load safe while writers are active.

Dry-run validates the complete file without opening or checking the selected
destination. A failed load after its guard is acquired leaves that fresh target
unusable; recreate it and retry the same dump.

Direct messages use `@name` and route through the member's current name, not
through the display name captured in old messages:

```bash
$ taut say @claude "can you check the parser branch?"
$ taut log @claude
$ taut list --dms
DM with Claude  no unread
$ taut read dm.d_aaaaaaaaaaaaaaaaaaaaaaaaaa
$ taut say dm.d_aaaaaaaaaaaaaaaaaaaaaaaaaa "same conversation, no name lookup"
```

The `@name-or-alias` form follows the current route owner each time. The
`dm.d_*` value shown by JSON or `list --dms` is the stable conversation handle,
so it still reopens the same pair after either participant renames. Sending to
that handle requires the existing fully valid conversation and never creates or
repairs one. Only `say @name` can start a conversation.

Channels may render as `#general` in human output, but bare `general` remains
the command-line form. If you want to type the hash, quote it:
`taut say '#general' "hello"`; an unquoted leading `#` is too easy for shells
to treat as a comment.

## The Identity Trick

Nobody logs in to taut. Each participant gets a stable opaque member id, and
that id is what owns memberships, cursors, direct messages, and notifications.
The name you see is a current display name. It can change.

```bash
$ taut whoami --json
{"member_id":"m_abcd1234abcd1234abcd1234ab","name":"Claude","aliases":[],"kind":"agent","presence":"here","last_active_ts":"1837025672140161024","persona":null}
$ taut set name Codex
$ taut whoami --json | jq -r .member_id
m_abcd1234abcd1234abcd1234ab
```

Messages keep the sender name from the moment they were written. If `Claude`
renames to `Codex`, old messages still say `Claude`; new messages say `Codex`.
Machine consumers use `from_id` when they need stable identity:

```json
{"thread":"general","ts":"1837025672140161024","from_id":"m_abcd1234abcd1234abcd1234ab","from":"Claude","kind":"message","text":"parser is green"}
```

Taut keeps these ids as integers in Python and storage. External JSON renders
them as exact 19-digit strings so JavaScript cannot silently round them.

The automatic, selector-free path uses process evidence. When no `--as` or
continuity token selects the acting member, taut walks the caller's process
ancestry, looks past shells and wrapper commands, and derives a deterministic
identity claim for the process or human session:

- anchor pid and its start token, where available
- executable path, argv, cwd, uid
- process group, session id, controlling tty
- an opaque host identity

That claim maps to the member id (the exact evidence contract is
[IAN-3] in the
[identity spec](https://github.com/VanL/taut/blob/main/docs/specs/03-identity-addressing-notifications.md)). If the claim is known, taut knows who is
speaking. Taut also captures this evidence when an allowed first-contact
operation must create a member, when `rejoin` deliberately associates the
current process, and when `whoami --explain` renders current evidence. If an
agent restarts and gets a new process claim, taut creates a new member only when
it cannot safely infer continuity. Then it tells you what it noticed:

```text
created new identity 'Claudette'
note: you may be one of these:
  Claude  same executable, same cwd
reclaim with 'taut rejoin Claude'
```

Automatic human and agent display names use the same small rule: taut derives a
valid route seed from the OS login or agent process name, then capitalizes its
first ASCII letter. The source is evidence, not the Taut name: an OS login of
`van` defaults to `Van`, and a `codex` process defaults to `Codex`. Explicit
names supplied through `--as`, `TAUT_AS`, or `set name` keep their exact casing.
Routes remain case-insensitive.

Repeated instances use short curated families before the shared historical
pool and numeric suffixes. For example, Pi instances begin `Pi`, `Tau`, `Phi`.

There are three identity modes:

1. With no explicit selector, taut captures current evidence and infers the
   member through claims, anchor healing, and human-session fallback.
2. `--as NAME_OR_ALIAS`, `TAUT_AS`, or a valid continuity token selects the
   member for the current operation without full process/session capture. An
   existing selector does not rewrite that member's process claim, anchor, or
   fingerprint. A missing explicit name creates a member only when the command
   already permits creation, such as `join` or a viable first-contact
   `say @route`; stable-handle send is existing-only.
3. `taut rejoin Claude` (or `taut rejoin --token TOKEN`) captures the current
   process claim and deliberately associates it with the selected existing
   member. It does not rename the member or rewrite history.

For process trees that churn constantly, every member gets a continuity token
at creation. Stash it in your agent's state, and
`TAUT_TOKEN=taut-7f3k9q2m taut say ...` is that same member from anywhere. It is
continuity, not security: anyone with storage access can still use `--as`.

Presence remains evidence-based. `taut who` checks whether local agent process
claims still appear alive; members anchored elsewhere in a shared Postgres
backend show remote-style presence rather than pretending local liveness is
knowable.

When the magic guesses wrong, `--as NAME_OR_ALIAS` (or `TAUT_AS`) always wins for
that command without teaching selector-free resolution a new process claim. One
boundary to know: recognition cannot cross ssh or container walls unless you
pass `TAUT_AS` or `TAUT_TOKEN` through.

## Command Reference

| Command | Description |
|---------|-------------|
| `taut init` | Create `.taut.db` in the current directory |
| `taut join THREAD [--as NAME] [--persona TEXT] [--new]` | Join (creating if needed) a channel; you start at now |
| `taut leave THREAD` | Leave a thread; history stays |
| `taut set name NAME` | Change your current display/routing name; old messages keep the old name |
| `taut say THREAD\|@NAME\|DM_HANDLE [TEXT\|-]` | Post to a channel, sub-thread, person-addressed DM, or existing stable DM (stdin with `-` or a pipe); only `@NAME` may create a DM |
| `taut reply THREAD MSG_ID [TEXT\|-]` | Reply in a sub-thread, creating it on first reply |
| `taut message show MSG_ID` | Show one visible message without claiming it; advances that thread's seen cursor through the message |
| `taut message delete MSG_ID` | Delete one of your own ordinary messages; no related state is cascaded |
| `taut message react MSG_ID REACTION` | Advance seen state and best-effort broadcast a consumable reaction pointer to the message's current non-actor audience |
| `taut channel show CHANNEL` | Show the current topic and update attribution without resolving an actor or changing shared state |
| `taut channel topic CHANNEL TEXT` | Set one exact, nonblank, single-line channel topic of at most 500 Unicode code points |
| `taut channel topic CHANNEL --clear` | Clear the channel topic without posting a message or notification |
| `taut channel rename OLD NEW` | Rename a channel and its sub-threads |
| `taut read [THREAD_OR_DM]` | Show unread and advance your bookmark; a DM accepts `@name-or-alias` or its stable handle; bare = all your threads |
| `taut inbox` | Claim and show notification pointers for mentions, replies, new DMs, and reactions |
| `taut log THREAD_OR_DM [--since TS] [--limit N]` | Show channel, sub-thread, or accessible DM history; never moves your bookmark or activity for a DM |
| `taut search QUERY... [--channel CHANNEL] [--dm @NAME] [--dms]` | Search visible channel and DM history without moving cursors; add `--from`, `--kind`, `--before`, `--limit`, or `--reindex` to refine or rebuild |
| `taut system dump --output FILE` | Write an owner-only portable logical dump of registered pending messages, core authority, and installed durable extension state |
| `taut system load --input FILE [--dry-run]` | Validate or restore a dump into a fresh target; maintenance requires quiescence |
| `taut system doctor` | Passively run six fixed workspace checks; no repair, work claims, or provider loading |
| `taut list [--all \| --dms]` | Your threads with unread state; `--all` = every thread; `--dms` = every accessible DM, including read and empty conversations |
| `taut watch [THREAD_OR_DM ...]` | Follow selected channels/sub-threads or existing DMs; default = everything you're in plus your notification inbox |
| `taut who [THREAD]` | Members and presence |
| `taut whoami [--explain]` | Who taut thinks you are, and why |
| `taut rejoin [NAME] [--token TOKEN]` | Associate the current process claim with an existing member |

Global options: `--db PATH`, `--as NAME`, `--token TOKEN`, `--json`,
`-t/--timestamps`, `-q/--quiet`. Environment: `TAUT_DB`, `TAUT_AS`,
`TAUT_TOKEN`. Project reaction and terminal-rendering policy live in
`.taut.toml`. The actor-free `system` namespace accepts only `--db`, `--json`,
and `--quiet`; actor selectors and timestamps are usage errors.

**Exit codes** (SimpleBroker's convention): `0` success, `1` error, `2`
empty / nothing new / not found. So this is a polling inbox:

```bash
while sleep 5; do taut read -q && notify-send "taut: new messages"; done
```

Exit `2` deliberately combines empty and not-found results. Scripts that need
to distinguish those cases can inspect stderr when a diagnostic exists; blank
`say` and `reply` attempts are the deliberate silent case. The numeric code only
means that no requested record was produced. `--json` applies to successful
stdout records, not diagnostics: errors and warnings remain concise text on
stderr with the same exit codes.

The system doctor has one scoped exception: exit `2` means the report was
completed and one or more findings were detected. Framework, target, or
backend failures exit `1`; a healthy completed report exits `0`.

`say` and `reply` treat text as blank when it is empty or every character is
whitespace under Python's `str.isspace()` or has Unicode category `Cf`. A blank
attempt writes nothing and exits `2` without stdout or stderr. This is a small
input guard, not an exhaustive visibility test: an invisible non-`Cf` mark may
still be accepted. Any accepted text is stored exactly, without trimming or
normalization.

Multiline and other nonblank UTF-8 remain valid:

```bash
printf 'first line\nsecond line\n' | taut say general -
```

One high-water cursor represents each member's position in a thread. If an
older unread message prevents your cursor from advancing when you post, your
own new post remains unread behind it and can appear in the next `taut read`.
Taut does not add per-message read flags to hide only your own traffic.

Deleting a message removes only that broker row. It does not recall output
already fetched by another process, move or repair cursors, remove notification
pointers, close an empty DM, or delete a reply sub-thread rooted at that id.
An author may still delete after leaving because delete searches registered
chat threads. That post-departure operation is blind and irreversible: there
may be no permitted way to inspect the row first. It intentionally reveals only
whether a matching deletable own message was found.

For `reply`, `MSG_ID` accepts the full 19-digit message id (always
works, any age) or a unique suffix of 4+ digits — ids are timestamps,
and the last few digits are the part that varies. Suffix search covers
the thread's most recent 1,000 messages. `message show` and
`message delete` are stricter: they require the full 19-digit id so
the target is exact.

`message react` also requires the full id. It works only for an ordinary
message visible through a current membership. The audience is the current
exact channel, sub-thread, or validated DM membership, minus the actor. A
reaction is a consumable notification, not retained chat state; repeats create
distinct events. The actor's high-water cursor advances before one atomic
best-effort broadcast. A broadcast warning does not rewind the cursor and is
not safe to blind-retry because commit may already have occurred.

`read` is paged: one invocation displays and marks seen up to 1,000 unread
messages per thread. To drain a large backlog, run `taut read` again until it
exits `2` for nothing unread.

Search is also source-hydrated and cursor-neutral. Its index stores derived
lexemes and message identity, not a second verbatim body. Bare search covers
registered channels, their sub-threads, and DMs visible to the resolved actor;
explicit scope flags replace that default with their union. Results are newest
first. The SQLite and PostgreSQL interfaces, filters, visibility checks, and
ordering are the same, while backend-native Unicode tokenization can produce
different lexical matches. Portable ASCII word searches have the shared
result floor. Use `--json` for the fixed per-hit facet record and `--reindex`
to rebuild the disposable index before one query. The optional `taut-mcp`
adapter exposes the same core operation as its explicit `search` tool; it adds
no second query language or cross-backend ranking promise.

## Working With Agents

The agent side of taut is just the CLI with `--json` (ndjson): an
agent joins, catches up, and replies with three shell commands and
zero setup, keying on `from_id` for stable identity. The recipes — 
join/catch-up/say, identity selection, DM handles, the notification
and vanilla-`broker read` hazards, exit codes, and a session-start
pattern for `CLAUDE.md` / `AGENTS.md` — live in one place, the
[agent kernel](https://github.com/VanL/taut/blob/main/docs/agent-kernel.md).

## Python Library

From Python, the CLI's exact semantics are available as a library, plus a
multi-thread watcher (peek-only for chat history, claim/read for notifications,
cursor-tracked, membership-aware, with its fan-in waiter installed through
SimpleBroker's watcher lifecycle hooks):

```python
from taut import (
    Channel,
    DoctorCheck,
    DoctorReport,
    Message,
    MessageDeletion,
    MessageReaction,
    SearchHit,
    TautClient,
)

client = TautClient()  # finds .taut.db like git finds .git
# (or TautClient(db_path="…"))
client.join("general")
channel: Channel = client.set_channel_topic("general", "General project coordination")
print(channel.topic, channel.topic_updated_by_name)
message = client.say("general", "build finished: 312 passed")
print(message.ts)
shown = client.show_message(str(message.ts))  # peek; advances seen through it
reaction: MessageReaction = client.react_to_message(
    str(message.ts), "ack"
)  # requires another current member; best-effort pointer fanout
print(reaction.audience_count)
deleted: MessageDeletion = client.delete_message(str(message.ts))

for msg in client.read(limit=100):  # up to 100 per joined thread; advances cursors
    print(msg.thread, msg.from_id, msg.from_name, msg.text)

for dm in client.list_direct_messages():
    print(dm.name, dm.display_name, dm.unread)
    sent = client.say(dm.name, "stable existing conversation")
    assert sent.thread == dm.name

for msg in client.log("@claude"):  # stable dm.d_* handles also work
    print(msg.thread, msg.from_name, msg.text)

for hit in client.search("parser green", channels=("general",)):
    assert isinstance(hit, SearchHit)
    print(hit.thread, hit.ts, hit.kind, hit.text)


def handle(event):
    if isinstance(event, Message):
        print(event.thread, event.from_name, event.text)
    else:
        print("notification", event.type, event.thread, event.reaction)


watcher = client.watch(handle, threads=["@claude"])
thread = watcher.start()  # or watcher.run_forever() to block
# ...
watcher.stop()
thread.join(timeout=2)
```

Dump/load are actor-free class methods and do not require a client instance:

```python
dumped = TautClient.dump(output="backup.taut.jsonl")
checked = TautClient.load(input_path=dumped.path, dry_run=True)
restored = TautClient.load(input_path=dumped.path, db_path="restored.db")
```

Doctor is actor-free as well:

```python
report: DoctorReport = TautClient.doctor()
for check in report.checks:
    assert isinstance(check, DoctorCheck)
    print(check.name, check.status, check.detail)
```

## Trust Model (Read This Before Filing the Issue)

Taut's trust model is deliberately weak, and saying so loudly is part of
the design. The exact boundary is [TAUT-9] in the
[core spec](https://github.com/VanL/taut/blob/main/docs/specs/02-taut-core.md):

- **Everyone who can access the storage is root of the chat.** Any process
  that can read `.taut.db` or the configured Postgres schema can read all
  history; any that can write it can post as anyone — `--as` requires no
  proof.
- **Identity claims identify; they do not authenticate.** Process evidence,
  names, rejoin, and tokens make the common case frictionless and attribution
  inspectable (`whoami --explain`, claims on record) — not impossible to spoof.
  Explicit `as` and token selection choose an acting member; they do not prove
  who launched the process or silently bind that process for later commands.
- **The boundary is storage access.** `.taut.db` is created `0600`. Want
  another local user in the SQLite chat? That's a `chmod`/group decision you
  make, not one taut manages. With Postgres, the boundary is who can reach and
  write the configured database/schema. Wider, same shape: storage access *is*
  membership.
- **Summon widens what storage write access can cause.** A writer can inject
  user-role turns and storage-backed control requests into a summoned harness.
  With local SQLite that writer already has access to the same machine. With a
  shared Postgres workspace, a remote database writer can influence tools on
  the harness host. Grant write access only to principals authorized for that
  effect, or run the harness with separately constrained tools. Message
  framing, personas, driver evidence, names, and continuity tokens do not form
  an authorization boundary.

Untrusted content can still arrive indirectly. An agent may read a hostile web
page, follow a prompt injection, and echo terminal control bytes into chat.
Taut's human renderers make C0, DEL, and C1 controls visible by default before
writing dynamic text to a terminal. Storage, Python objects, and `--json`
remain exact. This is a safety control against accidental relay, not a security
boundary: a trusted caller may change or disable the display policy, and an
explicit Summon PTY attach remains a byte-transparent terminal protocol.
The exact escape contract is [TAUT-6.4] in the
[core spec](https://github.com/VanL/taut/blob/main/docs/specs/02-taut-core.md).

The baseline policy lives in packaged `taut/defaults.toml`. Humans can append
this optional table to a complete `.taut.toml`:

```toml
[terminal_text]
inherit_defaults = true
escape_patterns = ['[\u202a-\u202e]']
```

Omit the table to use packaged defaults. Set `inherit_defaults = false` to
replace them; an empty replacement disables filtering. The nearest
`.taut.toml` above the current directory owns presentation even when `--db` or
`TAUT_DB` selects storage elsewhere. A presentation-only table is not a full
project config: normal project discovery still requires `version`, `backend`,
and `target`.

Embedders and extensions use the same lazy public
`taut.escape_terminal_text(text, additional_patterns=...,
inherit_defaults=...)` function. Explicit `inherit_defaults=False` bypasses
both project and packaged policy. Project regexes are trusted local code-like
configuration: they can disable this safety default or impose expensive regex
work.

The one-line threat model: every participant could already do worse than
lie in chat, because they run code on your machine, as you. Taut is for
coordination inside a trust domain, not for establishing one.

## Things That Look Weird but Aren't

<details>
<summary><strong>Ordinary reading never deletes — isn't this a message queue?</strong></summary>

SimpleBroker queues normally hand each message to exactly one consumer.
Taut inverts that for chat history on purpose: channel, sub-thread, and
direct-message readers *peek*, and the queue **is** the history. "Read"
means "move my bookmark" — each member's position lives in a sidecar table,
and unread is just "is there anything after my bookmark?", answered by the
broker itself. `message show` is also a peek, but it advances the acting
member's cursor through the shown message. `message delete` is the explicit
exception: an author may remove their own ordinary message.

Notification inboxes are different. They are pointers for mentions,
replies, new direct
messages, and reactions, so `taut inbox` and `taut watch` claim them. If two sessions are the
same member, one can drain the other's notifications. That is the intended
single-directory model. A crash after `inbox` or notification watch has claimed
a pointer but before it displays can lose that pointer. A notification pointer
may also outlive a message that its author deletes. Taut does not cascade or
repair that pointer; later notification-worthy activity may create a new one,
while ordinary chat activity does not necessarily create one.

One consequence worth knowing: if you point a vanilla `broker read` at a taut
chat-history queue, you will consume messages out of the history. Taut
tolerates it; your teammates may not.

Owning contracts: [TAUT-7] read model in the
[core spec](https://github.com/VanL/taut/blob/main/docs/specs/02-taut-core.md);
[IAN-7] notifications in the
[identity spec](https://github.com/VanL/taut/blob/main/docs/specs/03-identity-addressing-notifications.md).
</details>

<details>
<summary><strong>Where's the daemon?</strong></summary>

There isn't one. SQLite WAL gives concurrent
readers and writers; SimpleBroker gives durable ordered queues over it;
`taut watch` is an efficient poller (burst, then backoff, woken by the
database's own change counter) rather than a resident service. When no
one is watching, taut is no processes at all. The no-daemon account —
including what could ever change it — is adopted alternative A4 in the
[program theory](https://github.com/VanL/taut/blob/main/docs/program-theory.md);
watcher behavior is [TAUT-8.4] in the
[core spec](https://github.com/VanL/taut/blob/main/docs/specs/02-taut-core.md).
</details>

<details>
<summary><strong>One file? Really?</strong></summary>

By default, yes. Messages, threads, members, identity claims, names,
notifications, and read cursors all live in `.taut.db` (SQLite's transient
`-wal`/`-shm` companions come and go). A stopped-workspace physical copy is
still possible, but `taut system dump` is the portable logical backup and also
works across SQLite and PostgreSQL. Under `taut-pg`, the same `taut_*` sidecar
tables live beside SimpleBroker's tables in the configured Postgres schema.
Owning contracts: [TAUT-2] storage model in the
[core spec](https://github.com/VanL/taut/blob/main/docs/specs/02-taut-core.md)
and the
[persistence spec](https://github.com/VanL/taut/blob/main/docs/specs/08-persistence-io.md).
</details>

<details>
<summary><strong>Why is every message a little JSON envelope?</strong></summary>

`{"from_id":"m_abcd...","from":"van","kind":"message","text":"hi"}` — because
stable sender id, sender-name snapshot, and type have to live somewhere,
message bodies can contain newlines and terminal escapes, and JSON-per-line is
the convention every shell tool already speaks. The broker's 64-bit hybrid
timestamp is the message id *and* its time, so the envelope never carries
either. Bodies that aren't envelopes (someone `broker write`-ing into a
thread) render as plain text from sender `?` instead of breaking anything.
Owning contract: [TAUT-6.1] and [TAUT-6.3] in the
[core spec](https://github.com/VanL/taut/blob/main/docs/specs/02-taut-core.md).
</details>

<details>
<summary><strong>Why no auth, signing, or encryption?</strong></summary>

Because it would be theater at this layer. Anyone in the trust boundary
(your machine, your uid) can already modify the database file directly.
Taut spends its effort on the thing that's actually missing — frictionless
identity and coordination — and is honest that the filesystem is the
security model. The refusal is durable: adopted alternative A3 in the
[program theory](https://github.com/VanL/taut/blob/main/docs/program-theory.md),
with the boundary itself specified by [TAUT-9] in the
[core spec](https://github.com/VanL/taut/blob/main/docs/specs/02-taut-core.md).
</details>

<details>
<summary><strong>Why argparse and a small dependency set?</strong></summary>

Taut follows SimpleBroker's discipline: the install should be boring.
Runtime dependencies are exactly `simplebroker>=7.0.0` and `psutil`. The CLI is
argparse, the storage is stdlib `sqlite3` (via SimpleBroker), and `psutil`
keeps identity capture from relying on fragile platform-specific command
parsing. The planned TUI ships as an optional extra so the core dependency
set stays small. The dependency contract is exact in the
[core spec](https://github.com/VanL/taut/blob/main/docs/specs/02-taut-core.md)
(runtime dependencies section), and dependencies are gated against the
package manifests.
</details>

## Documentation Map

This README is the human product entry and, per section, the contract
of record until a section is ceded to its spec — the
[product-section registry](https://github.com/VanL/taut/blob/main/docs/specs/product-section-registry.md)
is the authority table naming the winning contract for each behavior
family. The layers:

- **Conceptual account:**
  [`docs/program-theory.md`](https://github.com/VanL/taut/blob/main/docs/program-theory.md) — what kind of
  system Taut is, the durable principles and non-goals, and the
  adopted design decisions with their reconsider-when conditions.
- **Exact behavior (normative):** the specs, indexed at
  [`docs/specs/00-specs-index.md`](https://github.com/VanL/taut/blob/main/docs/specs/00-specs-index.md) —
  core ([`02-taut-core.md`](https://github.com/VanL/taut/blob/main/docs/specs/02-taut-core.md)), identity
  ([`03-identity-addressing-notifications.md`](https://github.com/VanL/taut/blob/main/docs/specs/03-identity-addressing-notifications.md)),
  summon ([`04-summon.md`](https://github.com/VanL/taut/blob/main/docs/specs/04-summon.md)), MCP
  ([`05-taut-mcp.md`](https://github.com/VanL/taut/blob/main/docs/specs/05-taut-mcp.md)), search
  ([`06-search.md`](https://github.com/VanL/taut/blob/main/docs/specs/06-search.md)).
- **Extension depth:** each extension's own README —
  [`extensions/taut_pg/README.md`](https://github.com/VanL/taut/blob/main/extensions/taut_pg/README.md),
  [`extensions/taut_summon/README.md`](https://github.com/VanL/taut/blob/main/extensions/taut_summon/README.md),
  [`extensions/taut_mcp/README.md`](https://github.com/VanL/taut/blob/main/extensions/taut_mcp/README.md).
- **Released behavior deltas:** [CHANGELOG.md](https://github.com/VanL/taut/blob/main/CHANGELOG.md).
- **For agents using a Taut workspace:** the
  [agent kernel](https://github.com/VanL/taut/blob/main/docs/agent-kernel.md)
  — the one home for agent-executable recipes; a machine-oriented link
  index also ships as
  [`llms.txt`](https://github.com/VanL/taut/blob/main/llms.txt).
- **For agents working in this repository:** start at
  [`AGENTS.md`](https://github.com/VanL/taut/blob/main/AGENTS.md), which routes to the canonical startup
  order.

## Roadmap

Docs-first: everything ships behind its own spec.

**Shipped** (each with its governing spec):

- **Summon** — `taut-summon` hosts an agent harness as a thread member
  (chat its ears, the CLI its mouth), daemon-free, speaking the
  agent-task control contract Weft pioneered, with a conformance suite
  portable enough for Weft to run against its own agent lane
  ([`docs/specs/04-summon.md`](https://github.com/VanL/taut/blob/main/docs/specs/04-summon.md)).
  The universal PTY adapter hosts named providers including `claude`
  and `codex`.
- **MCP** — `taut-mcp` exposes the workspace to MCP clients: stdio
  lifecycle, per-workspace identity, CLI-shaped tools
  ([`docs/specs/05-taut-mcp.md`](https://github.com/VanL/taut/blob/main/docs/specs/05-taut-mcp.md)).
- **Search** — cursor-neutral full-text search over visible history,
  SQLite FTS5 and PostgreSQL text search behind one API
  ([`docs/specs/06-search.md`](https://github.com/VanL/taut/blob/main/docs/specs/06-search.md)).

**Shipped:** portable dump/load maintenance and the passive six-check system
doctor.

**Ahead, in order:**

- **TUI** (`taut-chat[tui]`): panes for threads, live presence, zero new core
  dependencies.
- **Redis/Valkey backend.** Queues already work (`simplebroker-redis`).
  Taut's member/cursor state rides sidecar *tables* on SQL backends, so
  Redis needs a small data-structure mapping instead — same instance,
  second connection, `taut:*` keys. Design first, then it ships.

## Development

Taut is developed docs-first: the spec
([`docs/specs/02-taut-core.md`](https://github.com/VanL/taut/blob/main/docs/specs/02-taut-core.md)) defines
behavior, dated plans in [`docs/plans/`](https://github.com/VanL/taut/tree/main/docs/plans) define execution,
and both are kept in CI-grade sync with the code. Start with
[`AGENTS.md`](https://github.com/VanL/taut/blob/main/AGENTS.md) if you're contributing — human or otherwise.

```bash
git clone git@github.com:VanL/taut.git && cd taut
uv sync --all-extras
uv run --extra dev pytest
uv run bin/check-cli-claims
uv run --extra dev pytest extensions/taut_summon/tests
uv run --project extensions/taut_mcp --extra dev pytest extensions/taut_mcp/tests
uv run ./bin/pytest-pg --fast
uv run ruff check taut tests bin extensions/taut_pg/taut_pg extensions/taut_pg/tests extensions/taut_summon/taut_summon extensions/taut_summon/tests extensions/taut_mcp/taut_mcp extensions/taut_mcp/tests
uv run ruff format --check taut tests bin extensions/taut_pg/taut_pg extensions/taut_pg/tests extensions/taut_summon/taut_summon extensions/taut_summon/tests extensions/taut_mcp/taut_mcp extensions/taut_mcp/tests
uv run --extra dev mypy taut tests bin/release.py extensions/taut_pg/taut_pg extensions/taut_pg/tests --config-file pyproject.toml
# separate run: each extension's tests carry a top-level conftest module,
# and one mypy invocation cannot hold two modules named `conftest`
uv run --extra dev mypy taut tests extensions/taut_summon/taut_summon extensions/taut_summon/tests --config-file pyproject.toml
uv run --project extensions/taut_mcp --extra dev mypy extensions/taut_mcp/taut_mcp extensions/taut_mcp/tests --config-file extensions/taut_mcp/pyproject.toml
uv build --out-dir dist .
uv build --out-dir extensions/taut_pg/dist extensions/taut_pg
uv build --out-dir extensions/taut_summon/dist extensions/taut_summon
uv build --out-dir extensions/taut_mcp/dist extensions/taut_mcp
```

Tests follow the house anti-mocking rule: the broker is never mocked,
identity tests spawn real process chains, and CLI tests drive the real
entry point.

Release preparation is local; publication is tag-driven:

```bash
uv run python bin/release.py --dry-run
uv run python bin/release.py --version X.Y.Z
uv run python bin/release.py pg --dry-run
uv run python bin/release.py summon --dry-run
uv run python bin/release.py mcp --dry-run
uv run python bin/release.py all --dry-run
uv run python bin/release.py all --check-repository-settings
```

The helper updates version files, runs the release gates, manages root
`vX.Y.Z` tags plus extension `taut_pg/vX.Y.Z`, `taut_summon/vX.Y.Z`, and
`taut_mcp/vX.Y.Z` tags, syncs first-party dependency floors and retained locks,
checks both PyPI and GitHub publication state, and pushes to GitHub. Every
target runs the same universal local prechecks,
including the explicit non-PostgreSQL MCP lane. Live MCP PostgreSQL proof comes
from the required canonical MCP workflow, not from skipped local cases. Tag
pushes run the package's GitHub Actions release gate, which requires the exact
commit's root, PostgreSQL, and MCP workflows. The gate stages the exact
root-workflow bundle as a draft GitHub Release, publishes those bytes through
the package's top-level PyPI Trusted Publisher, verifies PyPI filenames and
SHA-256 digests, and only then publishes the GitHub Release as immutable. It
does not rebuild.

Before the first real release, enable immutable GitHub Releases and create a
`pypi` environment whose custom tag policies are exactly `v*`, `taut_pg/v*`,
`taut_summon/v*`, and `taut_mcp/v*`. Configure four PyPI Trusted Publishers
for repository `VanL/taut`, environment `pypi`, and the exact top-level
workflow for each distribution:

- `taut-chat`: `.github/workflows/release-gate.yml`
- `taut-pg`: `.github/workflows/release-gate-pg.yml`
- `taut-summon`: `.github/workflows/release-gate-summon.yml`
- `taut-mcp`: `.github/workflows/release-gate-mcp.yml`

The settings check verifies the GitHub half. PyPI publisher configuration is
operator-owned and must be checked in PyPI before pushing release tags.

## License

MIT © Van Lindberg

## Acknowledgments

Built on [SimpleBroker](https://github.com/VanL/simplebroker), with the
multi-queue watcher pattern adapted from
[Weft](https://github.com/VanL/weft).

The name is the design goal: the opposite of slack.
