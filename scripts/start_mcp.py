#!/usr/bin/env python
"""Launch the trading-mcp stdio server, ensuring its one setup-requiring
dependency -- the Playwright Chromium browser -- is present first.

Chromium is what mints Reddit's loid cookie and drives the CBOE/AAII/
Morningstar scrapers. Without it those tools degrade (the dependency
middleware blocks the Reddit tools outright). ``playwright install chromium``
is idempotent: a fast no-op when the pinned revision is already on disk, a
download otherwise -- so it's safe to run on every startup.

stdout is the MCP JSON-RPC channel, so the installer's progress output goes
to stderr (where the client logs it) to avoid corrupting the protocol.

This wrapper is written in Python rather than a shell script so a single
``.mcp.json`` entry works identically on Windows, macOS, and Linux. It is
meant to be invoked inside the trading-mcp uv environment, e.g.::

    uv run --package trading-mcp python scripts/start_mcp.py

so ``playwright`` and ``trading-mcp`` are already on PATH.
"""

import os
import subprocess
import sys

# Repo root is the parent of this script's directory; some server-side
# relative paths assume cwd is the project root.
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)

# Ensure Chromium is present. Route installer output to stderr so it never
# lands on the JSON-RPC stdout channel.
subprocess.run(
    ["playwright", "install", "chromium"],
    stdout=sys.stderr,
    check=True,
)

# Hand off to the server. We use a child process (inheriting this process's
# stdin/stdout/stderr) rather than os.exec* because exec is emulated on
# Windows and breaks stdio pipe inheritance for the MCP client.
result = subprocess.run(["trading-mcp"])
sys.exit(result.returncode)
