"""Tradier streaming wire-format parsing → neutral market events.

The connect/reconnect loop needs a live production token to exercise, but the
parsing is pure and is where the wire-format risk lives (string-typed numbers,
epoch-ms date strings, event types we ignore). These pin it.
"""

from trading_clients.market_stream import Quote, TimeSale, Trade
from trading_clients.tradier_stream_client import parse_message, parse_tradier_event

# The quote payload is quoted verbatim from the Tradier streaming docs.
_QUOTE = {
    "type": "quote",
    "symbol": "SPY",
    "bid": 281.84,
    "bidsz": 60,
    "bidexch": "M",
    "biddate": "1557757189000",
    "ask": 281.85,
    "asksz": 6,
    "askexch": "Z",
    "askdate": "1557757190000",
}
_TRADE = {
    "type": "trade",
    "symbol": "SPY",
    "exch": "J",
    "price": "281.85",
    "size": "100",
    "cvol": "100",
    "date": "1557757190000",
    "last": "281.85",
}
_TIMESALE = {
    "type": "timesale",
    "symbol": "SPY",
    "exch": "Q",
    "bid": "281.84",
    "ask": "281.85",
    "last": "281.85",
    "size": "100",
    "date": "1557757190000",
    "seq": 352,
    "flag": "",
    "cancel": False,
    "correction": False,
    "session": "normal",
}


def test_parse_quote() -> None:
    q = parse_tradier_event(_QUOTE)
    assert q == Quote(
        symbol="SPY",
        bid=281.84,
        ask=281.85,
        bid_size=60,
        ask_size=6,
        ms=1557757190000,  # the freshest of biddate/askdate
    )


def test_parse_trade_coerces_string_numbers() -> None:
    t = parse_tradier_event(_TRADE)
    assert t == Trade(symbol="SPY", price=281.85, size=100, ms=1557757190000)
    assert isinstance(t, Trade)


def test_parse_timesale_maps_last_to_price() -> None:
    ts = parse_tradier_event(_TIMESALE)
    assert ts == TimeSale(
        symbol="SPY",
        price=281.85,
        size=100,
        bid=281.84,
        ask=281.85,
        ms=1557757190000,
    )


def test_summary_and_unknown_types_are_ignored() -> None:
    assert parse_tradier_event({"type": "summary", "symbol": "SPY", "open": 281.0}) is None
    assert parse_tradier_event({"type": "nope", "symbol": "SPY"}) is None


def test_missing_symbol_is_dropped() -> None:
    assert parse_tradier_event({"type": "quote", "bid": 1.0, "ask": 1.1}) is None


def test_malformed_price_is_dropped() -> None:
    assert parse_tradier_event({"type": "trade", "symbol": "SPY", "price": ""}) is None


def test_parse_message_splits_linebreak_delimited_frame() -> None:
    import json

    frame = json.dumps(_QUOTE) + "\n" + json.dumps(_TRADE) + "\n"
    events = parse_message(frame)
    assert [type(e).__name__ for e in events] == ["Quote", "Trade"]


def test_parse_message_skips_blank_and_bad_lines() -> None:
    import json

    frame = "\n  \nnot-json\n" + json.dumps(_TRADE)
    events = parse_message(frame)
    assert len(events) == 1
    assert isinstance(events[0], Trade)
