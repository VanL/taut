"""Manual identity-selector performance report.

Run explicitly with:

    uv run --extra dev pytest tests/test_identity_performance.py -m slow -n 0 -s

Durations are evidence, not CI thresholds. Deterministic capture counts are the
contract assertion.
"""

from __future__ import annotations

import platform
import statistics
import sys
import time
from importlib import metadata
from pathlib import Path
from typing import Literal

import pytest

import taut.identity as identity
from taut.client import Message, TautClient

pytestmark = [pytest.mark.sqlite_only, pytest.mark.slow]

Scenario = Literal["explicit", "token", "automatic"]
SAMPLE_COUNT = 11
CALLS_PER_SAMPLE = 50


def _benchmark_client(db: Path, scenario: Scenario) -> tuple[TautClient, str]:
    TautClient.init(db_path=db)
    if scenario == "automatic":
        owner = TautClient(db_path=db, persistent=True)
    else:
        owner = TautClient(db_path=db, as_name="Reviewer", persistent=True)
    try:
        owner.join("general")
        created = owner.last_created_member
        assert created is not None
        assert created.token is not None
        if scenario == "explicit":
            actor = TautClient(
                db_path=db,
                as_name="Reviewer",
                persistent=True,
            )
        elif scenario == "token":
            actor = TautClient(
                db_path=db,
                token=created.token,
                persistent=True,
            )
        else:
            actor = TautClient(db_path=db, persistent=True)
        return actor, created.member_id
    finally:
        owner.close()


@pytest.mark.parametrize("scenario", ["explicit", "token", "automatic"])
def test_identity_selector_performance_report(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    scenario: Scenario,
) -> None:
    db = tmp_path / f"{scenario}.db"
    actor, member_id = _benchmark_client(db, scenario)
    real_capture = actor._capture
    capture_count = 0

    def counted_capture() -> identity.IdentityCapture:
        nonlocal capture_count
        capture_count += 1
        return real_capture()

    monkeypatch.setattr(actor, "_capture", counted_capture)
    samples_ms_per_call: list[float] = []
    last_message: Message | None = None
    total_started = time.perf_counter()
    try:
        actor.say("general", f"{scenario} warmup")
        capture_count = 0
        for sample in range(SAMPLE_COUNT):
            started_ns = time.perf_counter_ns()
            for call in range(CALLS_PER_SAMPLE):
                last_message = actor.say(
                    "general",
                    f"{scenario} sample {sample} call {call}",
                )
            elapsed_ns = time.perf_counter_ns() - started_ns
            samples_ms_per_call.append(elapsed_ns / 1_000_000 / CALLS_PER_SAMPLE)
    finally:
        actor.close()
    total_seconds = time.perf_counter() - total_started

    assert last_message is not None
    assert last_message.from_id == member_id
    expected_captures = (
        SAMPLE_COUNT * CALLS_PER_SAMPLE if scenario == "automatic" else 0
    )
    assert capture_count == expected_captures

    quartiles = statistics.quantiles(
        samples_ms_per_call,
        n=4,
        method="inclusive",
    )
    print(
        "identity-selector-performance",
        f"scenario={scenario}",
        f"samples={SAMPLE_COUNT}",
        f"calls_per_sample={CALLS_PER_SAMPLE}",
        f"median_ms_per_call={statistics.median(samples_ms_per_call):.3f}",
        f"q1_ms_per_call={quartiles[0]:.3f}",
        f"q3_ms_per_call={quartiles[2]:.3f}",
        f"capture_count={capture_count}",
        f"total_seconds={total_seconds:.3f}",
        f"platform={platform.platform()}",
        f"machine={platform.machine()}",
        f"python={sys.version.split()[0]}",
        f"psutil={metadata.version('psutil')}",
        f"simplebroker={metadata.version('simplebroker')}",
    )
