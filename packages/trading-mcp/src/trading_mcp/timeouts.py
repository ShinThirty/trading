"""Per-tool execution timeout: the middleware + the meta helper tools use to
override it.

Every tool call is bounded by a wall-clock budget so a wedged provider HTTP
call, a stalled yfinance worker (offloaded to a thread, no native timeout), or
a hung Playwright scrape returns a clean ``ToolError`` instead of hanging the
MCP session indefinitely. A tool that legitimately runs long (PDF download +
parse, option backtest, Playwright transcript) raises its own budget via
``meta=timeout(seconds)`` — combine with :func:`depends` by dict-spreading both.

This is only the *server-side* half. ``asyncio.wait_for`` runs on the same
event loop, so it can only fire for hangs that yield to it (awaited I/O,
``to_thread`` offloads) — not a pure event-loop-blocking call, and not a wedged
stdio transport. The client (Claude Code) enforces ``MCP_TOOL_TIMEOUT``
independently, which is the only boundary that survives a dead server. Belt and
suspenders: set the client budget above the largest server budget so this
middleware's named error wins for ordinary hangs, and the client timeout is the
backstop for transport stalls.

Note ``wait_for`` cancels the awaitable but cannot kill a ``to_thread`` worker
(Python can't kill threads) — the tool returns promptly and frees the session,
but the orphaned thread runs to completion on its own.
"""

import asyncio
from typing import Any

from fastmcp.exceptions import ToolError
from fastmcp.server.middleware import CallNext, Middleware, MiddlewareContext
from fastmcp.tools import ToolResult
from mcp import types as mt

# Meta key under which a tool records a custom per-call timeout (seconds).
_TIMEOUT_KEY = "timeout_s"

# Default per-call budget for any tool that doesn't override it.
DEFAULT_TIMEOUT_S = 120.0


def timeout(seconds: float) -> dict[str, Any]:
    """Build a tool's ``meta`` raising its per-call timeout above the default.

    Combine with :func:`trading_mcp.dependencies.depends` via dict-spread when a
    tool needs both::

        @mcp.tool(meta={**depends(Dependency.PLAYWRIGHT), **timeout(180)})
    """
    return {_TIMEOUT_KEY: seconds}


class TimeoutMiddleware(Middleware):
    """Bounds every tool call to a wall-clock budget. A tool that exceeds it
    aborts with a clean ``ToolError`` naming the tool, instead of hanging the
    session. Tools override the default via ``meta=timeout(seconds)``."""

    def __init__(self, default_s: float = DEFAULT_TIMEOUT_S) -> None:
        self._default_s = default_s

    async def on_call_tool(
        self,
        context: MiddlewareContext[mt.CallToolRequestParams],
        call_next: CallNext[mt.CallToolRequestParams, ToolResult],
    ) -> ToolResult:
        budget = self._default_s
        fctx = context.fastmcp_context
        if fctx is not None:
            tool = await fctx.fastmcp.get_tool(context.message.name)
            meta = (tool.meta or {}) if tool is not None else {}
            budget = meta.get(_TIMEOUT_KEY, self._default_s)
        try:
            return await asyncio.wait_for(call_next(context), budget)
        except TimeoutError:
            raise ToolError(
                f"{context.message.name} timed out after {budget:.0f}s — the upstream "
                "provider or scrape didn't respond. Retry, or try again shortly."
            ) from None
