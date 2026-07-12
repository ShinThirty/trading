"""DxLinkFeed dispatch + the tape-to-PaperBroker wiring, plus the COMPACT wire parser.

No socket here: events are pushed through the dispatch seam the run loop uses, and the
wire parser is exercised against the documented COMPACT FEED_DATA shape. The point is to
prove (a) each event type reaches only its own subscribers, (b) ``drive_paper_fills`` turns
a tape print into a paper fill, and (c) the COMPACT chunk-by-field-count decode is correct.
"""

from trading_clients.dxlink_stream_client import (
    DxLinkStreamClient,
    _feed_setup_msg,
    _feed_subscription_msg,
    parse_dxlink_feed,
)
from trading_clients.market_stream import Quote, TimeSale, Trade
from trading_scalper.domain import Order, OrderType, Side
from trading_scalper.feed import DxLinkFeed, drive_paper_fills
from trading_scalper.paper import PaperBroker


async def _noop_token() -> tuple[str, str]:
    return ("tok", "wss://example/realtime")


def _feed() -> DxLinkFeed:
    # Constructing the client opens no socket and makes no request.
    return DxLinkFeed(DxLinkStreamClient(_noop_token))


# ── dispatch + paper wiring ─────────────────────────────────


def test_dispatch_routes_each_event_to_its_own_subscribers() -> None:
    feed = _feed()
    quotes: list[Quote] = []
    trades: list[Trade] = []
    timesales: list[TimeSale] = []
    feed.on_quote(quotes.append)
    feed.on_trade(trades.append)
    feed.on_timesale(timesales.append)

    feed._dispatch(Quote("/MES", bid=6249.75, ask=6250.0))
    feed._dispatch(Trade("/MES", price=6250.0))
    feed._dispatch(TimeSale("/MES", price=6250.0))

    assert len(quotes) == 1
    assert len(trades) == 1
    assert len(timesales) == 1
    assert quotes[0].ask == 6250.0
    assert trades[0].price == 6250.0


def test_drive_paper_fills_triggers_a_resting_stop_off_the_tape() -> None:
    feed = _feed()
    paper = PaperBroker(multiplier=5)
    drive_paper_fills(feed, paper)

    paper.place(Order("/MES", Side.BUY, 2, OrderType.MARKET, limit_price=6300.0))  # long 2
    paper.place(Order("/MES", Side.SELL, 2, OrderType.STOP, stop_price=6290.0))  # protective stop

    feed._dispatch(Trade("/MES", price=6295.0))  # above the stop — no trigger
    assert paper.net_position("/MES") == 2

    feed._dispatch(TimeSale("/MES", price=6288.0))  # tape through the stop — fills flat
    assert paper.net_position("/MES") == 0


def test_quotes_set_the_book_but_never_trigger_resting_orders() -> None:
    feed = _feed()
    paper = PaperBroker(multiplier=5)
    drive_paper_fills(feed, paper)
    paper.place(Order("/MES", Side.SELL, 1, OrderType.STOP, stop_price=6290.0))  # protective stop

    feed._dispatch(Quote("/MES", bid=6280.0, ask=6280.25))  # a quote must not cross a resting order
    assert paper.net_position("/MES") == 0  # stop untouched (was never long)

    # but the quote DID set the book: a market buy now fills at the ask, not a stale last
    fills: list[float] = []
    paper.on_order_event(lambda e: fills.append(e.fill_price) if e.fill_price else None)
    paper.place(Order("/MES", Side.BUY, 1, OrderType.MARKET))
    assert paper.net_position("/MES") == 1
    assert fills == [6280.25]  # filled at the offer (paid the spread), not the bid/last


# ── COMPACT FEED_DATA wire parsing (pure) ───────────────────


