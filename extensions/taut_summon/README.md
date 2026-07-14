# taut-summon

Summon extension for Taut: host an existing agent harness (Claude Code and
friends) as an ordinary member of a taut workspace.

This package is intentionally separate from `taut`. The summon driver is the
agent's terminal, not its runtime: it injects chat into the harness's own
live session (its ears), and the agent speaks through the ordinary `taut`
CLI selected by its continuity token (its mouth). The full contract lives in
the core repository at `docs/specs/04-summon.md`.

## Status

Functional. The CLI surface (`taut-summon run|stop|status`) and the installed
root verbs (`taut summon`, `taut dismiss`), the foreground driver
(bootstrap, chat injection, event pump, crash-resume, clean shutdown), the
session ledger with a single-driver guard and PTY `wired` flag, the control
plane (STOP/STATUS/PING) with a rate backstop, the default persona, and the
provider adapters are implemented. `pty` is the default adapter for the
interactive harnesses (`claude`, `codex`, `coder`, `grok`, `qwen`, `kimi`,
`opencode`, `pi`); `claude-stream` remains available for Claude Code's
structured stream-json mode. See
`docs/plans/2026-07-06-taut-summon-plan.md`,
`docs/plans/2026-07-07-taut-summon-pty-harness-adapter-plan.md`, and
`docs/implementation/05-taut-summon-architecture.md` for the driver design.
Command registration and rich-host composition are documented in
`docs/implementation/06-command-extensions.md`.

## Requirements

- Python 3.11+
- Core `taut` and `taut-summon` installed in the same environment
- A SQL-sidecar backend (SQLite or Postgres) — summon state rides sidecar
  tables

## Installation

Taut releases are GitHub-only until package-name clearance changes. Install
the core package first, then inject the extension wheel into the same
environment:

```bash
pipx install "git+https://github.com/VanL/taut.git@v0.6.1"
pipx inject taut ./taut_summon-0.6.1-py3-none-any.whl
```

## Usage

```bash
taut summon claude              # summon a claude into #general
taut summon reviewer --provider claude dev
taut summon reviewer --provider claude-stream dev
taut dismiss reviewer
taut-summon status
```

When the workspace is discoverable from the current directory, `--db` is not
required. The quickstart above exercises the same discovery path for the
driver, control loop, and recovered broker handles.

`taut-summon --help` lists the three verbs and their exit classes; each verb's
own `--help` documents every positional and flag. Exit `0` is success, `1` is
an invocation, adapter, storage, or unresponsive-driver error, and `2` means
nothing is currently summoned. With no verb, help goes to stderr and exits `1`.

Installing this package registers native `taut summon` and `taut dismiss`
command adapters through Taut's command-extension interface. The root and
standalone consoles use the same parser configuration and controller adapters;
neither console invokes the other. `taut-summon status` remains the standalone
control-plane listing and inspection command.

On first PTY use, summon attaches your terminal so you can answer trust,
login, or model prompts in the real harness UI. Detach with `Ctrl-\ Ctrl-\`.
After detach the member is marked wired and future summons run detached.
Use `taut summon --attach NAME` to re-enter setup, or `--detach` for an
explicit detached run. PTY output is never parsed as speech; the agent speaks
by running `taut say`.

The PTY orientation is the first injected user turn, not a privileged system
message. Chat continuation lines are indented to keep attribution visible, but
chat remains untrusted user-role workspace input. Notification injection is
at most once because inbox records are consumable pointers; the source chat is
durable. The rate backstop limits posting volume and does not detect a
low-rate semantic loop.

## Trust boundary

Anyone who can write the configured Taut storage can feed user-role input and
storage-backed control requests to the summoned harness. For SQLite this is the
local file-access boundary. For shared Postgres, a remote database writer can
therefore influence tools on the harness host. Restrict storage writers to
principals authorized for that effect, or constrain the harness tools
separately. Names, personas, message framing, driver evidence, and continuity
tokens preserve attribution or lifecycle state; they are not authorization.

Control requests carry driver evidence as a stale-generation fence. That
evidence prevents an old queued command from acting on a replacement driver;
it does not authenticate the requester.

## Testing

From the repository root:

```bash
uv run pytest extensions/taut_summon/tests
```

Local runs attempt the live PTY harness smoke matrix by default. A provider
skips with an explicit reason when its binary is absent, the fresh test
database has not been onboarded with a real attach/detach cycle, or status
cannot reach a usable detached session. CI skips the real-harness matrix
unless `TAUT_SUMMON_LIVE_HARNESS=1` is set. For a fast local loop, use:

```bash
TAUT_SUMMON_LIVE_HARNESS=0 uv run pytest extensions/taut_summon/tests
```

Run `taut summon --attach <name>` once for a provider that still needs trust,
login, or model setup before expecting its detached live smoke to pass.
For a hard local external-provider smoke, use strict mode. It prewires the
temporary test session to model an already-onboarded provider and fails on
missing binaries, readiness gaps, status timeouts, unanswered terminal queries,
or injection catch-up failures. The external-provider lane does not require
hosted CLIs to auto-execute shell commands; the local LLM lane below owns the
deterministic sentinel-posting proof.

```bash
TAUT_SUMMON_LIVE_HARNESS_STRICT=1 uv run pytest extensions/taut_summon/tests/test_live_harness.py
```

The local LLM smoke runs locally by default when a loopback OpenAI-compatible
endpoint lists the served model, and it runs in CI through the dedicated
Ollama-backed workflow job. Defaults:

```bash
TAUT_SUMMON_LOCAL_LLM_ENDPOINT=http://127.0.0.1:11434/v1
TAUT_SUMMON_LOCAL_LLM_MODEL=taut-summon-local-model:latest
```

To run it locally with Ollama:

```bash
ollama pull qwen2.5:0.5b
cat > /tmp/TautSummonModelfile <<'EOF'
FROM qwen2.5:0.5b
PARAMETER num_ctx 2048
PARAMETER num_predict 64
PARAMETER temperature 0
EOF
ollama create taut-summon-local-model:latest -f /tmp/TautSummonModelfile
uv run pytest extensions/taut_summon/tests/test_live_local_llm.py
```

Use `TAUT_SUMMON_LOCAL_LLM=0` to skip the local LLM smoke locally, or
`TAUT_SUMMON_LOCAL_LLM=1` to make missing endpoint/model setup fail instead of
skip.
