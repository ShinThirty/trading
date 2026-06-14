"""Tradier streaming-market-data transport: HTTP session create + WebSocket.

Tradier streaming is a two-step handshake: POST a session to get a short-lived
``sessionid`` (~5 min to connect), then open a WebSocket and send a subscribe
frame referencing it. Messages arrive as line-delimited JSON. This client owns
that handshake plus an auto-reconnect loop that re-creates the session on drop.

Important: streaming is **production-only** — the Tradier sandbox serves 15-min
delayed data and cannot stream (exchange restriction), so a sandbox token 401s
on session-create. This client always targets ``api.tradier.com`` / ``ws.tradier.com``
and treats 401/403 as fatal rather than spinning on backoff.

The wire parsing (``parse_tradier_event`` / ``parse_message``) is pure and unit-
tested; only ``stream`` / ``_create_session`` touch the network.
"""

import asyncio
import json
from collections.abc import AsyncIterator

import httpx
import websockets
from websockets.exceptions import WebSocketException

from trading_clients.market_stream import MarketEvent, Quote, TimeSale, Trade

SESSION_URL = "https://api.tradier.com/v1/markets/events/session"
WS_URL = "wss://ws.tradier.com/v1/markets/events"
DEFAULT_FILTERS = ("quote", "trade", "timesale")


def _f(value: object) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str) and value:
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _i(value: object) -> int | None:
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str) and value:
        try:
            return int(value)
        except ValueError:
            try:
                return int(float(value))
            except ValueError:
                return None
    return None


def _ms(*values: object) -> int | None:
    nums = [n for n in (_i(v) for v in values) if n is not None]
    return max(nums) if nums else None


def parse_tradier_event(payload: dict) -> MarketEvent | None:
    """Map one parsed Tradier streaming JSON object to a neutral market event.

    Returns ``None`` for events we don't model (summary, unknown types) or for
    malformed payloads (missing symbol / price).
    """
    symbol = payload.get("symbol")
    if not symbol:
        return None
    etype = payload.get("type")

    if etype == "quote":
        return Quote(
            symbol=symbol,
            bid=_f(payload.get("bid")),
            ask=_f(payload.get("ask")),
            bid_size=_i(payload.get("bidsz")),
            ask_size=_i(payload.get("asksz")),
            ms=_ms(payload.get("biddate"), payload.get("askdate")),
        )
    if etype in ("trade", "tradex"):
        price = _f(payload.get("price"))
        if price is None:
            return None
        return Trade(
            symbol=symbol,
            price=price,
            size=_i(payload.get("size")),
            ms=_i(payload.get("date")),
        )
    if etype == "timesale":
        last = _f(payload.get("last"))
        if last is None:
            return None
        return TimeSale(
            symbol=symbol,
            price=last,
            size=_i(payload.get("size")),
            bid=_f(payload.get("bid")),
            ask=_f(payload.get("ask")),
            ms=_i(payload.get("date")),
        )
    return None


def parse_message(message: str | bytes) -> list[MarketEvent]:
    """Parse one WebSocket frame (possibly several line-delimited JSON objects)."""
    text = message.decode() if isinstance(message, bytes) else message
    events: list[MarketEvent] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        event = parse_tradier_event(payload)
        if event is not None:
            events.append(event)
    return events


class TradierStreamClient:
    """Owns the Tradier session handshake + an auto-reconnecting WebSocket stream."""

    def __init__(self, api_token: str) -> None:
        self._token = api_token
        self._http = httpx.AsyncClient(timeout=15)

    async def close(self) -> None:
        await self._http.aclose()

    async def _create_session(self) -> str:
        resp = await self._http.post(
            SESSION_URL,
            headers={"Authorization": f"Bearer {self._token}", "Accept": "application/json"},
        )
        resp.raise_for_status()
        data = resp.json()
        try:
            return data["stream"]["sessionid"]
        except (KeyError, TypeError) as exc:
            raise RuntimeError(
                f"Tradier streaming session response missing sessionid: {data!r}. "
                "Streaming needs a PRODUCTION Tradier token — the sandbox cannot stream."
            ) from exc

    async def stream(
        self,
        symbols: list[str],
        filters: tuple[str, ...] = DEFAULT_FILTERS,
        *,
        max_backoff: float = 30.0,
    ) -> AsyncIterator[MarketEvent]:
        """Yield neutral market events, reconnecting (with a fresh session) on drop.

        Raises on a 401/403 session-create — a bad or sandbox token is a config
        error, not a transient fault, so we surface it instead of looping.
        """
        backoff = 1.0
        while True:
            try:
                sessionid = await self._create_session()
                async with websockets.connect(WS_URL, ping_interval=15) as ws:
                    await ws.send(
                        json.dumps(
                            {
                                "symbols": symbols,
                                "sessionid": sessionid,
                                "filter": list(filters),
                                "linebreak": True,
                                "validOnly": True,
                                "advancedDetails": False,
                            }
                        )
                    )
                    backoff = 1.0  # clean connect — reset backoff
                    async for message in ws:
                        for event in parse_message(message):
                            yield event
            except asyncio.CancelledError:
                raise
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code in (401, 403):
                    raise  # fatal: bad/sandbox token — don't spin on backoff
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, max_backoff)
            except (
                httpx.TransportError,
                OSError,
                TimeoutError,
                WebSocketException,
            ):
                # transient transport faults (drop, reset, timeout) — reconnect on backoff
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, max_backoff)
