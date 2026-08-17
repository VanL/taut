"""Run the real CLI after an out-of-band readiness acknowledgement."""

from __future__ import annotations

import faulthandler
import os
import socket
import subprocess
import sys
import time
from pathlib import Path


def _required_env(name: str) -> str:
    value = os.environ.pop(name, None)
    if not value:
        raise RuntimeError(f"missing CLI readiness environment: {name}")
    return value


def main() -> int:
    host = _required_env("TAUT_TEST_CLI_READY_HOST")
    port = int(_required_env("TAUT_TEST_CLI_READY_PORT"))
    token = _required_env("TAUT_TEST_CLI_READY_TOKEN")
    diagnostic_path = Path(_required_env("TAUT_TEST_CLI_DIAGNOSTIC"))
    connect_timeout = float(_required_env("TAUT_TEST_CLI_CONNECT_TIMEOUT"))

    diagnostic_delay = float(_required_env("TAUT_TEST_CLI_DIAGNOSTIC_DELAY"))
    after_ready_delay = float(os.environ.pop("TAUT_TEST_CLI_AFTER_READY_DELAY", "0"))
    with diagnostic_path.open("w", encoding="utf-8") as diagnostic:
        with socket.create_connection(
            (host, port), timeout=connect_timeout
        ) as readiness:
            readiness.sendall(f"spawned {token}\n".encode("ascii"))
            if os.environ.pop("TAUT_TEST_CLI_EXIT_BEFORE_READY", None):
                return 86
            startup_delay = float(os.environ.pop("TAUT_TEST_CLI_STARTUP_DELAY", "0"))
            if startup_delay:
                time.sleep(startup_delay)
            from taut.cli import main as taut_main

            faulthandler.dump_traceback_later(
                diagnostic_delay,
                repeat=False,
                file=diagnostic,
            )
            descendant_pid_path = os.environ.pop(
                "TAUT_TEST_CLI_DESCENDANT_PID_PATH",
                None,
            )
            if descendant_pid_path:
                descendant = subprocess.Popen(
                    [sys.executable, "-c", "import time; time.sleep(30)"],
                )
                Path(descendant_pid_path).write_text(
                    str(descendant.pid),
                    encoding="ascii",
                )
            readiness.sendall(f"ready {token}\n".encode("ascii"))

        try:
            if after_ready_delay:
                time.sleep(after_ready_delay)
            return taut_main(sys.argv[1:])
        finally:
            faulthandler.cancel_dump_traceback_later()


if __name__ == "__main__":
    raise SystemExit(main())
