"""Actor-free project onboarding and packaged agent-kernel resource access.

Spec references:
- docs/specs/02-taut-core.md [TAUT-6.4], [TAUT-8.1], [TAUT-8.2], [TAUT-8.3]
- docs/specs/08-persistence-io.md [PIO-6.2]
"""

from __future__ import annotations

import ctypes
import errno
import json
import os
import secrets
import shutil
import stat
import sys
import tomllib
from collections.abc import Callable
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import TYPE_CHECKING

from simplebroker import target_for_directory

from taut import addressing
from taut._config import load_config
from taut._exceptions import TautError
from taut._maintenance import backend_install_hint_error
from taut.client._base import _raise_invalid_project_config
from taut.client._models import OnboardAction, OnboardFileStep, OnboardReport

if TYPE_CHECKING:
    from taut.client._models import InitResult

ONBOARD_START_MARKER = "<!-- taut:onboard:start -->"
ONBOARD_END_MARKER = "<!-- taut:onboard:end -->"
DEFAULT_IGNORE_LINES: tuple[str, ...] = (
    ".taut.db",
    ".taut.db.lock",
    ".taut.lock",
    ".taut.db-wal",
    ".taut.db-shm",
)
MANAGED_ONBOARD_FILENAMES: tuple[str, ...] = (
    "AGENTS.md",
    "CLAUDE.md",
    ".gitignore",
    ".dockerignore",
    ".mcp.json",
)
DEFAULT_MCP_SERVER_ENTRY: dict[str, object] = {
    "command": "taut",
    "args": ["mcp"],
}
_O_BINARY = getattr(os, "O_BINARY", 0)
_O_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
_O_DIRECTORY = getattr(os, "O_DIRECTORY", 0)
_LINK_UNSUPPORTED_ERRNOS = frozenset(
    {
        errno.EOPNOTSUPP,
        getattr(errno, "ENOTSUP", errno.EOPNOTSUPP),
        errno.EPERM,
        errno.ENOSYS,
        errno.EINVAL,
        errno.EXDEV,
    }
)


@dataclass(frozen=True, slots=True)
class _PlannedWrite:
    rel_name: str
    resolved_target: Path
    action: OnboardAction
    payload: bytes | None = None
    expected_id: tuple[int, int] | None = None


@dataclass(frozen=True, slots=True)
class _PlannedIgnore:
    rel_name: str
    resolved_target: Path | None
    action: OnboardAction
    append_bytes: bytes = b""
    expected_id: tuple[int, int] | None = None


def read_agent_kernel() -> str:
    """Return the wheel-packaged agent kernel markdown text."""

    return (
        resources.files("taut").joinpath("agent-kernel.md").read_text(encoding="utf-8")
    )


def _same_path_or_file(left: Path, right: Path) -> bool:
    if left.resolve(strict=False) == right.resolve(strict=False):
        return True
    try:
        return left.exists() and right.exists() and os.path.samefile(left, right)
    except OSError:
        return False


def _render_agents_block(channel: str) -> str:
    return (
        f"{ONBOARD_START_MARKER}\n"
        "## Taut Workspace Coordination\n\n"
        "Shared local chat for humans and agents in this repository.\n\n"
        "1. **Session start (catch up without moving cursors):**\n"
        f"   `taut join {channel} --recent 20`\n"
        "   `taut inbox`\n"
        "   `taut list`\n"
        "2. **Check unread messages since your bookmark:**\n"
        "   `taut read`\n"
        "3. **Post status, blockers, or handoffs:**\n"
        f"   `taut say {channel} "
        '"summary" --join`\n'
        "4. **Full agent protocol reference (no network or workspace state required):**\n"
        "   `taut onboard --print-kernel`\n"
        f"{ONBOARD_END_MARKER}"
    )


