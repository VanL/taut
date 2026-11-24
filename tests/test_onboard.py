from __future__ import annotations

import errno
import json
import os
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from simplebroker import Queue

from taut._exceptions import TautError
from taut.client import TautClient
from taut.commands._dispatch import dispatch
from tests.conftest import PROJECT_ROOT, run_cli
from tests.test_cli import (
    _assert_only_structural_newlines,
    _write_terminal_project_config,
)

pytestmark = [pytest.mark.sqlite_only, pytest.mark.usefixtures("clean_env")]


def _cli(cwd: Path, *args: str) -> SimpleNamespace:
    rc, out, err = run_cli(*args, cwd=cwd)
    return SimpleNamespace(returncode=rc, stdout=out, stderr=err)


def test_onboard_empty_directory_creates_db_and_agents_never_ignore_files(
    tmp_path: Path,
) -> None:
    first = _cli(tmp_path, "onboard", "--json")
    assert first.returncode == 0, first.stderr
    payload = json.loads(first.stdout)

    assert payload["root"] == str(tmp_path.resolve())
    assert payload["channel"] == "general"
    assert payload["init"]["created"] is True
    assert Path(payload["init"]["db"]).resolve() == (tmp_path / ".taut.db").resolve()
    assert payload["files"] == [
        {"path": "AGENTS.md", "action": "created"},
        {"path": ".gitignore", "action": "skipped_absent"},
        {"path": ".dockerignore", "action": "skipped_absent"},
        {"path": ".mcp.json", "action": "skipped_disabled"},
    ]
    assert (tmp_path / ".taut.db").is_file()
    assert (tmp_path / "AGENTS.md").is_file()
    assert not os.path.lexists(tmp_path / ".gitignore")
    assert not os.path.lexists(tmp_path / ".dockerignore")
    assert not os.path.lexists(tmp_path / ".mcp.json")

    agents_text = (tmp_path / "AGENTS.md").read_text(encoding="utf-8")
    assert "<!-- taut:onboard:start -->" in agents_text
    assert "<!-- taut:onboard:end -->" in agents_text
    assert "taut join general --recent 20" in agents_text
    assert "taut onboard --print-kernel" in agents_text

    if os.name != "nt":
        prev_umask = os.umask(0)
        os.umask(prev_umask)
        expected_mode = 0o666 & ~prev_umask
        assert ((tmp_path / "AGENTS.md").stat().st_mode & 0o777) == expected_mode

    second = _cli(tmp_path, "onboard", "--json")
    assert second.returncode == 0, second.stderr
    second_payload = json.loads(second.stdout)
    assert second_payload["init"]["created"] is False
    assert second_payload["files"] == [
        {"path": "AGENTS.md", "action": "unchanged"},
        {"path": ".gitignore", "action": "skipped_absent"},
        {"path": ".dockerignore", "action": "skipped_absent"},
        {"path": ".mcp.json", "action": "skipped_disabled"},
    ]


def test_onboard_existing_ignore_files_append_exact_lines_preserving_inode_and_mode(
    tmp_path: Path,
) -> None:
    gitignore = tmp_path / ".gitignore"
    dockerignore = tmp_path / ".dockerignore"
    # Note: no trailing newline on .gitignore, leading-space ' .taut.db', and negation '!.taut.db'
    gitignore.write_text("node_modules/\n .taut.db\n!.taut.db", encoding="utf-8")
    dockerignore.write_text("dist/\n.taut.db\n.taut.lock\n", encoding="utf-8")
    if os.name != "nt":
        gitignore.chmod(0o640)
        dockerignore.chmod(0o644)

    orig_git_ino = gitignore.stat().st_ino
    orig_docker_ino = dockerignore.stat().st_ino

    first = _cli(tmp_path, "onboard", "--json")
    assert first.returncode == 0, first.stderr
    payload = json.loads(first.stdout)
    assert payload["files"] == [
        {"path": "AGENTS.md", "action": "created"},
        {"path": ".gitignore", "action": "updated"},
        {"path": ".dockerignore", "action": "updated"},
        {"path": ".mcp.json", "action": "skipped_disabled"},
    ]

    assert gitignore.stat().st_ino == orig_git_ino
    assert dockerignore.stat().st_ino == orig_docker_ino
    if os.name != "nt":
        assert (gitignore.stat().st_mode & 0o777) == 0o640
        assert (dockerignore.stat().st_mode & 0o777) == 0o644

    git_text = gitignore.read_text(encoding="utf-8")
    assert git_text == (
        "node_modules/\n"
        " .taut.db\n"
        "!.taut.db\n"
        ".taut.db\n"
        ".taut.db.lock\n"
        ".taut.lock\n"
        ".taut.db-wal\n"
        ".taut.db-shm\n"
    )
    assert ".taut.toml" not in git_text

    docker_text = dockerignore.read_text(encoding="utf-8")
    assert docker_text == (
        "dist/\n.taut.db\n.taut.lock\n.taut.db.lock\n.taut.db-wal\n.taut.db-shm\n"
    )

    second = _cli(tmp_path, "onboard", "--json")
    assert second.returncode == 0, second.stderr
    second_payload = json.loads(second.stdout)
    assert second_payload["files"] == [
        {"path": "AGENTS.md", "action": "unchanged"},
        {"path": ".gitignore", "action": "unchanged"},
        {"path": ".dockerignore", "action": "unchanged"},
        {"path": ".mcp.json", "action": "skipped_disabled"},
    ]
    assert gitignore.read_text(encoding="utf-8") == git_text
    assert dockerignore.read_text(encoding="utf-8") == docker_text


