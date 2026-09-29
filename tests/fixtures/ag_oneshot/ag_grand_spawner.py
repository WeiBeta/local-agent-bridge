"""Spawn a pipe-holding grandchild, then exit; the grandchild never self-exits.

The grandchild inherits the stdout pipe write end, so after this child exits
the pipe has no EOF until the capture's Job channel reclaims the grandchild
(probe P4 shape).
"""

from __future__ import annotations

import os
import subprocess
import sys


def main() -> int:
    fixture_dir = os.path.dirname(os.path.abspath(__file__))
    child_script = os.path.join(fixture_dir, "ag_child.py")
    grand = subprocess.Popen(
        [sys.executable, child_script, "sleep", "300", "GRAND-ALIVE"],
        stdout=sys.stdout,
        stderr=subprocess.DEVNULL,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    sys.stdout.write(f"GRAND-PID {grand.pid}\n")
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
