# taut-tui

`taut-tui` is Taut's human-first terminal interface extension. It reflects
the public capabilities of `taut-chat` and loaded first-party extensions in a
full-screen Textual application. It does not define a second chat model or
derive forms from CLI arguments.

Install it beside core, or use core's convenience extra:

```bash
python -m pip install taut-chat taut-tui
# equivalent convenience install
python -m pip install 'taut-chat[tui]'
taut tui
```

The extension publishes `tui` through the `taut.commands` entry-point group.
There is intentionally no separate `taut-tui` console script. Without this
distribution installed, core does not claim the `tui` command.

The interface provides transcript-first navigation, native typed actions and
forms, vi-like and conventional keys, mouse controls, state-preserving terminal
reflow, actor-free system reports, and supervised terminal handoff to
`taut-summon` when that extension is available. Workspace load remains a
CLI-only maintenance action.

The governing behavior is in
[`docs/specs/10-taut-tui.md`](../../docs/specs/10-taut-tui.md). Architecture
and ownership rationale are in
[`docs/implementation/12-taut-tui.md`](../../docs/implementation/12-taut-tui.md).

## Development

From the repository root:

```bash
uv run --project extensions/taut_tui --extra dev \
  pytest extensions/taut_tui/tests -n 0
uv run --project extensions/taut_tui --extra dev \
  ruff check extensions/taut_tui/taut_tui extensions/taut_tui/tests
uv run --project extensions/taut_tui --extra dev \
  mypy extensions/taut_tui/taut_tui extensions/taut_tui/tests
```

The exact framework-floor lane runs the complete suite with Textual 3.0.0.
