# Taut

  [![CI](https://github.com/VanL/taut/actions/workflows/test.yml/badge.svg)](https://github.com/VanL/taut/actions/workflows/test.yml)
  [![codecov](https://codecov.io/gh/VanL/taut/branch/main/graph/badge.svg)](https://codecov.io/gh/VanL/taut)
  [![Python versions](https://img.shields.io/badge/python-3.11%20%7C%203.12%20%7C%203.13%20%7C%203.14-blue)](https://github.com/VanL/taut/blob/main/pyproject.toml)

*Slack in your terminal, for you and your agents. No server, no daemon, no
config, no accounts. One SQLite file by default; Postgres when you need it.*

> **Status:** alpha, GitHub-release only. This README is the intended product
> contract, written first on purpose. The core specification lives in
> [`docs/specs/02-taut-core.md`](docs/specs/02-taut-core.md); identity,
> addressing, direct messages, and notifications are specified in
> [`docs/specs/03-identity-addressing-notifications.md`](docs/specs/03-identity-addressing-notifications.md).

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

## Features

- **Zero configuration by default** — no server, no daemon, no dotfiles, no
  account. `taut init` creates one file; that file is the entire SQLite
  installation.
- **Humans and agents are both first-class** — every command has `--json`
  (ndjson) output; agents are recognized automatically (see below).
- **Real history** — messages are never consumed. Reading moves *your*
  bookmark; the conversation stays.
- **Unread tracking per participant** — `taut list` shows what's new *for
  you*; exit codes make it shell-composable.
- **Live following** — `taut watch` streams every thread you're in, and
  picks up threads you join while it runs.
- **Direct messages by current name** — `taut say @claude ...` maps the
  current name to a member-id pair queue, so later renames do not move the
  conversation.
- **Consumable notifications** — mentions and new DMs can wake the member's
  notification inbox without adding per-device state.
- **Stable member identity** — names can change, but messages, cursors,
  direct messages, and notifications stay tied to an opaque member id.
  Process evidence makes the common case automatic; `whoami --explain`
  keeps it inspectable.
- **SimpleBroker all the way down** — `.taut.db` is a standard SimpleBroker
  database. `broker -f .taut.db list` works. Plumbing is not hidden.

## Installation

```bash
pipx install "git+https://github.com/VanL/taut.git@v0.4.0"       # CLI use
uv add "taut @ git+https://github.com/VanL/taut.git@v0.4.0"      # as a library
```

Requirements: Python 3.11+. Runtime dependencies are `simplebroker>=5.1.0`
(which itself has none) and `psutil` for cross-platform process metadata.

PyPI install names stay out of the documented path until the `taut` package
name is cleared.

### Postgres Extension

`taut-pg` is a separate package. Install it into the same environment as
`taut`; it brings in `simplebroker-pg` and the Postgres driver dependencies.
Until PyPI clearance changes, install core from the desired Taut tag and
inject a compatible extension wheel from the extension release stream. The
extension uses its own `taut_pg/vX.Y.Z` tags, so its version does not have to
match the core package version:

```bash
pipx install "git+https://github.com/VanL/taut.git@v0.4.0"
pipx inject taut ./taut_pg-0.4.0-py3-none-any.whl
```

The Postgres database must already exist. Create `.taut.toml` in the project
root:

```toml
version = 1
backend = "postgres"
target = "postgresql://postgres:postgres@127.0.0.1:54329/taut_test"

[backend_options]
schema = "taut_project"
```

Then run `taut init` normally. It initializes the configured schema and
tables; it does not provision the database. `taut init --json` reports `db`
as the resolved backend display target. For Postgres, `created` is `false`
because Taut does not have a public backend creation signal. `TAUT_DB`,
`--db`, and `db_path=` remain filesystem path selectors; `.taut.toml` is the
Postgres door.

## Quick Start

```bash
# One-time, per project (like git init)
$ cd ~/myproject
$ taut init

# Channels are created by joining them
$ taut join general
$ taut say general "anyone awake?"

# …an agent in another terminal joins and answers…

# What's new for me? (exit 2 when nothing — composable in scripts)
$ taut list
general  2 unread
$ taut read general
── general ──────────────────────────────────────
  09:15 · claude joined
  09:15 claude  yes. what broke?

# History never disappears; log doesn't move your bookmark
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

Direct messages use `@name` and route through the member's current name, not
through the display name captured in old messages:

```bash
$ taut say @claude "can you check the parser branch?"
```

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
{"member_id":"m_abcd1234abcd1234abcd1234ab","name":"claude","kind":"agent","presence":"here","last_active_ts":1837025672140161024,"persona":null}
$ taut set name codex
$ taut whoami --json | jq -r .member_id
m_abcd1234abcd1234abcd1234ab
```

Messages keep the sender name from the moment they were written. If `claude`
renames to `codex`, old messages still say `claude`; new messages say `codex`.
Machine consumers use `from_id` when they need stable identity:

```json
{"thread":"general","ts":1837025672140161024,"from_id":"m_abcd1234abcd1234abcd1234ab","from":"claude","kind":"message","text":"parser is green"}
```

The automatic part is still process evidence. When a command runs, taut walks
the caller's process ancestry, looks past shells and wrapper commands, and
records a deterministic identity claim for the process or human session:

- pid + process start time where available
- executable path, argv, cwd, uid
- parent chain, process group, session, controlling tty
- host identity plus hostname for display

That claim maps to the member id. If the claim is known, taut knows who is
speaking. If an agent restarts and gets a new process claim, taut creates a new
member only when it cannot safely infer continuity. Then it tells you what it
noticed:

```text
created new identity 'claudette'
note: you may be one of these:
  claude  same executable, same cwd
reclaim with 'taut rejoin claude'
```

`taut rejoin claude` associates the current process claim with the member
currently named `claude`. It does not rename the member and it does not rewrite
history.

For process trees that churn constantly, every member also gets a continuity
token at creation. Stash it in your agent's state, and
`TAUT_TOKEN=taut-7f3k9q2m taut say ...` is that same member from anywhere. It is
continuity, not security: anyone with storage access can still use `--as`.

Presence remains evidence-based. `taut who` checks whether local agent process
claims still appear alive; members anchored elsewhere in a shared Postgres
backend show remote-style presence rather than pretending local liveness is
knowable.

When the magic guesses wrong, `--as NAME_OR_ALIAS` (or `TAUT_AS`) always wins for
that command. One boundary to know: recognition cannot cross ssh or container
walls unless you pass `TAUT_AS` or `TAUT_TOKEN` through.

## Command Reference

| Command | Description |
|---------|-------------|
| `taut init` | Create `.taut.db` in the current directory |
| `taut join THREAD [--as NAME] [--persona TEXT] [--new]` | Join (creating if needed) a channel; you start at now |
| `taut leave THREAD` | Leave a thread; history stays |
| `taut set name NAME` | Change your current display/routing name; old messages keep the old name |
| `taut say THREAD\|@NAME [TEXT\|-]` | Post to a channel, sub-thread, or direct message (stdin with `-` or a pipe) |
| `taut reply THREAD MSG_ID [TEXT\|-]` | Reply in a sub-thread, creating it on first reply |
| `taut read [THREAD]` | Show unread and advance your bookmark; bare = all your threads |
| `taut inbox` | Claim and show notification pointers for mentions and new DMs |
| `taut log THREAD [--since TS] [--limit N]` | Show history; never moves your bookmark |
| `taut list [--all]` | Your threads with unread state; `--all` = every thread |
| `taut watch [THREAD ...]` | Follow live; default = everything you're in plus your notification inbox |
| `taut rename OLD NEW` | Rename a channel and its sub-threads |
| `taut who [THREAD]` | Members and presence |
| `taut whoami [--explain]` | Who taut thinks you are, and why |
| `taut rejoin [NAME] [--token TOKEN]` | Associate the current identity evidence with an existing member |

Global options: `--db PATH`, `--as NAME`, `--token TOKEN`, `--json`,
`-t/--timestamps`, `-q/--quiet`. Environment: `TAUT_DB`, `TAUT_AS`,
`TAUT_TOKEN`. That's the whole configuration surface.

**Exit codes** (SimpleBroker's convention): `0` success, `1` error, `2`
empty / nothing new / not found. So this is a polling inbox:

```bash
while sleep 5; do taut read -q && notify-send "taut: new messages"; done
```

`MSG_ID` accepts the full 19-digit message id (always works, any age) or
a unique suffix of 4+ digits — ids are timestamps, and the last few
digits are the part that varies. Suffix search covers the thread's most
recent 1,000 messages.

`read` is paged: one invocation displays and marks seen up to 1,000 unread
messages per thread. To drain a large backlog, run `taut read` again until it
exits `2` for nothing unread.

## Working With Agents

The agent side of taut is just the CLI with `--json`:

```bash
# An agent catching up and replying
$ taut read --json
{"thread":"general","ts":1837025672140161024,"from_id":"m_k7p9x2q4m6n8r1s3t5v7w9y0za","from":"van","kind":"message","text":"anyone awake?"}
$ taut say general "on it"

# An agent following everything, as a stream
$ taut watch --json | while IFS= read -r line; do handle "$line"; done
```

A pattern that works well in `CLAUDE.md` / `AGENTS.md`:

```markdown
This project uses taut for coordination. At the start of a session run
`taut join dev`, check `taut read --json`, and post status updates with
`taut say dev "..."`. If taut says it created a new identity, run the
suggested `taut rejoin` command.
```

From Python, the CLI's exact semantics are available as a library, plus a
multi-thread watcher (peek-only for chat history, claim/read for notifications,
cursor-tracked, membership-aware, with its fan-in waiter installed through
SimpleBroker's watcher lifecycle hooks):

```python
from taut import Message, TautClient

client = TautClient()           # finds .taut.db like git finds .git
                                # (or TautClient(db_path="…"))
client.join("general")
message = client.say("general", "build finished: 312 passed")
print(message.ts)

for msg in client.read():       # advances this member's cursors
    print(msg.thread, msg.from_id, msg.from_name, msg.text)

def handle(event):
    if isinstance(event, Message):
        print(event.thread, event.from_name, event.text)
    else:
        print("notification", event.type, event.thread)

watcher = client.watch(handle)
thread = watcher.start()        # or watcher.run_forever() to block
# ...
watcher.stop()
thread.join(timeout=2)
```

## Trust Model (Read This Before Filing the Issue)

Taut's trust model is deliberately weak, and saying so loudly is part of
the design:

- **Everyone who can access the storage is root of the chat.** Any process
  that can read `.taut.db` or the configured Postgres schema can read all
  history; any that can write it can post as anyone — `--as` requires no
  proof.
- **Identity claims identify; they do not authenticate.** Process evidence,
  names, rejoin, and tokens make the common case frictionless and attribution
  inspectable (`whoami --explain`, claims on record) — not impossible to spoof.
- **The boundary is storage access.** `.taut.db` is created `0600`. Want
  another local user in the SQLite chat? That's a `chmod`/group decision you
  make, not one taut manages. With Postgres, the boundary is who can reach and
  write the configured database/schema. Wider, same shape: storage access *is*
  membership.

The one-line threat model: every participant could already do worse than
lie in chat, because they run code on your machine, as you. Taut is for
coordination inside a trust domain, not for establishing one.

## Things That Look Weird but Aren't

<details>
<summary><strong>Reading never deletes — isn't this a message queue?</strong></summary>

SimpleBroker queues normally hand each message to exactly one consumer.
Taut inverts that for chat history on purpose: channel, sub-thread, and
direct-message readers *peek*, and the queue **is** the history. "Read"
means "move my bookmark" — each member's position lives in a sidecar table,
and unread is just "is there anything after my bookmark?", answered by the
broker itself.

Notification inboxes are different. They are pointers for pings and new direct
messages, so `taut inbox` and `taut watch` claim them. If two sessions are the
same member, one can drain the other's notifications. That is the intended
single-directory model.

One consequence worth knowing: if you point a vanilla `broker read` at a taut
chat-history queue, you will consume messages out of the history. Taut
tolerates it; your teammates may not.
</details>

<details>
<summary><strong>Where's the daemon?</strong></summary>

There isn't one. SQLite WAL gives concurrent
readers and writers; SimpleBroker gives durable ordered queues over it;
`taut watch` is an efficient poller (burst, then backoff, woken by the
database's own change counter) rather than a resident service. When no
one is watching, taut is no processes at all.
</details>

<details>
<summary><strong>One file? Really?</strong></summary>

By default, yes. Messages, threads, members, identity claims, names,
notifications, and read cursors all live in `.taut.db` (SQLite's transient
`-wal`/`-shm` companions come and go). Backup is `cp`, deletion is `rm`, and
"export the workspace" is the file. Under `taut-pg`, the same `taut_*` sidecar
tables live beside SimpleBroker's tables in the configured Postgres schema.
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
</details>

<details>
<summary><strong>Why no auth, signing, or encryption?</strong></summary>

Because it would be theater at this layer. Anyone in the trust boundary
(your machine, your uid) can already modify the database file directly.
Taut spends its effort on the thing that's actually missing — frictionless
identity and coordination — and is honest that the filesystem is the
security model.
</details>

<details>
<summary><strong>Why argparse and a small dependency set?</strong></summary>

Taut follows SimpleBroker's discipline: the install should be boring.
Runtime dependencies are exactly `simplebroker>=5.1.0` and `psutil`. The CLI is
argparse, the storage is stdlib `sqlite3` (via SimpleBroker), and `psutil`
keeps identity capture from relying on fragile platform-specific command
parsing. The planned TUI ships as an optional extra so the core dependency
set stays small.
</details>

## Roadmap

In order, each behind its own spec (this project is docs-first):

- **`taut summon` — captive agents.** Spawn an agent *as a thread
  member*: messages in the thread become its prompts, its output becomes
  replies. Ships as a separate extension (`taut-summon`) so the core
  keeps the same small dependency set, runs daemon-free, and speaks the
  same agent-task contract Weft pioneered — same control verbs, same queue
  shapes — with a conformance suite both projects can run.
- **TUI** (`taut[tui]`): panes for threads, live presence, zero new core
  dependencies.
- **Redis/Valkey backend.** Queues already work (`simplebroker-redis`).
  Taut's member/cursor state rides sidecar *tables* on SQL backends, so
  Redis needs a small data-structure mapping instead — same instance,
  second connection, `taut:*` keys. Design first, then it ships.

## Development

Taut is developed docs-first: the spec
([`docs/specs/02-taut-core.md`](docs/specs/02-taut-core.md)) defines
behavior, dated plans in [`docs/plans/`](docs/plans/) define execution,
and both are kept in CI-grade sync with the code. Start with
[`AGENTS.md`](AGENTS.md) if you're contributing — human or otherwise.

```bash
git clone git@github.com:VanL/taut.git && cd taut
uv sync --all-extras
uv run pytest
uv run ./bin/pytest-pg --fast
uv run ruff check taut tests bin extensions/taut_pg/taut_pg extensions/taut_pg/tests
uv run ruff format --check taut tests bin extensions/taut_pg/taut_pg extensions/taut_pg/tests
uv run --extra dev mypy taut tests bin/release.py extensions/taut_pg/taut_pg extensions/taut_pg/tests --config-file pyproject.toml
uv build
uv build extensions/taut_pg
```

Tests follow the house anti-mocking rule: the broker is never mocked,
identity tests spawn real process chains, and CLI tests drive the real
entry point.

Release prep is local and GitHub-only:

```bash
uv run python bin/release.py --dry-run
uv run python bin/release.py --version X.Y.Z
uv run python bin/release.py --target pg --dry-run
```

The helper updates version files, runs the release gates, manages root
`vX.Y.Z` tags and extension `taut_pg/vX.Y.Z` tags, and pushes to GitHub. Tag
pushes run the GitHub Actions release gate, which creates the GitHub Release
and uploads the built source/wheel artifacts. It does not upload to PyPI.

## License

MIT © Van Lindberg

## Acknowledgments

Built on [SimpleBroker](https://github.com/VanL/simplebroker), with the
multi-queue watcher pattern adapted from
[Weft](https://github.com/VanL/weft).

The name is the design goal: the opposite of slack.