def _merge_agents_text(rel_name: str, existing: str, block: str) -> str:
    start_count = existing.count(ONBOARD_START_MARKER)
    end_count = existing.count(ONBOARD_END_MARKER)
    if start_count == 0 and end_count == 0:
        if not existing:
            return f"{block}\n"
        sep = (
            "\n"
            if existing.endswith("\n\n")
            else ("\n\n" if not existing.endswith("\n") else "\n")
        )
        return f"{existing}{sep}{block}\n"
    if start_count != 1 or end_count != 1:
        raise TautError(
            f"cannot update {rel_name}: unbalanced or duplicate taut:onboard markers"
        )
    start_idx = existing.index(ONBOARD_START_MARKER)
    end_idx = existing.index(ONBOARD_END_MARKER)
    if end_idx < start_idx:
        raise TautError(f"cannot update {rel_name}: reversed taut:onboard markers")
    replaced = (
        existing[:start_idx] + block + existing[end_idx + len(ONBOARD_END_MARKER) :]
    )
    return replaced if replaced.endswith("\n") else f"{replaced}\n"


def _open_pinned_parent_fd(
    root_fd: int | None,
    resolved_root: Path,
    resolved_target: Path,
) -> tuple[int | None, str, tuple[str, ...]]:
    rel_parts = resolved_target.relative_to(resolved_root).parts
    if not rel_parts:
        raise TautError("onboarding target cannot be workspace root")
    dir_parts = rel_parts[:-1]
    if root_fd is None:
        return None, rel_parts[-1], dir_parts
    current_fd = os.dup(root_fd)
    try:
        for part in dir_parts:
            next_fd = os.open(
                part,
                os.O_RDONLY | _O_DIRECTORY | _O_NOFOLLOW,
                dir_fd=current_fd,
            )
            os.close(current_fd)
            current_fd = next_fd
    except OSError as exc:
        os.close(current_fd)
        raise TautError(
            f"cannot access {resolved_target.name} inside workspace root: {exc}"
        ) from exc
    return current_fd, rel_parts[-1], dir_parts


def _assert_parent_inside_root(
    root_fd: int | None,
    parent_fd: int | None,
    *,
    dir_parts: tuple[str, ...],
    rel_name: str,
) -> None:
    if root_fd is None or parent_fd is None or not dir_parts:
        return
    walk_fd = os.dup(root_fd)
    try:
        for part in dir_parts:
            next_walk = os.open(
                part,
                os.O_RDONLY | _O_DIRECTORY | _O_NOFOLLOW,
                dir_fd=walk_fd,
            )
            os.close(walk_fd)
            walk_fd = next_walk
        if not os.path.samestat(os.fstat(walk_fd), os.fstat(parent_fd)):
            raise TautError(
                f"cannot write {rel_name}: parent directory changed during onboarding"
            )
    except OSError as exc:
        raise TautError(
            f"cannot write {rel_name}: parent directory moved outside workspace root: {exc}"
        ) from exc
    finally:
        os.close(walk_fd)
    up_fd = os.dup(parent_fd)
    try:
        for _ in dir_parts:
            next_up = os.open(
                "..",
                os.O_RDONLY | _O_DIRECTORY | _O_NOFOLLOW,
                dir_fd=up_fd,
            )
            os.close(up_fd)
            up_fd = next_up
        if not os.path.samestat(os.fstat(up_fd), os.fstat(root_fd)):
            raise TautError(
                f"cannot write {rel_name}: parent directory moved outside workspace root"
            )
    except OSError as exc:
        raise TautError(
            f"cannot write {rel_name}: parent directory moved outside workspace root: {exc}"
        ) from exc
    finally:
        os.close(up_fd)


def _read_utf8_with_identity(
    resolved_target: Path,
    rel_name: str,
    *,
    root_fd: int | None,
    resolved_root: Path,
) -> tuple[str, tuple[int, int]]:
    parent_fd, leaf_name, dir_parts = _open_pinned_parent_fd(
        root_fd, resolved_root, resolved_target
    )
    try:
        _assert_parent_inside_root(
            root_fd, parent_fd, dir_parts=dir_parts, rel_name=rel_name
        )
        if parent_fd is not None:
            fd = os.open(leaf_name, os.O_RDONLY | _O_NOFOLLOW, dir_fd=parent_fd)
        else:
            fd = os.open(resolved_target, os.O_RDONLY | _O_BINARY)
        try:
            st = os.fstat(fd)
            if not stat.S_ISREG(st.st_mode):
                raise TautError(
                    f"cannot onboard {rel_name}: path is not a regular file"
                )
            chunks: list[bytes] = []
            while True:
                _assert_parent_inside_root(
                    root_fd, parent_fd, dir_parts=dir_parts, rel_name=rel_name
                )
                chunk = os.read(fd, 65536)
                if not chunk:
                    break
                chunks.append(chunk)
            raw = b"".join(chunks)
        finally:
            os.close(fd)
    except TautError:
        raise
    except OSError as exc:
        raise TautError(f"cannot read {rel_name}: {exc}") from exc
    finally:
        if parent_fd is not None:
            os.close(parent_fd)
    try:
        return raw.decode("utf-8", errors="strict"), (int(st.st_dev), int(st.st_ino))
    except UnicodeDecodeError as exc:
        raise TautError(f"cannot update {rel_name}: file is not valid UTF-8") from exc


