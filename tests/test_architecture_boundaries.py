from __future__ import annotations

from pathlib import Path

import pytest
from taut_summon._control import _ControlReactor

from taut._broker_retry import is_transient_broker_error
from taut.watcher import (
    REACTOR_LIFECYCLE_METHODS,
    BaseReactor,
    TautWatcher,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PACKAGE_ROOTS = (
    PROJECT_ROOT / "taut",
    PROJECT_ROOT / "extensions" / "taut_pg" / "taut_pg",
    PROJECT_ROOT / "extensions" / "taut_summon" / "taut_summon",
)

pytestmark = pytest.mark.shared


def test_production_code_uses_public_simplebroker_surface_only() -> None:
    offenders: list[str] = []

    for root in PACKAGE_ROOTS:
        for path in sorted(root.rglob("*.py")):
            text = path.read_text(encoding="utf-8")
            for needle in (
                "simplebroker._",
                'getattr(broker, "_',
                "broker._runner",
                "broker._retrieve",
            ):
                if needle in text:
                    offenders.append(f"{path.relative_to(PROJECT_ROOT)}: {needle}")

    assert offenders == []


@pytest.mark.parametrize("reactor_type", [TautWatcher, _ControlReactor])
def test_first_party_reactors_inherit_guarded_lifecycle_templates(
    reactor_type: type[BaseReactor],
) -> None:
    for method_name in REACTOR_LIFECYCLE_METHODS:
        assert getattr(reactor_type, method_name) is getattr(BaseReactor, method_name)


def test_legacy_retry_import_shim_fails_closed() -> None:
    with pytest.raises(RuntimeError, match="upgrade taut-summon"):
        is_transient_broker_error(RuntimeError("database is locked"))
