"""bond_math — corporate bond yield and spread math (pure fns).

Pins the accrued-interest reconstruction (the one thing here worth ~100bp if it
regresses), the price/yield round trip, curve interpolation including
flat-extrapolation past both ends, and the None paths for rows a holdings file
routinely contains but can't be valued.
"""

from datetime import date

from pytest import approx
from trading_clients import bond_math as bm

ASOF = date(2026, 8, 13)

# Independently-quoted CoreWeave levels (price, quoted yield-to-worst) used
# during the data-source POC. Our YTM should land just *above* each YTW because
# these are callable bonds trading below par.
CRWV_QUOTES = [
    (9.75, date(2031, 10, 1), 93.83, 11.35),
    (9.625, date(2032, 7, 15), 92.09, 11.49),
    (9.00, date(2031, 2, 1), 94.50, 10.57),
]


def test_ytm_matches_independent_quotes() -> None:
    """The end-to-end check: clean price in, market yield out, within 5bp.

    This is the test that would have caught solving to the clean price instead
    of the dirty price — that bug put the first bond at 12.36% against a quoted
    11.35%.
    """
    for coupon, maturity, price, quoted_ytw in CRWV_QUOTES:
        years = bm.years_between(ASOF, maturity)
        ytm = bm.yield_to_maturity(price, coupon, years)
        assert ytm is not None
        assert ytm == approx(quoted_ytw, abs=0.05)


def test_ytm_sits_at_or_above_ytw_for_discount_bonds() -> None:
    """A callable bond below par yields more to maturity than to worst."""
    for coupon, maturity, price, quoted_ytw in CRWV_QUOTES:
        ytm = bm.yield_to_maturity(price, coupon, bm.years_between(ASOF, maturity))
        assert ytm is not None
        assert ytm >= quoted_ytw


def test_accrued_interest_reconstructs_hand_measured_value() -> None:
    """3.60pts of accrual was measured by hand on the 9.75%/2031 for this date.

    Derived here from time-to-maturity alone, with no coupon calendar — so
    agreeing to a few hundredths is real corroboration that the period
    structure is right, not a tautology.
    """
    years = bm.years_between(ASOF, date(2031, 10, 1))
    assert bm.accrued_interest(9.75, years) == approx(3.60, abs=0.05)


def test_accrued_is_zero_when_next_coupon_is_a_full_period_out() -> None:
    assert bm.accrued_interest(8.0, 5.0) == approx(0.0)
    assert bm.accrued_interest(8.0, 0.5) == approx(0.0)


def test_accrued_never_exceeds_one_period_coupon() -> None:
    for years in (0.1, 0.37, 1.0, 2.49, 7.77, 29.3):
        assert 0.0 <= bm.accrued_interest(6.0, years) < 6.0 / 2


def test_price_yield_round_trip() -> None:
    """dirty(ytm) - accrued must return the clean price we started from."""
    cases = [
        (9.75, date(2031, 10, 1), 93.83),
        (5.0, date(2029, 3, 15), 101.5),
        (2.95, date(2052, 4, 1), 64.2),
        (0.5, date(2027, 1, 4), 99.0),
    ]
    for coupon, maturity, clean in cases:
        years = bm.years_between(ASOF, maturity)
        ytm = bm.yield_to_maturity(clean, coupon, years)
        assert ytm is not None
        back = bm.dirty_price_from_yield(ytm / 100, coupon, years) - bm.accrued_interest(
            coupon, years
        )
        assert back == approx(clean, abs=1e-6)


def test_bond_at_par_yields_its_coupon() -> None:
    assert bm.yield_to_maturity(100.0, 7.0, 10.0) == approx(7.0, abs=1e-6)


def test_yield_moves_inversely_to_price() -> None:
    years = bm.years_between(ASOF, date(2033, 6, 1))
    cheap = bm.yield_to_maturity(80.0, 6.0, years)
    rich = bm.yield_to_maturity(105.0, 6.0, years)
    assert cheap is not None and rich is not None
    assert cheap > rich


def test_unvaluable_rows_return_none_rather_than_raising() -> None:
    """Matured bonds and zero prices are routine in a holdings file."""
    assert bm.yield_to_maturity(0.0, 5.0, 3.0) is None
    assert bm.yield_to_maturity(-1.0, 5.0, 3.0) is None
    assert bm.yield_to_maturity(95.0, 5.0, 0.0) is None
    assert bm.yield_to_maturity(95.0, 5.0, -1.0) is None


def test_clean_price_from_market_value() -> None:
    assert bm.clean_price_from_market_value(15_916_882.20, 16_980_000.0) == approx(93.74, abs=0.01)
    assert bm.clean_price_from_market_value(100.0, 0.0) is None


def test_curve_interpolates_between_points() -> None:
    curve = [(2.0, 3.90), (5.0, 4.38), (10.0, 4.70)]
    assert bm.interpolate_yield(curve, 5.0) == approx(4.38)
    assert bm.interpolate_yield(curve, 3.5) == approx(4.14)
    assert bm.interpolate_yield(curve, 7.5) == approx(4.54)


def test_curve_flat_extrapolates_past_both_ends() -> None:
    """A 39-year bond takes the 30Y yield rather than an invented one."""
    curve = [(2.0, 3.90), (30.0, 5.10)]
    assert bm.interpolate_yield(curve, 39.0) == approx(5.10)
    assert bm.interpolate_yield(curve, 0.25) == approx(3.90)
    assert bm.interpolate_yield([], 5.0) is None


def test_g_spread_is_basis_points() -> None:
    assert bm.g_spread_bp(11.35, 4.38) == approx(697.0)


def test_value_bond_end_to_end() -> None:
    curve = [(t, 4.4) for _, t in bm.TREASURY_CMT_TENORS]
    v = bm.value_bond(
        isin="US21873SAG30",
        name="COREWEAVE INC COMPANY GUAR 144A 10/31 9.75",
        coupon_pct=9.75,
        maturity=date(2031, 10, 1),
        market_value=15_916_882.20,
        par_value=16_980_000.0,
        asof=ASOF,
        curve=curve,
    )
    assert v is not None
    assert v.clean_price == approx(93.74, abs=0.01)
    assert v.ytm_pct is not None and v.ytm_pct == approx(11.39, abs=0.05)
    assert v.g_spread_bp is not None and v.g_spread_bp == approx(699.0, abs=6.0)


def test_value_bond_skips_matured_and_parless_rows() -> None:
    common = {
        "isin": "X",
        "name": "N",
        "coupon_pct": 5.0,
        "market_value": 1000.0,
        "par_value": 1000.0,
        "asof": ASOF,
    }
    assert bm.value_bond(**{**common, "maturity": date(2020, 1, 1)}) is None
    assert bm.value_bond(**{**common, "maturity": date(2030, 1, 1), "par_value": 0.0}) is None


def test_value_bond_without_curve_has_no_spread() -> None:
    v = bm.value_bond(
        isin="X",
        name="N",
        coupon_pct=5.0,
        maturity=date(2030, 1, 1),
        market_value=980.0,
        par_value=1000.0,
        asof=ASOF,
    )
    assert v is not None
    assert v.ytm_pct is not None
    assert v.benchmark_pct is None
    assert v.g_spread_bp is None
