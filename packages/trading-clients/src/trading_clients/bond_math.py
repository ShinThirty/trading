"""Corporate bond math (pure functions, no I/O).

Turns the three things a holdings file actually gives you — clean price, coupon,
maturity — into the two numbers a credit read needs: a yield and a spread over
Treasuries. Same shape as `bsm.py` / `vrp.py`: no clients, no dates fetched, no
network.

**Clean price is derived, not quoted.** ETF holdings files publish par value and
market value, not price. `clean_price_from_market_value` is MV/par x 100. That
SSGA's market value excludes accrued interest was settled empirically, not
assumed.

**Accrued interest is reconstructed, not supplied.** The yield solve discounts
cash flows to the *dirty* price, so the clean price a holdings file gives has to
have accrued added back first. No coupon calendar is needed for this: coupon
dates sit on a regular schedule anchored at maturity, so the fraction of a period
until the next coupon falls out of the time to maturity
(`w = (years * freq) mod 1`), and accrued is the remaining `(1 - w)` of it.
Getting this wrong is worth ~100bp, not a rounding artifact — solving to the
clean price directly puts a 9.75%/2031 bond at 12.36% when the market says 11.35%.
The reconstruction is self-checking: it independently reproduces a hand-measured
3.60pt accrual to within 0.03pt.

**YTM, not YTW.** Almost every high-yield bond is callable and a holdings file
carries no call schedule, so this computes yield to *maturity* — for a bond below
par, slightly above its yield-to-worst. Do not present these as YTW.

**Nominal G-spread, not OAS.** `g_spread_bp` subtracts an interpolated Treasury
constant-maturity yield from the bond's YTM. That is *not* like-for-like with the
ICE BofA index spreads in FRED (BAMLH0A0HYM2 et al.), which are option-adjusted;
a nominal spread on callable paper reads wider than its OAS. Directionally
useful, quantitatively approximate — label it that way.
"""

from dataclasses import dataclass
from datetime import date
from math import floor

# Treasury constant-maturity series on FRED, mapped to their tenor in years.
# Used to build the interpolation grid for `g_spread_bp`. Kept here (rather than
# in the caller) because it is tenor arithmetic, not I/O — the caller supplies
# the observed yields.
TREASURY_CMT_TENORS: tuple[tuple[str, float], ...] = (
    ("DGS1MO", 1 / 12),
    ("DGS3MO", 0.25),
    ("DGS6MO", 0.5),
    ("DGS1", 1.0),
    ("DGS2", 2.0),
    ("DGS3", 3.0),
    ("DGS5", 5.0),
    ("DGS7", 7.0),
    ("DGS10", 10.0),
    ("DGS20", 20.0),
    ("DGS30", 30.0),
)

DAYS_PER_YEAR = 365.25
DEFAULT_FREQ = 2

# Bisection bounds. The upper bound sits far above any live coupon yield so
# genuinely distressed paper (sub-50 price) still solves instead of silently
# pinning at the ceiling.
_YIELD_LO = 1e-6
_YIELD_HI = 5.0
_BISECTION_STEPS = 200


@dataclass(frozen=True)
class BondValuation:
    """A single bond priced off a holdings row, with its spread to Treasuries.

    `ytm_pct` and `benchmark_pct` are percents (11.35 = 11.35%); `g_spread_bp`
    is basis points. `benchmark_pct` / `g_spread_bp` are None when the caller
    supplied no curve.
    """

    isin: str
    name: str
    coupon_pct: float
    maturity: date
    clean_price: float
    accrued: float
    years_to_maturity: float
    ytm_pct: float | None
    benchmark_pct: float | None = None
    g_spread_bp: float | None = None


def years_between(start: date, end: date) -> float:
    """Calendar years from `start` to `end`, negative if `end` is in the past."""
    return (end - start).days / DAYS_PER_YEAR


def clean_price_from_market_value(market_value: float, par_value: float) -> float | None:
    """Implied clean price per 100 of par. None when par is zero/absent.

    Holdings files report position-level dollars; dividing recovers the price the
    pricing service used. Verified accrued-exclusive (clean) for SSGA.
    """
    if not par_value:
        return None
    return market_value / par_value * 100.0


def period_structure(years: float, freq: int = DEFAULT_FREQ) -> tuple[int, float]:
    """Return (number of remaining coupons, fraction of a period until the next).

    Coupons sit on a regular schedule anchored at maturity, so the stub `w` is
    just the fractional part of the remaining period count — `w == 1.0` means a
    coupon falls exactly one full period out (no stub).
    """
    periods = years * freq
    whole = floor(periods)
    w = periods - whole
    if w <= 0:
        w = 1.0
        whole -= 1
    return whole + 1, w