def _inspect_candidate(resolved_root: Path, rel_name: str) -> tuple[bool, Path]:
    candidate = resolved_root / rel_name
    if not os.path.lexists(candidate):
        return False, candidate
    if candidate.is_symlink() and not candidate.exists():
        raise TautError(f"cannot onboard {rel_name}: broken symlink")
    resolved = candidate.resolve()
    if not resolved.is_relative_to(resolved_root):
        raise TautError(
            f"cannot onboard {rel_name}: symlink resolves outside workspace root"
        )
    if candidate.is_dir():
        raise TautError(f"cannot onboard {rel_name}: path is a directory")
    if not candidate.is_file():
        raise TautError(f"cannot onboard {rel_name}: path is not a regular file")
    return True, resolved


def _resolve_sqlite_companions_and_config_name(
    resolved_root: Path,
    db_path: str | Path | None,
) -> tuple[tuple[Path, ...], str]:
    from taut.client import _validate_sqlite_path

    config = load_config()
    project_config_name = str(config["PROJECT_CONFIG_NAME"])
    explicit = db_path or str(config["DB"]) or None
    sqlite_file: Path | None
    if explicit is not None:
        candidate = Path(explicit).expanduser()
        if not candidate.is_absolute():
            candidate = resolved_root / candidate
        _validate_sqlite_path(candidate)
        sqlite_file = candidate
    else:
        try:
            target_obj = target_for_directory(resolved_root, config=config)
        except (tomllib.TOMLDecodeError, ValueError) as exc:
            _raise_invalid_project_config(exc, project_config_name)
        except RuntimeError as exc:
            hinted = backend_install_hint_error(exc)
            if hinted is not None:
                raise hinted from exc
            raise TautError(str(exc)) from exc
        sqlite_file = (
            Path(target_obj.target) if target_obj.backend_name == "sqlite" else None
        )
        if sqlite_file is not None:
            _validate_sqlite_path(sqlite_file)
    if sqlite_file is None:
        return (), project_config_name
    companions: list[Path] = [resolved_root / ".taut.lock"]
    for base in {sqlite_file, sqlite_file.resolve(strict=False)}:
        companions.extend(
            (
                base,
                Path(f"{base}.lock"),
                Path(f"{base}-wal"),
                Path(f"{base}-shm"),
            )
        )
    return tuple(companions), project_config_name


def _preflight_aliases(
    resolved_root: Path,
    enabled_names: tuple[str, ...],
    sqlite_companions: tuple[Path, ...],
    project_config_name: str,
) -> None:
    protected_names = (*MANAGED_ONBOARD_FILENAMES, project_config_name)
    for rel_name in enabled_names:
        candidate = resolved_root / rel_name
        if any(_same_path_or_file(candidate, comp) for comp in sqlite_companions):
            raise TautError(
                f"cannot onboard {rel_name}: aliases SQLite database or lock/sidecar path"
            )
        for other_name in protected_names:
            if other_name == rel_name:
                continue
            other = resolved_root / other_name
            if {rel_name, other_name} == {"AGENTS.md", "CLAUDE.md"}:
                if (
                    os.path.lexists(candidate)
                    and os.path.lexists(other)
                    and candidate.resolve() == other.resolve()
                ):
                    continue
                if _same_path_or_file(candidate, other):
                    raise TautError(
                        "cannot onboard AGENTS.md and CLAUDE.md: distinct hard-linked "
                        "paths would be severed by atomic replacement"
                    )
                continue
            if _same_path_or_file(candidate, other):
                raise TautError(
                    f"cannot onboard {rel_name}: aliases protected project file {other_name}"
                )


