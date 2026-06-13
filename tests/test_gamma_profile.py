"""gamma_exposure_profile — dealer GEX profile from an option chain (pure fn).

Pins the signed dollar-gamma math, the call/put walls, the regime sign, and the
zero-gamma cumulative crossing on a hand-built chain with known outputs.
"""

from pytest import approx
from trading_clients.options import gamma_exposure_profile


def _opt(option_type: str, strike: float, oi: int, gamma: float | None = 0.05) -> dict:
    greeks = {} if gamma is None else {"gamma": gamma}
    return {"option_type": option_type, "strike": strike, "open_interest": oi, "greeks": greeks}


def test_profile_walls_regime_and_flip() -> None:
    # spot=100 → dollar_gamma = gamma * OI * 100 * 100**2 * 0.01 = gamma * OI * 10_000
    chain = [
        _opt("put", 95, 1000),  # put_gex   = -500_000
        _opt("put", 100, 500),  # put_gex   = -250_000
        _opt("call", 100, 500),  # call_gex = +250_000  → net@100 = 0
        _opt("call", 105, 2000),  # call_gex = +1_000_000
    ]
    p = gamma_exposure_profile(chain, spot=100.0)

    assert p["total_gex"] == approx(500_000.0)
    assert p["regime"] == "positive"
    assert p["call_wall"] == 105.0  # largest positive call gamma
    assert p["put_wall"] == 95.0  # largest put gamma magnitude
    assert p["zero_gamma"] == approx(102.5)  # cum crosses zero between 100 and 105
    assert len(p["by_strike"]) == 3  # strikes 95, 100, 105 (100 merges call+put)


def test_negative_regime_when_puts_dominate() -> None:
    chain = [
        _opt("put", 95, 3000),  # -1_500_000
        _opt("call", 105, 1000),  # +500_000
    ]
    p = gamma_exposure_profile(chain, spot=100.0)

    assert p["total_gex"] == approx(-1_000_000.0)
    assert p["regime"] == "negative"
    assert p["call_wall"] == 105.0
    assert p["put_wall"] == 95.0
    assert p["zero_gamma"] is None  # cumulative stays negative — never flips


def test_skips_missing_greeks_and_zero_oi() -> None:
    chain = [
        _opt("call", 100, 0),  # zero OI → skipped
        _opt("put", 95, 1000, gamma=None),  # no gamma → skipped
        _opt("call", 105, 1000),  # the only contributor
    ]
    p = gamma_exposure_profile(chain, spot=100.0)

    assert len(p["by_strike"]) == 1
    assert p["call_wall"] == 105.0
    assert p["put_wall"] is None
    assert p["regime"] == "positive"


def test_nonpositive_spot_is_empty() -> None:
    p = gamma_exposure_profile([_opt("call", 105, 1000)], spot=0.0)
    assert p["by_strike"] == []
    assert p["call_wall"] is None and p["zero_gamma"] is None
