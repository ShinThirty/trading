"""Webull crypto bars arrive newest-first; every consumer needs oldest-first.

Guards the failure that motivated the sort in CryptoBarsResponse. The indicators
in trading_clients.indicators are written oldest-first and expose their latest
reading as [-1]. Fed the provider's raw newest-first array, [-1] is the value at
the *oldest* bar in the window — eight months stale on a 250-bar daily series.

On 2026-08-21, mid-way through a +24.5% week, get_btc_entry_signals reported
RSI 41.7 "neutral" and price *below* a $88,987 SMA(50). The true readings were
RSI 86.3 "overbought" and price *above* a $64,538 SMA(50): every technical row
inverted, and the $88,987 was simply the 50-bar average around 2025-12-15.
"""

from trading_clients import indicators as ta
from trading_clients.endpoints.webull import CryptoBarsResponse


def _payload(closes_newest_first: list[float]) -> list[dict]:
    """Wrap closes in the provider's envelope, newest bar first — as Webull sends."""
    n = len(closes_newest_first)
    return [
        {
            "result": [
                {"time": f"2026-{(n - i):02d}-01T04:00:00.000+0000", "close": c}
                for i, c in enumerate(closes_newest_first)
            ]
        }
    ]


def test_bars_are_reordered_oldest_first() -> None:
    resp = CryptoBarsResponse.from_response(_payload([78_407.54, 74_485.95, 69_144.23]))
    assert [b["close"] for b in resp.bars] == [69_144.23, 74_485.95, 78_407.54]


def test_already_ascending_input_is_left_alone() -> None:
    """Idempotent: a provider that changes its mind must not re-break the series."""
    ascending = list(reversed(_payload([3.0, 2.0, 1.0])[0]["result"]))
    resp = CryptoBarsResponse.from_response([{"result": ascending}])
    assert [b["close"] for b in resp.bars] == [1.0, 2.0, 3.0]


def test_indicators_read_the_newest_bar_not_the_oldest() -> None:
    """The regression itself: [-1] must describe today, not the far end of the window."""
    # 50 flat bars, then a rally — chronologically. Sent newest-first.
    chronological = [60_000.0] * 50 + [62_000.0, 66_000.0, 72_000.0, 78_000.0]
    resp = CryptoBarsResponse.from_response(_payload(list(reversed(chronological))))

    closes = [float(b["close"]) for b in resp.bars]
    assert closes == chronological

    sma50 = ta.sma(closes, 50)[-1]
    assert sma50 is not None
    assert sma50 == sum(chronological[-50:]) / 50  # the recent 50, not the first 50

    rsi = ta.rsi(closes)[-1]
    assert rsi is not None
    assert rsi > 70  # a rally into the newest bar reads overbought


def test_bars_missing_a_timestamp_do_not_crash() -> None:
    resp = CryptoBarsResponse.from_response([{"result": [{"close": 1.0}, {"close": 2.0}]}])
    assert len(resp.bars) == 2


def test_empty_and_malformed_payloads_stay_empty() -> None:
    assert CryptoBarsResponse.from_response([]).bars == []
    assert CryptoBarsResponse.from_response([{"result": []}]).bars == []
