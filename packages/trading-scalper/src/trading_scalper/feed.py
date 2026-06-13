"""TradierFeed: adapts the Tradier streaming transport to the MarketDataFeed port.

Holds the per-event-type callback registries and fans each parsed market event
out to its subscribers. ``run`` drives the underlying auto-reconnecting stream;
``_dispatch`` is the seam the run loop (and the tests) push events through, so
the routing is verifiable without a live socket.

``drive_paper_fills`` is the Phase-2 wiring that connects the live tape to the
PaperBroker matching engine: every trade/timesale print advances the broker, so
MARKET orders fill at the last price and resting STOP/LIMIT orders trigger when
the tape crosses them.
"""

from collections.abc import Callable

from trading_clients.market_stream import MarketEvent, Quote, TimeSale, Trade
from trading_clients.tradier_stream_client import DEFAULT_FILTERS, TradierStreamClient

from trading_scalper.paper import PaperBroker
from trading_scalper.ports import MarketDataFeed


class TradierFeed:
    """A ``MarketDataFeed`` backed by ``TradierStreamClient``."""

    def __init__(
        self,
        client: TradierStreamClient,
        filters: tuple[str, ...] = DEFAULT_FILTERS,
    ) -> None:
        self._client = client
        self._filters = filters
        self._symbols: list[str] = []
        self._quote_cbs: list[Callable[[Quote], None]] = []
        self._trade_cbs: list[Callable[[Trade], None]] = []
        self._timesale_cbs: list[Callable[[TimeSale], None]] = []

    async def subscribe(self, symbols: list[str]) -> None:
        self._symbols = list(symbols)

    def on_quote(self, cb: Callable[[Quote], None]) -> None:
        self._quote_cbs.append(cb)

    def on_trade(self, cb: Callable[[Trade], None]) -> None:
        self._trade_cbs.append(cb)

    def on_timesale(self, cb: Callable[[TimeSale], None]) -> None:
        self._timesale_cbs.append(cb)

    async def run(self) -> None:
        """Consume the live stream until cancelled, dispatching each event."""
        async for event in self._client.stream(self._symbols, self._filters):
            self._dispatch(event)

    def _dispatch(self, event: MarketEvent) -> None:
        if isinstance(event, Quote):
            for cb in self._quote_cbs:
                cb(event)
        elif isinstance(event, Trade):
            for cb in self._trade_cbs:
                cb(event)
        elif isinstance(event, TimeSale):
            for cb in self._timesale_cbs:
                cb(event)


def drive_paper_fills(feed: MarketDataFeed, broker: PaperBroker) -> None:
    """Wire the live tape to the paper matching engine.

    Each trade/timesale print advances ``PaperBroker`` so MARKET orders fill at
    the last price and resting STOP/LIMIT orders trigger when the tape crosses
    them. Quotes are not wired in — only prints move the engine.
    """
    feed.on_trade(lambda t: broker.trade(t.symbol, t.price))
    feed.on_timesale(lambda ts: broker.trade(ts.symbol, ts.price))
