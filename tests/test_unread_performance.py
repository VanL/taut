"""Manual SQLite measurements for bounded unread-list work.

Run serially with output enabled:

    uv run --extra dev pytest tests/test_unread_performance.py -m slow -n 0 -s

The measurements are evidence for local comparison, not CI thresholds.
"""

from __future__ import annotations

import statistics
import time
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
from simplebroker import Queue

import taut.identity as identity
from taut.client import TautClient
from taut.envelope import encode_envelope

pytestmark = [pytest.mark.sqlite_only, pytest.mark.slow]

WARMUP_SAMPLES = 3
TIMED_SAMPLES = 11
STANDARD_PAYLOAD_BYTES = 256
LARGE_PAYLOAD_BYTES = 16 * 1024


@dataclass(frozen=True, slots=True)
class Scenario:
    thread_count: int
    unread_depth: int
    payload_bytes: int = STANDARD_PAYLOAD_BYTES


STANDARD_SCENARIOS = tuple(
    Scenario(thread_count, unread_depth)
    for thread_count in (1, 10, 50)
    for unread_depth in (0, 1, 100, 1000)
)
SCENARIOS = (*STANDARD_SCENARIOS, Scenario(1, 1000, LARGE_PAYLOAD_BYTES))


def _fixed_capture() -> identity.IdentityCapture:
    process = identity.ProcessInfo(
        pid=4242,
        ppid=None,
        start_time="benchmark-start",
        exe="/usr/bin/codex",
        argv=("codex",),
        uid=1000,
        cwd="/benchmark",
    )
    return identity.IdentityCapture(
        chain=(process,),
        host=identity.HostIdentity("host:benchmark", "benchmark-host"),
        uid=1000,
        login="benchmark",
        anchor=process,
        kind="agent",
        rule="benchmark capture",
    )


def _envelope_of_size(payload_bytes: int) -> str:
    empty = encode_envelope(
        from_id="benchmark-bob",
        from_name="bob",
        kind="message",
        text="",
    )
    if payload_bytes < len(empty):
        raise ValueError("payload size is too small for a valid envelope")
    body = encode_envelope(
        from_id="benchmark-bob",
        from_name="bob",
        kind="message",
        text="x" * (payload_bytes - len(empty)),
    )
    assert len(body.encode("utf-8")) == payload_bytes
    return body


def _seed_unread(queue: Queue, *, body: str, count: int) -> None:
    if count == 0:
        return
    first_timestamp = queue.generate_timestamp() + 1
    queue.insert_messages((body, first_timestamp + offset) for offset in range(count))


def _run_scenario(scenario: Scenario) -> tuple[float, float, float]:
    with TemporaryDirectory(prefix="taut-unread-benchmark-") as directory:
        db_path = Path(directory) / ".taut.db"
        TautClient.init(db_path=db_path)
        client = TautClient(
            db_path=db_path,
            as_name="alice",
            identity_capture=_fixed_capture(),
        )
        try:
            body = _envelope_of_size(scenario.payload_bytes)
            for index in range(scenario.thread_count):
                thread = f"thread-{index}"
                client.join(thread)
                queue = client.queue(thread, persistent=True)
                _seed_unread(queue, body=body, count=scenario.unread_depth)

            for _ in range(WARMUP_SAMPLES):
                client.list_threads(all_threads=True)

            samples_ms: list[float] = []
            result = []
            for _ in range(TIMED_SAMPLES):
                started_ns = time.perf_counter_ns()
                result = client.list_threads(all_threads=True)
                samples_ms.append((time.perf_counter_ns() - started_ns) / 1_000_000)

            expected_count = min(scenario.unread_depth, 1000)
            assert len(result) == scenario.thread_count
            assert all(thread.unread_count == expected_count for thread in result)
            quartiles = statistics.quantiles(
                samples_ms,
                n=4,
                method="inclusive",
            )
            return statistics.median(samples_ms), quartiles[0], quartiles[2]
        finally:
            client.close()


def test_unread_list_benchmark() -> None:
    total_started = time.perf_counter()
    print("threads,unread_depth,payload_bytes,median_ms,q1_ms,q3_ms")
    for scenario in SCENARIOS:
        median_ms, q1_ms, q3_ms = _run_scenario(scenario)
        print(
            f"{scenario.thread_count},{scenario.unread_depth},"
            f"{scenario.payload_bytes},{median_ms:.3f},{q1_ms:.3f},{q3_ms:.3f}"
        )
    print(f"total_runtime_seconds={time.perf_counter() - total_started:.3f}")