def _plan_agent_steps(
    resolved_root: Path,
    inspected: dict[str, tuple[bool, Path]],
    channel: str,
    *,
    update_agents: bool,
    root_fd: int | None,
) -> tuple[_PlannedWrite, ...]:
    if not update_agents:
        return (
            _PlannedWrite("AGENTS.md", resolved_root / "AGENTS.md", "skipped_disabled"),
        )
    agents_exists, agents_resolved = inspected["AGENTS.md"]
    claude_exists, claude_resolved = inspected["CLAUDE.md"]
    block = _render_agents_block(channel)
    if not agents_exists and not claude_exists:
        return (
            _PlannedWrite(
                "AGENTS.md",
                agents_resolved,
                "created",
                f"{block}\n".encode(),
            ),
        )
    targets: list[tuple[str, Path]] = []
    if agents_exists and claude_exists and agents_resolved == claude_resolved:
        targets.append(("AGENTS.md", agents_resolved))
    else:
        if agents_exists:
            targets.append(("AGENTS.md", agents_resolved))
        if claude_exists:
            targets.append(("CLAUDE.md", claude_resolved))
    planned: list[_PlannedWrite] = []
    for rel_name, resolved_target in targets:
        existing, file_id = _read_utf8_with_identity(
            resolved_target,
            rel_name,
            root_fd=root_fd,
            resolved_root=resolved_root,
        )
        merged = _merge_agents_text(rel_name, existing, block)
        if merged == existing:
            planned.append(_PlannedWrite(rel_name, resolved_target, "unchanged"))
        else:
            planned.append(
                _PlannedWrite(
                    rel_name,
                    resolved_target,
                    "updated",
                    merged.encode(),
                    expected_id=file_id,
                )
            )
    return tuple(planned)


def _plan_ignore_steps(
    resolved_root: Path,
    inspected: dict[str, tuple[bool, Path]],
    *,
    update_ignore: bool,
    root_fd: int | None,
) -> tuple[_PlannedIgnore, ...]:
    if not update_ignore:
        return tuple(
            _PlannedIgnore(name, None, "skipped_disabled")
            for name in (".gitignore", ".dockerignore")
        )
    planned: list[_PlannedIgnore] = []
    for rel_name in (".gitignore", ".dockerignore"):
        exists, resolved_target = inspected[rel_name]
        if not exists:
            planned.append(_PlannedIgnore(rel_name, None, "skipped_absent"))
            continue
        existing, file_id = _read_utf8_with_identity(
            resolved_target,
            rel_name,
            root_fd=root_fd,
            resolved_root=resolved_root,
        )
        existing_lines = set(existing.splitlines())
        missing = [line for line in DEFAULT_IGNORE_LINES if line not in existing_lines]
        if not missing:
            planned.append(_PlannedIgnore(rel_name, resolved_target, "unchanged"))
            continue
        prefix = "\n" if existing and not existing.endswith("\n") else ""
        append_payload = (prefix + "\n".join(missing) + "\n").encode()
        planned.append(
            _PlannedIgnore(
                rel_name,
                resolved_target,
                "updated",
                append_payload,
                expected_id=file_id,
            )
        )
    return tuple(planned)


def _reject_duplicate_json_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    obj: dict[str, object] = {}
    for key, value in pairs:
        if key in obj:
            raise ValueError(f"duplicate JSON key {key!r}")
        obj[key] = value
    return obj


@dataclass(frozen=True, slots=True)
class _RawJsonNumber:
    token: str


def _reject_json_constant(token: str) -> object:
    raise ValueError(f"non-standard JSON constant {token!r}")


def _dump_json_scalar(value: object) -> str | None:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, _RawJsonNumber):
        return value.token
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    return None


def _push_json_container(
    stack: list[str | tuple[object, int]],
    value: object,
    level: int,
) -> None:
    pad = "  " * (level + 1)
    close_pad = "  " * level
    if isinstance(value, list):
        if not value:
            stack.append("[]")
            return
        stack.append(f"\n{close_pad}]")
        for idx in range(len(value) - 1, -1, -1):
            if idx < len(value) - 1:
                stack.append(",")
            stack.append((value[idx], level + 1))
            stack.append(f"\n{pad}")
        stack.append("[")
        return
    if isinstance(value, dict):
        if not value:
            stack.append("{}")
            return
        items = list(value.items())
        stack.append(f"\n{close_pad}}}")
        for idx in range(len(items) - 1, -1, -1):
            key, val = items[idx]
            if idx < len(items) - 1:
                stack.append(",")
            stack.append((val, level + 1))
            stack.append(f"\n{pad}{json.dumps(str(key), ensure_ascii=False)}: ")
        stack.append("{")
        return
    raise TypeError(f"unsupported JSON value: {type(value).__name__}")


