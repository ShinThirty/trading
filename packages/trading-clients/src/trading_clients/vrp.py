"""Variance risk premium math (pure functions, no I/O).

VRP = E^Q[sigma^2] - E^P[sigma^2] — what the option market charges for variance
minus what variance actually shows up. It is a *variance* premium, so the
arithmetic happens in variance units (vol^2) and is converted back to vol points
only for display.

Two estimates live here, and the distinction is the whole point of the module:

**Ex-ante** (`vrp_snapshot`) — today's implied vol against a *forecast* of
forward realized vol. This is what you can act on. The naive IV-HV spread
(TastyTrade's `iv-hv-30-day-difference`, surfaced by `get_entry_signals`)
compares forward-looking IV to *trailing* realized vol, so it misreads the
window right after a vol spike. The forecast leg is **HAR-RV** (Corsi 2009),
which learns mean reversion from the daily/weekly/monthly structure of realized
variance. That choice is load-bearing: the first cut used EWMA, whose lack of
mean reversion kept a crash at 40-70% weight for weeks and consequently labelled
*every* name in a sold-off sector "cheap" — a forecast lag masquerading as a
premium. `regime_break` flags the residual contamination HAR does not remove.

**Ex-post** (`vrp_series`) — implied at time t against realized over the *same
forward window*. Only computable after the window closes, and only where a
historical implied series exists (VIX for the index; our providers expose no
per-name IV history). This is the series that says whether the premium was
actually earned, and it supplies the percentile that makes a snapshot readable.

Realized variance here is **not demeaned**, following the realized-variance
literature: at daily frequency the mean return is an order of magnitude below
the noise, and subtracting an estimated mean adds more error than it removes.
`options.historical_volatility` *does* demean — the two will differ slightly by
construction, which is expected and not a bug.
"""

from dataclasses import dataclass
from math import exp, log, sqrt

from trading_clients.table_helpers import kv_table

TRADING_DAYS = 252

# RiskMetrics daily decay. EWMA is a martingale in variance (no mean reversion),
# so the h-day forecast equals the spot estimate — appropriate at a 21-day
# horizon, and knowingly slow to come down after a vol spike. The long-run RV is
# reported alongside so that bias stays visible rather than buried.
EWMA_LAMBDA = 0.94


def log_returns(closes: list[float]) -> list[float]:
    """Daily log returns. Skips non-positive prices rather than raising."""
    out: list[float] = []
    for prev, cur in zip(closes, closes[1:], strict=False):
        if prev > 0 and cur > 0:
            out.append(log(cur / prev))
    return out


def realized_variance(closes: list[float], window: int = 21) -> float | None:
    """Annualized realized variance over the last `window` trading days.

    RV^2 = (252 / n) * sum(r_i^2), non-demeaned. Returns a decimal variance
    (0.04 = 20% vol), or None if there aren't enough bars.
    """
    if len(closes) < window + 1:
        return None
    rets = log_returns(closes[-(window + 1) :])
    if not rets:
        return None
    return (TRADING_DAYS / len(rets)) * sum(r * r for r in rets)


def realized_vol(closes: list[float], window: int = 21) -> float | None:
    """Annualized realized volatility — sqrt of `realized_variance`."""
    var = realized_variance(closes, window)
    return sqrt(var) if var is not None else None


def downside_realized_vol(closes: list[float], window: int = 21) -> float | None:
    """Annualized realized vol computed from down-days only.

    Exists because the comparison at the heart of VRP is asymmetric: realized
    variance weights up- and down-moves identically, but implied vol is anchored
    on the downside via skew. A violent *rally* therefore inflates total RV while
    IV falls, manufacturing a spurious "options are cheap" reading — the failure
    mode that motivated this function.

    Scaled by 2 so that under symmetric returns it equals total realized vol,
    making the two directly comparable. A downside vol far below total vol means
    the move was one-way up, and the total-RV comparison should not be trusted.
    """
    if len(closes) < window + 1:
        return None
    rets = log_returns(closes[-(window + 1) :])
    if not rets:
        return None
    var = (TRADING_DAYS / len(rets)) * 2 * sum(r * r for r in rets if r < 0)
    return sqrt(var)


