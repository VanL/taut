"""Shared fixtures and the real-process driver harness for summon tests.

Backend posture ([SUM-8]): summon requires a SQL-sidecar backend, because
its session ledger rides extension-owned sidecar tables. This suite runs on
SQLite; Postgres parity of the ledger DDL rides the dialect pattern copied
from core, and a PG execution lane for these tests is follow-on wiring
(see the summon plan's Out of Scope). Plain pytest — no backend-marker
machinery.

This module is also the one home for the real-process driver harness so
both ``test_driver.py`` (the taut-specific deep proofs) and
``test_conformance.py`` (the portable, parameterized [SUM-12] suite) drive
the *same* harness — never a divergent copy. The anti-mocking floor
([SUM-12]) is baked in: every driver is a real ``taut-summon run``
foreground subprocess against a real SQLite database, peer writers are real
``taut`` CLI subprocesses, and the harness child is the real scripted
provider. What reached the harness process is observed through the
provider's received-log (``TAUT_SUMMON_RECEIVED_LOG``), the observable form
of [SUM-5.4]'s process-boundary delivery guarantee.
"""

from __future__ import annotations

import json
import os
import re
import signal
import sqlite3
import subprocess
import sys
import time
from collections.abc import Callable, Iterable, Iterator
from pathlib import Path
from typing import Any, Protocol

import pytest
from simplebroker import Queue
from simplebroker.ext import OperationalError
from taut_summon._state import list_sessions

from taut.client import TautClient
from taut.identity import capture_process, route_key

_SUMMON_SQLITE_TEST_ENV: dict[str, str] = {
    # The real-process harness is a high-churn SQLite workload: driver,
    # provider, and peer CLI subprocesses all share one temporary DB per test.
    # Disable maintenance writes, but keep SQLite's default FULL sync semantics.
    # NORMAL is faster locally but weakens the storage proof and can mask the
    # summon behavior under test behind broker recovery noise.
    "BROKER_AUTO_VACUUM": "0",
    "BROKER_SYNC_MODE": "FULL",
}

EXTENSION_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = EXTENSION_ROOT.parents[1]

SummonCliRunner = Callable[..., tuple[int, str, str]]

# Generous for slow CI runners: every use is a wait-until (cheap when
# green), and each driver test runs a real three-process pipeline
# (driver + provider + CLI writers). Broad xdist runs co-locate process-heavy
# tests during broad mixed-suite runs; isolated process lanes override that
# grouping with ``-n auto --dist load`` as an intentional pressure proof.
_DEADLINE = 90.0
# Bootstrap PING is the live readiness authority. Keep the per-request timeout
# generous enough for slow CI and loaded local runs without adding a Taut-level
# broker retry loop.
_CONTROL_BOOTSTRAP_REQUEST_TIMEOUT = 60.0
_SUMMONED_MEMBER_RE = re.compile(
    r"summoned '.*?' \(member (?P<member_id>[^,]+), provider "
)


def _run_summon_cli(
    *args: object,
    cwd: Path,
    timeout: float = 20.0,
) -> tuple[int, str, str]:
    """Run the real ``taut-summon`` entry point in a subprocess."""

    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUNBUFFERED"] = "1"
    env.update(_SUMMON_SQLITE_TEST_ENV)
    # The package and core taut are importable from the repo checkout even
    # when neither is installed in the running environment.
    paths = [str(EXTENSION_ROOT), str(PROJECT_ROOT)]
    existing = env.get("PYTHONPATH")
    if existing:
        paths.append(existing)
    env["PYTHONPATH"] = os.pathsep.join(paths)
    completed = subprocess.run(
        [sys.executable, "-m", "taut_summon", *map(str, args)],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=False,
    )
    return completed.returncode, completed.stdout.strip(), completed.stderr.strip()


@pytest.fixture
def run_summon_cli() -> SummonCliRunner:
    return _run_summon_cli


# --- shared real-process harness ---------------------------------------------


