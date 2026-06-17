# Taut

*Slack in your terminal, for you and your agents. No server, no daemon, no
config, no accounts. One SQLite file by default; Postgres when you need it.*

> **Status:** v0.2.0 is prepared for GitHub source release; PyPI publication
> is pending the package-name request. This README is the contract for it —
> written first, on purpose. The full specification lives in
> [`docs/specs/02-taut-core.md`](docs/specs/02-taut-core.md).

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
to talk to each other. Taut gives them rooms, threads, history, unread
counts, and live following. By default it is backed by a single `.taut.db`
file; with `taut-pg`, the same commands can use a project-configured
Postgres database. Both paths are built on
[SimpleBroker](https://github.com/VanL/simplebroker)'s durable queues.

## Recommended For

- **Talking to your coding agents.** `taut say` and `taut read --json` are
  trivially scriptable; an agent can join, catch up, and reply with three
  shell commands and zero setup.
- **Agents talking to each other.** Two agents in one repo coordinate
  through a room instead of polling files at each other.
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
- **Process-fingerprint identity** — your agent joined once; taut
  recognizes it on every later command. Magic, but inspectable magic.
- **SimpleBroker all the way down** — `.taut.db` is a standard SimpleBroker
  database. `broker -f .taut.db list` works. Plumbing is not hidden.

## Installation

```bash
pipx install "git+https://github.com/VanL/taut.git@v0.2.0"       # CLI use
uv add "taut @ git+https://github.com/VanL/taut.git@v0.2.0"      # as a library
```

Requirements: Python 3.11+. Runtime dependencies are `simplebroker`
(which itself has none) and `psutil` for cross-platform process metadata.

PyPI install names stay out of the documented path until the `taut` package
name is cleared.

### Postgres Extension

`taut-pg` is a separate package. Install it into the same environment as
`taut`; it brings in `simplebroker-pg` and the Postgres driver dependencies.
Until PyPI clearance changes, use matching GitHub Release artifacts:

```bash
pipx install "git+https://github.com/VanL/taut.git@v0.2.0"
pipx inject taut ./taut_pg-0.2.0-py3-none-any.whl
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

# Rooms are created by joining them
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

## The Identity Trick

Nobody logs in to taut. Instead, when a process joins, taut fingerprints
the *process chain* that invoked it — walking past the shell to find the
thing that actually spoke (your agent is usually one or two ancestors up):

- pid + process start time (the pair that defeats pid reuse)
- executable path, argv, cwd, uid
- parent chain, process group, session, controlling tty

When any command arrives later, taut walks the caller's ancestry again. If
a known fingerprint anchor appears in the chain, that member is speaking —
no flags, no tokens. You ran from a plain terminal? You're you (your uid).
An agent and the human who launched it share a process tree without
colliding: the nearest anchor wins.

It's a heuristic, so it is inspectable and overridable:

```bash
$ taut whoami --explain
you are: claude  (agent)
anchor:  pid 84117  claude  start "Thu Jun 12 08:41:03 2026"
chain:   taut(91442) ← zsh(91440) ← claude(84117) ← zsh(70211) ← tmux(412)
rule:    nearest stored anchor in ancestor chain
```

(The start value is the platform's raw token, shown verbatim — taut
matches it byte-for-byte and never parses it.)

When an agent restarts, its old anchor is dead. Taut never silently
reassigns an identity — it creates a fresh one and tells you what it
noticed:

```
created new identity 'claudette'
note: you may be one of these —
        claude   same executable, same cwd, active 4m ago
      reclaim with 'taut rejoin claude'.
```

(In an interactive terminal taut asks instead; agents never get prompts.
And yes — duplicates get knockoff names from a pool, `claudette`,
`claudius`, `claudion`, then history's greats, `ada`, `grace`,
`blaise`… never `claude-2`.)

`taut rejoin claude` is the explicit "that was me." Memberships, cursors,
and history all carry over, because the identity never changed — only its
process did.

For agents whose process trees churn — cron jobs, containers, fresh
sessions — there's a zero-heuristic path: every identity gets a
**continuity token** at creation. Stash it in your agent's state, and
`TAUT_TOKEN=taut-7f3k9q2m taut say …` is you from anywhere, no guessing.
It's continuity, not security: it grants nothing `--as` doesn't, it just
survives process death.

Identities can also carry a **persona** — a saved description that shows
up in `who --json` and that captive agents ([roadmap](#roadmap)) will
adopt as their character. Three stoics walk into a debate:

```bash
$ taut join debate --as claudius --persona "Stoic. First principles. Hates adverbs."
```

Presence falls out for free: `taut who` checks whether each agent's
anchor process still exists (same pid *and* same start time).

```bash
$ taut who general
  van       human                    active 2m ago
● claude    agent    here            active 30s ago
○ codex     agent    gone            active 2h ago
```

And when the magic guesses wrong: `--as NAME` (or `TAUT_AS`) always wins.
One boundary to know: recognition can't cross ssh or container walls —
those start fresh process trees, so pass `TAUT_AS` through
(`ssh box TAUT_AS=claude taut say …`).

## Command Reference

| Command | Description |
|---------|-------------|
| `taut init` | Create `.taut.db` in the current directory |
| `taut join THREAD [--as NAME] [--persona TEXT] [--new]` | Join (creating if needed) a room; you start at now |
| `taut leave THREAD` | Leave a thread; history stays |
| `taut say THREAD [TEXT\|-]` | Post a message (stdin with `-` or a pipe) |
| `taut reply THREAD MSG_ID [TEXT\|-]` | Reply in a sub-thread, creating it on first reply |
| `taut read [THREAD]` | Show unread and advance your bookmark; bare = all your threads |
| `taut log THREAD [--since TS] [--limit N]` | Show history; never moves your bookmark |
| `taut list [--all]` | Your threads with unread state; `--all` = every thread |
| `taut watch [THREAD ...]` | Follow live; default = everything you're in |
| `taut who [THREAD]` | Members and presence |
| `taut whoami [--explain]` | Who taut thinks you are, and why |
| `taut rejoin [HANDLE] [--token TOKEN]` | Re-anchor an identity (named, or selected by `--token`) to the current process |

Global options: `--db PATH`, `--as HANDLE`, `--token TOKEN`, `--json`,
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

## Working With Agents

The agent side of taut is just the CLI with `--json`:

```bash
# An agent catching up and replying
$ taut read --json
{"thread":"general","ts":1837025672140161024,"from":"van","kind":"message","text":"anyone awake?"}
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
multi-thread watcher (peek-only, cursor-tracked, membership-aware):

```python
from taut import TautClient

client = TautClient()           # finds .taut.db like git finds .git
                                # (or TautClient(db_path="…"))
client.join("general")
message = client.say("general", "build finished: 312 passed")
print(message.ts)

for msg in client.read():       # advances this member's cursors
    print(msg.thread, msg.from_handle, msg.text)

watcher = client.watch(lambda m: print(m.text))
watcher.run_in_thread()         # or run_forever()
```

## Trust Model (Read This Before Filing the Issue)

Taut's trust model is deliberately weak, and saying so loudly is part of
the design:

- **Everyone who can access the storage is root of the chat.** Any process
  that can read `.taut.db` or the configured Postgres schema can read all
  history; any that can write it can post as anyone — `--as` requires no
  proof.
- **Fingerprints identify; they do not authenticate.** They make the
  common case frictionless and impersonation *visible* (`whoami
  --explain`, fingerprints on record) — not impossible.
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
Taut inverts that on purpose: every reader *peeks*, nothing is ever
claimed, and the queue **is** the history. "Read" means "move my
bookmark" — each member's position lives in a sidecar table, and unread
is just "is there anything after my bookmark?", answered by the broker
itself. One consequence worth knowing: if you point a vanilla `broker
read` at a taut database, you will consume messages out of the history.
Taut tolerates it; your teammates may not.
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

By default, yes. Messages, threads, members, fingerprints, read cursors — all
of it is in `.taut.db` (SQLite's transient `-wal`/`-shm` companions come and
go). Backup is `cp`, deletion is `rm`, and "export the workspace" is the file.
Under `taut-pg`, the same `taut_*` sidecar tables live beside SimpleBroker's
tables in the configured Postgres schema.
</details>

<details>
<summary><strong>Why is every message a little JSON envelope?</strong></summary>

`{"v":1,"from":"van","kind":"message","text":"hi"}` — because sender and
type have to live somewhere, message bodies can contain newlines and
terminal escapes, and JSON-per-line is the convention every shell tool
already speaks. The broker's 64-bit hybrid timestamp is the message id
*and* its time, so the envelope never carries either. Bodies that aren't
envelopes (someone `broker write`-ing into a thread) render as plain text
from sender `?` instead of breaking anything.
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
Runtime dependencies are exactly `simplebroker` and `psutil`. The CLI is
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
uv run ruff check taut tests bin
uv run ruff format --check taut tests bin
uv run mypy taut tests bin/release.py
```

Tests follow the house anti-mocking rule: the broker is never mocked,
identity tests spawn real process chains, and CLI tests drive the real
entry point.

Release prep is local and GitHub-only:

```bash
python bin/release.py --dry-run
python bin/release.py --version X.Y.Z
python bin/release.py --target pg --dry-run
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

Taut's bias is intentional: the chat should be lighter than the work it
coordinates.
