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

The interface provides transcript-first navigation, a multiline composer
(Enter sends; Ctrl-Enter or Ctrl-J inserts a newline; Ctrl-Tab inserts a tab),
native typed actions and forms, vi-like and conventional keys, mouse controls,
state-preserving terminal reflow, actor-free system reports, and supervised
terminal handoff to `taut-summon` when that extension is available. Tab and
Shift-Tab remain focus navigation. `:` opens the textual command input from
normal mode; a composer draft beginning with a whitespace- or Enter-delimited
known command such as `:summon grok` moves into that input instead of being
sent as chat. Tab, keyboard selection, or one click inserts a command
completion, but the passive completion list never takes typing focus. `:q`
and `:quit` use the guarded TUI quit path. Ctrl-C and Ctrl-D request that same
quit from any mode or modal while Textual owns the terminal; PageDown remains
the page-down key.
Workspace load remains a CLI-only maintenance action.

When a first `:summon grok` or native Summon form will actually attach to a
provider, the TUI shows a native confirmation before the provider starts. It
explains that the next screen is provider setup rather than Taut chat and names
the `Ctrl-\ Ctrl-\` return chord. Confirming reserves the handoff for that run;
Textual suspends only while the raw provider terminal is attached, then redraws
and continues supervising the foreground run. Cancelling or closing the TUI
before confirmation does not start the provider.

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

The retained lock runs the complete suite with Textual 8.2.8. There is no
separate older-Textual compatibility lane.
