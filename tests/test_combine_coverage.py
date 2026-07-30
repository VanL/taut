from __future__ import annotations

import importlib.util
import re
import subprocess
import sys
import warnings
from pathlib import Path
from types import ModuleType

import pytest
from coverage import Coverage, CoverageData
from coverage.exceptions import CoverageWarning

pytestmark = pytest.mark.sqlite_only

PROJECT_ROOT = Path(__file__).resolve().parents[1]
COMBINER = PROJECT_ROOT / "bin" / "combine-coverage.py"


def _load_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("combine_coverage", COMBINER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_populated_shard(path: Path) -> None:
    data = CoverageData(basename=str(path))
    data.add_lines({str((PROJECT_ROOT / "taut" / "__main__.py").resolve()): {1}})
    data.write()


def _write_empty_shard(path: Path) -> None:
    coverage = Coverage(data_file=str(path), config_file=False)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", CoverageWarning)
        coverage.start()
        coverage.stop()
        coverage.save()


def test_combine_coverage_rejects_directory_without_shards(tmp_path: Path) -> None:
    module = _load_module()
    shard_dir = tmp_path / "shards"
    shard_dir.mkdir()

    with pytest.raises(module.CoverageCombineError, match=re.escape(str(shard_dir))):
        module.combine_coverage(shard_dir, tmp_path / ".coverage")


def test_combine_coverage_rejects_zero_byte_before_opening_any_shard(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()
    shard_dir = tmp_path / "shards"
    shard_dir.mkdir()
    _write_populated_shard(shard_dir / ".coverage.a-valid")
    zero_byte = shard_dir / ".coverage.z-zero"
    zero_byte.touch()

    def unexpected_read(self: CoverageData) -> None:
        raise AssertionError("CoverageData.read() ran before zero-byte validation")

    monkeypatch.setattr(module.CoverageData, "read", unexpected_read)

    with pytest.raises(module.CoverageCombineError, match=re.escape(str(zero_byte))):
        module.combine_coverage(shard_dir, tmp_path / ".coverage")


def test_combine_coverage_rejects_every_unreadable_nonzero_shard_before_combine(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()
    shard_dir = tmp_path / "shards"
    shard_dir.mkdir()
    _write_populated_shard(shard_dir / ".coverage.a-valid")
    unreadable = shard_dir / ".coverage.z-unreadable"
    unreadable.write_bytes(b"not a Coverage data file")

    def unexpected_combine(
        self: Coverage,
        data_paths: list[str] | None = None,
        strict: bool = False,
        keep: bool = False,
    ) -> None:
        raise AssertionError("combine ran before every shard was validated")

    monkeypatch.setattr(module.Coverage, "combine", unexpected_combine)

    with pytest.raises(module.CoverageCombineError, match=re.escape(str(unreadable))):
        module.combine_coverage(shard_dir, tmp_path / ".coverage")


def test_combine_coverage_accepts_populated_and_empty_shards_without_warning(
    tmp_path: Path,
) -> None:
    module = _load_module()
    shard_dir = tmp_path / "shards"
    nested_dir = shard_dir / "nested"
    nested_dir.mkdir(parents=True)
    populated = shard_dir / ".coverage.populated"
    empty = nested_dir / ".coverage.empty"
    _write_populated_shard(populated)
    _write_empty_shard(empty)
    output = tmp_path / ".coverage"

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        module.combine_coverage(shard_dir, output)

    assert [
        warning for warning in caught if issubclass(warning.category, CoverageWarning)
    ] == []
    combined = CoverageData(basename=str(output))
    combined.read()
    assert combined.lines(str((PROJECT_ROOT / "taut" / "__main__.py").resolve())) == [1]
    assert populated.exists()
    assert empty.exists()


def test_combine_coverage_promotes_combine_warning_to_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()
    shard_dir = tmp_path / "shards"
    shard_dir.mkdir()
    _write_populated_shard(shard_dir / ".coverage.populated")

    def warn_during_combine(
        self: Coverage,
        data_paths: list[str] | None = None,
        strict: bool = False,
        keep: bool = False,
    ) -> None:
        assert data_paths == [str(shard_dir)]
        assert strict is True
        assert keep is True
        warnings.warn("forced combine warning", CoverageWarning, stacklevel=2)

    monkeypatch.setattr(module.Coverage, "combine", warn_during_combine)

    with pytest.raises(module.CoverageCombineError, match="forced combine warning"):
        module.combine_coverage(shard_dir, tmp_path / ".coverage")


def test_combine_coverage_cli_saves_requested_output(tmp_path: Path) -> None:
    shard_dir = tmp_path / "shards"
    shard_dir.mkdir()
    shard = shard_dir / ".coverage.populated"
    _write_populated_shard(shard)
    output = tmp_path / ".coverage"

    result = subprocess.run(
        [
            sys.executable,
            str(COMBINER),
            str(shard_dir),
            "--output",
            str(output),
        ],
        cwd=PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert output.exists()
    assert shard.exists()
    assert result.stderr == ""


def test_combine_coverage_cli_contains_bad_input_without_traceback(
    tmp_path: Path,
) -> None:
    shard_dir = tmp_path / "shards"
    shard_dir.mkdir()
    unreadable = shard_dir / ".coverage.unreadable"
    unreadable.write_bytes(b"not a Coverage data file")

    result = subprocess.run(
        [
            sys.executable,
            str(COMBINER),
            str(shard_dir),
            "--output",
            str(tmp_path / ".coverage"),
        ],
        cwd=PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 2
    assert str(unreadable) in result.stderr
    assert "Traceback" not in result.stderr
    assert not (tmp_path / ".coverage").exists()
