"""Cost-basis ledger — the one place position+P&L arithmetic lives.

Everything downstream (PaperBroker.realized_pnl, the DisciplineEngine breaker)
trusts these numbers without re-deriving them, so the math is pinned here:
long/short round trips, average cost on adds, partial closes, flip-through-zero,
and the contract multiplier.
"""

from trading_scalper.ledger import Ledger


def test_long_round_trip_profit() -> None:
    ledger = Ledger(multiplier=100)
    assert ledger.record("QQQ", True, 2, 5.00) == 0.0  # open — no realization
    assert ledger.net_qty("QQQ") == 2
    assert ledger.record("QQQ", False, 2, 6.00) == 200.0  # (6-5) * 2 * 100
    assert ledger.realized == 200.0
    assert ledger.net_qty("QQQ") == 0
    assert ledger.symbols() == []


def test_long_round_trip_loss() -> None:
    ledger = Ledger()
    ledger.record("QQQ", True, 1, 6.00)
    assert ledger.record("QQQ", False, 1, 5.00) == -100.0


def test_short_round_trip_profit() -> None:
    ledger = Ledger()
    ledger.record("QQQ", False, 1, 6.00)  # short 1 @ 6
    assert ledger.net_qty("QQQ") == -1
    assert ledger.record("QQQ", True, 1, 5.00) == 100.0  # cover @ 5


def test_average_cost_on_adds() -> None:
    ledger = Ledger()
    ledger.record("QQQ", True, 1, 4.00)
    ledger.record("QQQ", True, 1, 6.00)  # avg cost now 5.00
    assert ledger.record("QQQ", False, 2, 5.50) == 100.0  # (5.50-5.00) * 2 * 100


def test_partial_close_realizes_only_the_closed_lot() -> None:
    ledger = Ledger()
    ledger.record("QQQ", True, 4, 5.00)
    assert ledger.record("QQQ", False, 1, 6.00) == 100.0  # close 1 of 4
    assert ledger.net_qty("QQQ") == 3
    assert ledger.realized == 100.0


def test_flip_through_zero_opens_fresh() -> None:
    ledger = Ledger()
    ledger.record("QQQ", True, 1, 5.00)  # long 1 @ 5
    assert ledger.record("QQQ", False, 3, 6.00) == 100.0  # close 1 (+100), open short 2 @ 6
    assert ledger.net_qty("QQQ") == -2
    assert ledger.record("QQQ", True, 2, 7.00) == -200.0  # cover short 2 @ 7: (6-7)*2*100


def test_multiplier_one_for_underlying() -> None:
    ledger = Ledger(multiplier=1)
    ledger.record("SPY", True, 10, 100.0)
    assert ledger.record("SPY", False, 10, 101.0) == 10.0


def test_micro_futures_multiplier() -> None:
    """/MES is $5/point: a 20-point winner on one contract is +$100, a short the mirror."""
    ledger = Ledger(multiplier=5)
    ledger.record("/MES", True, 1, 6300.0)  # long 1 @ 6300
    assert ledger.record("/MES", False, 1, 6320.0) == 100.0  # (6320-6300) * 1 * 5

    short = Ledger(multiplier=5)
    short.record("/MES", False, 2, 6300.0)  # short 2 @ 6300
    assert short.record("/MES", True, 2, 6290.0) == 100.0  # (6300-6290) * 2 * 5, covering lower
