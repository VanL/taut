"""Platform import contract for the shared real-terminal test helpers."""

from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

pytestmark = pytest.mark.shared


@pytest.mark.parametrize("unavailable_module", ("fcntl", "pty", "termios"))
def test_terminal_helpers_import_without_posix_modules(
    unavailable_module: str,
) -> None:
    source = textwrap.dedent(
        """
        import importlib.abc
        import sys

        # Keep the dependency's own native platform imports outside this
        # probe. Only terminal_probe's optional POSIX imports are unavailable.
        import psutil

        unavailable = sys.argv[1]
        sys.modules.pop(unavailable, None)

        class UnavailablePosixModule(importlib.abc.MetaPathFinder):
            def find_spec(self, fullname, path=None, target=None):
                if fullname == unavailable:
                    raise ModuleNotFoundError(
                        "POSIX-only import forbidden: " + fullname,
                        name=fullname,
                    )
                return None

        sys.meta_path.insert(0, UnavailablePosixModule())
        from tests.helpers.terminal_probe import (
            HostTerminal,
            PosixHostShell,
            run_terminal_child,
            strip_terminal_bytes,
        )

        assert callable(HostTerminal.open)
        assert callable(PosixHostShell.open)
        assert callable(run_terminal_child)
        assert strip_terminal_bytes(b"plain\\r\\n") == "plain\\n"
        print("terminal-helper-imported")
        """
    )
    result = subprocess.run(
        [sys.executable, "-c", source, unavailable_module],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "terminal-helper-imported"