def _dump_json(root: object) -> str:
    out: list[str] = []
    stack: list[str | tuple[object, int]] = [(root, 0)]
    while stack:
        item = stack.pop()
        if isinstance(item, str):
            out.append(item)
            continue
        value, level = item
        scalar = _dump_json_scalar(value)
        if scalar is not None:
            out.append(scalar)
            continue
        _push_json_container(stack, value, level)
    return "".join(out)


def _plan_mcp_step(
    resolved_root: Path,
    inspected: dict[str, tuple[bool, Path]],
    *,
    mcp: bool,
    root_fd: int | None,
) -> _PlannedWrite:
    if not mcp:
        return _PlannedWrite(
            ".mcp.json", resolved_root / ".mcp.json", "skipped_disabled"
        )
    exists, resolved_target = inspected[".mcp.json"]
    if not exists:
        body = _dump_json({"mcpServers": {"taut": DEFAULT_MCP_SERVER_ENTRY}}) + "\n"
        return _PlannedWrite(".mcp.json", resolved_target, "created", body.encode())
    raw, file_id = _read_utf8_with_identity(
        resolved_target,
        ".mcp.json",
        root_fd=root_fd,
        resolved_root=resolved_root,
    )
    try:
        parsed = json.loads(
            raw,
            object_pairs_hook=_reject_duplicate_json_keys,
            parse_constant=_reject_json_constant,
            parse_float=_RawJsonNumber,
            parse_int=_RawJsonNumber,
        )
    except (json.JSONDecodeError, ValueError, RecursionError) as exc:
        raise TautError(f"cannot update .mcp.json: invalid JSON ({exc})") from exc
    if not isinstance(parsed, dict):
        raise TautError("cannot update .mcp.json: root value must be a JSON object")
    servers = parsed.get("mcpServers")
    if "mcpServers" in parsed and not isinstance(servers, dict):
        raise TautError("cannot update .mcp.json: mcpServers must be a JSON object")
    if isinstance(servers, dict) and "taut" in servers:
        if servers["taut"] == DEFAULT_MCP_SERVER_ENTRY:
            return _PlannedWrite(".mcp.json", resolved_target, "unchanged")
        raise TautError(
            "cannot update .mcp.json: mcpServers.taut already exists with different configuration"
        )
    updated_servers = dict(servers) if isinstance(servers, dict) else {}
    updated_servers["taut"] = dict(DEFAULT_MCP_SERVER_ENTRY)
    updated_doc = dict(parsed)
    updated_doc["mcpServers"] = updated_servers
    rendered = _dump_json(updated_doc) + "\n"
    return _PlannedWrite(
        ".mcp.json",
        resolved_target,
        "updated",
        rendered.encode(),
        expected_id=file_id,
    )


def _write_all_fd(
    fd: int,
    data: bytes,
    *,
    before_write: Callable[[], None] | None = None,
) -> None:
    view = memoryview(data)
    written = 0
    while written < len(view):
        if before_write is not None:
            before_write()
        written += os.write(fd, view[written:])


