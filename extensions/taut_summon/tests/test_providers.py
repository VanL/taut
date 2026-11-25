"""Provider registry names, lazy controller imports, and pass-through arg validation ([SUM-7.2], [SUM-13])."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from taut._constants import PER_BASENAME_NAME_POOLS

PROJECT_ROOT = Path(__file__).resolve().parents[3]


def test_agy_name_pool_registered_in_core_constants() -> None:
    assert PER_BASENAME_NAME_POOLS["agy"] == ("Agatha", "Agnes", "Agis", "Agathon")
    assert "gemini" in PER_BASENAME_NAME_POOLS


def test_provider_names_do_not_import_runtime_modules() -> None:
    code = """
import json
import sys
from taut_summon import SummonController

ctrl = SummonController()
names = ctrl.provider_names()
loaded = sorted(
    name for name in sys.modules
    if name.startswith(("simplebroker", "taut", "taut_summon"))
)
print(json.dumps({
    "names": list(names),
    "loaded": loaded,
}))
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=PROJECT_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    expected = [
        "agy",
        "claude",
        "coder",
        "codex",
        "gemini",
        "grok",
        "kimi",
        "opencode",
        "pi",
        "pty",
        "qwen",
        "scripted",
    ]
    assert payload["names"] == expected
    forbidden = (
        "simplebroker",
        "taut.client",
        "taut.state",
        "taut_summon._adapter",
        "taut_summon._control",
        "taut_summon._driver",
        "taut_summon._pty",
        "taut_summon._state",
        "taut_summon.interaction",
    )
    loaded = payload["loaded"]
    assert not [name for name in loaded if name.startswith(forbidden)]


def test_provider_names_match_adapter_registry_and_validate_provider_args() -> None:
    from taut_summon import SummonController, adapter_names
    from taut_summon._adapter import (
        AdapterError,
        get_adapter,
        validate_provider_args,
    )
    from taut_summon._pty import PtyAdapter

    assert adapter_names() == SummonController().provider_names()

    validate_provider_args("claude", ("--model", "sonnet"))
    validate_provider_args(None, ("--model", "sonnet"))
    with pytest.raises(AdapterError, match="non-empty"):
        validate_provider_args("claude", ("",))
    with pytest.raises(AdapterError, match="non-empty"):
        validate_provider_args(None, ("",))
    with pytest.raises(AdapterError, match="NUL"):
        validate_provider_args("claude", ("bad\x00arg",))
    with pytest.raises(AdapterError, match="NUL"):
        validate_provider_args(None, ("bad\x00arg",))
    with pytest.raises(AdapterError, match="scripted"):
        validate_provider_args("scripted", ("--extra",))

    base = get_adapter("claude")
    assert isinstance(base, PtyAdapter)
    extended = base.with_extra_args(
        ("--allowedTools=Bash(taut *),Bash(taut-chat *)", "--model", "opus")
    )
    assert base.argv == ("claude",)
    assert extended.argv == (
        "claude",
        "--allowedTools=Bash(taut *),Bash(taut-chat *)",
        "--model",
        "opus",
    )
