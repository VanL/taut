"""Public CLI search contract.

Spec reference: docs/specs/06-search.md [SRCH-5].
"""

from __future__ import annotations

import json
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest

from taut import EmptyResultError, SearchHit, TautClient
from taut.commands._dispatch import dispatch
from taut.commands._registry import CommandRegistry
from taut.commands._rendering import emit_search_warnings
from tests.conftest import run_cli

pytestmark = [pytest.mark.sqlite_only, pytest.mark.usefixtures("clean_env")]


class _SearchClientProbe:
    """Real command-boundary probe with a replaceable search outcome."""

    def __init__(
        self,
        *,
        calls: list[tuple[str, dict[str, object]]],
        outcome: list[SearchHit] | BaseException,
        **kwargs: object,
    ) -> None:
        self.calls = calls
        self.outcome = outcome
        self.constructor_kwargs = kwargs
        self.last_thread_display_names: dict[str, str] = {}
        self.last_search_warnings: list[str] = []
        self.closed = False

    def search(self, query: str, **kwargs: object) -> list[SearchHit]:
        self.calls.append((query, kwargs))
        if isinstance(self.outcome, BaseException):
            raise self.outcome
        return self.outcome

    def close(self) -> None:
        self.closed = True


def _probe_hit(*, text: str = "alpha beta") -> SearchHit:
    return SearchHit(
        thread="general",
        ts=1_800_000_000_000_000_001,
        from_id="m_probe",
        from_name="alice",
        kind="message",
        text=text,
        thread_kind="channel",
        channel="general",
        parent=None,
        members=None,
    )


def test_search_json_formats_id_while_python_hit_remains_integer() -> None:
    from taut.commands._rendering import search_hit_object

    hit = _probe_hit()

    assert search_hit_object(hit)["ts"] == "1800000000000000001"
    assert hit.ts == 1_800_000_000_000_000_001


def _dispatch_search_probe(
    argv: list[str],
    *,
    outcome: list[SearchHit] | BaseException | None = None,
) -> tuple[int, str, str, _SearchClientProbe, list[tuple[str, dict[str, object]]]]:
    calls: list[tuple[str, dict[str, object]]] = []
    clients: list[_SearchClientProbe] = []

    def factory(**kwargs: object) -> _SearchClientProbe:
        client = _SearchClientProbe(
            calls=calls,
            outcome=[_probe_hit()] if outcome is None else outcome,
            **kwargs,
        )
        clients.append(client)
        return client

    stdout = StringIO()
    stderr = StringIO()
    result = dispatch(
        argv,
        registry=CommandRegistry(entry_points=()),
        stdin=StringIO(),
        stdout=stdout,
        stderr=stderr,
        client_factory=factory,
    )
    assert len(clients) == 1
    return result, stdout.getvalue(), stderr.getvalue(), clients[0], calls


def test_cli_search_emits_the_fixed_ndjson_facets(tmp_path: Path) -> None:
    assert run_cli("init", cwd=tmp_path)[0] == 0
    assert run_cli("--as", "van", "join", "general", cwd=tmp_path)[0] == 0
    sent = run_cli(
        "--as",
        "van",
        "say",
        "general",
        "find the parser needle",
        "--json",
        cwd=tmp_path,
    )
    assert sent[0] == 0, sent[2]
    message = json.loads(sent[1])

    rc, out, err = run_cli(
        "search",
        "parser",
        "needle",
        "--json",
        cwd=tmp_path,
    )

    assert rc == 0, err
    assert json.loads(out) == {
        "channel": "general",
        "from": "van",
        "from_id": message["from_id"],
        "kind": "message",
        "members": None,
        "parent": None,
        "text": "find the parser needle",
        "thread": "general",
        "thread_kind": "channel",
        "ts": message["ts"],
    }
    assert err == ""


def test_cli_search_help_is_agent_usable_and_no_match_is_exit_two(
    tmp_path: Path,
) -> None:
    rc, out, err = run_cli("search", "--help", cwd=tmp_path)

    assert rc == 0
    assert "exact 19-digit message id" in out
    assert "1 through 1000" in out
    assert "Exit 0 for hits, 2 for no hits" in out
    assert err == ""

    assert run_cli("init", cwd=tmp_path)[0] == 0
    rc, out, err = run_cli("search", "absent", cwd=tmp_path)
    assert rc == 2
    assert out == ""
    assert "no search results" in err


