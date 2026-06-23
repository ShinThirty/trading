"""gamma_exposure_profile — dealer GEX profile from an option chain (pure fn).

Pins the signed dollar-gamma math, the call/put walls, the regime sign, and the
zero-gamma cumulative crossing on a hand-built chain with known outputs.
"""

from pytest import approx
from trading_clients.options import gamma_exposure_profile, scalp_regime_read


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

    assert p.total_gex == approx(500_000.0)
    assert p.regime == "positive"
    assert p.call_wall == 105.0  # largest positive call gamma
    assert p.put_wall == 95.0  # largest put gamma magnitude
    assert p.zero_gamma == approx(102.5)  # cum crosses zero between 100 and 105
    assert len(p.by_strike) == 3  # strikes 95, 100, 105 (100 merges call+put)


def test_flip_picks_crossing_nearest_spot() -> None:
    # Two zero crossings: a deep low-strike artifact (~81.7) and a near-spot one (~95.4).
    # The real QQQ chain wobbles around zero far from the money, so the *first* crossing
    # scanning up is junk — the flip must be the crossing closest to spot.
    # spot=100 → net per strike = sign * gamma(0.001) * OI * 100 * 100**2 * 0.01 = sign * OI * 10
    chain = [
        _opt("call", 80, 10, gamma=0.001),  # net +100  → cum +100
        _opt("put", 85, 30, gamma=0.001),  # net -300  → cum -200  (cross ~81.7 between 80,85)
        _opt("call", 98, 25, gamma=0.001),  # net +250  → cum  +50  (cross ~95.4 between 85,98)
        _opt("call", 110, 5, gamma=0.001),  # net  +50  → cum +100
    ]
    p = gamma_exposure_profile(chain, spot=100.0)

    assert p.zero_gamma == approx(95.4, abs=0.05)  # near-spot, NOT the ~81.7 artifact
    assert p.regime == "positive"


def test_negative_regime_when_puts_dominate() -> None:
    chain = [
        _opt("put", 95, 3000),  # -1_500_000
        _opt("call", 105, 1000),  # +500_000
    ]
    p = gamma_exposure_profile(chain, spot=100.0)

    assert p.total_gex == approx(-1_000_000.0)
    assert p.regime == "negative"
    assert p.call_wall == 105.0
    assert p.put_wall == 95.0
    assert p.zero_gamma is None  # cumulative stays negative — never flips


def test_skips_missing_greeks_and_zero_oi() -> None:
    chain = [
        _opt("call", 100, 0),  # zero OI → skipped
        _opt("put", 95, 1000, gamma=None),  # no gamma → skipped
        _opt("call", 105, 1000),  # the only contributor
    ]
    p = gamma_exposure_profile(chain, spot=100.0)

    assert len(p.by_strike) == 1
    assert p.call_wall == 105.0
    assert p.put_wall is None
    assert p.regime == "positive"


def test_nonpositive_spot_is_empty() -> None:
    p = gamma_exposure_profile([_opt("call", 105, 1000)], spot=0.0)
    assert p.by_strike == []
    assert p.call_wall is None and p.zero_gamma is None


# ── scalp_regime_read: front-exp regime/flip + aggregate walls ──────────────


def test_scalp_read_takes_regime_and_flip_from_front_walls_from_aggregate() -> None:
    spot = 100.0
    # Front (0DTE): puts dominate → NEGATIVE / trending, flip near spot.
    front = gamma_exposure_profile([_opt("put", 99, 2000), _opt("call", 101, 500)], spot)
    # Aggregate (≤7DTE): a big far call magnet at 105 — the structural wall.
    aggregate = gamma_exposure_profile([_opt("put", 95, 800), _opt("call", 105, 5000)], spot)
    read = scalp_regime_read(front, aggregate)

    assert read.regime == front.regime == "negative"  # regime from the front exp
    assert read.zero_gamma == front.zero_gamma  # flip from the front exp
    assert read.call_wall == aggregate.call_wall == 105.0  # walls from the aggregate
    assert read.put_wall == aggregate.put_wall == 95.0
    assert read.front_total_gex == front.total_gex
    assert read.aggregate_total_gex == aggregate.total_gex


def test_scalp_read_flags_the_6_16_conflict() -> None:
    spot = 100.0
    # The 6/16 shape: aggregate reads POSITIVE (fade) but the front has flipped NEGATIVE.
    front = gamma_exposure_profile([_opt("put", 99, 3000), _opt("call", 101, 500)], spot)
    aggregate = gamma_exposure_profile([_opt("put", 95, 500), _opt("call", 105, 4000)], spot)
    assert front.regime == "negative" and aggregate.regime == "positive"

    read = scalp_regime_read(front, aggregate)
    assert read.regime == "negative"  # the gate trusts the front
    assert read.conflict is not None
    assert "POSITIVE" in read.conflict and "NEGATIVE" in read.conflict


def test_scalp_read_no_conflict_when_signs_agree() -> None:
    spot = 100.0
    front = gamma_exposure_profile([_opt("call", 101, 2000), _opt("put", 99, 500)], spot)
    aggregate = gamma_exposure_profile([_opt("call", 105, 3000), _opt("put", 95, 500)], spot)
    assert front.regime == aggregate.regime == "positive"

    assert scalp_regime_read(front, aggregate).conflict is None