def trailing_return(closes: list[float], window: int = 21) -> float | None:
    """Simple return over the trailing window, as a decimal."""
    if len(closes) < window + 1 or closes[-(window + 1)] <= 0:
        return None
    return closes[-1] / closes[-(window + 1)] - 1


def ewma_variance(closes: list[float], lam: float = EWMA_LAMBDA) -> float | None:
    """Annualized EWMA variance — the fallback forward-vol forecast.

    Seeded with the sample variance of the first 21 returns, then decayed
    forward. Needs ~60 bars before the seed washes out.

    Superseded by `har_forecast_variance` as the headline forecaster: EWMA has
    no mean reversion, so a crash keeps ~40-70% of its weight for weeks (11-day
    half-life) while implied vol has already normalized. That gap reads as "VRP"
    when it is really forecast lag — it labelled every post-crash name cheap.
    Retained as a fallback for short histories and as a visible cross-check.
    """
    rets = log_returns(closes)
    if len(rets) < 22:
        return None
    seed = rets[:21]
    var = sum(r * r for r in seed) / len(seed)
    for r in rets[21:]:
        var = (1 - lam) * r * r + lam * var
    return var * TRADING_DAYS


def ewma_variance_series(closes: list[float], lam: float = EWMA_LAMBDA) -> list[float | None]:
    """Running EWMA variance aligned to `closes` (one entry per bar).

    Same recursion as `ewma_variance`, exposed as a series so a historical
    ex-ante VRP can be built in one pass instead of recomputing per date.
    Entries before the seed window are None.
    """
    out: list[float | None] = [None] * len(closes)
    rets = log_returns(closes)
    if len(rets) < 22:
        return out
    seed = rets[:21]
    var = sum(r * r for r in seed) / len(seed)
    # rets[i] spans closes[i] -> closes[i+1], so the estimate after consuming
    # rets[i] is known as of closes[i+1].
    out[21] = var * TRADING_DAYS
    for i, r in enumerate(rets[21:], start=21):
        var = (1 - lam) * r * r + lam * var
        if i + 1 < len(out):
            out[i + 1] = var * TRADING_DAYS
    return out


# ── HAR-RV (Corsi 2009) ─────────────────────────────────────
#
# Regresses log forward realized variance on the log of its daily, weekly and
# monthly components. Mean reversion is learned rather than assumed: when the
# daily term spikes far above the monthly, the fitted weights pull the forecast
# back toward the longer horizons — which is exactly the behaviour EWMA lacks.
#
# Out-of-sample check (fit on first 60% of ~1100 bars, scored on the rest;
# SPY/QQQ/MU/NVDA/AMD/LRCX/JPM, 21-day horizon, error = log realized - log
# forecast, so negative means over-forecasting):
#
#                          bias              rmse
#   post-spike  HAR      +0.016  (x1.008)    0.837   n=782
#   (RV pctl>80) EWMA    -0.330  (x0.848)    0.944
#   normal      HAR      -0.018  (x0.991)    0.679   n=2144
#               EWMA     +0.063  (x1.032)    0.714
#
# EWMA over-forecasts vol by ~18% precisely when trailing realized vol is
# elevated, which is what made every post-crash name read "cheap". HAR is
# unbiased in both regimes and lower-RMSE in both. Note the *unconditional*
# EWMA bias is near zero — the two conditional errors cancel — so an aggregate
# backtest would have hidden this entirely.
#
# Caveat this does not fix: per-name fits degrade when a name's vol regime
# shifts inside the training window (MU scored +0.552 post-spike, its forward
# vol running well above the fit). Forecast dispersion stays ~23% higher after
# spikes for every name, which is what `regime_break` warns about.

HAR_MIN_ROWS = 100  # fitted rows required before the model is trusted
_VAR_FLOOR = 1e-6  # keeps log() safe on a flat day


def _solve(a: list[list[float]], b: list[float]) -> list[float] | None:
    """Gauss-Jordan with partial pivoting. None if the system is singular."""
    n = len(b)
    m = [[*row, b[i]] for i, row in enumerate(a)]
    for col in range(n):
        piv = max(range(col, n), key=lambda r: abs(m[r][col]))
        if abs(m[piv][col]) < 1e-12:
            return None
        m[col], m[piv] = m[piv], m[col]
        for r in range(n):
            if r == col:
                continue
            f = m[r][col] / m[col][col]
            for c in range(col, n + 1):
                m[r][c] -= f * m[col][c]
    return [m[i][n] / m[i][i] for i in range(n)]