def test_onboard_ignore_unlink_after_preflight_maps_to_skipped_absent_without_recreating(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import taut._onboard as onboard_mod

    gitignore = tmp_path / ".gitignore"
    gitignore.write_text("node_modules/\n", encoding="utf-8")
    real_open = os.open

    def unlinking_open(path: Any, flags: int, *args: Any, **kwargs: Any) -> int:
        if (
            Path(path).name == ".gitignore"
            and (flags & os.O_APPEND) != 0
            and gitignore.exists()
        ):
            assert (flags & os.O_CREAT) == 0
            gitignore.unlink()
        return real_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(onboard_mod.os, "open", unlinking_open)
    report = TautClient.onboard(root=tmp_path)
    steps = {step.path: step.action for step in report.files}
    assert steps[".gitignore"] == "skipped_absent"
    assert not os.path.lexists(gitignore)


def test_onboard_agents_and_claude_selection_symlink_dedup_and_channel_update(
    tmp_path: Path,
) -> None:
    # 1. Only CLAUDE.md exists -> updates CLAUDE.md, does NOT create AGENTS.md.
    sub_claude = tmp_path / "claude_only"
    sub_claude.mkdir()
    (sub_claude / "CLAUDE.md").write_text("# Claude Entry\n", encoding="utf-8")
    res_claude = _cli(sub_claude, "onboard", "--json")
    assert res_claude.returncode == 0, res_claude.stderr
    data_claude = json.loads(res_claude.stdout)
    assert data_claude["files"][0] == {"path": "CLAUDE.md", "action": "updated"}
    assert not (sub_claude / "AGENTS.md").exists()
    assert "# Claude Entry\n" in (sub_claude / "CLAUDE.md").read_text(encoding="utf-8")

    # 2. Both distinct regular AGENTS.md and CLAUDE.md exist -> updates both.
    sub_both = tmp_path / "both_regular"
    sub_both.mkdir()
    (sub_both / "AGENTS.md").write_text("# Agents\n", encoding="utf-8")
    (sub_both / "CLAUDE.md").write_text("# Claude\n", encoding="utf-8")
    res_both = _cli(sub_both, "onboard", "--json")
    assert res_both.returncode == 0, res_both.stderr
    data_both = json.loads(res_both.stdout)
    assert data_both["files"][:2] == [
        {"path": "AGENTS.md", "action": "updated"},
        {"path": "CLAUDE.md", "action": "updated"},
    ]

    # 3. In-root symlink CLAUDE.md -> AGENTS.md -> deduplicated single write, preserves symlink & mode!
    if os.name != "nt":
        sub_sym = tmp_path / "symlink_pair"
        sub_sym.mkdir()
        agents_file = sub_sym / "AGENTS.md"
        claude_link = sub_sym / "CLAUDE.md"
        agents_file.write_text("# Shared Guide\n", encoding="utf-8")
        agents_file.chmod(0o640)
        claude_link.symlink_to("AGENTS.md")

        res_sym = _cli(sub_sym, "onboard", "--json")
        assert res_sym.returncode == 0, res_sym.stderr
        data_sym = json.loads(res_sym.stdout)
        assert data_sym["files"][0] == {"path": "AGENTS.md", "action": "updated"}
        assert not any(f["path"] == "CLAUDE.md" for f in data_sym["files"])
        assert claude_link.is_symlink()
        assert (agents_file.stat().st_mode & 0o777) == 0o640
        content_v1 = agents_file.read_text(encoding="utf-8")
        assert content_v1.count("<!-- taut:onboard:start -->") == 1
        assert "taut join general --recent 20" in content_v1

        # Re-run with --channel '#dev' -> updates block in place!
        res_dev = _cli(sub_sym, "onboard", "--channel", "#dev", "--json")
        assert res_dev.returncode == 0, res_dev.stderr
        data_dev = json.loads(res_dev.stdout)
        assert data_dev["channel"] == "dev"
        assert data_dev["files"][0] == {"path": "AGENTS.md", "action": "updated"}
        content_v2 = agents_file.read_text(encoding="utf-8")
        assert content_v2.count("<!-- taut:onboard:start -->") == 1
        assert "taut join dev --recent 20" in content_v2
        assert "taut join general --recent 20" not in content_v2

        # Re-run with --channel dev again -> unchanged!
        res_dev2 = _cli(sub_sym, "onboard", "--channel", "dev", "--json")
        assert res_dev2.returncode == 0, res_dev2.stderr
        assert json.loads(res_dev2.stdout)["files"][0] == {
            "path": "AGENTS.md",
            "action": "unchanged",
        }


def test_onboard_mcp_creates_merges_preserves_siblings_and_is_idempotent(
    tmp_path: Path,
) -> None:
    sub_new = tmp_path / "new_mcp"
    sub_new.mkdir()
    res1 = _cli(sub_new, "onboard", "--mcp", "--json")
    assert res1.returncode == 0, res1.stderr
    assert json.loads(res1.stdout)["files"][-1] == {
        "path": ".mcp.json",
        "action": "created",
    }
    parsed = json.loads((sub_new / ".mcp.json").read_text(encoding="utf-8"))
    assert parsed == {"mcpServers": {"taut": {"command": "taut", "args": ["mcp"]}}}

    res2 = _cli(sub_new, "onboard", "--mcp", "--json")
    assert res2.returncode == 0, res2.stderr
    assert json.loads(res2.stdout)["files"][-1] == {
        "path": ".mcp.json",
        "action": "unchanged",
    }

    sub_merge = tmp_path / "merge_mcp"
    sub_merge.mkdir()
    mcp_file = sub_merge / ".mcp.json"
    mcp_file.write_text(
        json.dumps(
            {"mcpServers": {"other": {"command": "other-mcp"}}, "topExtra": 42},
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    if os.name != "nt":
        mcp_file.chmod(0o640)
    res_merge = _cli(sub_merge, "onboard", "--mcp", "--json")
    assert res_merge.returncode == 0, res_merge.stderr
    assert json.loads(res_merge.stdout)["files"][-1] == {
        "path": ".mcp.json",
        "action": "updated",
    }
    merged = json.loads(mcp_file.read_text(encoding="utf-8"))
    assert merged == {
        "mcpServers": {
            "other": {"command": "other-mcp"},
            "taut": {"command": "taut", "args": ["mcp"]},
        },
        "topExtra": 42,
    }
    if os.name != "nt":
        assert (mcp_file.stat().st_mode & 0o777) == 0o640

    # Sibling JSON numbers outside IEEE-754 / Decimal range + 600-level nesting preserve cleanly!
    sub_big_num = tmp_path / "big_num_mcp"
    sub_big_num.mkdir()
    deep_value: object = 0
    for _ in range(600):
        deep_value = [deep_value]
    (sub_big_num / ".mcp.json").write_text(
        '{"mcpServers": {}, "huge": 1e400, "zero_exp": 0e1000000000000000000, "deep": '
        + ("[" * 600)
        + "0"
        + ("]" * 600)
        + "}\n",
        encoding="utf-8",
    )
    res_big = _cli(sub_big_num, "onboard", "--mcp", "--json")
    assert res_big.returncode == 0, res_big.stderr
    assert json.loads(res_big.stdout)["files"][-1] == {
        "path": ".mcp.json",
        "action": "updated",
    }
    raw_big = (sub_big_num / ".mcp.json").read_text(encoding="utf-8")
    assert "1e400" in raw_big
    assert "0e1000000000000000000" in raw_big
    assert '"taut"' in raw_big
    res_big2 = _cli(sub_big_num, "onboard", "--mcp", "--json")
    assert res_big2.returncode == 0, res_big2.stderr
    assert json.loads(res_big2.stdout)["files"][-1] == {
        "path": ".mcp.json",
        "action": "unchanged",
    }


def test_onboard_preflight_fails_closed_before_storage_or_file_mutation(
    tmp_path: Path,
) -> None:
    # 1. --db colliding with managed files (with and without --no-init)
    for idx, args in enumerate(
        (
            ("onboard", "--db", "AGENTS.md"),
            ("onboard", "--db", ".gitignore"),
            ("onboard", "--db", ".mcp.json", "--mcp"),
            ("onboard", "--db", "AGENTS.md", "--no-init"),
        )
    ):
        case_dir = tmp_path / f"db_collision_{idx}"
        case_dir.mkdir()
        (case_dir / ".gitignore").write_text("keep\n", encoding="utf-8")
        res = _cli(case_dir, *args)
        assert res.returncode == 1
        assert "unknown command: onboard" not in res.stderr
        assert (
            "alias" in res.stderr or "collide" in res.stderr or "database" in res.stderr
        )
        assert not (case_dir / "AGENTS.md").exists()
        assert (case_dir / ".gitignore").read_text(encoding="utf-8") == "keep\n"

    # 2. Hard-link and symlink alias checks (POSIX)
    if os.name != "nt":
        # 2a. Hard-linked .gitignore <-> pre-existing chat.db (both binary AND valid UTF-8!)
        hl_db_dir = tmp_path / "hl_db"
        hl_db_dir.mkdir()
        raw_db = hl_db_dir / "chat.db"
        q = Queue("raw", db_path=str(raw_db))
        q.write("hello")
        q.close()
        raw_bytes = raw_db.read_bytes()
        os.link(raw_db, hl_db_dir / ".gitignore")
        res_hl_db = _cli(hl_db_dir, "onboard", "--db", "chat.db", "--no-init")
        assert res_hl_db.returncode == 1
        assert "aliases SQLite database" in res_hl_db.stderr
        assert raw_db.read_bytes() == raw_bytes
        assert not (hl_db_dir / "AGENTS.md").exists()

        hl_utf8_dir = tmp_path / "hl_utf8_db"
        hl_utf8_dir.mkdir()
        utf8_db = hl_utf8_dir / "chat.db"
        utf8_db.write_text("# valid utf8 placeholder\n", encoding="utf-8")
        os.link(utf8_db, hl_utf8_dir / ".gitignore")
        res_hl_utf8 = _cli(hl_utf8_dir, "onboard", "--db", "chat.db", "--no-init")
        assert res_hl_utf8.returncode == 1
        assert "aliases SQLite database" in res_hl_utf8.stderr
        assert utf8_db.read_text(encoding="utf-8") == "# valid utf8 placeholder\n"

        # 2a-bis. Symlinked --db link.db -> real.db checks canonical companions (real.db-wal)!
        sym_db_dir = tmp_path / "sym_db_companions"
        sym_db_dir.mkdir()
        (sym_db_dir / "real.db").write_text("", encoding="utf-8")
        (sym_db_dir / "link.db").symlink_to("real.db")
        (sym_db_dir / "real.db-wal").write_text("wal\n", encoding="utf-8")
        (sym_db_dir / ".gitignore").symlink_to("real.db-wal")
        for extra in ((), ("--no-init",)):
            res_sym_db = _cli(sym_db_dir, "onboard", "--db", "link.db", *extra)
            assert res_sym_db.returncode == 1
            assert "aliases SQLite database" in res_sym_db.stderr
            assert (sym_db_dir / "real.db-wal").read_text(encoding="utf-8") == "wal\n"

        # 2a-ter. Protected .taut.toml cannot be aliased by .gitignore (symlink or hard link)!
        toml_dir = tmp_path / "toml_alias"
        toml_dir.mkdir()
        toml_body = 'version = 1\nbackend = "sqlite"\ntarget = ".taut.db"\n'
        (toml_dir / ".taut.toml").write_text(toml_body, encoding="utf-8")
        (toml_dir / ".gitignore").symlink_to(".taut.toml")
        res_toml = _cli(toml_dir, "onboard")
        assert res_toml.returncode == 1
        assert "protected project file .taut.toml" in res_toml.stderr
        assert (toml_dir / ".taut.toml").read_text(encoding="utf-8") == toml_body
        assert not (toml_dir / ".taut.db").exists()

        # 2b. In-root symlink .gitignore -> .mcp.json BOTH without --mcp (disabled role!) and with --mcp
        for with_mcp in (False, True):
            role_dir = tmp_path / f"role_alias_{with_mcp}"
            role_dir.mkdir()
            (role_dir / ".mcp.json").write_text(
                '{"mcpServers": {}}\n', encoding="utf-8"
            )
            (role_dir / ".gitignore").symlink_to(".mcp.json")
            cli_args = ("onboard", "--mcp") if with_mcp else ("onboard",)
            res_role = _cli(role_dir, *cli_args)
            assert res_role.returncode == 1
            assert "unknown command: onboard" not in res_role.stderr
            assert not (role_dir / ".taut.db").exists()
            assert (role_dir / ".mcp.json").read_text(
                encoding="utf-8"
            ) == '{"mcpServers": {}}\n'

        # 2c. Hard-linked AGENTS.md <-> CLAUDE.md (distinct paths sharing an inode)
        hl_agents_dir = tmp_path / "hl_agents"
        hl_agents_dir.mkdir()
        (hl_agents_dir / "AGENTS.md").write_text("# Agents\n", encoding="utf-8")
        os.link(hl_agents_dir / "AGENTS.md", hl_agents_dir / "CLAUDE.md")
        res_hl_agents = _cli(hl_agents_dir, "onboard")
        assert res_hl_agents.returncode == 1
        assert "unknown command: onboard" not in res_hl_agents.stderr
        assert not (hl_agents_dir / ".taut.db").exists()
        assert (hl_agents_dir / "AGENTS.md").stat().st_ino == (
            hl_agents_dir / "CLAUDE.md"
        ).stat().st_ino

        # 2d. Hard-linked .gitignore <-> AGENTS.md
        hl_cross_dir = tmp_path / "hl_cross"
        hl_cross_dir.mkdir()
        (hl_cross_dir / "AGENTS.md").write_text("# Agents\n", encoding="utf-8")
        os.link(hl_cross_dir / "AGENTS.md", hl_cross_dir / ".gitignore")
        res_hl_cross = _cli(hl_cross_dir, "onboard")
        assert res_hl_cross.returncode == 1
        assert "unknown command: onboard" not in res_hl_cross.stderr
        assert not (hl_cross_dir / ".taut.db").exists()

        # 2e. Symlink escaping root (AGENTS.md -> ../outside.md) & broken symlink (.gitignore)
        outside = tmp_path / "outside.md"
        outside.write_text("# Outside\n", encoding="utf-8")
        esc_dir = tmp_path / "escape_sym"
        esc_dir.mkdir()
        (esc_dir / "AGENTS.md").symlink_to("../outside.md")
        res_esc = _cli(esc_dir, "onboard")
        assert res_esc.returncode == 1
        assert "unknown command: onboard" not in res_esc.stderr
        assert "outside" in res_esc.stderr
        assert not (esc_dir / ".taut.db").exists()
        assert outside.read_text(encoding="utf-8") == "# Outside\n"

        # Disabled roles ALSO enforce standalone root containment and file-type checks!
        res_esc_disabled = _cli(esc_dir, "onboard", "--no-agents")
        assert res_esc_disabled.returncode == 1
        assert "outside" in res_esc_disabled.stderr
        assert not (esc_dir / ".taut.db").exists()

        mcp_esc_dir = tmp_path / "mcp_escape_disabled"
        mcp_esc_dir.mkdir()
        (mcp_esc_dir / ".mcp.json").symlink_to("../outside.md")
        res_mcp_esc = _cli(mcp_esc_dir, "onboard")  # --mcp omitted!
        assert res_mcp_esc.returncode == 1
        assert "outside" in res_mcp_esc.stderr
        assert not (mcp_esc_dir / ".taut.db").exists()

        broken_dir = tmp_path / "broken_sym"
        broken_dir.mkdir()
        (broken_dir / ".gitignore").symlink_to("missing_target")
        res_broken = _cli(broken_dir, "onboard")
        assert res_broken.returncode == 1
        assert "unknown command: onboard" not in res_broken.stderr
        assert "broken symlink" in res_broken.stderr
        assert not (broken_dir / ".taut.db").exists()

    # 3. Directory collision, invalid UTF-8, unbalanced markers, invalid/conflicting .mcp.json, invalid --channel
    dir_coll = tmp_path / "dir_coll"
    dir_coll.mkdir()
    (dir_coll / ".dockerignore").mkdir()
    res_dir_coll = _cli(dir_coll, "onboard")
    assert res_dir_coll.returncode == 1
    assert "directory" in res_dir_coll.stderr
    assert not (dir_coll / ".taut.db").exists()

    bad_utf8 = tmp_path / "bad_utf8"
    bad_utf8.mkdir()
    (bad_utf8 / "AGENTS.md").write_bytes(b"\xff\xfeinvalid")
    res_utf8 = _cli(bad_utf8, "onboard")
    assert res_utf8.returncode == 1
    assert "UTF-8" in res_utf8.stderr
    assert not (bad_utf8 / ".taut.db").exists()

    for idx, marker_body in enumerate(
        (
            "<!-- taut:onboard:start -->\nmissing end\n",
            "missing start\n<!-- taut:onboard:end -->\n",
            "<!-- taut:onboard:end -->\n<!-- taut:onboard:start -->\n",
            "<!-- taut:onboard:start -->\n<!-- taut:onboard:end -->\n<!-- taut:onboard:start -->\n<!-- taut:onboard:end -->\n",
        )
    ):
        marker_dir = tmp_path / f"bad_marker_{idx}"
        marker_dir.mkdir()
        (marker_dir / "AGENTS.md").write_text(marker_body, encoding="utf-8")
        res_marker = _cli(marker_dir, "onboard")
        assert res_marker.returncode == 1
        assert "taut:onboard" in res_marker.stderr
        assert not (marker_dir / ".taut.db").exists()

    for idx, mcp_body in enumerate(
        (
            "{not valid json",
            "[]\n",
            '{"mcpServers": []}\n',
            '{"mcpServers": {"taut": {"command": "custom-mcp"}}}\n',
            '{"mcpServers": {"taut": {"command": "custom-mcp"}}, "mcpServers": {}}\n',
            '{"mcpServers": {}, "bad": NaN}\n',
        )
    ):
        mcp_dir = tmp_path / f"bad_mcp_{idx}"
        mcp_dir.mkdir()
        (mcp_dir / ".mcp.json").write_text(mcp_body, encoding="utf-8")
        res_mcp = _cli(mcp_dir, "onboard", "--mcp")
        assert res_mcp.returncode == 1
        assert ".mcp.json" in res_mcp.stderr or "mcpServers" in res_mcp.stderr
        assert not (mcp_dir / ".taut.db").exists()
        assert (mcp_dir / ".mcp.json").read_text(encoding="utf-8") == mcp_body

    for bad_chan in ("bad name", "general.1837025672140161024", "@van"):
        chan_dir = tmp_path / f"bad_chan_{bad_chan.replace(' ', '_')}"
        chan_dir.mkdir()
        res_chan = _cli(chan_dir, "onboard", "--channel", bad_chan)
        assert res_chan.returncode == 1
        assert "unknown command: onboard" not in res_chan.stderr
        assert not (chan_dir / ".taut.db").exists()


def test_onboard_disable_flags_human_output_quiet_and_python_type_checks(
    tmp_path: Path,
) -> None:
    sub = tmp_path / "flags"
    sub.mkdir()
    (sub / ".gitignore").write_text("dist/\n", encoding="utf-8")
    res = _cli(sub, "onboard", "--no-init", "--no-agents", "--no-ignore", "--json")
    assert res.returncode == 0, res.stderr
    payload = json.loads(res.stdout)
    assert payload["init"] is None
    assert payload["files"] == [
        {"path": "AGENTS.md", "action": "skipped_disabled"},
        {"path": ".gitignore", "action": "skipped_disabled"},
        {"path": ".dockerignore", "action": "skipped_disabled"},
        {"path": ".mcp.json", "action": "skipped_disabled"},
    ]
    assert not (sub / ".taut.db").exists()
    assert not (sub / "AGENTS.md").exists()
    assert (sub / ".gitignore").read_text(encoding="utf-8") == "dist/\n"

    human_dir = tmp_path / "human"
    human_dir.mkdir()
    human_res = _cli(human_dir, "onboard")
    assert human_res.returncode == 0, human_res.stderr
    assert "AGENTS.md: created" in human_res.stdout
    _assert_only_structural_newlines(human_res.stdout)

    quiet_res = _cli(human_dir, "onboard", "-q")
    assert quiet_res.returncode == 0, quiet_res.stderr
    assert quiet_res.stdout == ""

    with pytest.raises(TypeError, match="mcp must be a bool"):
        TautClient.onboard(root=tmp_path, mcp="yes")  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="init_storage must be a bool"):
        TautClient.onboard(root=tmp_path, init_storage=1)  # type: ignore[arg-type]
    with pytest.raises(TautError):
        TautClient.onboard(root=tmp_path / "nonexistent_root_dir")


def test_onboard_rejects_actor_and_timestamp_globals_and_print_kernel_flags(
    tmp_path: Path,
) -> None:
    for bad_args in (
        ("--as", "van", "onboard"),
        ("onboard", "--as", "van"),
        ("--token", "tok", "onboard"),
        ("onboard", "--token", "tok"),
        ("-t", "onboard"),
        ("onboard", "-t"),
        ("--json", "onboard", "--print-kernel"),
        ("onboard", "--print-kernel", "--json"),
        ("-q", "onboard", "--print-kernel"),
        ("onboard", "--print-kernel", "-q"),
        ("--db", "x.db", "onboard", "--print-kernel"),
        ("onboard", "--print-kernel", "--db", "x.db"),
        ("onboard", "--print-kernel", "--mcp"),
        ("onboard", "--print-kernel", "--channel", "dev"),
        ("onboard", "--print-kernel", "--no-init"),
        ("onboard", "--print-kernel", "--no-agents"),
        ("onboard", "--print-kernel", "--no-ignore"),
    ):
        res = _cli(tmp_path, *bad_args)
        assert res.returncode == 1, f"expected exit 1 for {bad_args}"
        assert "unknown command: onboard" not in res.stderr
    assert not (tmp_path / ".taut.db").exists()
    assert not (tmp_path / "AGENTS.md").exists()


def test_onboard_print_kernel_applies_line_by_line_terminal_policy_and_escapes_c1_nel(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected_kernel = (PROJECT_ROOT / "docs" / "agent-kernel.md").read_text(
        encoding="utf-8"
    )
    assert TautClient.agent_kernel() == expected_kernel

    # 1. Uninitialized empty directory: prints exact kernel without creating .taut.db or AGENTS.md.
    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()
    res = _cli(empty_dir, "onboard", "--print-kernel")
    assert res.returncode == 0, res.stderr
    assert res.stdout == expected_kernel.strip()
    monkeypatch.chdir(empty_dir)
    exact_out = StringIO()
    exact_err = StringIO()
    assert (
        dispatch(["onboard", "--print-kernel"], stdout=exact_out, stderr=exact_err) == 0
    )
    assert exact_out.getvalue() == expected_kernel
    assert not (empty_dir / ".taut.db").exists()
    assert not (empty_dir / "AGENTS.md").exists()

    # 2. Valid configured .taut.toml escape_patterns applies via write_human_line while preserving \n!
    policy_dir = tmp_path / "policy"
    policy_dir.mkdir()
    _write_terminal_project_config(
        policy_dir,
        escape_patterns=("Session-start",),
    )
    monkeypatch.chdir(policy_dir)
    policy_out = StringIO()
    policy_err = StringIO()
    assert (
        dispatch(["onboard", "--print-kernel"], stdout=policy_out, stderr=policy_err)
        == 0
    )
    rendered_policy = policy_out.getvalue()
    assert "Session-start" not in rendered_policy
    assert "\\x53\\x65\\x73\\x73\\x69\\x6f\\x6e" in rendered_policy
    assert rendered_policy.count("\n") == expected_kernel.count("\n")

    # 3. C1 U+0085 NEL is NOT split into a raw newline (splits strictly on "\n", not splitlines()!).
    c1_dir = tmp_path / "c1"
    c1_dir.mkdir()
    monkeypatch.chdir(c1_dir)
    monkeypatch.setattr(
        TautClient,
        "agent_kernel",
        classmethod(lambda cls: "Header\x85Next\nSecond line\n"),
    )
    c1_out = StringIO()
    c1_err = StringIO()
    assert dispatch(["onboard", "--print-kernel"], stdout=c1_out, stderr=c1_err) == 0
    assert c1_out.getvalue() == "Header\\x85Next\nSecond line\n"

    # 4. Malformed .taut.toml fails closed with exit 1 ([TAUT-6.4]).
    bad_toml_dir = tmp_path / "bad_toml"
    bad_toml_dir.mkdir()
    (bad_toml_dir / ".taut.toml").write_text("not = [valid toml\n", encoding="utf-8")
    res_bad = _cli(bad_toml_dir, "onboard", "--print-kernel")
    assert res_bad.returncode == 1
    assert "terminal output policy is unavailable" in res_bad.stderr


def test_onboard_post_preflight_swap_and_o_excl_staging_races_fail_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import taut._onboard as onboard_mod

    # 1. O_EXCL collision on staging path MUST NOT unlink the pre-existing file!
    excl_dir = tmp_path / "o_excl_preserve"
    excl_dir.mkdir()
    preexisting_staged = excl_dir / ".AGENTS.md.taut-deadbeefdeadbeef.tmp"
    preexisting_staged.write_text("foreign staging sentinel\n", encoding="utf-8")
    with (
        monkeypatch.context() as patch,
        pytest.raises(TautError, match="cannot write AGENTS.md"),
    ):
        patch.setattr(onboard_mod.secrets, "token_hex", lambda _n: "deadbeefdeadbeef")
        TautClient.onboard(root=excl_dir, init_storage=False)
    assert (
        preexisting_staged.read_text(encoding="utf-8") == "foreign staging sentinel\n"
    )
    assert not (excl_dir / "AGENTS.md").exists()

    # 2. Destination created between preflight and create-only publish MUST NOT overwrite it!
    race_create_dir = tmp_path / "race_create"
    race_create_dir.mkdir()
    real_stage = onboard_mod._stage_and_publish

    def race_create_stage(*args: Any, **kwargs: Any) -> None:
        (race_create_dir / "AGENTS.md").write_text(
            "concurrently created\n", encoding="utf-8"
        )
        real_stage(*args, **kwargs)

    with (
        monkeypatch.context() as patch,
        pytest.raises(TautError, match="cannot write AGENTS.md"),
    ):
        patch.setattr(onboard_mod, "_stage_and_publish", race_create_stage)
        TautClient.onboard(root=race_create_dir, init_storage=False)
    assert (race_create_dir / "AGENTS.md").read_text(
        encoding="utf-8"
    ) == "concurrently created\n"

    # 2b. Filesystems lacking hard links (os.link -> EOPNOTSUPP) fall back to exclusive O_CREAT|O_EXCL!
    no_link_dir = tmp_path / "no_hard_links"
    no_link_dir.mkdir()

    def unsupported_link(*_args: Any, **_kwargs: Any) -> None:
        raise OSError(errno.EOPNOTSUPP, "Operation not supported")

    with monkeypatch.context() as patch:
        patch.setattr(onboard_mod.os, "link", unsupported_link)
        report_nl = TautClient.onboard(root=no_link_dir, mcp=True, init_storage=False)
    assert [(s.path, s.action) for s in report_nl.files] == [
        ("AGENTS.md", "created"),
        (".gitignore", "skipped_absent"),
        (".dockerignore", "skipped_absent"),
        (".mcp.json", "created"),
    ]
    assert (no_link_dir / "AGENTS.md").is_file()
    assert (no_link_dir / ".mcp.json").is_file()

    # And under EOPNOTSUPP, atomic no-overwrite rename STILL refuses to overwrite a racing destination!
    no_link_race_dir = tmp_path / "no_hard_links_race"
    no_link_race_dir.mkdir()
    real_noreplace = onboard_mod._atomic_rename_noreplace

    def racing_noreplace(**kwargs: Any) -> None:
        (no_link_race_dir / "AGENTS.md").write_text("raced\n", encoding="utf-8")
        real_noreplace(**kwargs)

    with (
        monkeypatch.context() as patch,
        pytest.raises(TautError, match="cannot write AGENTS.md"),
    ):
        patch.setattr(onboard_mod.os, "link", unsupported_link)
        patch.setattr(onboard_mod, "_atomic_rename_noreplace", racing_noreplace)
        TautClient.onboard(root=no_link_race_dir, init_storage=False)
    assert (no_link_race_dir / "AGENTS.md").read_text(encoding="utf-8") == "raced\n"


def test_onboard_post_preflight_symlink_swap_and_moved_parent_fail_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import taut._onboard as onboard_mod

    # 2c. Subdirectory parent_fd moved outside root after _open_pinned_parent_fd fails closed!
    if os.name != "nt":
        move_parent_dir = tmp_path / "move_parent_ws"
        move_parent_dir.mkdir()
        subdir = move_parent_dir / "nested"
        subdir.mkdir()
        (subdir / "AGENTS.md").write_text("# Nested\n", encoding="utf-8")
        (move_parent_dir / "AGENTS.md").symlink_to("nested/AGENTS.md")
        escaped_dest = tmp_path / "escaped_nested"
        real_publish = onboard_mod._publish_staged_file

        def move_subdir_before_publish(**kwargs: Any) -> None:
            if subdir.exists():
                subdir.rename(escaped_dest)
            real_publish(**kwargs)

        with (
            monkeypatch.context() as patch,
            pytest.raises(TautError, match="parent directory"),
        ):
            patch.setattr(
                onboard_mod, "_publish_staged_file", move_subdir_before_publish
            )
            TautClient.onboard(
                root=move_parent_dir, init_storage=False, update_ignore=False
            )
        assert (escaped_dest / "AGENTS.md").read_text(encoding="utf-8") == "# Nested\n"

        # Also test moving subdir DURING os.chmod (between chmod and os.replace) AND DURING os.fstat!
        chmod_ws = tmp_path / "move_during_chmod_ws"
        chmod_ws.mkdir()
        chmod_sub = chmod_ws / "nested"
        chmod_sub.mkdir()
        (chmod_sub / "AGENTS.md").write_text("# Chmod\n", encoding="utf-8")
        (chmod_ws / "AGENTS.md").symlink_to("nested/AGENTS.md")
        escaped_chmod = tmp_path / "escaped_chmod"
        real_chmod = os.chmod

        def moving_chmod(*args: Any, **kwargs: Any) -> None:
            real_chmod(*args, **kwargs)
            if chmod_sub.exists():
                chmod_sub.rename(escaped_chmod)

        with (
            monkeypatch.context() as patch,
            pytest.raises(TautError, match="parent directory"),
        ):
            patch.setattr(onboard_mod.os, "chmod", moving_chmod)
            TautClient.onboard(root=chmod_ws, init_storage=False, update_ignore=False)
        assert (escaped_chmod / "AGENTS.md").read_text(encoding="utf-8") == "# Chmod\n"

        fstat_ws = tmp_path / "move_during_fstat_ws"
        fstat_ws.mkdir()
        fstat_sub = fstat_ws / "nested"
        fstat_sub.mkdir()
        (fstat_sub / "AGENTS.md").write_text("# Fstat\n", encoding="utf-8")
        (fstat_ws / "AGENTS.md").symlink_to("nested/AGENTS.md")
        escaped_fstat = tmp_path / "escaped_fstat"
        real_fstat = os.fstat
        real_os_read = os.read
        target_ino = (fstat_sub / "AGENTS.md").stat().st_ino
        moved_on_fstat = False
        reads_after_move: list[int] = []

        def moving_fstat(fd: int) -> os.stat_result:
            nonlocal moved_on_fstat
            st = real_fstat(fd)
            if st.st_ino == target_ino and fstat_sub.exists():
                fstat_sub.rename(escaped_fstat)
                moved_on_fstat = True
            return st

        def spy_os_read(fd: int, n: int) -> bytes:
            if moved_on_fstat:
                reads_after_move.append(fd)
            return real_os_read(fd, n)

        with (
            monkeypatch.context() as patch,
            pytest.raises(TautError, match="parent directory"),
        ):
            patch.setattr(onboard_mod.os, "fstat", moving_fstat)
            patch.setattr(onboard_mod.os, "read", spy_os_read)
            TautClient.onboard(root=fstat_ws, init_storage=False, update_ignore=False)
        assert moved_on_fstat is True
        assert reads_after_move == []


def test_onboard_post_preflight_symlink_swap_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import taut._onboard as onboard_mod

    real_stage = onboard_mod._stage_and_publish

    # 3. Post-preflight symlink swap on .gitignore and AGENTS.md fails closed without touching outside!
    if os.name != "nt":
        outside_secret = tmp_path / "outside_secret.txt"
        outside_secret.write_text("do not touch\n", encoding="utf-8")

        swap_ign_dir = tmp_path / "swap_ignore"
        swap_ign_dir.mkdir()
        (swap_ign_dir / ".gitignore").write_text("node_modules/\n", encoding="utf-8")
        real_apply_ignore = onboard_mod._apply_planned_ignore

        def swap_before_ignore(step: Any, **kwargs: Any) -> Any:
            if step.rel_name == ".gitignore":
                (swap_ign_dir / ".gitignore").unlink()
                (swap_ign_dir / ".gitignore").symlink_to(outside_secret)
            return real_apply_ignore(step, **kwargs)

        with (
            monkeypatch.context() as patch,
            pytest.raises(TautError, match="cannot update \\.gitignore"),
        ):
            patch.setattr(onboard_mod, "_apply_planned_ignore", swap_before_ignore)
            TautClient.onboard(
                root=swap_ign_dir, init_storage=False, update_agents=False
            )
        assert outside_secret.read_text(encoding="utf-8") == "do not touch\n"

        swap_agents_dir = tmp_path / "swap_agents"
        swap_agents_dir.mkdir()
        (swap_agents_dir / "AGENTS.md").write_text("# Local\n", encoding="utf-8")

        def swap_before_stage(*args: Any, **kwargs: Any) -> None:
            (swap_agents_dir / "AGENTS.md").unlink()
            (swap_agents_dir / "AGENTS.md").symlink_to(outside_secret)
            real_stage(*args, **kwargs)

        with (
            monkeypatch.context() as patch,
            pytest.raises(TautError, match="cannot write AGENTS.md"),
        ):
            patch.setattr(onboard_mod, "_stage_and_publish", swap_before_stage)
            TautClient.onboard(
                root=swap_agents_dir, init_storage=False, update_ignore=False
            )
        assert outside_secret.read_text(encoding="utf-8") == "do not touch\n"