def _atomic_rename_noreplace(
    *,
    parent_fd: int | None,
    staged_name: str,
    leaf_name: str,
    staged_path: Path,
    resolved_target: Path,
) -> None:
    if sys.platform == "win32":
        win_dll = ctypes.WinDLL("kernel32", use_last_error=True)
        ok = win_dll.MoveFileExW(
            ctypes.c_wchar_p(str(staged_path)),
            ctypes.c_wchar_p(str(resolved_target)),
            ctypes.c_uint(0),
        )
        if not ok:
            err = ctypes.get_last_error()
            raise ctypes.WinError(err)
        return
    assert parent_fd is not None
    libc = ctypes.CDLL(None, use_errno=True)
    if sys.platform == "darwin" and hasattr(libc, "renameatx_np"):
        rc = libc.renameatx_np(
            ctypes.c_int(parent_fd),
            os.fsencode(staged_name),
            ctypes.c_int(parent_fd),
            os.fsencode(leaf_name),
            ctypes.c_uint(0x4),
        )
    elif sys.platform.startswith("linux") and hasattr(libc, "renameat2"):
        rc = libc.renameat2(
            ctypes.c_int(parent_fd),
            os.fsencode(staged_name),
            ctypes.c_int(parent_fd),
            os.fsencode(leaf_name),
            ctypes.c_uint(1),
        )
    else:
        raise OSError(
            errno.EOPNOTSUPP,
            "atomic no-overwrite rename is unavailable on this platform",
            str(resolved_target),
        )
    if rc != 0:
        err = ctypes.get_errno()
        raise OSError(err, os.strerror(err), str(resolved_target))


def _publish_staged_file(
    *,
    root_fd: int | None,
    parent_fd: int | None,
    dir_parts: tuple[str, ...],
    leaf_name: str,
    staged_name: str,
    staged_path: Path,
    resolved_target: Path,
    create_only: bool,
    expected_id: tuple[int, int] | None,
) -> None:
    _assert_parent_inside_root(
        root_fd,
        parent_fd,
        dir_parts=dir_parts,
        rel_name=resolved_target.name,
    )
    if not create_only:
        orig_st = (
            os.stat(leaf_name, dir_fd=parent_fd, follow_symlinks=False)
            if parent_fd is not None
            else os.stat(resolved_target, follow_symlinks=False)
        )
        if not stat.S_ISREG(orig_st.st_mode) or (
            expected_id is not None
            and (int(orig_st.st_dev), int(orig_st.st_ino)) != expected_id
        ):
            raise TautError(
                f"cannot write {resolved_target.name}: target changed during onboarding"
            )
        if parent_fd is not None:
            _assert_parent_inside_root(
                root_fd,
                parent_fd,
                dir_parts=dir_parts,
                rel_name=resolved_target.name,
            )
            os.chmod(
                staged_name,
                stat.S_IMODE(orig_st.st_mode),
                dir_fd=parent_fd,
                follow_symlinks=False,
            )
            _assert_parent_inside_root(
                root_fd,
                parent_fd,
                dir_parts=dir_parts,
                rel_name=resolved_target.name,
            )
            os.replace(
                staged_name,
                leaf_name,
                src_dir_fd=parent_fd,
                dst_dir_fd=parent_fd,
            )
        else:
            shutil.copymode(resolved_target, staged_path)
            os.replace(staged_path, resolved_target)
        return
    try:
        _assert_parent_inside_root(
            root_fd,
            parent_fd,
            dir_parts=dir_parts,
            rel_name=resolved_target.name,
        )
        if parent_fd is not None:
            os.link(
                staged_name,
                leaf_name,
                src_dir_fd=parent_fd,
                dst_dir_fd=parent_fd,
                follow_symlinks=False,
            )
        else:
            os.link(staged_path, resolved_target)
    except OSError as exc:
        if exc.errno not in _LINK_UNSUPPORTED_ERRNOS:
            raise
        _assert_parent_inside_root(
            root_fd,
            parent_fd,
            dir_parts=dir_parts,
            rel_name=resolved_target.name,
        )
        _atomic_rename_noreplace(
            parent_fd=parent_fd,
            staged_name=staged_name,
            leaf_name=leaf_name,
            staged_path=staged_path,
            resolved_target=resolved_target,
        )
        return
    _cleanup_staged_file(parent_fd, staged_name, staged_path)


def _cleanup_staged_file(
    parent_fd: int | None,
    staged_name: str,
    staged_path: Path,
) -> None:
    try:
        if parent_fd is not None:
            os.unlink(staged_name, dir_fd=parent_fd)
        else:
            os.unlink(staged_path)
    except OSError:
        pass


