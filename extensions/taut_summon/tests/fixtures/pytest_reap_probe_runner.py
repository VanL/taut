"""Keep the inner pytest host alive after its fixture teardown completes."""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest


def main() -> int:
    result_path = Path(os.environ["TAUT_SUMMON_FIXTURE_REAP_RESULT"])
    returncode = pytest.main(
        [
            "-n",
            "0",
            "tests/test_pty_adapter.py::test_spawn_fake_assertion_failure_probe",
        ]
    )
    result_path.write_text(str(returncode), encoding="utf-8")
    time.sleep(10.0)
    return returncode


if __name__ == "__main__":
    raise SystemExit(main())
