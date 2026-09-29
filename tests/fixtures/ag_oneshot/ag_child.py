"""Bounded offline fixture child for AG oneshot capture tests.

Every mode is tiny and time-bounded. The long-sleep modes never self-exit,
so successful reclamation can only be proven by the capture's own Job
channel, never by the fixture conveniently dying on its own.
"""

from __future__ import annotations

import sys
import time


def pattern(length: int) -> bytes:
    return bytes((index * 31 + 7) % 256 for index in range(length))


def main(argv: list[str]) -> int:
    if not argv:
        return 2
    mode = argv[0]
    if mode == "quick":
        exit_code, stdout_length, stderr_length, stdin_mark = (
            int(argv[1]),
            int(argv[2]),
            int(argv[3]),
            argv[4] == "1",
        )
        if stdin_mark:
            first = sys.stdin.buffer.read(1)
            sys.stdout.buffer.write(b"STDIN-EOF:" + (b"1" if first else b"0"))
        sys.stdout.buffer.write(pattern(stdout_length))
        sys.stderr.buffer.write(pattern(stderr_length))
        sys.stdout.buffer.flush()
        sys.stderr.buffer.flush()
        return exit_code
    if mode == "flood_exit":
        exit_code, stdout_length, stderr_length = int(argv[1]), int(argv[2]), int(argv[3])
        sys.stdout.buffer.write(pattern(stdout_length))
        sys.stderr.buffer.write(pattern(stderr_length))
        sys.stdout.buffer.flush()
        sys.stderr.buffer.flush()
        return exit_code
    if mode == "flood_sleep":
        stdout_length, stderr_length, sleep_seconds = (
            int(argv[1]),
            int(argv[2]),
            float(argv[3]),
        )
        sys.stdout.buffer.write(pattern(stdout_length))
        sys.stderr.buffer.write(pattern(stderr_length))
        sys.stdout.buffer.flush()
        sys.stderr.buffer.flush()
        time.sleep(sleep_seconds)
        return 0
    if mode == "sleep":
        sleep_seconds = float(argv[1])
        marker = argv[2] if len(argv) > 2 else None
        if marker is not None:
            sys.stdout.write(marker + "\n")
            sys.stdout.flush()
        time.sleep(sleep_seconds)
        return 0
    if mode == "raw_hex":
        stdout_bytes = bytes.fromhex(argv[1])
        stderr_bytes = bytes.fromhex(argv[2])
        exit_code = int(argv[3])
        sys.stdout.buffer.write(stdout_bytes)
        sys.stderr.buffer.write(stderr_bytes)
        sys.stdout.buffer.flush()
        sys.stderr.buffer.flush()
        return exit_code
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