def _daily_variance(closes: list[float]) -> list[float]:
    """Per-bar annualized variance proxy (r^2 * 252), floored for log safety."""
    return [max(r * r * TRADING_DAYS, _VAR_FLOOR) for r in log_returns(closes)]


def _har_components(dv: list[float], i: int) -> tuple[float, float, float] | None:
    """Daily / weekly / monthly annualized variance as of return index `i`."""
    if i < 21 or i >= len(dv):
        return None
    return dv[i], sum(dv[i - 4 : i + 1]) / 5, sum(dv[i - 21 : i + 1]) / 22


@dataclass(frozen=True)
class HarModel:
    """Fitted HAR-RV coefficients on log variance."""

    coef: list[float]  # intercept, beta_daily, beta_weekly, beta_monthly
    resid_var: float
    rows: int

    def predict(self, daily: float, weekly: float, monthly: float) -> float:
        c = self.coef
        y = c[0] + c[1] * log(daily) + c[2] * log(weekly) + c[3] * log(monthly)
        # Lognormal retransformation: E[exp(y)] = exp(mu + sigma^2 / 2). Without
        # it the level forecast is biased low by roughly half the residual var.
        return exp(y + self.resid_var / 2)


def fit_har(closes: list[float], horizon: int = 21) -> HarModel | None:
    """Fit HAR-RV by OLS, targeting mean annualized variance over `horizon`.

    Direct multi-horizon form — the regressand is the realized variance actually
    delivered over the next `horizon` bars, so the fit answers the question the
    VRP asks rather than a one-step-ahead proxy that must then be scaled.

    Training rows overlap by horizon-1 bars, so the coefficients are consistent
    but their standard errors would be understated. We use point forecasts only
    and never report significance, so the overlap is harmless here.
    """
    dv = _daily_variance(closes)
    rows: list[list[float]] = []
    ys: list[float] = []
    for i in range(21, len(dv) - horizon):
        comp = _har_components(dv, i)
        if comp is None:
            continue
        fwd = sum(dv[i + 1 : i + 1 + horizon]) / horizon
        if fwd <= 0:
            continue
        rows.append([1.0, log(comp[0]), log(comp[1]), log(comp[2])])
        ys.append(log(fwd))

    if len(rows) < HAR_MIN_ROWS:
        return None

    k = 4
    xtx = [[sum(r[a] * r[b] for r in rows) for b in range(k)] for a in range(k)]
    xty = [sum(r[a] * y for r, y in zip(rows, ys, strict=True)) for a in range(k)]
    coef = _solve(xtx, xty)
    if coef is None:
        return None

    resid = [
        y - sum(c * x for c, x in zip(coef, r, strict=True)) for r, y in zip(rows, ys, strict=True)
    ]
    resid_var = sum(e * e for e in resid) / max(len(resid) - k, 1)
    return HarModel(coef=coef, resid_var=resid_var, rows=len(rows))


def har_forecast_variance(closes: list[float], horizon: int = 21) -> float | None:
    """Annualized variance expected over the next `horizon` bars, via HAR-RV."""
    model = fit_har(closes, horizon)
    if model is None:
        return None
    dv = _daily_variance(closes)
    comp = _har_components(dv, len(dv) - 1)
    return model.predict(*comp) if comp else None


def har_variance_series(closes: list[float], horizon: int = 21) -> list[float | None]:
    """HAR forecast at each bar, aligned to `closes`.

    Fits once on the full sample and applies those coefficients to every date's
    contemporaneous features. The coefficients therefore carry mild look-ahead;
    that is acceptable because this series is only used to *rank* today's
    reading against its own history, and a constant coefficient set shifts every
    observation alike, leaving the ranking intact.
    """
    out: list[float | None] = [None] * len(closes)
    model = fit_har(closes, horizon)
    if model is None:
        return out
    dv = _daily_variance(closes)
    for i in range(len(dv)):
        comp = _har_components(dv, i)
        if comp is None:
            continue
        # dv[i] spans closes[i] -> closes[i+1], so it is known at closes[i+1].
        if i + 1 < len(out):
            out[i + 1] = model.predict(*comp)
    return out


