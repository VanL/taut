"""Hosted TUI repetition evidence, governed by the Windows root-cause plan."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.sqlite_only


def _recorder() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "record_tui_run", ROOT / "bin/record_tui_run.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_child_failure_is_preserved_with_started_and_final_evidence(
    tmp_path: Path,
) -> None:
    result = _recorder().run_repetition(
        [sys.executable, "-c", "raise SystemExit(7)"], tmp_path, 1
    )
    assert result == 7
    started = tmp_path / "run-1/started.json"
    assert started.is_file(), "child launch must leave retained start evidence"
    initial = json.loads(started.read_text())
    final = json.loads((tmp_path / "run-1/result.json").read_text())
    assert initial["state"] == "started"
    assert final["state"] == "completed"
    assert final["child_exit_code"] == 7
    assert final["exit_code"] == 7
    assert final["evidence_error"] == "missing JUnit result"
    assert final["ordinal"] == 1
    assert len(final["sha"]) == 40
    assert len(final["lock_sha256"]) == 64
    assert final["elapsed_seconds"] >= 0
    assert final["python"] and final["platform"]


def test_failure_report_drops_provider_content_from_artifact_tree(
    tmp_path: Path,
) -> None:
    secret = "provider-token-DO-NOT-UPLOAD"
    xml = (
        '<testsuites><testsuite name="pytest" tests="1" failures="1" errors="0" '
        'skipped="0" time="0.1"><testcase classname="recovery" name="test_gate" '
        f'time="0.1"><failure message="{secret}">{secret}</failure>'
        f'<system-out>{secret}</system-out><properties><property name="token" '
        f'value="{secret}"/></properties></testcase></testsuite></testsuites>'
    )
    source = (
        "import os; from pathlib import Path; "
        "report = Path(os.environ['TAUT_TUI_JUNIT_PATH']); "
        f"report.write_text({xml!r}); "
        f"print({secret!r}); raise SystemExit(7)"
    )
    assert _recorder().run_repetition([sys.executable, "-c", source], tmp_path, 1) == 7
    artifact_files = list((tmp_path / "run-1").rglob("*"))
    for path in artifact_files:
        if path.is_file():
            assert secret not in path.read_text(), (
                f"private content escaped in {path.name}"
            )
    safe = (tmp_path / "run-1/junit.xml").read_text()
    assert 'name="test_gate"' in safe
    assert "<failure" in safe
    assert "system-out" not in safe


def test_real_pytest_failure_keeps_console_but_publishes_only_safe_result(
    tmp_path: Path, capfd: pytest.CaptureFixture[str]
) -> None:
    marker = "private-gate-log-and-token"
    private_test = tmp_path / "test_private_gate.py"
    private_test.write_text(
        "def test_gate(record_property):\n"
        f"    record_property('provider-token', {marker!r})\n"
        f"    print({marker!r})\n"
        f"    assert False, {marker!r}\n"
    )
    source = (
        "import os, pytest; raise SystemExit(pytest.main(["
        f"'-c', os.devnull, '-o', 'addopts=', '-o', 'junit_logging=all', {str(private_test)!r}, "
        "'--junitxml=' + os.environ['TAUT_TUI_JUNIT_PATH']]))"
    )
    artifacts = tmp_path / "artifacts"
    assert _recorder().run_repetition([sys.executable, "-c", source], artifacts, 1) == 1
    assert marker in capfd.readouterr().out
    result = json.loads((artifacts / "run-1/result.json").read_text())
    assert result["child_exit_code"] == 1
    assert result["tests"] == result["failures"] == 1
    for path in artifacts.rglob("*"):
        if path.is_file():
            assert marker not in path.read_text()


def test_raw_report_is_outside_artifact_tree_even_when_launcher_is_interrupted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    recorder = _recorder()
    raw_paths: list[Path] = []

    def interrupted(*args: object, **kwargs: object) -> None:
        __tracebackhide__ = True
        env = kwargs["env"]
        assert isinstance(env, dict)
        raw = Path(env["TAUT_TUI_JUNIT_PATH"])
        raw_paths.append(raw)
        assert not raw.is_relative_to(tmp_path), "timeout could upload raw JUnit"
        raw.write_text("<failure>private-provider-screen</failure>")
        raise KeyboardInterrupt

    monkeypatch.setattr(
        recorder,
        "subprocess",
        SimpleNamespace(
            check_output=subprocess.check_output,
            run=interrupted,
        ),
    )
    with pytest.raises(KeyboardInterrupt):
        recorder.run_repetition([sys.executable, "-c", "pass"], tmp_path, 1)
    assert raw_paths
    assert not (tmp_path / "run-1/junit.xml").exists()


@pytest.mark.parametrize(
    "xml",
    [None, "<broken", "<testsuites/>", '<testsuite tests="0"/>'],
)
def test_zero_exit_without_valid_nonempty_junit_fails(
    tmp_path: Path, xml: str | None
) -> None:
    source = "pass"
    if xml is not None:
        source = (
            "import os; from pathlib import Path; "
            f"Path(os.environ['TAUT_TUI_JUNIT_PATH']).write_text({xml!r})"
        )
    code = _recorder().run_repetition([sys.executable, "-c", source], tmp_path, 1)
    assert code == 1, "missing or malformed result cannot qualify a repetition"
    final = json.loads((tmp_path / "run-1/result.json").read_text())
    assert final["child_exit_code"] == 0
    assert final["evidence_error"]


def _phase_fixture(kind: str) -> list[dict[str, object]]:
    phases = (
        ["navigation.source", "navigation.applied"]
        if kind == "navigation"
        else [
            "confirmation.resolved",
            "lease.acquired",
            "lease.restored",
            "lease.hold_returned",
            "provider.injected",
            "provider.consumed",
            "resource.closed",
            "provider.injected",
            "provider.consumed",
            "resource.closed",
        ]
    )
    records: list[dict[str, object]] = [
        {
            "sequence": index,
            "request": (2 if index < 8 else 3) if index >= 5 else 1,
            "phase": phase,
            "outcome": "success",
            "elapsed_s": index / 10,
            "source_dm_count": 1,
            "rendered_dm_count": 1,
        }
        for index, phase in enumerate(phases, 1)
    ]
    records.append(
        {
            "sequence": len(records) + 1,
            "request": 0,
            "phase": "test.summary",
            "outcome": "success",
            "elapsed_s": 1.0,
            "complete": True,
            "missing": [],
            "test_kind": kind,
            "python_version": "test-python",
            "platform": "test-platform",
        }
    )
    return records


def _run_evidence(
    tmp_path: Path,
    ordinal: int = 1,
    *,
    executed: int = 2,
    skipped: int = 1,
    child_code: int = 0,
) -> int:
    failed = int(child_code != 0)
    cases = "".join(
        f'<testcase name="ok-{index}" time="0.5">'
        + ("<failure/>" if failed and index == 0 else "")
        + "</testcase>"
        for index in range(executed)
    ) + "".join(
        f'<testcase name="skip-{index}" time="0.75"><skipped/></testcase>'
        for index in range(skipped)
    )
    xml = (
        f'<testsuites><testsuite tests="{executed + skipped}" skipped="{skipped}" '
        f'failures="{failed}" errors="0" time="1.25">{cases}'
        "</testsuite></testsuites>"
    )
    files = {
        kind + ".jsonl": "".join(json.dumps(row) + "\n" for row in _phase_fixture(kind))
        for kind in ("navigation", "recovery")
    }
    source = (
        "import os; from pathlib import Path; "
        "phase = Path(os.environ['TAUT_TUI_PHASE_DIR']); "
        "phase.mkdir(); "
        f"[(phase / name).write_text(text) for name, text in {files!r}.items()]; "
        f"Path(os.environ['TAUT_TUI_JUNIT_PATH']).write_text({xml!r}); "
        f"raise SystemExit({child_code})"
    )
    result = _recorder().run_repetition(
        [sys.executable, "-c", source], tmp_path, ordinal
    )
    assert isinstance(result, int)
    return result


def _successful_run(tmp_path: Path, ordinal: int = 1) -> None:
    assert _run_evidence(tmp_path, ordinal) == 0


def test_success_records_counts_durations_and_phase_directory(tmp_path: Path) -> None:
    _successful_run(tmp_path)
    result = json.loads((tmp_path / "run-1/result.json").read_text())
    assert result["tests"] == 3
    assert result["skipped"] == 1
    assert result["junit_seconds"] == 1.25
    assert result["failures"] == result["errors"] == 0
    assert result["evidence_error"] is None
    assert (tmp_path / "run-1/phases/navigation.jsonl").is_file()
    _recorder().verify_repetitions(tmp_path, 1)


@pytest.mark.parametrize("executed", [1, 3])
@pytest.mark.parametrize("child_code", [0, 7])
def test_capture_reconciles_phase_files_with_executed_tests(
    tmp_path: Path, executed: int, child_code: int
) -> None:
    code = _run_evidence(tmp_path, executed=executed, child_code=child_code)
    assert code == (child_code or 1), "partial phase coverage cannot qualify"
    result = json.loads((tmp_path / "run-1/result.json").read_text())
    assert result["child_exit_code"] == child_code
    assert result["tests"] == executed + 1
    assert result["skipped"] == 1
    assert result["failures"] == int(child_code != 0)
    assert result["phase_files"] == 2, "retain available diagnostics on failure"
    assert "phase file count" in result["evidence_error"]


@pytest.mark.parametrize("executed", [1, 3])
def test_verify_reconciles_phase_files_with_executed_tests(
    tmp_path: Path, executed: int
) -> None:
    _successful_run(tmp_path)
    directory = tmp_path / "run-1"
    junit = directory / "junit.xml"
    tree = ET.parse(junit)
    suite = tree.getroot()[0]
    if executed == 1:
        suite.remove(suite.findall("testcase")[0])
    else:
        ET.SubElement(suite, "testcase", name="unobserved", time="0")
    suite.set("tests", str(executed + 1))
    tree.write(junit)
    result_path = directory / "result.json"
    result = json.loads(result_path.read_text())
    result["tests"] = executed + 1
    result_path.write_text(json.dumps(result))
    with pytest.raises(ValueError, match="phase file count"):
        _recorder().verify_repetitions(tmp_path, 1)


@pytest.mark.parametrize("skipped", [0, 1, 3])
def test_mark_only_skips_do_not_require_phase_files(
    tmp_path: Path, skipped: int
) -> None:
    assert _run_evidence(tmp_path, skipped=skipped) == 0
    _recorder().verify_repetitions(tmp_path, 1)


@pytest.mark.parametrize(
    ("recorded_platform", "retirement", "valid"),
    [
        ("Windows-2025Server-10.0.26100-SP0", None, False),
        ("Windows-11-10.0.26100-SP0", "error", False),
        ("Windows-2025Server-10.0.26100-SP0", "success", True),
        ("Linux-6.11.0-x86_64-with-glibc2.39", None, True),
        ("macOS-15.6-arm64-arm-64bit", None, True),
    ],
)
def test_native_retirement_is_required_by_recorded_runtime_not_verifier_host(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    recorded_platform: str,
    retirement: str | None,
    valid: bool,
) -> None:
    recorder = _recorder()
    local_platform = (
        "Linux-verifier"
        if recorded_platform.startswith("Windows")
        else "Windows-verifier"
    )
    monkeypatch.setattr(
        recorder, "platform", SimpleNamespace(platform=lambda: local_platform)
    )
    for kind in ("navigation", "recovery"):
        records = _phase_fixture(kind)
        records[-1]["platform"] = recorded_platform
        if kind == "recovery" and retirement is not None:
            records.insert(
                -1,
                {
                    "request": 4,
                    "phase": "attach.retired",
                    "outcome": retirement,
                    "elapsed_s": 1.0,
                },
            )
        for sequence, record in enumerate(records, 1):
            record["sequence"] = sequence
        (tmp_path / f"{kind}.jsonl").write_text(
            "".join(json.dumps(record) + "\n" for record in records)
        )
    if valid:
        result = recorder.phase_evidence(tmp_path)
        assert result["pytest_platform"] == recorded_platform
        assert result["phase_files"] == 2
    else:
        with pytest.raises(ValueError, match="attach.retired"):
            recorder.phase_evidence(tmp_path)


@pytest.mark.parametrize(
    "contents",
    [None, "not json", "{}\n", '{"sequence":1,"phase":"recorder.tripwire"}\n'],
)
def test_verifier_rejects_missing_malformed_or_tripwire_phase_records(
    tmp_path: Path, contents: str | None
) -> None:
    _successful_run(tmp_path)
    (tmp_path / "run-1/phases/navigation.jsonl").unlink()
    if contents is not None:
        (tmp_path / "run-1/phases/test.jsonl").write_text(contents)
    with pytest.raises(ValueError, match="phase"):
        _recorder().verify_repetitions(tmp_path, 1)


@pytest.mark.parametrize("missing", ["result.json", "started.json"])
def test_verifier_rejects_timeout_or_missing_launch_record(
    tmp_path: Path, missing: str
) -> None:
    directory = tmp_path / "run-1"
    directory.mkdir()
    retained = "started.json" if missing == "result.json" else "result.json"
    (directory / retained).write_text('{"state":"started"}')
    with pytest.raises(ValueError, match="repetition 1"):
        _recorder().verify_repetitions(tmp_path, 1)


@pytest.mark.parametrize("value", ["0", "6", "1; echo injected", "1.0", " 1"])
def test_invalid_repeat_input_fails_before_launch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    monkeypatch.setenv("TAUT_TUI_REPETITIONS", value)
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "bin/record_tui_run.py"),
            "--ordinal",
            "1",
            "--output-dir",
            str(tmp_path / "unused"),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2
    assert "TAUT_TUI_REPETITIONS" in result.stderr
    assert not (tmp_path / "unused").exists()


@pytest.mark.parametrize("ordinal", ["0", "6", "-1", "not-a-number"])
def test_invalid_ordinal_fails_before_launch(tmp_path: Path, ordinal: str) -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "bin/record_tui_run.py"),
            "--ordinal",
            ordinal,
            "--output-dir",
            str(tmp_path / "unused"),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2
    assert not (tmp_path / "unused").exists()


def test_verification_cli_propagates_missing_result_failure(tmp_path: Path) -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "bin/record_tui_run.py"),
            "--verify",
            "--output-dir",
            str(tmp_path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 1
    assert "repetition 1" in result.stderr


def test_recording_cannot_overwrite_an_earlier_repetition(tmp_path: Path) -> None:
    (tmp_path / "run-1").mkdir()
    with pytest.raises(FileExistsError):
        _recorder().run_repetition([sys.executable, "-c", "pass"], tmp_path, 1)


def test_interrupted_launcher_leaves_started_record_without_false_completion(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    recorder = _recorder()

    def interrupted(*args: object, **kwargs: object) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr(
        recorder,
        "subprocess",
        SimpleNamespace(
            check_output=subprocess.check_output,
            run=interrupted,
        ),
    )
    with pytest.raises(KeyboardInterrupt):
        recorder.run_repetition([sys.executable, "-c", "pass"], tmp_path, 1)
    assert (
        json.loads((tmp_path / "run-1/started.json").read_text())["state"] == "started"
    )
    assert not (tmp_path / "run-1/result.json").exists()
    with pytest.raises(ValueError, match="repetition 1"):
        recorder.verify_repetitions(tmp_path, 1)


def test_missing_child_command_is_recorded_as_launch_error(tmp_path: Path) -> None:
    assert (
        _recorder().run_repetition([str(tmp_path / "not-installed")], tmp_path, 1)
        == 127
    )
    result = json.loads((tmp_path / "run-1/result.json").read_text())
    assert result["state"] == "launch-error"
    assert result["child_exit_code"] is None


def test_five_full_results_are_required_on_one_identity(tmp_path: Path) -> None:
    for ordinal in range(1, 6):
        _successful_run(tmp_path, ordinal)
    recorder = _recorder()
    recorder.verify_repetitions(tmp_path, 5)
    last = tmp_path / "run-5/result.json"
    result = json.loads(last.read_text())
    result["sha"] = "a" * 40
    last.write_text(json.dumps(result))
    with pytest.raises(ValueError, match="identities differ"):
        recorder.verify_repetitions(tmp_path, 5)


def test_skip_reduction_cannot_qualify_a_repetition(tmp_path: Path) -> None:
    _successful_run(tmp_path, 1)
    _successful_run(tmp_path, 2)
    directory = tmp_path / "run-2"
    junit = directory / "junit.xml"
    tree = ET.parse(junit)
    suite = tree.getroot()[0]
    suite.set("skipped", "0")
    for case in suite.findall("testcase"):
        skipped = case.find("skipped")
        if skipped is not None:
            case.remove(skipped)
    tree.write(junit)
    result_path = directory / "result.json"
    result = json.loads(result_path.read_text())
    result["skipped"] = 0
    # Give the formerly skipped case valid evidence, so this fires the distinct
    # cross-repetition skip-identity guard rather than the coverage guard.
    summary = {**_phase_fixture("navigation")[-1], "sequence": 1, "test_kind": "other"}
    (directory / "phases/formerly-skipped.jsonl").write_text(json.dumps(summary) + "\n")
    result["phase_files"] = 3
    result_path.write_text(json.dumps(result))
    with pytest.raises(ValueError, match="skips changed"):
        _recorder().verify_repetitions(tmp_path, 2)


def test_test_count_reduction_cannot_qualify_a_repetition(tmp_path: Path) -> None:
    _successful_run(tmp_path, 1)
    _successful_run(tmp_path, 2)
    # Both samples remain individually complete. Only their collection differs.
    directory = tmp_path / "run-1"
    junit = directory / "junit.xml"
    tree = ET.parse(junit)
    suite = tree.getroot()[0]
    suite.set("tests", "4")
    ET.SubElement(suite, "testcase", name="extra", time="0")
    tree.write(junit)
    result_path = directory / "result.json"
    result = json.loads(result_path.read_text())
    result["tests"] = 4
    summary = {**_phase_fixture("navigation")[-1], "sequence": 1, "test_kind": "other"}
    (directory / "phases/extra.jsonl").write_text(json.dumps(summary) + "\n")
    result["phase_files"] = 3
    result_path.write_text(json.dumps(result))
    with pytest.raises(ValueError, match="repetition identity, test count"):
        _recorder().verify_repetitions(tmp_path, 2)


@pytest.mark.parametrize("result", ["{}", "[]", "null", "not json"])
def test_malformed_final_record_cannot_qualify(tmp_path: Path, result: str) -> None:
    _successful_run(tmp_path)
    (tmp_path / "run-1/result.json").write_text(result)
    with pytest.raises(ValueError, match="repetition 1"):
        _recorder().verify_repetitions(tmp_path, 1)


@pytest.mark.parametrize("mutation", ["summary", "capacity", "generation", "missing"])
def test_phase_summary_or_required_flow_cannot_hide_incomplete_evidence(
    tmp_path: Path, mutation: str
) -> None:
    _successful_run(tmp_path)
    path = tmp_path / "run-1/phases/navigation.jsonl"
    records = _phase_fixture("navigation")
    if mutation == "summary":
        records.pop()
    elif mutation == "capacity":
        records[-1].update(complete=False, missing=["recorder.capacity"])
    elif mutation == "generation":
        records[1]["request"] = 2
    else:
        records[0]["source_dm_count"] = 0
    path.write_text("".join(json.dumps(record) + "\n" for record in records))
    with pytest.raises(ValueError, match="phase"):
        _recorder().verify_repetitions(tmp_path, 1)


def test_normal_background_error_does_not_fail_completed_required_flow(
    tmp_path: Path,
) -> None:
    _successful_run(tmp_path)
    path = tmp_path / "run-1/phases/navigation.jsonl"
    records = _phase_fixture("navigation")
    records.insert(
        0,
        {
            "phase": "background.work",
            "request": 2,
            "outcome": "error",
            "elapsed_s": 0,
            "error_type": "RuntimeError",
        },
    )
    for sequence, record in enumerate(records, 1):
        record["sequence"] = sequence
    path.write_text("".join(json.dumps(record) + "\n" for record in records))
    _recorder().verify_repetitions(tmp_path, 1)


@pytest.mark.parametrize("mutation", ["lease", "adapter", "wiring-only"])
def test_recovery_cannot_join_unrelated_request_completions(
    tmp_path: Path, mutation: str
) -> None:
    _successful_run(tmp_path)
    path = tmp_path / "run-1/phases/recovery.jsonl"
    records = _phase_fixture("recovery")
    if mutation == "lease":
        records[2]["request"] = 99
    elif mutation == "adapter":
        records[8]["request"] = 99
    else:
        for record in records:
            if record.get("request") == 3:
                record["request"] = 2
    path.write_text("".join(json.dumps(record) + "\n" for record in records))
    with pytest.raises(ValueError, match="recovery phase"):
        _recorder().verify_repetitions(tmp_path, 1)


def test_pytest_runtime_must_match_across_repetitions(tmp_path: Path) -> None:
    _successful_run(tmp_path, 1)
    _successful_run(tmp_path, 2)
    directory = tmp_path / "run-2"
    for path in (directory / "phases").glob("*.jsonl"):
        path.write_text(path.read_text().replace("test-python", "changed-python"))
    result_path = directory / "result.json"
    result = json.loads(result_path.read_text())
    result["pytest_python"] = "changed-python"
    result_path.write_text(json.dumps(result))
    with pytest.raises(ValueError, match="repetition identity"):
        _recorder().verify_repetitions(tmp_path, 2)


@pytest.mark.parametrize("mutation", ["duplicate", "navigation-order", "lease-order"])
def test_phase_evidence_rejects_duplicate_or_impossible_required_transitions(
    tmp_path: Path, mutation: str
) -> None:
    _successful_run(tmp_path)
    kind = "recovery" if mutation == "lease-order" else "navigation"
    records = _phase_fixture(kind)
    if mutation == "duplicate":
        records.insert(1, dict(records[0]))
        for index, record in enumerate(records, 1):
            record["sequence"] = index
    else:
        index = 1 if mutation == "lease-order" else 0
        records[index]["elapsed_s"] = 0.8
        records[index + 1]["elapsed_s"] = 0.2
    path = tmp_path / f"run-1/phases/{kind}.jsonl"
    path.write_text("".join(json.dumps(record) + "\n" for record in records))
    with pytest.raises(ValueError, match="phase"):
        _recorder().verify_repetitions(tmp_path, 1)


def test_consumption_before_inject_return_and_cross_thread_log_order_are_valid(
    tmp_path: Path,
) -> None:
    _successful_run(tmp_path)
    records = _phase_fixture("recovery")
    records[4]["elapsed_s"] = 0.6  # inject returned after consumed
    records[5]["elapsed_s"] = 0.5
    path = tmp_path / "run-1/phases/recovery.jsonl"
    path.write_text("".join(json.dumps(record) + "\n" for record in records))
    _recorder().verify_repetitions(tmp_path, 1)


@pytest.mark.parametrize(
    ("kind", "phase"),
    [
        ("navigation", "navigation.source"),
        ("recovery", "lease.acquired"),
        ("recovery", "confirmation.resolved"),
    ],
)
@pytest.mark.parametrize("terminal", ["error", "success"])
def test_conflicting_terminals_for_one_required_phase_cannot_qualify(
    tmp_path: Path, kind: str, phase: str, terminal: str
) -> None:
    _successful_run(tmp_path)
    records = _phase_fixture(kind)
    original = next(record for record in records if record["phase"] == phase)
    records.insert(0, {**original, "outcome": terminal})
    for index, record in enumerate(records, 1):
        record["sequence"] = index
    path = tmp_path / f"run-1/phases/{kind}.jsonl"
    path.write_text("".join(json.dumps(record) + "\n" for record in records))
    with pytest.raises(ValueError, match="duplicate terminal"):
        _recorder().verify_repetitions(tmp_path, 1)


def test_workflow_repetitions_are_sequential_bounded_and_preserve_exit() -> None:
    document = yaml.safe_load(
        (ROOT / ".github/workflows/test-tui-extension.yml").read_text()
    )
    job = document["jobs"]["tui-retained"]
    assert '{"1":35,"2":55,"3":75,"4":95,"5":115}' in job["timeout-minutes"]
    assert (
        "github.event_name == 'workflow_dispatch'" in job["env"]["TAUT_TUI_REPETITIONS"]
    )
    assert "matrix.os == 'windows-latest'" in job["env"]["TAUT_TUI_REPETITIONS"]
    steps = {step.get("name"): step for step in job["steps"]}
    for ordinal in range(1, 6):
        step = steps[f"Run Windows taut-tui repetition {ordinal}"]
        assert step["shell"] == "pwsh"
        assert step["run"].strip().endswith("exit $LASTEXITCODE")
        assert f"--ordinal {ordinal}" in step["run"]
        assert "${{" not in step["run"], "dispatch input must never enter shell code"
        assert "runner.os == 'Windows'" in step["if"]
        assert not step.get("continue-on-error", False)
        if ordinal > 1:
            assert "success()" in step["if"]
            assert f"env.TAUT_TUI_REPETITIONS >= {ordinal}" in step["if"]
            assert step["timeout-minutes"] == 20
    assert steps["Verify retained repetition evidence"]["if"] == "${{ always() }}"
    upload = steps["Upload retained TUI diagnostics"]
    assert upload["if"] == "${{ always() }}"
    assert upload["with"]["if-no-files-found"] == "error"


def test_retained_command_keeps_full_suite_lock_and_distribution(
    tmp_path: Path,
) -> None:
    command = _recorder().retained_command(tmp_path / "raw.xml")
    assert command[:16] == [
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
    ]
    assert command[-1] == f"--junitxml={tmp_path / 'raw.xml'}"


def test_tui_dispatch_bounds_repetitions_without_changing_other_events() -> None:
    document = yaml.safe_load(
        (ROOT / ".github/workflows/test-tui-extension.yml").read_text()
    )
    trigger = document[True]
    dispatch = trigger["workflow_dispatch"]
    assert isinstance(dispatch, dict), "dispatch must expose bounded Windows repeats"
    repeat = dispatch["inputs"]["windows_repeat"]
    assert repeat["type"] == "choice"
    assert repeat["default"] == "1"
    assert repeat["options"] == ["1", "2", "3", "4", "5"]
    assert trigger["workflow_call"] is None