@pytest.fixture(autouse=True)
def _clean_taut_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in ("TAUT_DB", "TAUT_AS", "TAUT_TOKEN"):
        monkeypatch.delenv(key, raising=False)
    for key, value in _SUMMON_SQLITE_TEST_ENV.items():
        monkeypatch.setenv(key, value)


def _base_env() -> dict[str, str]:
    env = os.environ.copy()
    for key in ("TAUT_DB", "TAUT_AS", "TAUT_TOKEN"):
        env.pop(key, None)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUNBUFFERED"] = "1"
    env.update(_SUMMON_SQLITE_TEST_ENV)
    paths = [str(EXTENSION_ROOT), str(PROJECT_ROOT)]
    existing = env.get("PYTHONPATH")
    if existing:
        paths.append(existing)
    env["PYTHONPATH"] = os.pathsep.join(paths)
    return env


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Mark real driver-process tests for default grouping and lane selection.

    The shared driver harness starts a foreground driver, a provider child,
    and peer CLI subprocesses. Every marked test owns test-local resources.
    Broad ``loadgroup`` runs co-locate the group to keep unrelated tests from
    changing the process lane's topology. Isolated release and CI lanes use
    ``-n auto --dist load`` so host-width pressure exposes ownership defects.
    """

    for item in items:
        fixture_names = set(getattr(item, "fixturenames", ()))
        fixture_info = getattr(item, "_fixtureinfo", None)
        if fixture_info is not None:
            fixture_names.update(fixture_info.names_closure)
        if "driver_factory" not in fixture_names:
            continue
        if item.get_closest_marker("xdist_group") is not None:
            continue
        item.add_marker(pytest.mark.xdist_group("process"))


def wait_until(
    predicate: Callable[[], bool],
    *,
    timeout: float = _DEADLINE,
    message: str = "condition",
) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.05)
    raise AssertionError(f"timed out waiting for {message}")


def taut_cli(
    *args: str,
    db: Path,
    cwd: Path,
    as_name: str | None = None,
    token: str | None = None,
    stdin: str | None = None,
) -> tuple[int, str, str]:
    """Run the real ``taut`` CLI in a subprocess (peer writer discipline)."""

    env = _base_env()
    if as_name is not None:
        env["TAUT_AS"] = as_name
    if token is not None:
        env["TAUT_TOKEN"] = token
    completed = subprocess.run(
        [sys.executable, "-m", "taut", "--db", str(db), *args],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        input=stdin,
        timeout=30.0,
        check=False,
    )
    return completed.returncode, completed.stdout.strip(), completed.stderr.strip()


def say(db: Path, cwd: Path, target: str, text: str, *, as_name: str = "van") -> None:
    rc, _out, err = taut_cli(
        "say", target, "-", db=db, cwd=cwd, as_name=as_name, stdin=text
    )
    assert rc == 0, f"taut say failed: {err}"


def summon_cli(
    *args: str, db: Path, cwd: Path, timeout: float = _DEADLINE
) -> tuple[int, str, str]:
    """Run the real ``taut-summon`` control client (stop/status) in a subprocess."""

    env = _base_env()
    completed = subprocess.run(
        [sys.executable, "-m", "taut_summon", *args, "--db", str(db)],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=timeout,
        check=False,
    )
    return completed.returncode, completed.stdout.strip(), completed.stderr.strip()


def _ctl_out_messages(db: Path, member_id: str) -> list[dict[str, Any]]:
    """Peek (never consume) the driver's outbound control replies."""

    from taut_summon._control import control_out_queue_name

    queue = Queue(control_out_queue_name(member_id), db_path=str(db))
    try:
        out: list[dict[str, Any]] = []
        for body in queue.peek_many(include_claimed=True):
            if not isinstance(body, str):  # with_timestamps=False yields str
                continue
            try:
                out.append(json.loads(body))
            except (json.JSONDecodeError, ValueError):
                continue
        return out
    finally:
        queue.close()