def test_parse_compact_trade_group_from_docs_shape() -> None:
    # the exact shape from Tastytrade's docs: data = [typeName, flatArray] with each event
    # occupying len(fields) consecutive values; Trade fields = eventType,eventSymbol,price,size,time
    msg = {
        "type": "FEED_DATA",
        "channel": 1,
        "data": ["Trade", ["Trade", "/MESU25:XCME", 6250.0, 3, 1_700_000_000_000]],
    }
    events = parse_dxlink_feed(msg)
    assert len(events) == 1
    t = events[0]
    assert isinstance(t, Trade)
    assert t.symbol == "/MESU25:XCME" and t.price == 6250.0 and t.size == 3
    assert t.ms == 1_700_000_000_000


def test_parse_compact_multiple_events_and_types() -> None:
    msg = {
        "type": "FEED_DATA",
        "data": [
            "Quote",
            ["Quote", "/MES", 6249.75, 6250.0, 10, 12, "Quote", "/MES", 6249.5, 6249.75, 8, 9],
            "TimeAndSale",
            ["TimeAndSale", "/MES", 6250.0, 2, 6249.75, 6250.0, 1_700_000_000_500],
        ],
    }
    events = parse_dxlink_feed(msg)
    quotes = [e for e in events if isinstance(e, Quote)]
    ts = [e for e in events if isinstance(e, TimeSale)]
    assert len(quotes) == 2 and len(ts) == 1
    assert quotes[0].bid == 6249.75 and quotes[0].ask == 6250.0
    assert quotes[0].bid_size == 10 and quotes[0].ask_size == 12
    assert quotes[1].bid == 6249.5
    assert ts[0].price == 6250.0 and ts[0].bid == 6249.75 and ts[0].ms == 1_700_000_000_500


def test_parse_compact_handles_nan_sentinel() -> None:
    # dxFeed sends the string "NaN" for an undefined double — it must map to None, not crash
    msg = {"type": "FEED_DATA", "data": ["Quote", ["Quote", "/MES", "NaN", 6250.0, "NaN", 12]]}
    q = parse_dxlink_feed(msg)[0]
    assert isinstance(q, Quote)
    assert q.bid is None and q.ask == 6250.0 and q.bid_size is None and q.ask_size == 12


def test_parse_skips_unknown_types_and_partial_tail() -> None:
    msg = {
        "type": "FEED_DATA",
        "data": [
            "Greeks",  # a type we don't model → skipped
            ["Greeks", "/MES", 0.2, 0.5],
            "Trade",
            ["Trade", "/MES", 6250.0, 3, 1_700_000_000_000, "Trade", "/MES"],  # trailing partial
        ],
    }
    events = parse_dxlink_feed(msg)
    assert len(events) == 1  # the one complete Trade; partial tail + unknown type dropped
    assert isinstance(events[0], Trade)


def test_parse_non_feed_data_is_empty() -> None:
    assert parse_dxlink_feed({"type": "FEED_CONFIG", "channel": 1}) == []


# ── handshake message builders (shape pinned without a socket) ──


def test_feed_setup_requests_compact_with_our_field_order() -> None:
    msg = _feed_setup_msg()
    assert msg["type"] == "FEED_SETUP" and msg["acceptDataFormat"] == "COMPACT"
    fields = msg["acceptEventFields"]
    # the Quote layout must match what parse_dxlink_feed decodes positionally
    assert fields["Quote"] == [
        "eventType",
        "eventSymbol",
        "bidPrice",
        "askPrice",
        "bidSize",
        "askSize",
    ]
    assert fields["TimeAndSale"][0:2] == ["eventType", "eventSymbol"]


def test_feed_subscription_adds_all_event_types_per_symbol() -> None:
    msg = _feed_subscription_msg(["/MESU25:XCME"])
    assert msg["reset"] is True
    types = {e["type"] for e in msg["add"]}
    assert types == {"Quote", "Trade", "TimeAndSale"}
    assert all(e["symbol"] == "/MESU25:XCME" for e in msg["add"])
