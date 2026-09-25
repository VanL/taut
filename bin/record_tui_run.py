#!/usr/bin/env python3
"""Record hosted TUI qualification under the Windows determinism plan."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import platform
import re
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
LEASE_PHASES = ("lease.acquired", "lease.restored", "lease.hold_returned")
PROVIDER_PHASES = ("provider.injected", "provider.consumed", "resource.closed")
REQUIRED_TERMINALS = {
    "navigation": {"navigation.source", "navigation.applied"},
    "recovery": {
        "confirmation.resolved",
        "attach.retired",
        *LEASE_PHASES,
        *PROVIDER_PHASES,
    },
}


def _write(path: Path, value: dict[str, Any]) -> None:
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def _junit(path: Path) -> dict[str, int | float]:
    if not path.is_file():
        raise ValueError("missing JUnit result")
    try:
        root = ET.parse(path).getroot()
        suites = [root] if root.tag == "testsuite" else list(root.findall("testsuite"))
        counts = {
            key: sum(int(suite.attrib[key]) for suite in suites)
            for key in ("tests", "skipped", "failures", "errors")
        }
        seconds = sum(float(suite.attrib["time"]) for suite in suites)
        cases = [case for suite in suites for case in suite.findall("testcase")]
        if (
            root.tag not in {"testsuites", "testsuite"}
            or counts["tests"] < 1
            or counts["tests"] != len(cases)
            or any(count < 0 for count in counts.values())
            or not math.isfinite(seconds)
            or seconds < 0
            or any(
                counts[key] != sum(case.find(tag) is not None for case in cases)
                for key, tag in (
                    ("skipped", "skipped"),
                    ("failures", "failure"),
                    ("errors", "error"),
                )
            )
        ):
            raise ValueError("inconsistent JUnit counts or duration")
    except (ET.ParseError, KeyError, ValueError) as exc:
        raise ValueError(f"invalid JUnit result: {type(exc).__name__}") from exc
    return {**counts, "junit_seconds": seconds}


def _publish_safe_junit(source: Path, destination: Path) -> dict[str, int | float]:
    """Retain case identity/status/duration, never pytest diagnostic content."""
    counts = _junit(source)
    original = ET.parse(source).getroot()
    root = ET.Element("testsuites")
    suites = (
        [original] if original.tag == "testsuite" else original.findall("testsuite")
    )
    for suite in suites:
        safe_suite = ET.SubElement(
            root,
            "testsuite",
            {
                key: suite.attrib[key]
                for key in ("name", "tests", "skipped", "failures", "errors", "time")
                if key in suite.attrib
            },
        )
        for case in suite.findall("testcase"):
            safe_case = ET.SubElement(
                safe_suite,
                "testcase",
                {
                    key: case.attrib[key]
                    for key in ("classname", "name", "time")
                    if key in case.attrib
                },
            )
            for status in ("failure", "error", "skipped"):
                if case.find(status) is not None:
                    ET.SubElement(safe_case, status)
    ET.ElementTree(root).write(destination, encoding="utf-8", xml_declaration=True)
    return counts


def _phase_records(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for sequence, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        record = json.loads(line)
        if (
            not isinstance(record, dict)
            or type(record.get("sequence")) is not int
            or record["sequence"] != sequence
        ):
            raise ValueError("malformed phase sequence")
        elapsed = record.get("elapsed_s")
        if (
            not isinstance(record.get("phase"), str)
            or type(record.get("request")) is not int
            or record["request"] < 0
            or (record["request"] == 0 and record["phase"] != "test.summary")
            or not isinstance(elapsed, (float, int))
            or isinstance(elapsed, bool)
            or not math.isfinite(elapsed)
            or elapsed < 0
            or record.get("outcome")
            not in {
                "started",
                "success",
                "error",
                "cancelled",
                "declined",
                "superseded",
            }
            or record["phase"] == "recorder.tripwire"
        ):
            raise ValueError("malformed phase record or explicit phase tripwire")
        records.append(record)
    return records


def _phase_summary(records: list[dict[str, Any]]) -> dict[str, Any]:
    if not records:
        raise ValueError("empty phase file")
    summary = records[-1]
    if (
        summary.get("phase") != "test.summary"
        or summary.get("request") != 0
        or summary.get("outcome") != "success"
        or summary.get("complete") is not True
        or summary.get("missing") != []
        or summary.get("test_kind") not in {"navigation", "recovery", "other"}
        or not isinstance(summary.get("python_version"), str)
        or not isinstance(summary.get("platform"), str)
        or not summary["python_version"]
        or not summary["platform"]
        or any(record["phase"] == "test.summary" for record in records[:-1])
    ):
        raise ValueError("missing, incomplete, or malformed phase summary")
    return summary


def _required_phases(
    records: list[dict[str, Any]], kind: str, runtime_platform: str
) -> None:
    successes = [record for record in records if record["outcome"] == "success"]
    if kind == "navigation":
        sources = {
            record["request"]
            for record in successes
            if record["phase"] == "navigation.source"
            and record.get("source_dm_count", 0) > 0
        }
        applied = {
            record["request"]
            for record in successes
            if record["phase"] == "navigation.applied"
            and record.get("rendered_dm_count", 0) > 0
        }
        if not sources.intersection(applied):
            raise ValueError("navigation phase source/apply proof is incomplete")
    if kind == "recovery":
        leases = _completed_owners(successes, LEASE_PHASES)
        adapters = _completed_owners(successes, PROVIDER_PHASES)
        confirmed = any(row["phase"] == "confirmation.resolved" for row in successes)
        if not leases or len(adapters) < 2 or not confirmed:
            raise ValueError("recovery phase identities do not prove both runs")
        if runtime_platform.split("-", 1)[0] == "Windows" and not any(
            row["phase"] == "attach.retired" for row in successes
        ):
            raise ValueError("Windows recovery phase lacks successful attach.retired")


def _completed_owners(
    records: list[dict[str, Any]], phases: tuple[str, ...]
) -> set[int]:
    groups = [
        {row["request"] for row in records if row["phase"] == phase} for phase in phases
    ]
    return set.intersection(*groups)


def _validate_phase_order(records: list[dict[str, Any]], kind: str) -> None:
    # Sequence numbers are log-write order. Causality uses captured transition
    # times for one owner only; consumption may precede inject() returning.
    edges = {
        "navigation": (("navigation.source", "navigation.applied"),),
        "recovery": (
            ("lease.acquired", "lease.restored"),
            ("lease.restored", "lease.hold_returned"),
            ("provider.injected", "resource.closed"),
            ("provider.consumed", "resource.closed"),
        ),
    }.get(kind, ())
    completed = _terminal_times(records, kind)
    for owner in {key[0] for key in completed}:
        for before, after in edges:
            first, last = completed.get((owner, before)), completed.get((owner, after))
            if first is not None and last is not None and first > last:
                raise ValueError(f"{kind} phase ownership/order violation")


def _terminal_times(
    records: list[dict[str, Any]], kind: str
) -> dict[tuple[int, str], float]:
    phases = REQUIRED_TERMINALS.get(kind, set())
    terminal_seen: set[tuple[int, str]] = set()
    completed: dict[tuple[int, str], float] = {}
    for row in records:
        if row["outcome"] == "started" or row["phase"] not in phases:
            continue
        key = (row["request"], row["phase"])
        if key in terminal_seen:
            raise ValueError(f"{kind} phase duplicate terminal outcome")
        terminal_seen.add(key)
        if row["outcome"] == "success":
            completed[key] = row["elapsed_s"]
    return completed


def phase_evidence(directory: Path) -> dict[str, Any]:
    """Validate explicit tripwires and required flows, not background outcomes."""
    kinds: set[str] = set()
    runtimes: set[tuple[str, str]] = set()
    paths = sorted(directory.glob("*.jsonl"))
    for path in paths:
        try:
            records = _phase_records(path)
            summary = _phase_summary(records)
            _required_phases(records, summary["test_kind"], summary["platform"])
            _validate_phase_order(records, summary["test_kind"])
        except (OSError, ValueError, TypeError) as exc:
            raise ValueError(f"invalid phase evidence in {path.name}: {exc}") from exc
        kinds.add(summary["test_kind"])
        runtimes.add((summary["python_version"], summary["platform"]))
    if not {"navigation", "recovery"}.issubset(kinds) or len(runtimes) != 1:
        raise ValueError("missing required phase flows or inconsistent pytest runtime")
    python_version, runtime_platform = next(iter(runtimes))
    return {
        "phase_files": len(paths),
        "pytest_python": python_version,
        "pytest_platform": runtime_platform,
    }


def _validate_phase_coverage(counts: dict[str, Any], phases: dict[str, Any]) -> None:
    # The retained suite's autouse observer covers every executed test. Only
    # collection marks skip it; runtime skips/xfails require a contract change.
    if phases["phase_files"] != counts["tests"] - counts["skipped"]:
        raise ValueError("phase file count does not match executed test count")


def run_repetition(command: list[str] | None, output_dir: Path, ordinal: int) -> int:
    """Run once, retaining launch evidence even if the Actions step is killed."""
    if ordinal not in range(1, 6):
        raise ValueError("ordinal must be between 1 and 5")
    # A killed Actions step may skip finally blocks. Raw failure text must
    # remain outside the uploaded tree even before sanitization runs.
    with tempfile.TemporaryDirectory(prefix="taut-tui-raw-junit-") as temporary:
        return _record_repetition(
            command, output_dir, ordinal, Path(temporary) / "raw.xml"
        )


def _record_repetition(
    command: list[str] | None, output_dir: Path, ordinal: int, raw_junit: Path
) -> int:
    directory = output_dir.resolve() / f"run-{ordinal}"
    directory.mkdir(parents=True, exist_ok=False)
    env = os.environ.copy()
    env["TAUT_TUI_PHASE_DIR"] = str(directory / "phases")
    env["TAUT_TUI_JUNIT_PATH"] = str(raw_junit)
    command_kind = "retained-tui-pytest" if command is None else "test-child"
    command = retained_command(raw_junit) if command is None else command
    record: dict[str, Any] = {
        "state": "started",
        "sha": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip(),
        "workflow": env.get("GITHUB_WORKFLOW"),
        "run_id": env.get("GITHUB_RUN_ID"),
        "run_attempt": env.get("GITHUB_RUN_ATTEMPT"),
        "platform": platform.platform(),
        "python": sys.version,
        "lock_sha256": hashlib.sha256(
            (ROOT / "extensions/taut_tui/uv.lock").read_bytes()
        ).hexdigest(),
        "ordinal": ordinal,
        "started_at": datetime.now(UTC).isoformat(),
        "command_kind": command_kind,
    }
    _write(directory / "started.json", record)
    started = time.monotonic()
    try:
        code = subprocess.run(command, cwd=ROOT, env=env, check=False).returncode
    except OSError as exc:
        record.update(
            state="launch-error",
            child_exit_code=None,
            exit_code=127,
            elapsed_seconds=time.monotonic() - started,
            evidence_error=type(exc).__name__,
        )
        _write(directory / "result.json", record)
        return 127
    evidence_error = None
    try:
        record.update(_publish_safe_junit(raw_junit, directory / "junit.xml"))
        if record["failures"] or record["errors"]:
            evidence_error = "JUnit reports failing tests"
        record.update(phase_evidence(directory / "phases"))
        _validate_phase_coverage(record, record)
    except ValueError as exc:
        evidence_error = str(exc)
    exit_code = code or int(evidence_error is not None)
    record.update(
        state="completed",
        child_exit_code=code,
        exit_code=exit_code,
        elapsed_seconds=time.monotonic() - started,
        evidence_error=evidence_error,
    )
    _write(directory / "result.json", record)
    return exit_code


def verify_repetitions(output_dir: Path, expected: int) -> None:
    """Reject missing/partial evidence and changes in the repeated sample."""
    if expected not in range(1, 6):
        raise ValueError("expected repetitions must be between 1 and 5")
    baseline: tuple[object, ...] | None = None
    for ordinal in range(1, expected + 1):
        directory = output_dir / f"run-{ordinal}"
        try:
            initial = json.loads((directory / "started.json").read_text())
            result = json.loads((directory / "result.json").read_text())
            _validate_result(initial, result, ordinal)
            counts = _junit(directory / "junit.xml")
            if any(result.get(key) != value for key, value in counts.items()):
                raise ValueError("recorded counts differ from JUnit")
            if counts["failures"] or counts["errors"]:
                raise ValueError("JUnit reports failing tests")
            phases = phase_evidence(directory / "phases")
            if any(result.get(key) != value for key, value in phases.items()):
                raise ValueError("recorded phase metadata differs from phase files")
            _validate_phase_coverage(counts, phases)
            fields = (
                "sha",
                "lock_sha256",
                "platform",
                "python",
                "workflow",
                "run_id",
                "run_attempt",
            )
            if any(result.get(key) != initial.get(key) for key in fields):
                raise ValueError("start and final identities differ")
            identity = tuple(result.get(key) for key in fields) + (
                counts["tests"],
                counts["skipped"],
                phases["pytest_python"],
                phases["pytest_platform"],
            )
            if baseline is not None and identity != baseline:
                raise ValueError("repetition identity, test count, or skips changed")
            baseline = identity
        except (OSError, TypeError, ValueError) as exc:
            raise ValueError(f"repetition {ordinal}: {exc}") from exc


def _validate_result(initial: Any, result: Any, ordinal: int) -> None:
    if not isinstance(initial, dict) or not isinstance(result, dict):
        raise TypeError("malformed completion objects")
    if (
        initial.get("state") != "started"
        or result.get("state") != "completed"
        or initial.get("ordinal") != ordinal
        or result.get("ordinal") != ordinal
        or type(result.get("child_exit_code")) is not int
        or type(result.get("exit_code")) is not int
        or result["child_exit_code"] != 0
        or result["exit_code"] != 0
        or result.get("evidence_error") is not None
    ):
        raise ValueError("unsuccessful or malformed completion")
    for key, length in (("sha", 40), ("lock_sha256", 64)):
        if (
            not isinstance(result.get(key), str)
            or re.fullmatch(rf"[0-9a-f]{{{length}}}", result[key]) is None
        ):
            raise ValueError(f"missing or malformed {key}")
    if any(
        not isinstance(result.get(key), str) or not result[key]
        for key in ("platform", "python", "started_at")
    ):
        raise ValueError("missing runtime or start metadata")
    elapsed = result.get("elapsed_seconds")
    if (
        not isinstance(elapsed, (float, int))
        or isinstance(elapsed, bool)
        or not math.isfinite(elapsed)
        or elapsed < 0
    ):
        raise ValueError("missing or malformed elapsed duration")


def retained_command(raw_junit: Path) -> list[str]:
    return [
        "uv",
        "run",
        "--project",
        "extensions/taut_tui",
        "--extra",
        "dev",
        "--locked",
        "pytest",
        "extensions/taut_tui/tests",
        "-v",
        "--tb=short",
        "-n",
        "2",
        "--dist",
        "loadfile",
        "--durations=40",
        f"--junitxml={raw_junit.resolve()}",
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    operation = parser.add_mutually_exclusive_group(required=True)
    operation.add_argument("--ordinal", type=int, choices=range(1, 6))
    operation.add_argument("--verify", action="store_true")
    parser.add_argument("--output-dir", type=Path, default=Path("tui-diagnostics"))
    args = parser.parse_args(argv)
    raw_expected = os.environ.get("TAUT_TUI_REPETITIONS", "1")
    if raw_expected not in {"1", "2", "3", "4", "5"}:
        parser.error("TAUT_TUI_REPETITIONS must be one of 1, 2, 3, 4, 5")
    expected = int(raw_expected)
    if args.ordinal is not None and args.ordinal > expected:
        parser.error("ordinal exceeds the requested repetitions")
    try:
        if args.verify:
            verify_repetitions(args.output_dir, expected)
            return 0
        return run_repetition(
            None,
            args.output_dir,
            args.ordinal,
        )
    except (OSError, ValueError) as exc:
        print(f"TUI evidence failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
