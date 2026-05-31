"""Tool dependency declarations + the middleware that enforces them.

A *dependency* is an external resource a tool can't function without — e.g.
``playwright`` (the shared Chromium that mints Reddit's loid cookie). A tool
declares its dependencies in its ``meta`` (built via :func:`depends`). One
:class:`DependencyMiddleware` inspects every tool call: if a declared
dependency is degraded it raises ``ToolError`` so the call returns a clean,
actionable message instead of an opaque downstream failure (e.g. a Reddit 403).

Only hard dependencies are modelled. A tool that still does something useful
without a resource — get_market_regime drops one sentiment input but still
returns a verdict; get_earnings_transcript falls back to Motley Fool — simply
doesn't declare it.

Dependency health lives in a :class:`DependencyRegistry` built once at lifespan
startup and stashed in the lifespan context. Absence means healthy — only
failures are recorded (see ``server.py``'s Playwright except block). This stays
in trading-mcp so trading-clients remains MCP-free.

Reference :class:`Dependency` members for the keys — never inline the raw
strings at a tool's call site.
"""

from enum import StrEnum
from typing import Any

from fastmcp import Context
from fastmcp.exceptions import ToolError
from fastmcp.server.middleware import CallNext, Middleware, MiddlewareContext
from fastmcp.tools import ToolResult
from mcp import types as mt

# Lifespan-context key under which the registry is stashed.
DEPENDENCIES_KEY = "dependencies"

# Meta key under which a tool records its declared dependencies.
_REQUIRES_KEY = "requires"


class Dependency(StrEnum):
    """Global registry of dependency keys — the external resources tools rely
    on. Add a member here when a new resource gets health tracking; reference
    members at call sites, never the raw strings."""

    PLAYWRIGHT = "playwright"


def depends(*deps: Dependency) -> dict[str, Any]:
    """Build a tool's ``meta`` declaring the dependencies it can't run without.

    If any is degraded at call time, the middleware aborts the call with a
    clean message rather than letting it fail downstream.

        @mcp.tool(meta=depends(Dependency.PLAYWRIGHT))
    """
    return {_REQUIRES_KEY: [d.value for d in deps]}


class DependencyRegistry:
    """Maps each degraded dependency to its reason. Absence ⇒ healthy."""

    def __init__(self) -> None:
        self._degraded: dict[str, str] = {}

    def degrade(self, dep: Dependency, reason: str) -> None:
        self._degraded[dep.value] = reason

    def reason(self, dep: str) -> str | None:
        """The degrade reason, or None if the dependency is healthy."""
        return self._degraded.get(dep)


def _registry(ctx: Context) -> DependencyRegistry | None:
    rc = ctx.request_context
    if rc is None:
        return None
    return rc.lifespan_context.get(DEPENDENCIES_KEY)


class DependencyMiddleware(Middleware):
    """Blocks a tool call with a clean message when a dependency it declared
    via :func:`depends` is degraded."""

    async def on_call_tool(
        self,
        context: MiddlewareContext[mt.CallToolRequestParams],
        call_next: CallNext[mt.CallToolRequestParams, ToolResult],
    ) -> ToolResult:
        fctx = context.fastmcp_context
        registry = _registry(fctx) if fctx is not None else None
        if fctx is not None and registry is not None:
            name = context.message.name
            tool = await fctx.fastmcp.get_tool(name)
            meta = (tool.meta or {}) if tool is not None else {}
            for dep in meta.get(_REQUIRES_KEY, []):
                reason = registry.reason(dep)
                if reason is not None:
                    raise ToolError(f"{name} unavailable — '{dep}' is degraded. {reason}")
        return await call_next(context)
