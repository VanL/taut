"""Parent containment for a mutant that intentionally freezes its child loop."""

from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest


@pytest.mark.parametrize("block_loop", [False, True])
def test_headless_lease_keeps_the_pilot_live_and_elicits_loop_blocking(
    tmp_path: Path, block_loop: bool
) -> None:
    child = Path(__file__).with_name("_lease_probe_child.py")
    root = child.resolve().parents[3]
    env = {
        **os.environ,
        "PYTHONPATH": os.pathsep.join((str(root), os.environ.get("PYTHONPATH", ""))),
    }
    env.pop("TAUT_TUI_PHASE_DIR", None)
    phases: queue.Queue[str | None] = queue.Queue()
    stderr = tmp_path / "child-stderr.txt"
    with stderr.open("w", encoding="utf-8") as errors:
        process = subprocess.Popen(
            [
                sys.executable,
                str(child),
                str(tmp_path),
                "block" if block_loop else "thread",
            ],
            cwd=root,
            env=env,
            stdout=subprocess.PIPE,
            stderr=errors,
            text=True,
            encoding="utf-8",
        )
        assert process.stdout is not None

        def read_phases() -> None:
            assert process.stdout is not None
            for line in process.stdout:
                phases.put(line.strip())
            phases.put(None)

        reader = threading.Thread(
            target=read_phases, name="lease-probe-phases", daemon=True
        )
        reader.start()
        seen: list[str] = []
        try:
            setup_deadline = time.monotonic() + 30
            while "acquired" not in seen:
                phase = phases.get(timeout=max(0, setup_deadline - time.monotonic()))
                assert phase is not None, stderr.read_text(encoding="utf-8")
                seen.append(phase)
            assert seen.index("confirmed") < seen.index("acquired")
            if block_loop:
                # Acquisition is flushed before this watchdog starts. The
                # mutant cannot service the already queued pilot continuation.
                with pytest.raises(subprocess.TimeoutExpired):
                    process.wait(timeout=2)
                process.terminate()
            else:
                assert process.wait(timeout=15) == 0, stderr.read_text(encoding="utf-8")
        finally:
            if process.poll() is None:
                process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
            reader.join(5)
            assert not reader.is_alive()
            process.stdout.close()
        retained = [
            json.loads(line)["phase"]
            for line in (tmp_path / "phases.jsonl")
            .read_text(encoding="utf-8")
            .splitlines()
        ]
        if block_loop:
            assert retained == ["confirmed", "acquired"]
            assert process.returncode != 0
        else:
            assert retained == [
                "confirmed",
                "acquired",
                "pilot-release",
                "restored",
                "retired",
            ]
