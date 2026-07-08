# taut-summon

Summon extension for Taut: host an existing agent harness (Claude Code and
friends) as an ordinary member of a taut workspace.

This package is intentionally separate from `taut`. The summon driver is the
agent's terminal, not its runtime: it injects chat into the harness's own
live session (its ears), and the agent speaks through the ordinary `taut`
CLI selected by its continuity token (its mouth). The full contract lives in
the core repository at `docs/specs/04-summon.md`.

## Status

Functional. The CLI surface (`taut-summon run|stop|status`) and the core
delegation verbs (`taut summon`, `taut dismiss`), the foreground driver
(bootstrap, chat injection, event pump, crash-resume, clean shutdown), the
session ledger with a single-driver guard and PTY `wired` flag, the control
plane (STOP/STATUS/PING) with a rate backstop, the default persona, and the
provider adapters are implemented. `pty` is the default adapter for the
interactive harnesses (`claude`, `codex`, `coder`, `grok`, `qwen`, `kimi`,
`opencode`, `pi`); `claude-stream` remains available for Claude Code's
structured stream-json mode. See
`docs/plans/2026-07-06-taut-summon-plan.md`,
`docs/plans/2026-07-07-taut-summon-pty-harness-adapter-plan.md`, and
`docs/implementation/05-taut-summon-architecture.md` for the design.

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
pipx install "git+https://github.com/VanL/taut.git@vX.Y.Z"
pipx inject taut ./taut_summon-0.1.0-py3-none-any.whl
```

## Usage

```bash
taut summon claude              # summon a claude into #general
taut summon reviewer --provider claude dev
taut summon reviewer --provider claude-stream dev
taut dismiss reviewer
taut-summon status
```

`taut summon`/`taut dismiss` delegate argv verbatim to `taut-summon
run`/`taut-summon stop`; both surfaces share one resolution contract.

On first PTY use, summon attaches your terminal so you can answer trust,
login, or model prompts in the real harness UI. Detach with `Ctrl-\ Ctrl-\`.
After detach the member is marked wired and future summons run detached.
Use `taut summon --attach NAME` to re-enter setup, or `--detach` for an
explicit detached run. PTY output is never parsed as speech; the agent speaks
by running `taut say`.

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