def _stage_and_publish(
    resolved_target: Path,
    payload: bytes,
    *,
    create_only: bool,
    expected_id: tuple[int, int] | None,
    root_fd: int | None,
    resolved_root: Path,
) -> None:
    parent_fd, leaf_name, dir_parts = _open_pinned_parent_fd(
        root_fd, resolved_root, resolved_target
    )
    staged_name = f".{leaf_name}.taut-{secrets.token_hex(8)}.tmp"
    staged_path = resolved_target.parent / staged_name
    open_mode = 0o666 if create_only else 0o600
    created_staged = False
    try:
        _assert_parent_inside_root(
            root_fd, parent_fd, dir_parts=dir_parts, rel_name=resolved_target.name
        )
        fd = (
            os.open(
                staged_name,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | _O_NOFOLLOW,
                open_mode,
                dir_fd=parent_fd,
            )
            if parent_fd is not None
            else os.open(
                staged_path,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | _O_BINARY,
                open_mode,
            )
        )
        created_staged = True
        try:
            _write_all_fd(
                fd,
                payload,
                before_write=lambda: _assert_parent_inside_root(
                    root_fd,
                    parent_fd,
                    dir_parts=dir_parts,
                    rel_name=resolved_target.name,
                ),
            )
        finally:
            os.close(fd)
        _publish_staged_file(
            root_fd=root_fd,
            parent_fd=parent_fd,
            dir_parts=dir_parts,
            leaf_name=leaf_name,
            staged_name=staged_name,
            staged_path=staged_path,
            resolved_target=resolved_target,
            create_only=create_only,
            expected_id=expected_id,
        )
        created_staged = False
    except TautError:
        raise
    except OSError as exc:
        raise TautError(f"cannot write {resolved_target.name}: {exc}") from exc
    finally:
        if created_staged:
            _cleanup_staged_file(parent_fd, staged_name, staged_path)
        if parent_fd is not None:
            os.close(parent_fd)


def _apply_planned_write(
    step: _PlannedWrite,
    *,
    root_fd: int | None,
    resolved_root: Path,
) -> OnboardFileStep:
    if step.action in ("skipped_disabled", "unchanged"):
        return OnboardFileStep(path=step.rel_name, action=step.action)
    assert step.payload is not None
    _stage_and_publish(
        step.resolved_target,
        step.payload,
        create_only=(step.action == "created"),
        expected_id=step.expected_id,
        root_fd=root_fd,
        resolved_root=resolved_root,
    )
    return OnboardFileStep(path=step.rel_name, action=step.action)


def _apply_planned_ignore(
    step: _PlannedIgnore,
    *,
    root_fd: int | None,
    resolved_root: Path,
) -> OnboardFileStep:
    if step.action in ("skipped_disabled", "skipped_absent", "unchanged"):
        return OnboardFileStep(path=step.rel_name, action=step.action)
    assert step.resolved_target is not None
    parent_fd, leaf_name, dir_parts = _open_pinned_parent_fd(
        root_fd, resolved_root, step.resolved_target
    )
    try:
        _assert_parent_inside_root(
            root_fd, parent_fd, dir_parts=dir_parts, rel_name=step.rel_name
        )
        try:
            if parent_fd is not None:
                fd = os.open(
                    leaf_name,
                    os.O_WRONLY | os.O_APPEND | _O_NOFOLLOW,
                    dir_fd=parent_fd,
                )
            else:
                fd = os.open(
                    step.resolved_target,
                    os.O_WRONLY | os.O_APPEND | _O_BINARY,
                )
        except FileNotFoundError:
            return OnboardFileStep(path=step.rel_name, action="skipped_absent")
        except OSError as exc:
            raise TautError(f"cannot update {step.rel_name}: {exc}") from exc
        try:
            st = os.fstat(fd)
            if not stat.S_ISREG(st.st_mode) or (
                step.expected_id is not None
                and (int(st.st_dev), int(st.st_ino)) != step.expected_id
            ):
                raise TautError(
                    f"cannot update {step.rel_name}: target changed during onboarding"
                )
            _write_all_fd(
                fd,
                step.append_bytes,
                before_write=lambda: _assert_parent_inside_root(
                    root_fd, parent_fd, dir_parts=dir_parts, rel_name=step.rel_name
                ),
            )
        except TautError:
            raise
        except OSError as exc:
            raise TautError(f"cannot update {step.rel_name}: {exc}") from exc
        finally:
            os.close(fd)
    finally:
        if parent_fd is not None:
            os.close(parent_fd)
    return OnboardFileStep(path=step.rel_name, action="updated")


