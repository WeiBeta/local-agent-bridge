"""Combined console entry for the bounded local source-slice bridge.

Eight subcommands: ``prepare``, ``collect`` and ``plan`` come from the slice
workspace module, ``run`` from the single-run module, two fixed session
commands from this entry, ``shadow`` routes to the offline replay module and
``cursor`` to the fixed Cursor call. The commands keep their own parsers; this entry
only routes the first token. There is no pass
through for arbitrary commands, models, URLs, paths or permission rules, and the
tool is not an OS sandbox.
"""

from __future__ import annotations

import sys

from local_agent_bridge.bridge import slice_run, slice_workspace
from local_agent_bridge.capture.keys import SessionKeyError, initialize_key
from local_agent_bridge.capture.retention import StorageError, peek_status

SUBCOMMANDS = (
    "prepare",
    "collect",
    "plan",
    "run",
    "session-status",
    "session-key-init",
    "shadow",
    "cursor",
)

USAGE = """usage: local-agent-bridge <command> [options]

Bounded local source-slice bridge (Windows 11). Commands:

  prepare   copy an explicit source list out of one local Git commit
  collect   report the editable diff of one task root (read-only)
  plan      print the fixed host-run plan for one untouched task root (read-only)
  run       preflight (default) or execute exactly one fixed local CLI run
  session-status  read-only file-length use of sessions and shadow domains
  session-key-init  explicitly create this product's Windows session key
  shadow    offline fingerprint, snapshot, replay or comparison of sealed bundles
  cursor    preflight (default) or execute one fixed Cursor CLI call

The Bridge commands, shadow and cursor have their own ``--help``; session commands take no options.
Current limits:

  * only existing text files can be prepared; added or deleted files are refused
  * one fixed local CLI invocation with fixed argv, model and effort
  * the caller cannot pass an argv, a model or permission rules
  * run captures accessible input and raw stdout/stderr as encrypted frames
  * this tool is not an OS sandbox and grants no authority
"""


def main(argv: list[str] | None = None) -> int:
    """Route to the owning module's own parser; every other input is refused."""
    arguments = list(sys.argv[1:] if argv is None else argv)
    if not arguments or arguments[0] in {"-h", "--help"}:
        print(USAGE, end="")
        return 0
    command = arguments[0]
    if command in {"prepare", "collect", "plan"}:
        return slice_workspace.main(arguments)
    if command == "run":
        return slice_run.main(arguments)
    if command == "shadow":
        from local_agent_bridge.shadow import replay

        return replay.main(arguments[1:])
    if command == "cursor":
        from local_agent_bridge.bridge import cursor_run

        return cursor_run.main(arguments[1:])
    if command == "session-status" and len(arguments) == 1:
        try:
            print(
                slice_run._canonical_json(
                    {"sessions": peek_status("sessions"), "shadow": peek_status("shadow")}
                ).decode()
            )
        except (StorageError, OSError):
            print("local-agent-bridge: session status unavailable", file=sys.stderr)
            return 2
        return 0
    if command == "session-key-init" and len(arguments) == 1:
        try:
            created = initialize_key()
        except SessionKeyError as error:
            print("local-agent-bridge: " + str(error), file=sys.stderr)
            return 2
        print(slice_run._canonical_json({"session_key_created": created}).decode())
        return 0
    print("local-agent-bridge: unknown command: " + command, file=sys.stderr)
    print(USAGE, end="", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
