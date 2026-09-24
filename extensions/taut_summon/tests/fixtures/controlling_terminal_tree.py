"""Block a provider leader and one foreground descendant on a real tty."""

from __future__ import annotations

import json
import os
import signal
import sys


def record(path: str, role: str) -> None:
    payload = json.dumps({"pid": os.getpid(), "role": role}) + "\n"
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    try:
        os.write(fd, payload.encode())
    finally:
        os.close(fd)


def main() -> None:
    pid_log = sys.argv[1]
    descendant = os.fork()
    if descendant == 0:
        record(pid_log, "descendant")
        signal.pause()
        raise AssertionError("signal.pause returned")
    record(pid_log, "leader")
    signal.pause()
    raise AssertionError("signal.pause returned")


if __name__ == "__main__":
    main()
