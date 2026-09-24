"""Prove a descendant that starts a new session has no controlling tty."""

from __future__ import annotations

import json
import os
import sys


def main() -> None:
    result = sys.argv[1]
    child = os.fork()
    if child == 0:
        os.setsid()
        try:
            tty_fd = os.open("/dev/tty", os.O_RDWR)
        except OSError:
            opened = False
        else:
            opened = True
            os.close(tty_fd)
        with open(result, "w", encoding="utf-8") as handle:
            json.dump({"opened_dev_tty": opened}, handle)
        os._exit(0)
    _, status = os.waitpid(child, 0)
    raise SystemExit(os.waitstatus_to_exitcode(status))


if __name__ == "__main__":
    main()
