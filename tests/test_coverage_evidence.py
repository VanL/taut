from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest
from coverage import CoverageData

pytestmark = pytest.mark.sqlite_only

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = PROJECT_ROOT / "bin" / "verify-coverage-evidence.py"


def _load_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "verify_coverage_evidence", SCRIPT_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _marker_lines(module: ModuleType) -> dict[str, set[int]]:
    return {
        str((PROJECT_ROOT / relative).resolve()): {
            module._marker_line(PROJECT_ROOT / relative, marker)
        }
        for relative, marker in module.REQUIRED_MARKERS.items()
    }


def test_named_coverage_evidence_requires_every_marker(tmp_path: Path) -> None:
    module = _load_module()
    data_file = tmp_path / ".coverage"
    lines = _marker_lines(module)
    omitted = str(
        (PROJECT_ROOT / "extensions/taut_summon/taut_summon/_control.py").resolve()
    )
    data = CoverageData(basename=str(data_file))
    data.add_lines({path: value for path, value in lines.items() if path != omitted})
    data.write()

    missing = module.missing_evidence(data_file)

    assert len(missing) == 1
    assert "taut_summon/_control.py" in missing[0]
    assert "self._reconcile_audit_threads()" in missing[0]


def test_named_coverage_evidence_accepts_all_markers(tmp_path: Path) -> None:
    module = _load_module()
    data_file = tmp_path / ".coverage"
    data = CoverageData(basename=str(data_file))
    data.add_lines(_marker_lines(module))
    data.write()

    assert module.missing_evidence(data_file) == []
