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
import signal
import subprocess
import sys
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from simplebroker import Queue
from simplebroker.ext import OperationalError

from taut.client import TautClient

EXTENSION_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = EXTENSION_ROOT.parents[1]

SummonCliRunner = Callable[..., tuple[int, str, str]]

# Generous for slow CI runners: every use is a wait-until (cheap when
# green), and each driver test runs a real three-process pipeline
# (driver + provider + CLI writers). xdist is the default; tests that
# require shared external resources must opt into narrower grouping rather
# than making the whole suite serial.
_DEADLINE = 90.0


def _run_summon_cli(
    *args: object,
    cwd: Path,
    timeout: float = 20.0,
) -> tuple[int, str, str]:
    """Run the real ``taut-summon`` entry point in a subprocess."""

    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUNBUFFERED"] = "1"
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


def _base_env() -> dict[str, str]:
    env = os.environ.copy()
    for key in ("TAUT_DB", "TAUT_AS", "TAUT_TOKEN"):
        env.pop(key, None)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUNBUFFERED"] = "1"
    paths = [str(EXTENSION_ROOT), str(PROJECT_ROOT)]
    existing = env.get("PYTHONPATH")
    if existing:
        paths.append(existing)
    env["PYTHONPATH"] = os.pathsep.join(paths)
    return env


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Group real driver-process tests under xdist without disabling xdist.

    The shared driver harness starts a foreground driver, a provider child,
    and peer CLI subprocesses. Running many of those at once makes host process
    scheduling the behavior under test and can starve the control loop.
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
        timeout=30.0,
    )
    return completed.returncode, completed.stdout.strip(), completed.stderr.strip()


def say(db: Path, cwd: Path, target: str, text: str, *, as_name: str = "van") -> None:
    rc, _out, err = taut_cli("say", target, text, db=db, cwd=cwd, as_name=as_name)
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
    db: Path, member_id: str, command: str, *, timeout: float = 15.0
) -> dict[str, Any] | None:
    """Send one control request from a client and await the correlated reply."""

    from taut_summon._control import ControlClient

    client = TautClient(db_path=db)
    control = ControlClient(client.queue, member_id)
    try:
        return control.request(command, timeout=timeout)
    finally:
        control.close()


class DriverProcess:
    """One real ``taut-summon run`` foreground driver under test control."""

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
    ) -> None:
        self.tag = tag
        self.db = db
        self.name = name
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
        command = [sys.executable, "-m", "taut_summon", "run", name]
        command.extend(threads)
        command.extend(["--db", str(db)])
        if provider is not None:
            command.extend(["--provider", provider])
        command.extend(extra_args)
        self._stderr_file = open(self.stderr_path, "w", encoding="utf-8")
        self.proc = subprocess.Popen(
            command,
            cwd=tmp_path,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=self._stderr_file,
            text=True,
        )

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
        wait_until(
            lambda: len(self.starts()) >= count,
            timeout=timeout,
            message=f"{count} provider start(s); stderr: {self.stderr_tail()}",
        )
        if not bootstrap:
            return

        # Barrier on bootstrap COMPLETION, not just provider start: the
        # driver spawns the child before joining threads ([SUM-4] needs
        # the child pid for the capture), so the provider's start line
        # precedes the joins. A message said into a thread before the
        # driver's join is correctly invisible ([TAUT-7.4] "joining
        # starts you at now") — tests must not race that window. The
        # session row is written by record_session, the last bootstrap
        # step.
        def _bootstrapped() -> bool:
            member = _member_by_name(self.db, self.name)
            if member is None:
                return False
            return _session_row(self.db, member.member_id) is not None

        wait_until(
            lambda: _bootstrapped(),
            timeout=timeout,
            message=f"bootstrap completion; stderr: {self.stderr_tail()}",
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
            f"got {self.messages()!r}; stderr: {self.stderr_tail()}",
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

    # --- lifecycle --------------------------------------------------------

    def stop(self, *, timeout: float = _DEADLINE) -> int:
        if self.proc.poll() is None:
            self.proc.send_signal(signal.SIGINT)
        try:
            rc = self.proc.wait(timeout=timeout)
        finally:
            self._stderr_file.flush()
        return rc

    def wait(self, *, timeout: float = _DEADLINE) -> int:
        rc = self.proc.wait(timeout=timeout)
        self._stderr_file.flush()
        return rc

    def cleanup(self) -> None:
        if self.proc.poll() is None:
            self.proc.kill()
            self.proc.wait(timeout=10)
        self._stderr_file.close()


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
    for proc in procs:
        proc.cleanup()


def _client(db: Path) -> TautClient:
    return TautClient(db_path=db)


def _member_by_name(db: Path, name: str) -> Any | None:
    for member in _client(db).who():
        if member.name == name or name in member.aliases:
            return member
    return None


def _session_row(db: Path, member_id: str) -> dict[str, Any] | None:
    from taut_summon._state import get_session

    queue = Queue("taut_summon_test_reader", db_path=str(db))
    try:
        return get_session(queue, member_id)  # type: ignore[return-value]
    except OperationalError:
        # The summon schema is created by the first driver's bootstrap; a
        # barrier that reads during a bootstrap race can arrive before the
        # taut_summon_sessions table exists — that member simply has no
        # session row yet.
        return None
    finally:
        queue.close()


def _member_token(db: Path, name: str) -> str:
    member = _member_by_name(db, name)
    assert member is not None, f"no member named {name}"
    row = _session_row(db, member.member_id)
    assert row is not None, f"no session row for {name}"
    return str(row["token"])
