"""DXLink (dxFeed) streaming-market-data transport for Tastytrade futures.

Tastytrade exposes dxFeed's DXLink WebSocket protocol. Streaming is a token +
channel handshake: fetch a short-lived streamer token (``TastyTradeClient.
get_quote_token`` → ``(token, dxlink_url)``), open the WebSocket, then walk the
DXLink state machine —

    SETUP → (AUTH_STATE UNAUTHORIZED) → AUTH → (AUTH_STATE AUTHORIZED)
          → CHANNEL_REQUEST(FEED) → (CHANNEL_OPENED) → FEED_SETUP
          → (FEED_CONFIG) → FEED_SUBSCRIPTION → FEED_DATA…

— plus a 30 s KEEPALIVE heartbeat. This client owns that handshake and an
auto-reconnect loop that re-fetches a fresh token on drop.

Because we send ``acceptEventFields`` ourselves, the server echoes each event's
COMPACT values in exactly the order we requested (see ``_FEED_FIELDS``), so the
wire parsing (``parse_dxlink_feed``) is pure and self-describing — only ``stream``
touches the network.

The token fetch surfaces a bad/expired Tastytrade OAuth token as an
``httpx.HTTPStatusError`` (401/403), treated as fatal rather than retried.
``[streaming]`` extra (``websockets``).
"""

import asyncio
import json
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

import httpx
import websockets
from websockets.exceptions import WebSocketException

from trading_clients.market_stream import MarketEvent, Quote, TimeSale, Trade

FEED_CHANNEL = 1  # client-chosen odd channel for the FEED service (0 is the control channel)
KEEPALIVE_INTERVAL = 30.0
PROTOCOL_VERSION = "0.1-trading-scalper/1.0"

# The COMPACT event layout we request — the server echoes values in exactly this order,
# with the leading "eventType"/"eventSymbol" as the first two fields of every event.
_FEED_FIELDS: dict[str, tuple[str, ...]] = {
    "Quote": ("eventType", "eventSymbol", "bidPrice", "askPrice", "bidSize", "askSize"),
    "Trade": ("eventType", "eventSymbol", "price", "size", "time"),
    "TimeAndSale": ("eventType", "eventSymbol", "price", "size", "bidPrice", "askPrice", "time"),
}

# What we subscribe to per symbol — the three tape/book event types the scalper consumes.
_EVENT_TYPES = ("Quote", "Trade", "TimeAndSale")

type QuoteTokenProvider = Callable[[], Awaitable[tuple[str, str]]]


