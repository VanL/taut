"""Process-chain identity capture and matching.

Spec references:
- docs/specs/02-taut-core.md [TAUT-5]
- docs/specs/03-identity-addressing-notifications.md [IAN-3], [IAN-4]
"""

from __future__ import annotations

import base64
import getpass
import hashlib
import importlib
import json
import os
import platform
import secrets
import socket
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import psutil

from taut._constants import (
    HISTORICAL_NAME_POOL,
    INFRASTRUCTURE_BASENAMES,
    PER_BASENAME_NAME_POOLS,
    SHELL_BASENAMES,
    WRAPPER_BASENAMES,
    capitalize_automatic_name,
    normalize_name_seed,
)
from taut._constants import (
    route_key as _route_key,
)
from taut.state import MemberRow

_PWD: Any | None
try:
    _PWD = importlib.import_module("pwd")
except ImportError:  # pragma: no cover - exercised on non-Unix platforms.
    _PWD = None


@dataclass(frozen=True, slots=True)
class ProcessInfo:
    """Best-effort evidence for one process in the caller ancestry."""

    pid: int
    ppid: int | None = None
    start_time: str | None = None
    exe: str | None = None
    argv: tuple[str, ...] = ()
    uid: int | None = None
    pgid: int | None = None
    session_id: int | None = None
    tty: str | None = None
    cwd: str | None = None

    @property
    def basename(self) -> str:
        source = (self.argv[0] if self.argv else "") or self.exe or ""
        name = Path(source).name.lower()
        return name or "process"

    @property
    def classification_basenames(self) -> tuple[str, ...]:
        names: list[str] = []
        for source in ((self.argv[0] if self.argv else None), self.exe):
            if not source:
                continue
            name = Path(source).name.lower()
            if name and name not in names:
                names.append(name)
        return tuple(names) or (self.basename,)


@dataclass(frozen=True, slots=True)
class HostIdentity:
    """Opaque host identity plus display label."""

    host_id: str
    host_label: str


@dataclass(frozen=True, slots=True)
class IdentityCapture:
    """Captured process evidence and selected anchor."""

    chain: tuple[ProcessInfo, ...]
    host: HostIdentity
    uid: int
    login: str
    anchor: ProcessInfo | None
    kind: str
    rule: str


@dataclass(frozen=True, slots=True)
class IdentityClaim:
    """Deterministic evidence claim for one captured identity source."""

    claim_hash: str
    claim_kind: str
    host_id: str | None
    host_label: str | None
    evidence: dict[str, Any]


def capture_identity() -> IdentityCapture:
    """Capture the current caller identity evidence."""

    host = capture_host_identity()
    uid = os.getuid() if hasattr(os, "getuid") else 0
    chain = capture_process_chain(os.getppid())
    anchor, rule = select_anchor(chain)
    login = _login_name(uid)
    return IdentityCapture(
        chain=tuple(chain),
        host=host,
        uid=uid,
        login=login,
        anchor=anchor,
        kind="agent" if anchor is not None else "human",
        rule=rule,
    )


def capture_host_identity() -> HostIdentity:  # noqa: C901 approved [DOM-10.2.1] [RUFF-SUP-052] exception
    """Return an opaque host id and human display label."""

    label = socket.gethostname()
    if sys.platform.startswith("linux"):
        for path in (Path("/etc/machine-id"), Path("/var/lib/dbus/machine-id")):
            try:
                value = path.read_text(encoding="utf-8").strip()
            except OSError:
                continue
            if value:
                return HostIdentity(host_id=f"machine-id:{value}", host_label=label)
    if sys.platform == "darwin":
        try:
            completed = subprocess.run(
                ["ioreg", "-rd1", "-c", "IOPlatformExpertDevice"],
                check=False,
                capture_output=True,
                text=True,
                timeout=2,
            )
        except (OSError, subprocess.SubprocessError):
            completed = None
        if completed is not None and completed.returncode == 0:
            for line in completed.stdout.splitlines():
                if "IOPlatformUUID" not in line:
                    continue
                _, _, value = line.partition("=")
                uuid = value.strip().strip('"')
                if uuid:
                    return HostIdentity(
                        host_id=f"ioplatformuuid:{uuid}", host_label=label
                    )
    return HostIdentity(host_id=f"hostname:{label}", host_label=label)


def capture_process_chain(start_pid: int, *, limit: int = 12) -> list[ProcessInfo]:
    """Capture ancestors from *start_pid* upward, field-by-field best effort."""

    chain: list[ProcessInfo] = []
    seen: set[int] = set()
    pid = start_pid
    while pid > 0 and pid not in seen and len(chain) < limit:
        seen.add(pid)
        proc = capture_process(pid)
        if proc is None:
            break
        chain.append(proc)
        if proc.ppid is None or proc.ppid == pid:
            break
        pid = proc.ppid
    return chain


