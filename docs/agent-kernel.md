# Taut Agent Kernel

This file is the sole home of agent-executable Taut recipes: the
smallest set of commands and hazards an agent needs to use a Taut
workspace well. It is a **view, never a contract** — it invents no
obligations. The winning contract for each behavior family is named in
`docs/specs/product-section-registry.md`; where this file and an owner
disagree, the owner wins. The [DOM-10.1] gates check this file's path
claims against the repository and its `taut` command claims against
the CLI's command registry (top-level verbs and required nested
operations — grammar-level checking, not execution).

## Join, catch up, speak

```bash
taut join dev                # join (creating if needed); you start at now
taut read --json             # your unread, as ndjson; advances your bookmark
taut say dev "parser tests green in ~20 min"
taut reply dev 0161024 "moving this to a thread"
```

- Exit codes are SimpleBroker's convention: `0` success, `1` error,
  `2` empty / nothing new / not found. `taut read -q` in a loop is a
  polling inbox.
- `taut log dev` shows history without moving your bookmark; `taut
  read` moves it. One high-water cursor represents your position per
  thread.
- Reads are paged at 1,000 unread messages per thread: rerun
  `taut read` until it exits `2` to drain a backlog.
- Message ids are 64-bit hybrid timestamps. `reply` accepts a unique
  suffix of 4+ digits over the thread's most recent 1,000 messages;
  `message show`, `message delete`, and `message react` require the
  full 19-digit id.
- Machine consumers key on `from_id` (the stable member id), never on
  `from` (a display-name snapshot frozen at write time).

## Identity: who you are

```bash
taut whoami --explain        # who taut thinks you are, and why
taut rejoin Claude           # associate this process with an existing member
TAUT_AS=Claude taut say dev "explicit selection always wins"
TAUT_TOKEN=taut-7f3k9q2m taut say dev "same member from anywhere"
```

- With no selector, process evidence picks the member automatically.
  If taut reports it created a new identity and suggests a
  `taut rejoin` command, run it.
- Every member gets a continuity token at creation. Stash it in your
  agent state; it survives process churn. It is continuity, not
  authentication.
- Recognition cannot cross ssh or container walls; pass `TAUT_AS` or
  `TAUT_TOKEN` through explicitly.

## Direct messages

```bash
taut say @van "build finished: 312 passed"
taut read dm.d_aaaaaaaaaaaaaaaaaaaaaaaaaa
taut list --dms
```

- `@name` routes through the member's *current* name each time. The
  `dm.d_*` value shown by `--json` or `taut list --dms` is the stable
  conversation handle and reopens the same pair after either
  participant renames.
- Navigation never creates a conversation; only `say @name` can start
  one.

## Hazards

- **Notification claims drain.** `taut inbox` and notification
  watching consume pointers. Two sessions of one member share one
  inbox: one can drain what the other expected. A pointer claimed
  just before a crash is not repaired — the chat history itself is
  still there.
- **Vanilla `broker read` consumes chat history.** Taut chat readers
  peek; SimpleBroker's own CLI reader does not. Pointing `broker
  read` at a taut chat queue eats messages out of the shared
  history. Use taut commands (or `broker peek`) for inspection.
- **Blank text is a silent no-op.** An empty or all-whitespace
  `say`/`reply` writes nothing and exits `2` with no stdout or
  stderr.
- **`--json` shapes successful stdout records only.** Errors and
  warnings remain concise text on stderr with the same exit codes.

## Following live

```bash
taut watch --json | while IFS= read -r line; do handle "$line"; done
```

`taut watch` follows everything you're in, plus your notification
inbox, and picks up threads you join while it runs.

## Session-start pattern for harness instructions

```markdown
This project uses taut for coordination. At the start of a session run
`taut join dev`, check `taut read --json`, and post status updates with
`taut say dev "..."`. If taut says it created a new identity, run the
suggested `taut rejoin` command.
```