def percentile_rank(history: list[float], value: float) -> float | None:
    """Percent of `history` strictly below `value` (0-100)."""
    if not history:
        return None
    return 100.0 * sum(1 for h in history if h < value) / len(history)


def classify(ratio: float) -> tuple[str, str]:
    """Map IV/forecast-RV to a (label, action) pair.

    Bands are on the ratio rather than raw vol points because single-name spreads
    scale with the level of vol — a +5 point spread is rich on a 15-vol name and
    unremarkable on a 60-vol one.
    """
    if ratio >= 1.30:
        return "Rich", "favors selling premium"
    if ratio >= 1.10:
        return "Modestly rich", "mild edge to selling premium"
    if ratio >= 0.95:
        return "Fair", "no vol edge either way — trade direction, not vol"
    return "Cheap", "favors buying premium"


@dataclass(frozen=True)
class VrpSnapshot:
    """Today's ex-ante read: implied vol vs forecast forward realized vol."""

    symbol: str
    implied_vol: float  # decimal, e.g. 0.28
    rv_short: float | None  # trailing 21d
    rv_long: float | None  # trailing 252d
    rv_forecast: float | None  # EWMA
    rv_short_percentile: float | None  # trailing 21d RV vs its own 1y history
    rv_downside: float | None = None  # down-days only, 2x-scaled
    trailing_return: float | None = None  # simple return over the short window
    short_window: int = 21  # bars behind rv_short / rv_downside / trailing_return
    rv_forecast_ewma: float | None = None  # the superseded forecaster, for contrast
    forecast_method: str = "EWMA"  # "HAR" when the fit succeeded

    @property
    def regime_break(self) -> bool:
        """True when trailing RV sits in the top fifth of its own year.

        This is a *precision* warning, not a bias one. HAR is measured unbiased
        in this regime (see the calibration table above), so the ratio is not
        systematically wrong — but forecast dispersion runs ~23% higher here
        (RMSE 0.837 vs 0.679), so any single reading deserves less weight.
        Rank against peers rather than acting on the level alone.
        """
        return self.rv_short_percentile is not None and self.rv_short_percentile > 80

    @property
    def upmove_artifact(self) -> bool:
        """True when total RV is inflated by a one-way rally.

        Realized variance is direction-blind; implied vol is skew-anchored on the
        downside. When the window rallied hard and downside vol sits well under
        total vol, the "options are cheap" reading is an artifact of that
        asymmetry, not a tradeable edge.
        """
        if self.rv_downside is None or self.rv_short is None or self.trailing_return is None:
            return False
        return self.trailing_return > 0.04 and self.rv_downside < 0.75 * self.rv_short

    @property
    def ratio(self) -> float | None:
        if not self.rv_forecast:
            return None
        return self.implied_vol / self.rv_forecast

    @property
    def vrp_vol_points(self) -> float | None:
        """Ex-ante VRP in vol points (IV - forecast RV)."""
        if self.rv_forecast is None:
            return None
        return (self.implied_vol - self.rv_forecast) * 100

    @property
    def vrp_variance_points(self) -> float | None:
        """Ex-ante VRP in variance points (IV^2 - forecast RV^2), x10000."""
        if self.rv_forecast is None:
            return None
        return (self.implied_vol**2 - self.rv_forecast**2) * 10000

    @property
    def naive_vol_points(self) -> float | None:
        """The IV-HV spread, for continuity with `get_entry_signals`."""
        if self.rv_short is None:
            return None
        return (self.implied_vol - self.rv_short) * 100

    def to_output(self) -> str:
        w = self.short_window
        data: dict[str, str] = {"IV (30d)": f"{self.implied_vol * 100:.1f}%"}
        if self.rv_short is not None:
            data[f"RV trailing ({w}d)"] = f"{self.rv_short * 100:.1f}%"
        if self.rv_long is not None:
            data["RV trailing (252d)"] = f"{self.rv_long * 100:.1f}%"
        if self.rv_forecast is not None:
            data[f"RV forecast ({self.forecast_method})"] = f"{self.rv_forecast * 100:.1f}%"
        if self.rv_forecast_ewma is not None and self.forecast_method != "EWMA":
            data["RV forecast (EWMA, superseded)"] = f"{self.rv_forecast_ewma * 100:.1f}%"
        if self.rv_downside is not None:
            data[f"RV downside-only ({w}d)"] = f"{self.rv_downside * 100:.1f}%"
        if self.trailing_return is not None:
            data[f"Trailing return ({w}d)"] = f"{self.trailing_return * 100:+.1f}%"

        vol_pts = self.vrp_vol_points
        var_pts = self.vrp_variance_points
        ratio = self.ratio
        if vol_pts is not None and var_pts is not None and ratio is not None:
            label, action = classify(ratio)
            data["VRP (vol pts)"] = f"{vol_pts:+.1f}"
            data["VRP (variance pts)"] = f"{var_pts:+.0f}"
            data["IV / forecast RV"] = f"{ratio:.2f}"
            data["Read"] = f"{label} — {action}"
            if self.upmove_artifact:
                data["Read"] = f"{label} (⚠ suspect)"
                data["⚠ Up-move artifact"] = (
                    "the window rallied and downside vol is far below total vol, so "
                    "realized variance is inflated by up-days that IV never prices. "
                    "This biases the read toward 'cheap' — compare IV to the "
                    "downside-only row instead, or re-run once the tape two-sides."
                )

        naive = self.naive_vol_points
        if naive is not None and vol_pts is not None:
            data["IV-HV (naive, trailing)"] = f"{naive:+.1f}"
            if abs(naive - vol_pts) >= 3:
                stale = (
                    "elevated" if (self.rv_short or 0) > (self.rv_forecast or 0) else "depressed"
                )
                data["⚠ Divergence"] = (
                    f"naive spread differs from forecast-based VRP by "
                    f"{abs(naive - vol_pts):.1f} pts — trailing RV is {stale} "
                    f"vs forecast. Trust the forecast row."
                )

        if self.rv_short_percentile is not None:
            data["Trailing RV percentile (1y)"] = f"{self.rv_short_percentile:.0f}%"
            if self.regime_break:
                data["⚠ Regime break"] = (
                    "trailing RV is in the top fifth of its own year. The forecast is "
                    "unbiased here but ~23% noisier, so weight this single reading less "
                    "and rank it against sector peers — after a sector-wide selloff the "
                    "whole group shifts together, and the spread between names carries "
                    "more information than any one level."
                )

        return kv_table(data)