def capture_process(pid: int) -> ProcessInfo | None:
    """Capture one process using psutil, with the /proc fallback on Linux."""

    psutil_process = _capture_psutil_process(pid)
    if psutil_process is not None:
        return psutil_process
    if sys.platform.startswith("linux"):
        return _capture_linux_process(pid)
    return None


def select_anchor(
    chain: tuple[ProcessInfo, ...] | list[ProcessInfo],
) -> tuple[ProcessInfo | None, str]:
    """Return the first non-wrapper process, or human fallback."""

    for proc in chain:
        names = tuple(
            _classification_basename(name) for name in proc.classification_basenames
        )
        if any(name in SHELL_BASENAMES or name in WRAPPER_BASENAMES for name in names):
            continue
        for name in names:
            if name in INFRASTRUCTURE_BASENAMES:
                return None, f"human fallback at infrastructure process {name}"
        name = proc.basename
        if proc.start_time is None:
            return None, f"human fallback because {name} has no start-time token"
        return proc, f"agent anchor selected at {name}"
    return None, "human fallback at top of readable process chain"


def _classification_basename(name: str) -> str:
    """Normalize one platform suffix for process-family classification only."""

    return name.casefold().removesuffix(".exe")


def fingerprint_for_process(proc: ProcessInfo | None) -> str | None:
    """Serialize stable diagnostic evidence for an anchor."""

    if proc is None:
        return None
    payload = {
        "pid": proc.pid,
        "ppid": proc.ppid,
        "start_time": proc.start_time,
        "exe": proc.exe,
        "argv": list(proc.argv),
        "uid": proc.uid,
        "pgid": proc.pgid,
        "session_id": proc.session_id,
        "tty": proc.tty,
        "cwd": proc.cwd,
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def claim_for_capture(capture: IdentityCapture) -> IdentityClaim:
    """Build the deterministic claim for captured local identity evidence."""

    if capture.anchor is not None:
        evidence = {
            "claim_kind": "agent_process",
            "host_id": capture.host.host_id,
            "anchor_pid": capture.anchor.pid,
            "anchor_start_time": capture.anchor.start_time,
            "exe": capture.anchor.exe,
            "argv": list(capture.anchor.argv),
            "cwd": capture.anchor.cwd,
            "uid": capture.uid,
            "process_uid": capture.anchor.uid,
            "pgid": capture.anchor.pgid,
            "session_id": capture.anchor.session_id,
            "tty": capture.anchor.tty,
        }
        return IdentityClaim(
            claim_hash=claim_hash(evidence),
            claim_kind="agent_process",
            host_id=capture.host.host_id,
            host_label=capture.host.host_label,
            evidence=evidence,
        )
    first = capture.chain[0] if capture.chain else None
    evidence = {
        "claim_kind": "human_session",
        "host_id": capture.host.host_id,
        "uid": capture.uid,
        "login": capture.login,
        "tty": first.tty if first is not None else None,
        "session_id": first.session_id if first is not None else None,
    }
    return IdentityClaim(
        claim_hash=claim_hash(evidence),
        claim_kind="human_session",
        host_id=capture.host.host_id,
        host_label=capture.host.host_label,
        evidence=evidence,
    )


def claim_for_token(token: str) -> IdentityClaim:
    """Build a continuity-token claim without storing the token as evidence."""

    token_digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
    evidence = {
        "claim_kind": "continuity_token",
        "token_hash": token_digest,
    }
    return IdentityClaim(
        claim_hash=claim_hash(evidence),
        claim_kind="continuity_token",
        host_id=None,
        host_label=None,
        evidence=evidence,
    )


def claim_hash(payload: dict[str, Any]) -> str:
    """Return the deterministic claim hash for canonical JSON evidence."""

    raw = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return "ic_" + _base32_lower(hashlib.sha256(raw).digest())


def random_member_id() -> str:
    """Mint an opaque durable member id."""

    return "m_" + _base32_lower(secrets.token_bytes(20))


def explain_capture(capture: IdentityCapture, matched_rule: str) -> dict[str, Any]:
    """Return diagnostic identity evidence for ``whoami --explain``."""

    return {
        "host_id": capture.host.host_id,
        "host_label": capture.host.host_label,
        "uid": capture.uid,
        "rule": matched_rule,
        "anchor": _process_summary(capture.anchor),
        "chain": [_process_summary(proc) for proc in capture.chain],
    }


def match_anchor(
    capture: IdentityCapture,
    members: list[MemberRow],
) -> MemberRow | None:
    """Return the nearest stored anchor in the captured chain."""

    for proc in capture.chain:
        if proc.start_time is None:
            continue
        for member in members:
            if member["host_id"] != capture.host.host_id:
                continue
            if (
                member["anchor_pid"] == proc.pid
                and member["anchor_start_time"] == proc.start_time
            ):
                return member
    return None


def member_presence(member: MemberRow, local_host_id: str) -> str:
    """Return a display presence value for one member."""

    if member["kind"] == "human" or member["anchor_pid"] is None:
        return "active"
    if member["host_id"] != local_host_id:
        return "remote"
    proc = capture_process(member["anchor_pid"])
    if proc is None or proc.start_time != member["anchor_start_time"]:
        return "gone"
    return "here"


def mint_token() -> str:
    """Generate a continuity token."""

    return "taut-" + secrets.token_urlsafe(12).lower().replace("_", "-")


def route_key(name: str) -> str:
    """Return the canonical route key for a member display name or alias."""

    return _route_key(name)


def choose_name(
    *,
    seed: str | None,
    taken: set[str],
    fallback: str = "agent",
) -> str:
    """Choose the first deterministic available name for a seed."""

    stem = normalize_name_seed(seed, fallback=fallback)
    display_stem = capitalize_automatic_name(stem)
    taken_keys = {route_key(name) for name in taken}
    if route_key(display_stem) not in taken_keys:
        return display_stem
    for name in PER_BASENAME_NAME_POOLS.get(stem, ()):
        if route_key(name) not in taken_keys:
            return name
    for name in HISTORICAL_NAME_POOL:
        if route_key(name) not in taken_keys:
            return name
    index = 2
    while True:
        suffix = f"-{index}"
        candidate = f"{display_stem[: 64 - len(suffix)]}{suffix}"
        if route_key(candidate) not in taken_keys:
            return candidate
        index += 1


def rank_candidates(
    capture: IdentityCapture,
    members: list[MemberRow],
    *,
    limit: int = 5,
) -> list[tuple[MemberRow, list[str]]]:
    """Return heuristic rejoin candidates for an unrecognized agent."""

    if capture.anchor is None:
        return []
    scored: list[tuple[int, int, MemberRow, list[str]]] = []
    current = capture.anchor
    for member in members:
        if member["kind"] != "agent" or not member["fingerprint"]:
            continue
        try:
            fp = json.loads(member["fingerprint"])
        except json.JSONDecodeError:
            continue
        score = 0
        reasons: list[str] = []
        if fp.get("exe") and fp.get("exe") == current.exe:
            score += 100
            reasons.append("same executable")
        if fp.get("cwd") and fp.get("cwd") == current.cwd:
            score += 40
            reasons.append("same cwd")
        if fp.get("tty") and fp.get("tty") == current.tty:
            score += 10
            reasons.append("same tty")
        if (
            fp.get("session_id") is not None
            and fp.get("session_id") == current.session_id
        ):
            score += 5
            reasons.append("same session")
        if score:
            scored.append((score, member["last_active_ts"], member, reasons))
    scored.sort(key=lambda item: (-item[0], -item[1], item[2]["display_name"]))
    return [(member, reasons) for _, _, member, reasons in scored[:limit]]


def _base32_lower(raw: bytes) -> str:
    return base64.b32encode(raw).decode("ascii").lower().rstrip("=")


def start_time_token(pid: int, proc: psutil.Process | None) -> str | None:
    """Return the unadjusted process-start token defined by [IAN-3.2]."""

    if sys.platform.startswith("linux"):
        try:
            stat = (Path("/proc") / str(pid) / "stat").read_text(encoding="utf-8")
            _prefix, separator, tail = stat.rpartition(") ")
            if not separator:
                return None
            ticks = tail.split()[19]
        except (OSError, IndexError):
            return None
        return f"proc:{ticks}" if ticks.isascii() and ticks.isdigit() else None
    if proc is None:
        return None
    try:
        if sys.platform == "darwin":
            # Public create_time() adjusts against a boot-clock observation.
            seconds = cast(Any, proc)._proc.create_time(monotonic=True)
        else:
            seconds = proc.create_time()
    except psutil.Error:
        return None
    return f"psutil:{round(seconds * 1_000_000)}"


def _capture_linux_process(pid: int) -> ProcessInfo | None:
    proc_dir = Path("/proc") / str(pid)
    try:
        stat = (proc_dir / "stat").read_text(encoding="utf-8")
    except OSError:
        return None
    try:
        prefix, _, tail = stat.rpartition(") ")
        raw_pid, _, comm = prefix.partition(" (")
        fields = tail.split()
        ppid = int(fields[1])
        pgid = int(fields[2])
        session_id = int(fields[3])
        tty_nr = fields[4]
        pid_value = int(raw_pid)
    except (IndexError, ValueError):
        return None
    argv = _read_linux_argv(proc_dir)
    exe = _safe_readlink(proc_dir / "exe")
    cwd = _safe_readlink(proc_dir / "cwd")
    uid = _read_linux_uid(proc_dir)
    return ProcessInfo(
        pid=pid_value,
        ppid=ppid,
        start_time=start_time_token(pid, None),
        exe=exe or comm,
        argv=argv,
        uid=uid,
        pgid=pgid,
        session_id=session_id,
        tty=None if tty_nr == "0" else tty_nr,
        cwd=cwd,
    )


def _capture_psutil_process(pid: int) -> ProcessInfo | None:
    try:
        proc = psutil.Process(pid)
    except psutil.Error:
        return None
    try:
        with proc.oneshot():
            ppid = _psutil_ppid(proc)
            start_time = start_time_token(pid, proc)
            exe = _psutil_exe(proc)
            argv = _psutil_argv(proc)
            cwd = _psutil_cwd(proc)
            uid = _psutil_uid(proc)
            tty = _psutil_terminal(proc)
    except psutil.Error:
        return None
    return ProcessInfo(
        pid=pid,
        ppid=ppid,
        start_time=start_time,
        exe=exe,
        argv=argv,
        uid=uid,
        pgid=_safe_getpgid(pid),
        session_id=_safe_getsid(pid),
        tty=tty,
        cwd=cwd,
    )


def _psutil_ppid(proc: psutil.Process) -> int | None:
    try:
        return proc.ppid()
    except psutil.Error:
        return None


def _psutil_exe(proc: psutil.Process) -> str | None:
    try:
        value = proc.exe()
    except (psutil.Error, OSError):
        return None
    return value or None


def _psutil_argv(proc: psutil.Process) -> tuple[str, ...]:
    try:
        return tuple(proc.cmdline())
    except (psutil.Error, OSError):
        return ()


def _psutil_cwd(proc: psutil.Process) -> str | None:
    try:
        value = proc.cwd()
    except (psutil.Error, OSError):
        return None
    return value or None


def _psutil_uid(proc: psutil.Process) -> int | None:
    try:
        uids = proc.uids()
    except (psutil.Error, AttributeError):
        return None
    return int(uids.real)


def _psutil_terminal(proc: psutil.Process) -> str | None:
    try:
        value = proc.terminal()
    except (psutil.Error, OSError, AttributeError):
        return None
    return value or None


def _safe_getpgid(pid: int) -> int | None:
    if not hasattr(os, "getpgid"):
        return None
    try:
        return os.getpgid(pid)
    except OSError:
        return None


def _safe_getsid(pid: int) -> int | None:
    if not hasattr(os, "getsid"):
        return None
    try:
        return os.getsid(pid)
    except OSError:
        return None


def _read_linux_argv(proc_dir: Path) -> tuple[str, ...]:
    try:
        raw = (proc_dir / "cmdline").read_bytes()
    except OSError:
        return ()
    return tuple(
        part.decode("utf-8", errors="replace") for part in raw.split(b"\0") if part
    )


def _read_linux_uid(proc_dir: Path) -> int | None:
    try:
        status = (proc_dir / "status").read_text(encoding="utf-8")
    except OSError:
        return None
    for line in status.splitlines():
        if line.startswith("Uid:"):
            fields = line.split()
            if len(fields) >= 2:
                try:
                    return int(fields[1])
                except ValueError:
                    return None
    return None


def _safe_readlink(path: Path) -> str | None:
    try:
        return str(path.readlink())
    except OSError:
        return None


def _login_name(uid: int) -> str:
    if _PWD is not None:
        try:
            return str(_PWD.getpwuid(uid).pw_name)
        except KeyError:
            pass
    try:
        return getpass.getuser()
    except Exception:  # noqa: BLE001 approved [DOM-10.2.1] [RUFF-SUP-068] exception
        return platform.node() or "human"


def _process_summary(proc: ProcessInfo | None) -> dict[str, Any] | None:
    if proc is None:
        return None
    return {
        "pid": proc.pid,
        "ppid": proc.ppid,
        "start_time": proc.start_time,
        "exe": proc.exe,
        "argv": list(proc.argv),
        "uid": proc.uid,
        "pgid": proc.pgid,
        "session_id": proc.session_id,
        "tty": proc.tty,
        "cwd": proc.cwd,
    }