def test_cli_search_human_dm_label_is_current_and_excerpt_is_bounded(
    tmp_path: Path,
) -> None:
    assert run_cli("init", cwd=tmp_path)[0] == 0
    assert run_cli("--as", "van", "join", "general", cwd=tmp_path)[0] == 0
    assert run_cli("--as", "bob", "join", "general", cwd=tmp_path)[0] == 0
    long_text = "prefix " * 80 + "needle" + " suffix" * 80
    sent = run_cli("--as", "van", "say", "@bob", long_text, cwd=tmp_path)
    assert sent[0] == 0, sent[2]

    rc, out, err = run_cli("--as", "van", "search", "needle", "--dms", cwd=tmp_path)

    assert rc == 0, err
    assert "DM with bob" in out
    assert "dm.d_" not in out
    assert "needle" in out
    assert len(out) < 400


def test_source_warning_renderer_is_stderr_only_and_quiet_suppresses() -> None:
    client = cast(
        TautClient,
        SimpleNamespace(last_search_warnings=["index queue offline"]),
    )
    stderr = StringIO()

    emit_search_warnings(client, quiet=False, stderr=stderr)

    assert stderr.getvalue() == "warning: index queue offline\n"
    quiet_stderr = StringIO()
    emit_search_warnings(
        client,
        quiet=True,
        stderr=quiet_stderr,
    )
    assert quiet_stderr.getvalue() == ""


def test_cli_search_delegates_every_flag_once_with_interspersed_query_words() -> None:
    dm_handle = "dm.d_abcdefghijklmnopqrstuvwxyz"
    rc, out, err, client, calls = _dispatch_search_probe(
        [
            "--db",
            "chat.db",
            "--as",
            "van",
            "search",
            "alpha",
            "--channel",
            "general",
            "beta",
            "--dm",
            "@bob",
            "--kind",
            "message",
            "--channel",
            "ops",
            "--dms",
            "--from",
            "alice",
            "--kind",
            "foreign",
            "--before",
            "1800000000000000001",
            "--limit",
            "7",
            "--reindex",
            "--dm",
            dm_handle,
            "--kind",
            "notice",
            "--token",
            "continuity-token",
            "--json",
        ]
    )

    assert rc == 0, err
    assert calls == [
        (
            "alpha beta",
            {
                "channels": ["general", "ops"],
                "direct_messages": ["@bob", dm_handle],
                "all_direct_messages": True,
                "from_member": "alice",
                "kinds": ["message", "foreign", "notice"],
                "before": "1800000000000000001",
                "limit": 7,
                "reindex": True,
            },
        )
    ]
    assert client.constructor_kwargs == {
        "db_path": "chat.db",
        "as_name": "van",
        "token": "continuity-token",
    }
    assert client.closed is True
    assert json.loads(out) == {
        "channel": "general",
        "from": "alice",
        "from_id": "m_probe",
        "kind": "message",
        "members": None,
        "parent": None,
        "text": "alpha beta",
        "thread": "general",
        "thread_kind": "channel",
        "ts": "1800000000000000001",
    }
    assert err == ""


@pytest.mark.parametrize(
    "argv",
    [
        ["--quiet", "search", "alpha"],
        ["search", "alpha", "--quiet"],
        ["search", "--quiet", "alpha"],
    ],
)
def test_cli_search_global_quiet_placement_preserves_success_exit(
    argv: list[str],
) -> None:
    rc, out, err, client, calls = _dispatch_search_probe(argv)

    assert rc == 0
    assert out == ""
    assert err == ""
    assert calls == [
        (
            "alpha",
            {
                "channels": [],
                "direct_messages": [],
                "all_direct_messages": False,
                "from_member": None,
                "kinds": [],
                "before": None,
                "limit": 50,
                "reindex": False,
            },
        )
    ]
    assert client.closed is True


def test_cli_search_literal_separator_makes_every_later_token_query_text() -> None:
    rc, out, err, _client, calls = _dispatch_search_probe(
        [
            "search",
            "--",
            "--channel",
            "general",
            "--dm",
            "@bob",
            "--json",
            "--quiet",
        ]
    )

    assert rc == 0, err
    assert calls[0][0] == "--channel general --dm @bob --json --quiet"
    assert calls[0][1]["channels"] == []
    assert calls[0][1]["direct_messages"] == []
    assert out.startswith("general alice: ")
    assert err == ""

    rc, _out, err, _client, calls = _dispatch_search_probe(
        ["search", "alpha", "--", "--channel", "general"]
    )
    assert rc == 0, err
    assert calls[0][0] == "alpha --channel general"
    assert calls[0][1]["channels"] == []


