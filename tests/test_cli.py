from __future__ import annotations

import json

import pytest

from tests.conftest import run_cli

pytestmark = pytest.mark.usefixtures("clean_env")


def test_cli_json_join_say_log(tmp_path) -> None:
    assert run_cli("init", "--json", cwd=tmp_path)[0] == 0
    rc, out, _ = run_cli("--as", "van", "join", "general", "--json", cwd=tmp_path)

    assert rc == 0
    lines = [json.loads(line) for line in out.splitlines()]
    assert lines[0]["handle"] == "van"
    assert lines[1]["kind"] == "notice"

    rc, out, _ = run_cli(
        "--as", "van", "say", "general", "hello", "--json", cwd=tmp_path
    )

    assert rc == 0
    assert json.loads(out)["text"] == "hello"

    rc, out, _ = run_cli("log", "general", "--json", cwd=tmp_path)

    assert rc == 0
    assert [json.loads(line)["text"] for line in out.splitlines()] == [
        "van created #general",
        "hello",
    ]


def test_cli_missing_database_exit_1(tmp_path) -> None:
    rc, _out, err = run_cli("list", cwd=tmp_path)

    assert rc == 1
    assert "No taut database found" in err


def test_cli_read_empty_exit_2(tmp_path) -> None:
    assert run_cli("init", cwd=tmp_path)[0] == 0
    assert run_cli("--as", "van", "join", "general", cwd=tmp_path)[0] == 0

    rc, _out, err = run_cli("--as", "van", "read", "general", cwd=tmp_path)

    assert rc == 2
    assert "nothing unread" in err


def test_cli_global_token_resolves_identity_before_and_after_command(tmp_path) -> None:
    assert run_cli("init", cwd=tmp_path)[0] == 0
    rc, out, _err = run_cli("--as", "van", "join", "general", "--json", cwd=tmp_path)
    assert rc == 0
    token = next(
        json.loads(line)["token"] for line in out.splitlines() if "token" in line
    )

    rc, out, _err = run_cli("--token", token, "whoami", "--json", cwd=tmp_path)

    assert rc == 0
    assert json.loads(out)["handle"] == "van"

    rc, out, _err = run_cli("whoami", "--json", "--token", token, cwd=tmp_path)

    assert rc == 0
    assert json.loads(out)["handle"] == "van"


def test_cli_whoami_invalid_token_is_error_exit_1(tmp_path) -> None:
    assert run_cli("init", cwd=tmp_path)[0] == 0

    rc, _out, err = run_cli(
        "whoami",
        "--json",
        cwd=tmp_path,
        env={"TAUT_TOKEN": "taut-invalid"},
    )

    assert rc == 1
    assert "TAUT_TOKEN does not match" in err


def test_cli_rejoin_token_is_not_consumed_by_global_hoisting(tmp_path) -> None:
    assert run_cli("init", cwd=tmp_path)[0] == 0
    rc, out, _err = run_cli("--as", "van", "join", "general", "--json", cwd=tmp_path)
    assert rc == 0
    token = next(
        json.loads(line)["token"] for line in out.splitlines() if "token" in line
    )

    rc, out, _err = run_cli("rejoin", "--token", token, "--json", cwd=tmp_path)

    assert rc == 0
    assert json.loads(out)["handle"] == "van"


def test_cli_rejoin_uses_global_token_or_as_selector(tmp_path) -> None:
    assert run_cli("init", cwd=tmp_path)[0] == 0
    rc, out, _err = run_cli("--as", "van", "join", "general", "--json", cwd=tmp_path)
    assert rc == 0
    token = next(
        json.loads(line)["token"] for line in out.splitlines() if "token" in line
    )

    rc, out, _err = run_cli("--token", token, "rejoin", "--json", cwd=tmp_path)

    assert rc == 0
    assert json.loads(out)["handle"] == "van"

    rc, out, _err = run_cli("--as", "van", "rejoin", "--json", cwd=tmp_path)

    assert rc == 0
    assert json.loads(out)["handle"] == "van"


def test_cli_rejoin_rejects_ambiguous_handle_and_token(tmp_path) -> None:
    assert run_cli("init", cwd=tmp_path)[0] == 0
    rc, out, _err = run_cli("--as", "van", "join", "general", "--json", cwd=tmp_path)
    assert rc == 0
    token = next(
        json.loads(line)["token"] for line in out.splitlines() if "token" in line
    )

    rc, _out, err = run_cli("rejoin", "van", "--token", token, cwd=tmp_path)

    assert rc == 1
    assert "exactly one" in err

    rc, _out, err = run_cli("--token", token, "rejoin", "van", cwd=tmp_path)

    assert rc == 1
    assert "exactly one" in err