def accrued_interest(coupon_pct: float, years: float, freq: int = DEFAULT_FREQ) -> float:
    """Interest accrued since the last coupon, per 100 of par.

    The `(1 - w)` of the current period already elapsed, times the periodic
    coupon. Zero when the next coupon is a full period away.
    """
    if years <= 0:
        return 0.0
    _, w = period_structure(years, freq)
    return (coupon_pct / freq) * (1.0 - w)


def dirty_price_from_yield(
    ytm: float, coupon_pct: float, years: float, freq: int = DEFAULT_FREQ
) -> float:
    """Present value of remaining cash flows at annual yield `ytm` (decimal).

    This is the **dirty** price — it includes accrued interest, because the
    buyer of a mid-period bond receives the whole next coupon. Subtract
    `accrued_interest` to get the quoted clean price.
    """
    if years <= 0:
        return 100.0
    n, w = period_structure(years, freq)
    c = coupon_pct / freq
    y = ytm / freq
    pv = sum(c / (1.0 + y) ** (k + w) for k in range(n))
    return pv + 100.0 / (1.0 + y) ** (n - 1 + w)


def yield_to_maturity(
    clean_price: float,
    coupon_pct: float,
    years: float,
    freq: int = DEFAULT_FREQ,
) -> float | None:
    """Annual yield to maturity as a percent, solved from a **clean** price.

    Accrued interest is added internally before the solve. Returns None for a
    non-positive price or a bond at/past maturity. Price is monotonically
    decreasing in yield, so bisection is unconditionally stable here — no
    derivative, no failure-to-converge branch.
    """
    if clean_price <= 0 or years <= 0:
        return None

    dirty = clean_price + accrued_interest(coupon_pct, years, freq)

    lo, hi = _YIELD_LO, _YIELD_HI
    # A price above the undiscounted sum of cash flows would imply a negative
    # yield, which we don't model; clamp rather than return a bogus root.
    if dirty_price_from_yield(lo, coupon_pct, years, freq) < dirty:
        return lo * 100.0

    for _ in range(_BISECTION_STEPS):
        mid = (lo + hi) / 2.0
        if dirty_price_from_yield(mid, coupon_pct, years, freq) > dirty:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2.0 * 100.0


def interpolate_yield(curve: list[tuple[float, float]], years: float) -> float | None:
    """Linearly interpolate a yield at `years` from (tenor_years, yield_pct) points.

    Flat-extrapolates past both ends: a 32-year bond gets the 30Y yield rather
    than an invented one. Returns None if the curve is empty.
    """
    if not curve:
        return None
    points = sorted(curve)
    if years <= points[0][0]:
        return points[0][1]
    if years >= points[-1][0]:
        return points[-1][1]
    for (x0, y0), (x1, y1) in zip(points, points[1:], strict=False):
        if x0 <= years <= x1:
            if x1 == x0:
                return y0
            return y0 + (y1 - y0) * (years - x0) / (x1 - x0)
    return points[-1][1]


def g_spread_bp(ytm_pct: float, benchmark_pct: float) -> float:
    """Nominal spread in basis points: bond YTM minus the interpolated Treasury.

    Not option-adjusted. On callable paper this reads wider than an OAS, so it is
    not directly comparable to FRED's ICE BofA index spreads.
    """
    return (ytm_pct - benchmark_pct) * 100.0


def value_bond(
    isin: str,
    name: str,
    coupon_pct: float,
    maturity: date,
    market_value: float,
    par_value: float,
    asof: date,
    curve: list[tuple[float, float]] | None = None,
    freq: int = DEFAULT_FREQ,
) -> BondValuation | None:
    """Price one holdings row end-to-end. None if it can't be valued.

    Returns None for matured bonds and for rows with no par value — both are
    routine in a holdings file (a bond maturing next week, a cash line) and
    neither is worth raising over.
    """
    clean = clean_price_from_market_value(market_value, par_value)
    if clean is None or clean <= 0:
        return None
    years = years_between(asof, maturity)
    if years <= 0:
        return None

    ytm = yield_to_maturity(clean, coupon_pct, years, freq)
    benchmark = interpolate_yield(curve, years) if curve else None
    spread = g_spread_bp(ytm, benchmark) if (ytm is not None and benchmark is not None) else None

    return BondValuation(
        isin=isin,
        name=name,
        coupon_pct=coupon_pct,
        maturity=maturity,
        clean_price=clean,
        accrued=accrued_interest(coupon_pct, years, freq),
        years_to_maturity=years,
        ytm_pct=ytm,
        benchmark_pct=benchmark,
        g_spread_bp=spread,
    )
