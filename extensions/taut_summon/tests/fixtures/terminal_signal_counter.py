"""Keep canonical ISIG input and exit after recording one terminal SIGINT."""

from __future__ import annotations

import json
import os
import signal
import sys
import termios


def main() -> None:
    interrupt_log = sys.argv[1]

    def record_interrupt(signum: int, _frame: object) -> None:
        payload = json.dumps({"signal": signum}) + "\n"
        fd = os.open(interrupt_log, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        try:
            os.write(fd, payload.encode())
        finally:
            os.close(fd)
        raise SystemExit(0)

    attrs = termios.tcgetattr(0)
    attrs[3] |= termios.ICANON | termios.ISIG
    termios.tcsetattr(0, termios.TCSANOW, attrs)
    signal.signal(signal.SIGINT, record_interrupt)
    os.write(1, b"ready\r\n")
    signal.pause()


if __name__ == "__main__":
    main()