@dataclass(frozen=True)
class VrpSeries:
    """Ex-post aligned VRP history — implied at t vs realized over t -> t+h."""

    label: str
    horizon_days: int
    observations: list[tuple[str, float, float, float]]  # date, iv, rv_fwd, vrp_var_pts

    @property
    def vrp_values(self) -> list[float]:
        return [o[3] for o in self.observations]

    @property
    def hit_rate(self) -> float | None:
        """Share of windows where the premium was actually positive."""
        vals = self.vrp_values
        if not vals:
            return None
        return 100.0 * sum(1 for v in vals if v > 0) / len(vals)

    @property
    def mean(self) -> float | None:
        vals = self.vrp_values
        return sum(vals) / len(vals) if vals else None

    @property
    def independent_windows(self) -> int:
        """Non-overlapping window count.

        A daily rolling series overlaps h-1/h with its neighbours, so the raw
        observation count wildly overstates the evidence. This is the honest n.
        """
        return len(self.observations) // self.horizon_days if self.horizon_days else 0

    def percentile_of(self, value: float) -> float | None:
        return percentile_rank(self.vrp_values, value)

    def to_output(self) -> str:
        if not self.observations:
            return "(no aligned observations)"
        mean = self.mean
        data: dict[str, str] = {
            "Window": f"{self.horizon_days} trading days forward",
            "Observations": (
                f"{len(self.observations)} overlapping ({self.independent_windows} independent)"
            ),
        }
        if mean is not None:
            data["Mean VRP (variance pts)"] = f"{mean:+.0f}"
        hit = self.hit_rate
        if hit is not None:
            data["Premium earned"] = f"{hit:.0f}% of windows"
        first, last = self.observations[0][0], self.observations[-1][0]
        data["Range"] = f"{first} → {last}"
        return kv_table(data)


