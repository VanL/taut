"""Real subprocess fixture for the debug action transport contract."""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path


def main() -> int:
    output = Path(sys.argv[1])
    if sys.argv[2:] == ["sleep"]:
        time.sleep(30)
    payload = sys.stdin.read()
    output.write_text(payload, encoding="utf-8")
    output.with_suffix(".marker").write_text(
        os.environ.get("TAUT_DEBUG_ACTION_ACTIVE", ""),
        encoding="utf-8",
    )
    output.with_suffix(".context").write_text(
        json.dumps(
            {
                "cwd": os.getcwd(),
                "probe": os.environ.get("TAUT_DEBUG_ACTION_PROBE"),
            }
        ),
        encoding="utf-8",
    )
    if sys.argv[2:] == ["noisy"]:
        print("debug action stdout must be suppressed")
        print("debug action stderr must be suppressed", file=sys.stderr)
    if sys.argv[2:] == ["nonzero"]:
        return 9
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
