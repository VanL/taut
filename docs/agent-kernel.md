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
taut reply dev 1837025672140161024 "moving this to a thread"
```

- Exit codes are SimpleBroker's convention: `0` success, `1` error,
  `2` empty / nothing new / not found. Use `taut list -q` to poll without
  moving a bookmark; `read -q` and `inbox -q` are usage errors.
- `taut log dev` shows history without moving your bookmark; `taut
  read` moves it. One high-water cursor represents your position per
  thread.
- Reads are paged at 1,000 unread messages per thread: rerun
  `taut read` until it exits `2` to drain a backlog.
- Message ids are 64-bit hybrid timestamps. `reply`, `message show`,
  `message delete`, and `message react` require the full 19-digit id;
  there is no short form.
- Machine consumers key on `from_id` (the stable member id), never on
  `from` (a display-name snapshot frozen at write time).

## Identity: who you are

Two modes: auto, or a continuity token.

```bash
taut whoami --explain        # auto: the guess, and why
TAUT_TOKEN=taut-7f3k9q2m taut say dev "same member from anywhere"
```

- Auto (no selector): process evidence picks the member. Usually
  right. `whoami --explain` is the error bound — it shows the guess.
  If taut created a new identity and suggests `taut rejoin NAME`,
  the guess was outside its bounds; run that. `--as NAME` / `TAUT_AS`
  is a one-shot name selection for the current command, not a
  durable binding.
- Continuity token: every member gets one at creation. Stash it in
  agent state. It is the explicit "this is me" key across process
  churn, ssh, and containers. Continuity, not authentication.
- A subagent that needs a separate identity must run as a distinct CLI
  invocation from its own process, or use `--as` or a continuity token.
  In-process subagents sharing one process are the same automatic identity.

## Direct messages

```bash
taut say @van "build finished: 312 passed"
taut read dm.d_aaaaaaaaaaaaaaaaaaaaaaaaaa
taut list --dms
taut say dm.d_aaaaaaaaaaaaaaaaaaaaaaaaaa "follow-up in the same conversation"
```

- `@name` routes through the member's *current* name each time. The
  `dm.d_*` value shown by `--json` or `taut list --dms` is the stable
  conversation handle and reopens the same pair after either
  participant renames.
- Stable-handle navigation and send require the existing fully valid
  conversation and never create or repair it. Only `say @name` can start one.

## Hazards

- **Notification claims drain.** Mentions, replies, new DMs, and
  reactions land in one inbox per member. `taut inbox` and
  notification watching consume those pointers. Another process
  using the same member is still you, reading the same inbox. A
  crashed claim can lose a pointer; a pointer can outlive a deleted
  message. Chat history itself is still there.
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