def _control_request(
    db: Path,
    member_id: str,
    command: str,
    *,
    timeout: float = 15.0,
    session_row: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Send one control request from a client and await the correlated reply."""

    from taut_summon._control import ControlClient

    client = TautClient(db_path=db)
    row = session_row
    if row is None:
        session_queue = Queue("taut_summon_test_reader", db_path=str(db))

        def found_session_row() -> bool:
            nonlocal row
            row = _session_row_from_queue(session_queue, member_id)
            return row is not None

        try:
            wait_until(
                found_session_row,
                timeout=timeout,
                message="control session row",
            )
        finally:
            session_queue.close()
    assert row is not None
    control = ControlClient(
        lambda name: client.queue(name),
        member_id,
        reply_queue_factory=lambda name: client.queue(name),
        driver_pid=row["driver_pid"],
        driver_start_time=row["driver_start_time"],
    )
    try:
        return control.request(command, timeout=timeout)
    finally:
        control.close()
        client.close()


def _await_control_request(
    db: Path,
    member_id: str,
    command: str,
    *,
    timeout: float = _DEADLINE,
    request_timeout: float = 5.0,
    driver: Any | None = None,
    session_row: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Wait until a control command completes a request/reply round trip."""

    deadline = time.monotonic() + timeout
    last_detail = "no attempts"
    while time.monotonic() < deadline:
        try:
            reply = _control_request(
                db,
                member_id,
                command,
                timeout=request_timeout,
                session_row=session_row,
            )
        except Exception as exc:  # noqa: BLE001 approved [DOM-10.2.1] [RUFF-SUP-071] exception
            last_detail = f"{type(exc).__name__}: {exc}"
        else:
            last_detail = repr(reply)
            if reply is not None:
                return reply
        time.sleep(0.05)

    driver_detail = ""
    if driver is not None:
        driver_detail = (
            f"; driver_rc={driver.proc.poll()!r}; stderr: {driver.stderr_tail()}"
        )
    raise AssertionError(
        f"timed out waiting for {command.upper()} control round-trip; "
        f"last={last_detail}{driver_detail}"
    )


class DriverProcess:
    """One real foreground driver under test control through either console."""

    def __init__(
        self,
        tmp_path: Path,
        db: Path,
        name: str,
        *threads: str,
        provider: str | None = None,
        scenario: dict[str, Any] | None = None,
        backoff: str = "0.2,0.2",
        extra_args: tuple[str, ...] = (),
        extra_env: dict[str, str] | None = None,
        control_interval: float | None = None,
        tag: str = "driver",
        include_db: bool = True,
        console: str = "standalone",
    ) -> None:
        self.tag = tag
        self.db = db
        self.name = name
        self.tmp_path = tmp_path
        scenario = scenario if scenario is not None else {}
        self.scenario_path = tmp_path / f"{tag}-scenario.json"
        self.scenario_path.write_text(json.dumps(scenario), encoding="utf-8")
        self.received = tmp_path / f"{tag}-received.jsonl"
        self.stderr_path = tmp_path / f"{tag}.err"
        env = _base_env()
        env["TAUT_SUMMON_SCENARIO"] = str(self.scenario_path)
        env["TAUT_SUMMON_RECEIVED_LOG"] = str(self.received)
        env["TAUT_SUMMON_RESUME_BACKOFF"] = backoff
        env["TAUT_SUMMON_LOG"] = "DEBUG"
        if control_interval is not None:
            env["TAUT_SUMMON_CONTROL_INTERVAL"] = str(control_interval)
        if extra_env is not None:
            env.update(extra_env)
        if console == "standalone":
            command = [sys.executable, "-m", "taut_summon", "run", name]
        elif console == "root":
            command = [sys.executable, "-m", "taut"]
            if include_db:
                command.extend(["--db", str(db)])
            command.extend(["summon", name])
        else:
            raise ValueError(f"unknown driver console {console!r}")
        command.extend(threads)
        if include_db and console == "standalone":
            command.extend(["--db", str(db)])
        if provider is not None:
            command.extend(["--provider", provider])
        if "--attach" not in extra_args and "--detach" not in extra_args:
            command.append("--detach")
        command.extend(extra_args)
        self._stderr_file = open(self.stderr_path, "w", encoding="utf-8")  # noqa: SIM115 approved [DOM-10.2.1] [RUFF-SUP-076] exception
        self.proc = subprocess.Popen(
            command,
            cwd=tmp_path,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=self._stderr_file,
            text=True,
        )
        self._driver_start_time = self._capture_child_start_time()
        self._owned_member_id: str | None = None
        self._owned_session_row: dict[str, Any] | None = None
        self._cleanup_complete = False

    def _capture_child_start_time(self) -> str:
        start_time: str | None = None

        def captured_child_identity() -> bool:
            nonlocal start_time
            evidence = capture_process(self.proc.pid)
            if evidence is not None and evidence.start_time is not None:
                start_time = evidence.start_time
                return True
            if self.proc.poll() is not None:
                raise AssertionError(
                    "driver exited before its process identity was captured: "
                    f"exit={self.proc.returncode!r}; stderr={self.stderr_tail()!r}"
                )
            return False

        wait_until(captured_child_identity, message="driver process identity")
        assert start_time is not None
        return start_time

    # --- received-log accessors ------------------------------------------

    def entries(self) -> list[dict[str, Any]]:
        if not self.received.exists():
            return []
        out: list[dict[str, Any]] = []
        for line in self.received.read_text(encoding="utf-8").splitlines():
            if line.strip():
                out.append(json.loads(line))
        return out

    def starts(self) -> list[dict[str, Any]]:
        return [e for e in self.entries() if e["event"] == "start"]

    def messages(self, *, generation: int | None = None) -> list[str]:
        """Injected texts, optionally only those after the Nth start (0-based)."""

        texts: list[str] = []
        gen = -1
        for entry in self.entries():
            if entry["event"] == "start":
                gen += 1
                continue
            if entry["event"] != "message":
                continue
            if generation is None or gen == generation:
                texts.append(entry["text"])
        return texts

    def wait_for_start(
        self,
        count: int = 1,
        *,
        timeout: float = _DEADLINE,
        bootstrap: bool = True,
    ) -> None:
        def started() -> bool:
            entries = self.entries()
            failures = [
                entry for entry in entries if entry["event"] == "provider-error"
            ]
            if failures:
                raise AssertionError(
                    f"provider failed before start: {failures[-1]}; "
                    f"stderr: {self.stderr_tail()}"
                )
            return (
                len([entry for entry in entries if entry["event"] == "start"]) >= count
            )

        try:
            wait_until(
                started,
                timeout=timeout,
                message=f"{count} provider start(s)",
            )
        except AssertionError as exc:
            raise AssertionError(
                f"{exc}; driver_rc={self.proc.poll()!r}; "
                f"entries={self.entries()!r}; stderr: {self.stderr_tail()}"
            ) from None
        if not bootstrap:
            return

        wait_until(
            lambda: self._summoned_log_count() >= count,
            timeout=timeout,
            message=f"watch readiness; stderr: {self.stderr_tail()}",
        )
        session_row = self.wait_for_owned_session(
            timeout=timeout,
            message=f"bootstrap completion; stderr: {self.stderr_tail()}",
        )
        member_id = self.owned_member_id()
        _await_control_request(
            self.db,
            member_id,
            "PING",
            timeout=timeout,
            request_timeout=_CONTROL_BOOTSTRAP_REQUEST_TIMEOUT,
            driver=self,
            session_row=session_row,
        )

    def wait_for_message(
        self,
        text: str,
        *,
        generation: int | None = None,
        timeout: float = _DEADLINE,
    ) -> None:
        wait_until(
            lambda: any(text in m for m in self.messages(generation=generation)),
            timeout=timeout,
            message=f"injected message containing {text!r}; "
            f"got {self.messages()!r}; driver_rc={self.proc.poll()!r}; "
            f"stderr: {self.stderr_tail()}",
        )

    def child_pid(self) -> int:
        starts = self.starts()
        assert starts, "no provider start recorded yet"
        return int(starts[-1]["pid"])

    def stderr_tail(self) -> str:
        self._stderr_file.flush()
        if not self.stderr_path.exists():
            return ""
        return self.stderr_path.read_text(encoding="utf-8")[-2000:]

    def _summoned_log_count(self) -> int:
        self._stderr_file.flush()
        if not self.stderr_path.exists():
            return 0
        return self.stderr_path.read_text(encoding="utf-8").count(" summoned '")

    def _last_summoned_member_id(self) -> str | None:
        self._stderr_file.flush()
        if not self.stderr_path.exists():
            return None
        matches = list(
            _SUMMONED_MEMBER_RE.finditer(self.stderr_path.read_text(encoding="utf-8"))
        )
        if not matches:
            return None
        return matches[-1].group("member_id")

    def wait_for_owned_session(
        self,
        *,
        timeout: float = _DEADLINE,
        message: str = "owned driver session",
    ) -> dict[str, Any]:
        """Resolve this child through its PID/start evidence, never its name."""

        row: dict[str, Any] | None = None
        queue = Queue("taut_summon_test_owner_reader", db_path=str(self.db))

        def found_owned_session() -> bool:
            nonlocal row
            try:
                matches = [
                    candidate
                    for candidate in list_sessions(queue)
                    if candidate["driver_pid"] == self.proc.pid
                    and candidate["driver_start_time"] == self._driver_start_time
                ]
            except OperationalError:
                return False
            if len(matches) > 1:
                raise AssertionError(
                    "multiple session rows claim driver evidence "
                    f"pid={self.proc.pid}, start={self._driver_start_time!r}"
                )
            if not matches:
                if self.proc.poll() is not None:
                    raise AssertionError(
                        "driver exited before publishing its owned session"
                    )
                return False
            row = dict(matches[0])
            return True

        try:
            wait_until(found_owned_session, timeout=timeout, message=message)
        except AssertionError as exc:
            raise AssertionError(f"{exc}; {self._identity_diagnostic()}") from None
        finally:
            queue.close()
        assert row is not None
        self._owned_member_id = str(row["member_id"])
        self._owned_session_row = row
        return row

    def owned_member_id(self) -> str:
        if self._owned_member_id is None:
            self.wait_for_owned_session()
        assert self._owned_member_id is not None
        return self._owned_member_id

    def _identity_diagnostic(
        self,
        *,
        stop_reply: dict[str, Any] | None = None,
    ) -> str:
        stderr = self._redact_diagnostic(self.stderr_tail())
        session = self._owned_session_row
        session_identity = (
            None
            if session is None
            else {
                "member_id": session.get("member_id"),
                "driver_pid": session.get("driver_pid"),
                "driver_start_time": session.get("driver_start_time"),
                "provider": session.get("provider"),
            }
        )
        detail = (
            f"member={self._owned_member_id!r}, "
            f"session={session_identity!r}, child_pid={self.proc.pid}, "
            f"child_start={self._driver_start_time!r}, "
            f"child_exit={self.proc.poll()!r}, stop_reply={stop_reply!r}, "
            f"stderr={stderr[-2000:]!r}"
        )
        return self._redact_diagnostic(detail)

    @staticmethod
    def _redact_diagnostic(detail: str) -> str:
        return re.sub(
            r"(?i)(continuity[-_ ]?token|token)(\s*[:=]\s*)\S+",
            r"\1\2<redacted>",
            detail,
        )

    # --- lifecycle --------------------------------------------------------

    def stop(
        self,
        *,
        timeout: float = _DEADLINE,
    ) -> int:
        deadline = time.monotonic() + timeout
        stop_reply: dict[str, Any] | None = None
        if self.proc.poll() is None:
            try:
                row = self.wait_for_owned_session(
                    timeout=max(0.01, deadline - time.monotonic())
                )
                member_id = self.owned_member_id()
                _await_control_request(
                    self.db,
                    member_id,
                    "PING",
                    timeout=max(0.01, deadline - time.monotonic()),
                    request_timeout=min(5.0, max(0.01, deadline - time.monotonic())),
                    driver=self,
                    session_row=row,
                )
                stop_reply = _control_request(
                    self.db,
                    member_id,
                    "STOP",
                    timeout=max(0.01, deadline - time.monotonic()),
                    session_row=row,
                )
                if stop_reply is None or stop_reply.get("status") != "ack":
                    raise AssertionError(f"STOP was not acknowledged: {stop_reply!r}")
            except Exception as exc:
                primary = self._redact_diagnostic(f"{type(exc).__name__}: {exc}")
                raise AssertionError(
                    f"graceful driver stop failed: {primary}; "
                    f"{self._identity_diagnostic(stop_reply=stop_reply)}"
                ) from exc
        try:
            rc = self.proc.wait(timeout=max(0.01, deadline - time.monotonic()))
        finally:
            self._stderr_file.flush()
        return rc

    def wait(self, *, timeout: float = _DEADLINE) -> int:
        rc = self.proc.wait(timeout=timeout)
        self._stderr_file.flush()
        return rc

    def _provider_domain_identity(self) -> tuple[int, str, int] | None:
        starts = self.starts()
        if not starts:
            return None
        evidence = capture_process(int(starts[-1]["pid"]))
        if evidence is None or evidence.start_time is None or evidence.pgid is None:
            return None
        return evidence.pid, evidence.start_time, evidence.pgid

    @staticmethod
    def _provider_domain_matches(identity: tuple[int, str, int]) -> bool:
        pid, start_time, pgid = identity
        evidence = capture_process(pid)
        return (
            evidence is not None
            and evidence.start_time == start_time
            and evidence.pgid == pgid
        )

    def _hard_retire_provider_domain(
        self,
        identity: tuple[int, str, int] | None,
    ) -> None:
        """Best-effort fallback after the live driver lost its close path."""

        if identity is None or os.name == "nt":
            return
        if not self._provider_domain_matches(identity):
            return
        _pid, _start_time, pgid = identity
        try:
            os.killpg(pgid, signal.SIGKILL)
        except ProcessLookupError:
            return
        deadline = time.monotonic() + 5.0
        while self._provider_domain_matches(identity) and time.monotonic() < deadline:
            time.sleep(0.05)
        if self._provider_domain_matches(identity):
            raise AssertionError(
                "provider process group survived identity-checked SIGKILL; "
                f"{self._identity_diagnostic()}"
            )

    def _attempt_hard_provider_retirement(
        self,
        identity: tuple[int, str, int] | None,
        failures: list[Exception],
    ) -> bool:
        if identity is None or not self._provider_domain_matches(identity):
            return False
        try:
            self._hard_retire_provider_domain(identity)
        except (AssertionError, OSError) as exc:
            failures.append(exc)
        return True

    def _retire_after_signal_failure(
        self,
        identity: tuple[int, str, int] | None,
        failures: list[Exception],
    ) -> bool:
        """Retire the provider while its live driver can still reap it."""

        hard_fallback_attempted = self._attempt_hard_provider_retirement(
            identity,
            failures,
        )
        if self.proc.poll() is None:
            self.proc.kill()
            self.proc.wait(timeout=10.0)
        return hard_fallback_attempted

    def cleanup(self) -> None:
        if self._cleanup_complete:
            return
        try:
            provider_identity = self._provider_domain_identity()
        except (KeyError, OSError, ValueError):
            provider_identity = None
        failures: list[Exception] = []
        cooperative_cleanup_failed = False
        hard_fallback_attempted = False
        try:
            if self.proc.poll() is None:
                try:
                    self.stop(timeout=10.0)
                except (
                    AssertionError,
                    OSError,
                    subprocess.SubprocessError,
                ) as stop_exc:
                    try:
                        self.proc.send_signal(signal.SIGTERM)
                        self.proc.wait(timeout=10.0)
                    except (OSError, subprocess.SubprocessError) as signal_exc:
                        failures.extend((stop_exc, signal_exc))
                        cooperative_cleanup_failed = True
                        hard_fallback_attempted = self._retire_after_signal_failure(
                            provider_identity,
                            failures,
                        )
            cooperative_cleanup_failed = cooperative_cleanup_failed or (
                not hard_fallback_attempted
                and provider_identity is not None
                and self._provider_domain_matches(provider_identity)
            )
            if cooperative_cleanup_failed and not hard_fallback_attempted:
                self._attempt_hard_provider_retirement(provider_identity, failures)
        finally:
            self._cleanup_complete = True
            self._stderr_file.close()
        if failures:
            raise ExceptionGroup("driver cleanup failed", failures)


class _CleanupProcess(Protocol):
    def cleanup(self) -> None: ...


def _cleanup_driver_processes(procs: Iterable[_CleanupProcess]) -> None:
    """Attempt every owned cleanup before reporting teardown failures."""

    failures: list[Exception] = []
    for proc in procs:
        try:
            proc.cleanup()
        except Exception as exc:  # noqa: BLE001 approved [DOM-10.2.1] [RUFF-SUP-071] exception
            failures.append(exc)
    if failures:
        raise ExceptionGroup("driver fixture cleanup failed", failures)


@pytest.fixture
def summon_db(tmp_path: Path) -> Path:
    db = tmp_path / ".taut.db"
    TautClient.init(db_path=db)
    # A human-shaped peer creates #general and #dev before any summon.
    rc, _out, err = taut_cli("join", "general", db=db, cwd=tmp_path, as_name="van")
    assert rc == 0, err
    rc, _out, err = taut_cli("join", "dev", db=db, cwd=tmp_path, as_name="van")
    assert rc == 0, err
    return db


@pytest.fixture
def driver_factory(
    tmp_path: Path,
) -> Iterator[Callable[..., DriverProcess]]:
    procs: list[DriverProcess] = []

    def factory(*args: Any, **kwargs: Any) -> DriverProcess:
        proc = DriverProcess(tmp_path, *args, **kwargs)
        procs.append(proc)
        return proc

    yield factory
    _cleanup_driver_processes(procs)


def _who(db: Path, thread: str | None = None) -> list[Any]:
    client = TautClient(db_path=db)
    try:
        return list(client.who(thread))
    finally:
        client.close()


def _log(db: Path, thread: str) -> list[Any]:
    client = TautClient(db_path=db)
    try:
        return list(client.log(thread))
    finally:
        client.close()


def _member_by_name(db: Path, name: str) -> Any | None:
    key = route_key(name)
    for member in _who(db):
        if route_key(member.name) == key or key in map(route_key, member.aliases):
            return member
    return None


def _session_row_from_queue(queue: Queue, member_id: str) -> dict[str, Any] | None:
    from taut_summon._state import get_session

    try:
        return get_session(queue, member_id)  # type: ignore[return-value]
    except OperationalError:
        # The summon schema is created by the first driver's bootstrap; a
        # barrier that reads during a bootstrap race can arrive before the
        # taut_summon_sessions table exists — that member simply has no
        # session row yet.
        return None


def _session_row(db: Path, member_id: str) -> dict[str, Any] | None:
    queue = Queue("taut_summon_test_reader", db_path=str(db))
    try:
        return _session_row_from_queue(queue, member_id)
    finally:
        queue.close()


def _wait_for_session_row(
    db: Path,
    member_id: str,
    *,
    timeout: float = _DEADLINE,
    message: str = "session row",
) -> dict[str, Any]:
    row: dict[str, Any] | None = None
    queue = Queue("taut_summon_test_reader", db_path=str(db))

    def found_session_row() -> bool:
        nonlocal row
        row = _session_row_from_queue(queue, member_id)
        return row is not None

    try:
        wait_until(found_session_row, timeout=timeout, message=message)
    finally:
        queue.close()
    assert row is not None, f"no {message}"
    return row


def sqlite_integrity_check(db: Path) -> str:
    connection = sqlite3.connect(db)
    try:
        row = connection.execute("PRAGMA integrity_check").fetchone()
    finally:
        connection.close()
    assert row is not None
    return str(row[0])


def _member_token(db: Path, name: str) -> str:
    member = _member_by_name(db, name)
    assert member is not None, f"no member named {name}"
    row = _wait_for_session_row(
        db,
        member.member_id,
        message=f"session row for {name}",
    )
    return str(row["token"])
