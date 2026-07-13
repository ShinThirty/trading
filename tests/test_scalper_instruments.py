"""Instrument profiles — the two things about a futures root that are *ours*.

Everything the exchange can state (which month is live, $/pt, tick) is deliberately
absent from the registry and comes from ``contract.py`` — see ``test_scalper_contract``.
What's left is calibration (``geometry``) and our level source (``reference``).
"""

import pytest
from trading_scalper.instruments import profile_for, root_of


def test_reference_index_is_instrument_correlated() -> None:
    # the cash-index reference (gamma walls + carry basis) pairs by index, not by size
    assert profile_for("/MES").reference == "SPX"
    assert profile_for("/ES").reference == "SPX"
    assert profile_for("/MNQ").reference == "NDX"
    assert profile_for("/NQ").reference == "NDX"


def test_geometry_pairs_by_index_not_by_contract_size() -> None:
    # /MES and /ES are one price map; the Nasdaq complex is a different magnitude
    assert profile_for("/MES").geometry is profile_for("/ES").geometry
    assert profile_for("/MNQ").geometry is profile_for("/NQ").geometry
    assert profile_for("/MNQ").geometry != profile_for("/MES").geometry


def test_dated_contract_resolves_to_its_root_profile() -> None:
    inst = profile_for("/MESU26:XCME")  # a specific contract month from the feed
    assert inst is profile_for("/MES")
    assert inst.reference == "SPX"


def test_micro_root_not_shadowed_by_es() -> None:
    # "/MNQU26" must resolve to /MNQ's Nasdaq bands, never /NQ's — and never /MES's
    assert profile_for("/MNQU26:XCME").reference == "NDX"
    assert root_of("/MESU26:XCME") == "/MES"


def test_unknown_symbol_raises() -> None:
    # a typo should fail loudly, not silently scalp with the wrong index's tolerances
    with pytest.raises(KeyError, match="unknown futures symbol"):
        profile_for("AAPL")