@pytest.mark.parametrize(
    "argv",
    [
        ["--timestamps", "search", "alpha"],
        ["search", "alpha", "--timestamps"],
        ["search", "--timestamps", "alpha"],
    ],
)
def test_cli_search_global_timestamps_placement_adds_full_message_id(
    argv: list[str],
) -> None:
    rc, out, err, _client, _calls = _dispatch_search_probe(argv)

    assert rc == 0, err
    assert "1800000000000000001" in out


@pytest.mark.parametrize(
    ("tail", "diagnostic"),
    [
        ([], "the following arguments are required: QUERY"),
        (["needle", "--channel"], "argument --channel: expected one argument"),
        (["needle", "--dm"], "argument --dm: expected one argument"),
        (["needle", "--from"], "argument --from: expected one argument"),
        (["needle", "--kind"], "argument --kind: expected one argument"),
        (["needle", "--kind", "other"], "invalid choice"),
        (["needle", "--before"], "argument --before: expected one argument"),
        (["needle", "--limit"], "argument --limit: expected one argument"),
        (["needle", "--limit", "many"], "invalid int value"),
    ],
)
def test_cli_search_usage_boundaries_exit_one_without_client_or_traceback(
    tail: list[str],
    diagnostic: str,
) -> None:
    clients: list[object] = []
    stdout = StringIO()
    stderr = StringIO()

    rc = dispatch(
        ["search", *tail],
        registry=CommandRegistry(entry_points=()),
        stdin=StringIO(),
        stdout=stdout,
        stderr=stderr,
        client_factory=lambda **_kwargs: clients.append(object()),
    )

    assert rc == 1
    assert clients == []
    assert stdout.getvalue() == ""
    assert diagnostic in stderr.getvalue()
    assert "Traceback" not in stderr.getvalue()


@pytest.mark.parametrize(
    ("tail", "diagnostic"),
    [
        (["!!!"], "at least one alphanumeric token"),
        (["needle", "--channel", "#general"], "channel"),
        (["needle", "--dm", "bob"], "direct-message selectors"),
        (["needle", "--dm", "dm.bad"], "invalid direct-message selector"),
        (["needle", "--from", "@bad"], "name must match"),
        (["needle", "--before", "1234"], "19-digit"),
        (["needle", "--limit", "0"], "between 1 and 1000"),
        (["needle", "--limit", "1001"], "between 1 and 1000"),
        (["\x1b"], "at least one alphanumeric token"),
    ],
)
def test_cli_search_malformed_values_exit_one_without_partial_output_or_traceback(
    tmp_path: Path,
    tail: list[str],
    diagnostic: str,
) -> None:
    assert run_cli("init", cwd=tmp_path)[0] == 0

    rc, out, err = run_cli("search", *tail, cwd=tmp_path)

    assert rc == 1
    assert out == ""
    assert diagnostic in err
    assert "Traceback" not in err
    assert "\x1b" not in err


def test_cli_search_rejects_too_many_distinct_query_chunks(tmp_path: Path) -> None:
    assert run_cli("init", cwd=tmp_path)[0] == 0
    query = " ".join(f"q{index}" for index in range(257))

    rc, out, err = run_cli("search", query, cwd=tmp_path)

    assert rc == 1
    assert out == ""
    assert "at most 256 distinct query chunks" in err
    assert "Traceback" not in err


@pytest.mark.parametrize("limit", ["1", "1000"])
def test_cli_search_limit_inclusive_bounds_reach_the_search_operation(
    tmp_path: Path,
    limit: str,
) -> None:
    assert run_cli("init", cwd=tmp_path)[0] == 0

    rc, out, err = run_cli("search", "absent", "--limit", limit, cwd=tmp_path)

    assert rc == 2
    assert out == ""
    assert "no search results" in err
    assert "Traceback" not in err


