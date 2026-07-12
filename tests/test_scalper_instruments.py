"""Instrument registry — the point-value / tick lookup the CLI feeds the broker."""

from datetime import date

import pytest
from trading_scalper.instruments import front_month, instrument_for, third_friday


def test_micro_and_full_es_economics() -> None:
    mes = instrument_for("/MES")
    assert mes.point_value == 5 and mes.tick == 0.25
    es = instrument_for("/ES")
    assert es.point_value == 50 and es.tick == 0.25


def test_dated_contract_resolves_to_root() -> None:
    inst = instrument_for("/MESU25:XCME")  # a specific contract month from the feed
    assert inst.point_value == 5 and inst.tick == 0.25
    assert inst.symbol == "/MESU25:XCME"  # keeps the concrete symbol, borrows the economics


def test_micro_root_not_shadowed_by_es() -> None:
    # "/MESU25" must resolve to /MES ($5), never /ES ($50), despite sharing the ES complex
    assert instrument_for("/MESU25:XCME").point_value == 5


def test_unknown_symbol_raises() -> None:
    with pytest.raises(KeyError, match="unknown futures symbol"):
        instrument_for("AAPL")


def test_third_friday_known_expiries() -> None:
    assert third_friday(2026, 9) == date(2026, 9, 18)  # Sep 2026 ES/MES expiry
    assert third_friday(2026, 12) == date(2026, 12, 18)  # Dec 2026 expiry


def test_front_month_current_is_september() -> None:
    # mid-July 2026 is well before the Sep 10 roll → the Sep (U) contract is live
    assert front_month("/MES", date(2026, 7, 12)) == "/MESU26:XCME"
    assert front_month("/ES", date(2026, 7, 12)) == "/ESU26:XCME"


def test_front_month_rolls_at_the_roll_date() -> None:
    # Sep expiry is the 18th → roll date is the 10th (expiry − 8 days)
    assert front_month("/MES", date(2026, 9, 9)) == "/MESU26:XCME"  # day before: still Sep
    assert front_month("/MES", date(2026, 9, 10)) == "/MESZ26:XCME"  # roll day: now Dec


def test_front_month_crosses_the_year_boundary() -> None:
    # after the Dec 10 roll the front is next March (H) of the following year
    assert front_month("/MES", date(2026, 12, 15)) == "/MESH27:XCME"