def _validate_bool_flag(name: str, value: object) -> None:
    if type(value) is not bool:
        raise TypeError(f"{name} must be a bool")


def _enabled_onboard_names(
    *,
    update_agents: bool,
    update_ignore: bool,
    mcp: bool,
) -> tuple[str, ...]:
    names: list[str] = []
    if update_agents:
        names.extend(("AGENTS.md", "CLAUDE.md"))
    if update_ignore:
        names.extend((".gitignore", ".dockerignore"))
    if mcp:
        names.append(".mcp.json")
    return tuple(names)


def _open_root_fd(raw_stat: os.stat_result, resolved_root: Path) -> int | None:
    if os.name == "nt":
        return None
    try:
        fd = os.open(resolved_root, os.O_RDONLY | _O_DIRECTORY | _O_NOFOLLOW)
    except OSError as exc:
        raise TautError(f"cannot open workspace root {resolved_root}: {exc}") from exc
    try:
        if not os.path.samestat(raw_stat, os.fstat(fd)):
            raise TautError(
                f"cannot open workspace root {resolved_root}: root changed during onboarding"
            )
    except BaseException:
        os.close(fd)
        raise
    return fd


def onboard_workspace(
    *,
    root: str | Path | None = None,
    db_path: str | Path | None = None,
    channel: str = "general",
    mcp: bool = False,
    init_storage: bool = True,
    update_agents: bool = True,
    update_ignore: bool = True,
) -> OnboardReport:
    """Preflight and apply actor-free project onboarding."""

    _validate_bool_flag("mcp", mcp)
    _validate_bool_flag("init_storage", init_storage)
    _validate_bool_flag("update_agents", update_agents)
    _validate_bool_flag("update_ignore", update_ignore)
    canonical_channel = addressing.validate_chat_thread_name(
        channel,
        allow_subthread=False,
    )
    raw_root = Path.cwd() if root is None else Path(root).expanduser()
    try:
        raw_stat = os.stat(raw_root)
    except OSError as exc:
        raise TautError(
            f"cannot onboard {raw_root}: root is not an existing directory"
        ) from exc
    if not stat.S_ISDIR(raw_stat.st_mode):
        raise TautError(f"cannot onboard {raw_root}: root is not an existing directory")
    resolved_root = raw_root.resolve()
    root_fd = _open_root_fd(raw_stat, resolved_root)

    try:
        enabled_names = _enabled_onboard_names(
            update_agents=update_agents,
            update_ignore=update_ignore,
            mcp=mcp,
        )
        if enabled_names:
            sqlite_companions, project_config_name = (
                _resolve_sqlite_companions_and_config_name(resolved_root, db_path)
            )
            _preflight_aliases(
                resolved_root,
                enabled_names,
                sqlite_companions,
                project_config_name,
            )

        inspected = {
            rel_name: _inspect_candidate(resolved_root, rel_name)
            for rel_name in MANAGED_ONBOARD_FILENAMES
        }

        agent_plan = _plan_agent_steps(
            resolved_root,
            inspected,
            canonical_channel,
            update_agents=update_agents,
            root_fd=root_fd,
        )
        ignore_plan = _plan_ignore_steps(
            resolved_root,
            inspected,
            update_ignore=update_ignore,
            root_fd=root_fd,
        )
        mcp_plan = _plan_mcp_step(
            resolved_root,
            inspected,
            mcp=mcp,
            root_fd=root_fd,
        )

        from taut.client import TautClient

        init_result: InitResult | None = (
            TautClient.init(db_path=db_path, directory=resolved_root)
            if init_storage
            else None
        )
        completed_steps = (
            *(
                _apply_planned_write(step, root_fd=root_fd, resolved_root=resolved_root)
                for step in agent_plan
            ),
            *(
                _apply_planned_ignore(
                    step, root_fd=root_fd, resolved_root=resolved_root
                )
                for step in ignore_plan
            ),
            _apply_planned_write(
                mcp_plan, root_fd=root_fd, resolved_root=resolved_root
            ),
        )
    finally:
        if root_fd is not None:
            os.close(root_fd)

    return OnboardReport(
        root=str(resolved_root),
        channel=canonical_channel,
        init=init_result,
        files=completed_steps,
    )
