#!/usr/bin/env bash
# Launch the trading-mcp stdio server, ensuring its one setup-requiring
# dependency — the Playwright Chromium browser — is present first.
#
# Chromium is what mints Reddit's loid cookie and drives the CBOE/AAII/
# Morningstar scrapers. Without it those tools degrade (the dependency
# middleware blocks the Reddit tools outright). `playwright install chromium`
# is idempotent: a fast no-op when the pinned revision is already on disk, a
# download otherwise — so it's safe to run on every startup.
#
# stdout is the MCP JSON-RPC channel, so the installer's progress output goes
# to stderr (where the client logs it) to avoid corrupting the protocol.
set -euo pipefail

cd "$(dirname "$0")/.."

uv run --package trading-mcp playwright install chromium >&2

exec uv run --package trading-mcp trading-mcp
