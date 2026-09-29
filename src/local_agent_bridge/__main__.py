"""Console entry points for the Local Agent Bridge preview distribution."""

from __future__ import annotations

from local_agent_bridge.h3_mcp import h3_server


def main_h3() -> None:
    """Run the four-tool H3 MCP server without non-protocol stdout writes."""
    h3_server.run()


def main_bridge() -> None:
    """Run the bounded local source-slice bridge CLI."""
    from local_agent_bridge.cli import main

    raise SystemExit(main())


if __name__ == "__main__":
    main_h3()
