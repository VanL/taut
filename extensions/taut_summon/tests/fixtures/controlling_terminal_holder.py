"""Own one PTY master until this process is killed by the lifecycle test."""

from __future__ import annotations

import os
import signal
import sys

from taut_summon._process_domain_posix import spawn_process


def main() -> None:
    provider_script, pid_log = sys.argv[1:]
    master_fd, slave_fd = os.openpty()
    try:
        spawned = spawn_process(
            (sys.executable, provider_script, pid_log),
            stdin=slave_fd,
            stdout=slave_fd,
            stderr=slave_fd,
            controlling_terminal=True,
        )
    finally:
        os.close(slave_fd)
    print(spawned.process.pid, flush=True)
    signal.pause()
    os.close(master_fd)


if __name__ == "__main__":
    main()