def _f(value: object) -> float | None:
    """Parse a dxFeed numeric, mapping the "NaN" sentinel (an undefined double) to None."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str) and value and value != "NaN":
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _i(value: object) -> int | None:
    f = _f(value)
    return int(f) if f is not None else None


def parse_dxlink_feed(message: dict) -> list[MarketEvent]:
    """Map one COMPACT ``FEED_DATA`` message to neutral market events.

    COMPACT ``data`` is a flat, type-grouped list: ``[typeName, flatValues, typeName2,
    flatValues2, …]`` where each ``flatValues`` concatenates every event of that type,
    one event per ``len(_FEED_FIELDS[typeName])`` consecutive values (positionally the
    fields we requested). Unknown types and short/short-tail chunks are skipped.
    """
    data = message.get("data")
    if not isinstance(data, list):
        return []
    events: list[MarketEvent] = []
    for i in range(0, len(data) - 1, 2):
        type_name = data[i]
        flat = data[i + 1]
        fields = _FEED_FIELDS.get(type_name) if isinstance(type_name, str) else None
        if fields is None or not isinstance(flat, list):
            continue
        n = len(fields)
        for j in range(0, len(flat), n):
            chunk = flat[j : j + n]
            if len(chunk) < n:
                break  # trailing partial event — drop it
            event = _to_event(type_name, dict(zip(fields, chunk, strict=True)))
            if event is not None:
                events.append(event)
    return events


def _to_event(type_name: str, rec: dict[str, object]) -> MarketEvent | None:
    symbol = rec.get("eventSymbol")
    if not isinstance(symbol, str) or not symbol:
        return None
    if type_name == "Quote":
        return Quote(
            symbol=symbol,
            bid=_f(rec.get("bidPrice")),
            ask=_f(rec.get("askPrice")),
            bid_size=_i(rec.get("bidSize")),
            ask_size=_i(rec.get("askSize")),
        )
    if type_name == "Trade":
        price = _f(rec.get("price"))
        if price is None:
            return None
        return Trade(symbol=symbol, price=price, size=_i(rec.get("size")), ms=_i(rec.get("time")))
    if type_name == "TimeAndSale":
        price = _f(rec.get("price"))
        if price is None:
            return None
        return TimeSale(
            symbol=symbol,
            price=price,
            size=_i(rec.get("size")),
            bid=_f(rec.get("bidPrice")),
            ask=_f(rec.get("askPrice")),
            ms=_i(rec.get("time")),
        )
    return None


def _setup_msg() -> dict:
    return {
        "type": "SETUP",
        "channel": 0,
        "version": PROTOCOL_VERSION,
        "keepaliveTimeout": 60,
        "acceptKeepaliveTimeout": 60,
    }


def _auth_msg(token: str) -> dict:
    return {"type": "AUTH", "channel": 0, "token": token}


def _channel_request_msg() -> dict:
    return {
        "type": "CHANNEL_REQUEST",
        "channel": FEED_CHANNEL,
        "service": "FEED",
        "parameters": {"contract": "AUTO"},
    }


def _feed_setup_msg() -> dict:
    return {
        "type": "FEED_SETUP",
        "channel": FEED_CHANNEL,
        "acceptAggregationPeriod": 0.1,
        "acceptDataFormat": "COMPACT",
        "acceptEventFields": {k: list(v) for k, v in _FEED_FIELDS.items()},
    }


def _feed_subscription_msg(symbols: list[str]) -> dict:
    """FEED_SUBSCRIPTION: every event type for every symbol; ``reset`` clears prior subs."""
    add = [{"type": etype, "symbol": s} for s in symbols for etype in _EVENT_TYPES]
    return {"type": "FEED_SUBSCRIPTION", "channel": FEED_CHANNEL, "reset": True, "add": add}


class DxLinkStreamClient:
    """Owns the DXLink token+channel handshake and an auto-reconnecting event stream.

    ``token_provider`` is an async callable returning ``(streamer_token, dxlink_url)``
    — typically ``TastyTradeClient.get_quote_token`` — re-invoked on each reconnect for
    a fresh single-use token.
    """

    def __init__(
        self, token_provider: QuoteTokenProvider, *, keepalive_s: float = KEEPALIVE_INTERVAL
    ) -> None:
        self._token_provider = token_provider
        self._keepalive_s = keepalive_s

    async def close(self) -> None:
        """No persistent resources of our own — the Tastytrade client owns the HTTP pool."""

    async def _keepalive(self, ws: Any) -> None:
        while True:
            await asyncio.sleep(self._keepalive_s)
            await ws.send(json.dumps({"type": "KEEPALIVE", "channel": 0}))

    async def stream(
        self, symbols: list[str], *, max_backoff: float = 30.0
    ) -> AsyncIterator[MarketEvent]:
        """Yield neutral market events, reconnecting (with a fresh token) on drop.

        A 401/403 from the token fetch is a config error (bad/expired Tastytrade
        OAuth), surfaced rather than retried; transport faults reconnect on backoff.
        """
        backoff = 1.0
        while True:
            try:
                token, url = await self._token_provider()
                async with websockets.connect(url, ping_interval=None) as ws:
                    backoff = 1.0  # clean connect — reset backoff
                    async for event in self._session(ws, token, symbols):
                        yield event
            except asyncio.CancelledError:
                raise
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code in (401, 403):
                    raise  # fatal: bad/expired Tastytrade token — don't spin on backoff
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, max_backoff)
            except (httpx.TransportError, OSError, TimeoutError, WebSocketException):
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, max_backoff)

    async def _session(self, ws: Any, token: str, symbols: list[str]) -> AsyncIterator[MarketEvent]:
        """Drive one connection's DXLink handshake reactively, yielding FEED_DATA events.

        Each server frame advances the state machine with an **awaited** send (so the
        SETUP→AUTH→CHANNEL→FEED ordering can't race), and only ``FEED_DATA`` produces
        events. A background task heartbeats KEEPALIVE every 30 s.
        """

        async def send(payload: dict) -> None:
            await ws.send(json.dumps(payload))

        await send(_setup_msg())
        keepalive = asyncio.create_task(self._keepalive(ws))
        try:
            async for raw in ws:
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                mtype = msg.get("type")
                if mtype == "AUTH_STATE":
                    if msg.get("state") == "UNAUTHORIZED":
                        await send(_auth_msg(token))
                    elif msg.get("state") == "AUTHORIZED":
                        await send(_channel_request_msg())
                elif mtype == "CHANNEL_OPENED":
                    await send(_feed_setup_msg())
                elif mtype == "FEED_CONFIG":
                    await send(_feed_subscription_msg(symbols))
                elif mtype == "FEED_DATA":
                    for event in parse_dxlink_feed(msg):
                        yield event
        finally:
            keepalive.cancel()