def test_cli_search_before_is_an_exclusive_full_message_id(tmp_path: Path) -> None:
    assert run_cli("init", cwd=tmp_path)[0] == 0
    assert run_cli("--as", "van", "join", "general", cwd=tmp_path)[0] == 0
    first = run_cli(
        "--as",
        "van",
        "say",
        "general",
        "boundary needle",
        "--json",
        cwd=tmp_path,
    )
    second = run_cli(
        "--as",
        "van",
        "say",
        "general",
        "boundary needle",
        "--json",
        cwd=tmp_path,
    )
    first_id = json.loads(first[1])["ts"]
    second_id = json.loads(second[1])["ts"]

    rc, out, err = run_cli(
        "search",
        "boundary",
        "needle",
        "--before",
        str(second_id),
        "--json",
        cwd=tmp_path,
    )

    assert rc == 0, err
    assert [row["ts"] for row in map(json.loads, out.splitlines())] == [first_id]


def test_cli_search_author_and_kind_filters_fire_conjunctively(tmp_path: Path) -> None:
    assert run_cli("init", cwd=tmp_path)[0] == 0
    assert run_cli("--as", "van", "join", "general", cwd=tmp_path)[0] == 0
    assert run_cli("--as", "bob", "join", "general", cwd=tmp_path)[0] == 0
    van = run_cli(
        "--as",
        "van",
        "say",
        "general",
        "filtered needle",
        "--json",
        cwd=tmp_path,
    )
    assert van[0] == 0, van[2]
    assert (
        run_cli("--as", "bob", "say", "general", "filtered needle", cwd=tmp_path)[0]
        == 0
    )

    rc, out, err = run_cli(
        "search",
        "filtered",
        "--from",
        "van",
        "--kind",
        "message",
        "--json",
        cwd=tmp_path,
    )

    assert rc == 0, err
    assert [row["ts"] for row in map(json.loads, out.splitlines())] == [
        json.loads(van[1])["ts"]
    ]


@pytest.mark.parametrize(
    ("prefix", "tail", "diagnostic"),
    [
        ([], ["--channel", "missing"], "channel not found"),
        (["--as", "van"], ["--dm", "@missing"], "direct message not found"),
        ([], ["--from", "missing"], "member not found"),
        (["--as", "missing"], ["--dms"], "recognized caller"),
    ],
)
def test_cli_search_empty_and_well_formed_selector_misses_exit_two(
    tmp_path: Path,
    prefix: list[str],
    tail: list[str],
    diagnostic: str,
) -> None:
    assert run_cli("init", cwd=tmp_path)[0] == 0
    assert run_cli("--as", "van", "join", "general", cwd=tmp_path)[0] == 0

    rc, out, err = run_cli(*prefix, "search", "needle", *tail, cwd=tmp_path)

    assert rc == 2
    assert out == ""
    assert diagnostic in err
    assert "Traceback" not in err


@pytest.mark.parametrize(
    ("error", "expected_exit", "diagnostic"),
    [
        (EmptyResultError("no search results"), 2, "no search results"),
        (RuntimeError("search provider unavailable"), 1, "provider unavailable"),
    ],
)
def test_cli_search_failure_classes_have_no_partial_output_or_traceback(
    error: BaseException,
    expected_exit: int,
    diagnostic: str,
) -> None:
    rc, out, err, client, calls = _dispatch_search_probe(
        ["search", "needle", "--json"], outcome=error
    )

    assert rc == expected_exit
    assert out == ""
    assert diagnostic in err
    assert "Traceback" not in err
    assert len(calls) == 1
    assert client.closed is True


@pytest.mark.parametrize(
    ("error", "expected_exit"),
    [
        (EmptyResultError("no search results"), 2),
        (RuntimeError("search provider unavailable"), 1),
    ],
)
def test_cli_search_quiet_failure_preserves_exit_and_suppresses_diagnostic(
    error: BaseException,
    expected_exit: int,
) -> None:
    rc, out, err, _client, _calls = _dispatch_search_probe(
        ["search", "needle", "--quiet"], outcome=error
    )

    assert rc == expected_exit
    assert out == ""
    assert err == ""


def test_cli_search_human_output_escapes_control_text(tmp_path: Path) -> None:
    assert run_cli("init", cwd=tmp_path)[0] == 0
    assert run_cli("--as", "van", "join", "general", cwd=tmp_path)[0] == 0
    sent = run_cli(
        "--as",
        "van",
        "say",
        "general",
        "control needle \x1b[31mred",
        cwd=tmp_path,
    )
    assert sent[0] == 0, sent[2]

    rc, out, err = run_cli("search", "control", "needle", cwd=tmp_path)

    assert rc == 0, err
    assert "\\x1b[31mred" in out
    assert "\x1b" not in out