def vrp_snapshot(
    symbol: str,
    implied_vol: float,
    closes: list[float],
    short_window: int = 21,
    long_window: int = TRADING_DAYS,
) -> VrpSnapshot:
    """Build today's ex-ante VRP read from an IV quote and a price history.

    implied_vol: decimal (0.28 for 28%), typically the 30-day IV.
    closes: daily closing prices, oldest first.
    """
    rv_short = realized_vol(closes, short_window)
    rv_long = realized_vol(closes, long_window)

    ewma_var = ewma_variance(closes)
    rv_ewma = sqrt(ewma_var) if ewma_var is not None else None
    har_var = har_forecast_variance(closes, short_window)

    # HAR is the headline forecaster; EWMA is the fallback for short histories.
    if har_var is not None:
        rv_forecast, method = sqrt(har_var), "HAR"
    else:
        rv_forecast, method = rv_ewma, "EWMA"

    rv_history: list[float] = []
    if len(closes) > short_window + TRADING_DAYS:
        for end in range(len(closes) - TRADING_DAYS, len(closes) + 1):
            rv = realized_vol(closes[:end], short_window)
            if rv is not None:
                rv_history.append(rv)

    pctl = percentile_rank(rv_history, rv_short) if rv_short is not None else None

    return VrpSnapshot(
        symbol=symbol,
        implied_vol=implied_vol,
        rv_short=rv_short,
        rv_long=rv_long,
        rv_forecast=rv_forecast,
        rv_short_percentile=pctl,
        rv_downside=downside_realized_vol(closes, short_window),
        trailing_return=trailing_return(closes, short_window),
        short_window=short_window,
        rv_forecast_ewma=rv_ewma,
        forecast_method=method,
    )


def vrp_series(
    label: str,
    implied: list[tuple[str, float]],
    closes: list[tuple[str, float]],
    horizon_days: int = 21,
) -> VrpSeries:
    """Build the ex-post aligned series from a historical implied-vol series.

    implied: (date, vol as decimal) pairs, oldest first — e.g. VIXCLS / 100.
    closes: (date, close) pairs, oldest first, for the same underlying.
    horizon_days: forward realized window in trading days (21 ~= VIX's 30
        calendar days).

    Each observation pairs the implied vol quoted on date t with the variance
    that actually realized over the following `horizon_days` bars.
    """
    by_date = {d: i for i, (d, _) in enumerate(closes)}
    prices = [c for _, c in closes]

    obs: list[tuple[str, float, float, float]] = []
    for d, iv in implied:
        idx = by_date.get(d)
        if idx is None or idx + horizon_days >= len(prices):
            continue
        window = prices[idx : idx + horizon_days + 1]
        rets = log_returns(window)
        if not rets:
            continue
        rv_var = (TRADING_DAYS / len(rets)) * sum(r * r for r in rets)
        obs.append((d, iv, sqrt(rv_var), (iv**2 - rv_var) * 10000))

    return VrpSeries(label=label, horizon_days=horizon_days, observations=obs)


def ex_ante_history(
    implied: list[tuple[str, float]],
    closes: list[tuple[str, float]],
    horizon: int = 21,
) -> list[float]:
    """Historical *ex-ante* VRP (variance points), computed exactly as today's.

    Pairs each date's implied vol with the HAR forecast available on that date —
    the same forecaster the live snapshot uses, so percentiling today's reading
    against this stays like-for-like. Both legs are forecasts, so a high
    percentile means implied is unusually rich *relative to what was knowable at
    the time*, not relative to hindsight.

    Falls back to EWMA when the HAR fit is unavailable, which keeps the series
    internally consistent (every observation uses one forecaster) even on a
    short history.
    """
    by_date = {d: i for i, (d, _) in enumerate(closes)}
    prices = [c for _, c in closes]
    forecasts = har_variance_series(prices, horizon)
    if all(f is None for f in forecasts):
        forecasts = ewma_variance_series(prices)

    out: list[float] = []
    for d, iv in implied:
        idx = by_date.get(d)
        if idx is None:
            continue
        var = forecasts[idx]
        if var is None:
            continue
        out.append((iv**2 - var) * 10000)
    return out
