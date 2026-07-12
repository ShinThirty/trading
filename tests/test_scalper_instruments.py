"""Instrument registry — the point-value / tick lookup the CLI feeds the broker."""

import pytest
from trading_scalper.instruments import instrument_for


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
