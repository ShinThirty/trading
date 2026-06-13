"""TradierFeed dispatch + the tape-to-PaperBroker wiring.

No socket here: events are pushed through the dispatch seam the run loop uses.
The point is to prove (a) each event type reaches only its own subscribers and
(b) ``drive_paper_fills`` turns a tape print into a paper fill — so a resting
auto-stop will trigger off the live tape in Phase 2b.
"""

from trading_clients.market_stream import Quote, TimeSale, Trade
from trading_clients.tradier_stream_client import TradierStreamClient
from trading_scalper.domain import Order, OrderType, Side
from trading_scalper.feed import TradierFeed, drive_paper_fills
from trading_scalper.paper import PaperBroker


def _feed() -> TradierFeed:
    # Constructing the client opens no socket and makes no request.
    return TradierFeed(TradierStreamClient("test-token"))


def test_dispatch_routes_each_event_to_its_own_subscribers() -> None:
    feed = _feed()
    quotes: list[Quote] = []
    trades: list[Trade] = []
    timesales: list[TimeSale] = []
    feed.on_quote(quotes.append)
    feed.on_trade(trades.append)
    feed.on_timesale(timesales.append)

    feed._dispatch(Quote("QQQ", bid=1.0, ask=1.1))
    feed._dispatch(Trade("QQQ", price=1.05))
    feed._dispatch(TimeSale("QQQ", price=1.05))

    assert len(quotes) == 1
    assert len(trades) == 1
    assert len(timesales) == 1
    assert quotes[0].ask == 1.1
    assert trades[0].price == 1.05


def test_drive_paper_fills_triggers_a_resting_stop_off_the_tape() -> None:
    feed = _feed()
    paper = PaperBroker()
    drive_paper_fills(feed, paper)

    paper.place(Order("QQQ", Side.BUY, 2, OrderType.MARKET, limit_price=5.00))  # human long 2
    paper.place(Order("QQQ", Side.SELL, 2, OrderType.STOP, stop_price=4.50))  # protective stop

    feed._dispatch(Trade("QQQ", price=4.80))  # above the stop — no trigger
    assert paper.net_position("QQQ") == 2

    feed._dispatch(TimeSale("QQQ", price=4.40))  # tape through the stop — fills flat
    assert paper.net_position("QQQ") == 0


def test_drive_paper_fills_only_wires_prints_not_quotes() -> None:
    feed = _feed()
    paper = PaperBroker()
    drive_paper_fills(feed, paper)
    paper.place(Order("QQQ", Side.BUY, 1, OrderType.MARKET, limit_price=5.00))
    paper.place(Order("QQQ", Side.SELL, 1, OrderType.STOP, stop_price=4.50))

    feed._dispatch(Quote("QQQ", bid=4.0, ask=4.1))  # a quote must not move the engine
    assert paper.net_position("QQQ") == 1
