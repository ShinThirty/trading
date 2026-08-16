"""Option analytics: chains, expected move, strategy/roll analysis, comparators,
IV metrics, projection grid, and covered-call overlay tools.
"""

import asyncio
from dataclasses import dataclass
from datetime import date, timedelta
from math import gcd, sqrt

from fastmcp import Context, FastMCP
from trading_clients import options as opts
from trading_clients import vrp
from trading_clients.bsm import bsm_price
from trading_clients.endpoint import CONTRACT_MULTIPLIER
from trading_clients.endpoints import fred as fr
from trading_clients.endpoints import tastytrade as tt
from trading_clients.endpoints import tradier as t
from trading_clients.endpoints.webull import (
    ORDER_HISTORY,
    POSITIONS,
    AccountRequest,
    GetOrderHistoryRequest,
)
from trading_clients.options import EnrichedLeg
from trading_clients.table_helpers import fmt_number, kv_table, list_table, to_float, to_float_zero
from trading_clients.tradier_client import TradierClient

from trading_mcp.helpers import (
    _HV_EFF_FLOOR,
    _fred,
    _hv_effective_n,
    _retry,
    _tastytrade,
    _tradier,
    _webull,
)
from trading_mcp.portfolio_fetching import _fetch_risk_free_rate

mcp = FastMCP("options-tools")


# ── Chain discovery ─────────────────────────────────────────


@mcp.tool()
async def get_option_expirations(ctx: Context, symbol: str) -> str:
    """Get all available option expiration dates for an underlying symbol.
    Use this first to discover which expirations are available before fetching
    the full chain.

    symbol: underlying ticker symbol (e.g. 'AAPL', 'SPY', 'TSLA').
    Returns a list of expiration dates as strings (YYYY-MM-DD).

    Requires [tradier] section in ~/.tradingrc.
    """
    return (await _tradier(ctx).get(t.EXPIRATIONS, t.GetExpirationsRequest(symbol))).to_output()


@mcp.tool()
async def get_option_strikes(ctx: Context, symbol: str, expiration: str) -> str:
    """Get all available strike prices for an underlying symbol at a specific expiration.

    symbol: underlying ticker symbol (e.g. 'AAPL').
    expiration: expiration date (YYYY-MM-DD, from get_option_expirations).
    Returns a list of strike prices as numbers.

    Requires [tradier] section in ~/.tradingrc.
    """
    return (await _tradier(ctx).get(t.STRIKES, t.GetStrikesRequest(symbol, expiration))).to_output()


@mcp.tool()
async def get_option_chain(
    ctx: Context,
    symbol: str,
    expiration: str,
    greeks: bool = True,
    strike_count: int = 15,
) -> str:
    """Get the option chain for an underlying symbol at a specific expiration.

    Returns calls and puts near the money with: bid/ask with sizes, last price,
    day change/%, volume, open interest, and optionally greeks (IV, delta, gamma,
    theta, vega, rho).

    symbol: underlying ticker symbol (e.g. 'AAPL').
    expiration: expiration date (YYYY-MM-DD, from get_option_expirations).
    greeks: include greeks and IV per contract (default True).
    strike_count: number of strikes above and below ATM to include (default 15).
      Set to 0 for the full unfiltered chain.

    Typical workflow:
    1. get_option_expirations('AAPL') → list of dates
    2. get_option_chain('AAPL', '2026-04-17') → chain with greeks

    Requires [tradier] section in ~/.tradingrc.
    """
    tradier = _tradier(ctx)
    quote_resp, resp = await asyncio.gather(
        tradier.get(t.QUOTES, t.GetQuotesRequest(symbol, greeks=False)),
        tradier.get(t.CHAIN, t.GetChainRequest(symbol, expiration, greeks)),
    )
    last_price = quote_resp.quotes[0].get("last", 0) if quote_resp.quotes else 0
    if resp.options and strike_count > 0 and last_price:
        strikes = sorted({o["strike"] for o in resp.options})
        atm_idx = min(range(len(strikes)), key=lambda i: abs(strikes[i] - last_price))
        lo = max(0, atm_idx - strike_count)
        hi = min(len(strikes), atm_idx + strike_count + 1)
        keep = set(strikes[lo:hi])
        resp.options = [o for o in resp.options if o["strike"] in keep]
    return resp.to_output()


@mcp.tool()
async def get_option_lookup(ctx: Context, underlying: str) -> str:
    """Get all option symbols for an underlying, including alternate roots (e.g. SPXW
    for SPX weeklies). Useful for discovering available option contracts before pulling
    historical data with get_tradier_history.

    underlying: ticker symbol (e.g. 'AAPL', 'SPX', 'SPY').
    Returns a list of OCC option symbols (e.g. 'AAPL260417C00260000').

    Requires [tradier] section in ~/.tradingrc.
    """
    return (await _tradier(ctx).get(t.OPTION_LOOKUP, t.GetLookupRequest(underlying))).to_output()


# ── IV metrics ──────────────────────────────────────────────


@mcp.tool()
async def get_iv_metrics(ctx: Context, symbols: str) -> str:
    """Get implied volatility metrics: IV rank, IV percentile, IV index, 5-day IV change,
    30-day IV/HV, 60-day HV, 90-day HV, next earnings date, liquidity rating, and the
    timestamp the IV figures were last computed.

    IV Rank shows where current IV sits relative to its 52-week high/low (0-100).
    IV Percentile shows what % of days in the past year had lower IV (0-100%).
    IV 5d Chg shows how IV index moved over the last 5 days (expanding/contracting).
    HV 60d/90d provide longer historical vol windows to compare against IV.
    Liquidity rating is 1-4 stars: 3-4 = tight spreads (most liquid), 1-2 = wider spreads.
    Use these to time premium-selling strategies: high IV Rank = rich premiums.

    symbols: comma-separated ticker symbols (e.g. 'AAPL,QCOM,ADBE').

    Requires [tastytrade] section in ~/.tradingrc.
    """
    resp = await _tastytrade(ctx).get(tt.MARKET_METRICS, tt.MarketMetricsRequest(symbols))
    return resp.to_output()


_VOL_REGIME_SHIFT = 1.15  # HV20/HV50 ratio at which the trailing read is actively stale


def _vol_verdict(
    atm_iv: float | None,
    hv20: float | None,
    hv50: float | None,
    closes: list[float] | None = None,
) -> dict[str, str]:
    """Report the trailing IV/HV ratio as data, and route the verdict to VRP.

    This ratio used to carry a cheap/rich label, but it compares forward-looking IV to
    *trailing* realized vol, so after a vol spike it reads "cheap" exactly when forward
    vol is about to mean-revert down and the options are not cheap. WDC and AMD both
    printed 0.70 "cheap" days after their earnings gaps while the forecast-based read
    put them at fair.

    The verdict is delegated rather than recomputed here. `get_variance_risk_premium`
    fits HAR on ~1,600 calendar days and prices it against constant-maturity 30-day IV;
    this tool holds ~155 bars (HAR needs 100 rows to fit at all) and the ATM IV of one
    expiration. Fitting a second, weaker forecast here produced a materially different
    number for the same question — a competing source of truth is worse than no label.
    """
    out: dict[str, str] = {}
    if atm_iv is None or hv20 is None or hv20 <= 0:
        return out

    out["IV/HV Ratio (trailing)"] = f"{atm_iv / hv20:.2f}"
    note = (
        "trailing HV, not a forecast — reads 'cheap' right after a vol spike. "
        "Run get_variance_risk_premium for the cheap/rich verdict."
    )
    # An HV20-vs-HV50 gap catches a drifting vol regime, but NOT the case this whole
    # check exists for: a gap bar sits in both windows, so they agree with each other
    # while both run hot against forward vol. The concentration statistic sees it.
    concentrated = _hv_effective_n(closes) if closes else None
    if concentrated is not None and concentrated[0] < _HV_EFF_FLOOR:
        note = (
            f"⚠ one bar drives {concentrated[1]:.0f}% of recent variance "
            f"(~{concentrated[0]:.1f} effective bars) — the HV figures above are "
            "event-inflated, so this ratio understates how rich the options are. "
            "Run get_variance_risk_premium before acting on it."
        )
    elif hv50 is not None and hv50 > 0 and max(hv20 / hv50, hv50 / hv20) >= _VOL_REGIME_SHIFT:
        direction = "cooling" if hv20 < hv50 else "heating"
        note = (
            f"⚠ vol regime is {direction} (HV20 {hv20 * 100:.0f}% vs HV50 "
            f"{hv50 * 100:.0f}%), so this trailing ratio is stale in a known direction. "
            "Run get_variance_risk_premium before acting on it."
        )
    out["Vol read"] = note
    return out


@mcp.tool()
async def get_expected_move(ctx: Context, symbol: str, expiration: str) -> str:
    """Compute the expected move for a stock at a given option expiration.

    Shows the ATM straddle price (expected 1-sigma move), implied volatility,
    historical volatility, and IV/HV ratio. Useful for sizing positions.

    The IV/HV ratio is reported WITHOUT a cheap/rich verdict: it measures forward IV
    against trailing realized vol, which reads "cheap" precisely after a vol spike,
    when forward vol is about to mean-revert down. Use get_variance_risk_premium for
    the cheap/rich call — it forecasts forward realized vol instead. This tool flags
    when a vol-regime shift makes the trailing ratio stale in a known direction.

    symbol: underlying ticker symbol (e.g. 'AAPL').
    expiration: option expiration date (YYYY-MM-DD, from get_option_expirations).

    Requires [tradier] section in ~/.tradingrc.
    """
    tradier = _tradier(ctx)

    quote, chain, history = await asyncio.gather(
        tradier.get(t.QUOTES, t.GetQuotesRequest(symbol, greeks=False)),
        tradier.get(t.CHAIN, t.GetChainRequest(symbol, expiration, greeks=True)),
        tradier.get(t.HISTORY, t.GetHistoryRequest(symbol, "daily")),
    )

    if not quote.quotes:
        return f"(no quote for {symbol})"
    stock_price = float(quote.quotes[0].get("last") or quote.quotes[0].get("close", 0))

    if not chain.options:
        return f"(no option chain for {symbol} at {expiration})"

    em = opts.expected_move(chain.options, stock_price)

    closes = [float(b["close"]) for b in history.days] if history.days else []
    hv20 = opts.historical_volatility(closes, 20)
    hv50 = opts.historical_volatility(closes, 50)

    data: dict[str, str] = {"Stock Price": fmt_number(stock_price)}
    data["Expiration"] = expiration

    if em["straddle_price"] is not None:
        straddle = em["straddle_price"]
        data["ATM Straddle"] = fmt_number(straddle)
        data["Expected Move"] = f"±${fmt_number(straddle)} ({fmt_number(em['expected_move_pct'])}%)"
        data["Expected Range"] = (
            f"${fmt_number(stock_price - straddle)} — ${fmt_number(stock_price + straddle)}"
        )
        data["ATM Strikes"] = f"Call {em['atm_call_strike']}, Put {em['atm_put_strike']}"

    if em["atm_iv"] is not None:
        data["Implied Volatility"] = f"{em['atm_iv'] * 100:.1f}%"

    if hv20 is not None:
        data["Historical Vol (20d)"] = f"{hv20 * 100:.1f}%"
    if hv50 is not None:
        data["Historical Vol (50d)"] = f"{hv50 * 100:.1f}%"

    data.update(_vol_verdict(em["atm_iv"], hv20, hv50, closes))

    return f"## {symbol} Expected Move ({expiration})\n\n{kv_table(data)}"


# ── Variance risk premium ───────────────────────────────────

# VIX measures 30-calendar-day implied variance; 21 trading days is its realized
# equivalent, so that is the default forward window for the aligned series.
_VRP_HORIZON_DAYS = 21
# ~4.3 years of bars: enough for a 1y RV-percentile history (needs 252 windows
# each with 21 bars of runway) plus a multi-year ex-post VIX series.
_VRP_HISTORY_DAYS = 1600


@mcp.tool()
async def get_variance_risk_premium(
    ctx: Context,
    symbol: str,
    horizon_days: int = _VRP_HORIZON_DAYS,
    index_context: bool = True,
) -> str:
    """Measure the variance risk premium — whether options are priced above or
    below the variance the underlying actually delivers. Use before any decision
    to buy or sell premium.

    Reports the ex-ante VRP: current 30-day IV against an EWMA forecast of
    forward realized vol. This is sharper than the raw IV-HV spread from
    get_iv_metrics / get_entry_signals, which compares forward-looking IV to
    *trailing* realized vol and therefore reads deeply negative right after a
    vol spike — exactly when forward VRP is richest. When the two disagree by
    3+ vol points the output flags it; trust the forecast row.

    Read: ratio >= 1.30 rich (favors selling premium), 1.10-1.30 modestly rich,
    0.95-1.10 fair (no vol edge — trade direction instead), <0.95 cheap (favors
    buying premium — straddles, long calls/puts, debit spreads).

    With index_context (default on), also calibrates against SPX: the ex-post
    VIX-vs-realized series showing how often the index premium was actually
    earned, and where today's index VRP sits in its own history. Index VRP is
    largely a correlation premium and runs persistently richer than single-name
    VRP — do not read a single name's ratio against the index's typical level.

    symbol: underlying ticker (e.g. 'QQQ', 'NVDA').
    horizon_days: forward realized window in trading days (default 21 ~= 30
        calendar days, matching the 30-day IV and VIX).
    index_context: include the SPX/VIX calibration block (needs [fred]).

    Requires [tastytrade] and [tradier]; [fred] for index context.
    """
    tastytrade = _tastytrade(ctx)
    tradier = _tradier(ctx)
    sym = symbol.upper()
    start = (date.today() - timedelta(days=_VRP_HISTORY_DAYS)).isoformat()

    want_index = index_context and sym not in {"SPY", "SPX", "^GSPC"}

    async def _histories() -> tuple[object, object | None]:
        # Intra-provider calls stay sequential (shared rate bucket).
        own = await tradier.get(t.HISTORY, t.GetHistoryRequest(sym, "daily", start=start))
        spy = None
        if index_context:
            spy = (
                own
                if not want_index
                else await tradier.get(t.HISTORY, t.GetHistoryRequest("SPY", "daily", start=start))
            )
        return own, spy

    jobs: list = [
        tastytrade.get(tt.MARKET_METRICS, tt.MarketMetricsRequest(sym)),
        _histories(),
    ]
    fred = None
    if index_context:
        try:
            fred = _fred(ctx)
            jobs.append(fred.get(fr.OBSERVATIONS, fr.GetObservationsRequest("VIXCLS", limit=1300)))
        except RuntimeError:
            fred = None

    results = await asyncio.gather(*jobs, return_exceptions=True)
    iv_r, hist_r = results[0], results[1]
    vix_r = results[2] if len(results) > 2 else None

    if isinstance(hist_r, BaseException):
        return f"(no price history for {sym}: {hist_r})"
    own_hist, spy_hist = hist_r

    bars = getattr(own_hist, "days", None) or []
    closes = [float(b["close"]) for b in bars]
    if len(closes) < 80:
        return f"(insufficient price history for {sym} — {len(closes)} bars, need 80+)"

    iv_item = {}
    if not isinstance(iv_r, BaseException) and getattr(iv_r, "items", None):
        iv_item = iv_r.items[0]

    # `implied-volatility-30-day` arrives already in percent units; the
    # `implied-volatility-index` fallback is a decimal ratio.
    iv_30 = to_float(iv_item.get("implied-volatility-30-day"))
    implied = (
        iv_30 / 100 if iv_30 is not None else to_float(iv_item.get("implied-volatility-index"))
    )
    if implied is None or implied <= 0:
        return f"(no implied volatility available for {sym} — TastyTrade returned no IV metrics)"

    snap = vrp.vrp_snapshot(sym, implied, closes, short_window=horizon_days)

    out = [f"## {sym} Variance Risk Premium\n", snap.to_output()]

    liq = iv_item.get("liquidity-rating")
    if liq:
        out.append(f"\nLiquidity: {liq}/4 — spread friction erodes a thin edge.")

    # ── SPX / VIX calibration ───────────────────────────────
    if index_context and fred is not None and not isinstance(vix_r, BaseException) and vix_r:
        spy_bars = getattr(spy_hist, "days", None) or []
        spy_closes = [(str(b["date"]), float(b["close"])) for b in spy_bars]
        vix_obs = [
            (str(o.get("date")), float(o["value"]) / 100)
            for o in vix_r.observations
            if o.get("value") not in (None, "", ".")
        ]
        vix_obs.sort(key=lambda x: x[0])

        if vix_obs and spy_closes:
            series = vrp.vrp_series("SPX", vix_obs, spy_closes, horizon_days=horizon_days)
            ex_ante = vrp.ex_ante_history(vix_obs, spy_closes, horizon=horizon_days)

            out.append("\n### SPX calibration (VIX vs realized)\n")
            out.append(series.to_output())

            spy_only = [c for _, c in spy_closes]
            spy_var = vrp.har_forecast_variance(spy_only, horizon_days)
            method = "HAR"
            if spy_var is None:
                spy_var, method = vrp.ewma_variance(spy_only), "EWMA"
            today_vix = vix_obs[-1][1]
            if spy_var is not None:
                today_idx_vrp = (today_vix**2 - spy_var) * 10000
                pctl = vrp.percentile_rank(ex_ante, today_idx_vrp)
                data = {
                    "VIX": f"{today_vix * 100:.1f}%",
                    f"SPY RV forecast ({method})": f"{sqrt(spy_var) * 100:.1f}%",
                    "Index VRP today (variance pts)": f"{today_idx_vrp:+.0f}",
                }
                if pctl is not None:
                    data["Percentile vs own history"] = f"{pctl:.0f}%"
                out.append("\n" + kv_table(data))
                out.append(
                    "\nPercentile is like-for-like (today's forecast-based VRP against "
                    "the same calculation historically), not against the ex-post table above."
                )
    elif index_context and fred is None:
        out.append("\n(index context skipped — [fred] not configured)")

    if sym not in {"SPY", "SPX", "^GSPC"}:
        out.append(
            f"\n**No {sym} VRP percentile**: no provider exposes a per-name historical IV "
            "series, so the snapshot has no self-history to rank against. The trailing-RV "
            "percentile above is the available substitute — high RV percentile with a rich "
            "ratio usually means IV is chasing a move that already happened."
        )

    out.append(
        "\n⚠ Caveats: VRP concentrates in the OTM put wing, so a 15Δ put seller earns more "
        "than this ATM-anchored number implies; single-name VRP is much thinner than index "
        "VRP (the index premium is largely a correlation premium); and the premium is "
        "conditional — it can go negative into a known event."
    )

    return "\n".join(out)


# TODO(positioning-trend): Tradier exposes OI only as a live snapshot, not as a
# series — so we can't see OI accumulating into a print. Add a scheduled task
# that writes daily positioning rows (Vol P/C, OI P/C, Δ-Skew per expiration)
# for every pipeline ticker into ~/.trading/trading.db, then extend this tool
# with a `lookback_days` param that renders a trend column alongside today's
# snapshot. Build after the 2026-05-28 software basket validates the playbook;
# reuses the trading-alerts EventBridge harness. See conversation 2026-05-27
# for the design discussion (Path B).
@mcp.tool()
async def get_options_positioning(
    ctx: Context,
    symbol: str,
    expiration: str | None = None,
    dte_max: int = 60,
    atm_band_pct: float = 2.0,
) -> str:
    """Read single-name put/call positioning from the option chain.

    Aggregates volume and open interest across all strikes within a DTE window
    (or one specific expiration) and bins them by moneyness (OTM / ATM / ITM).
    Surfaces three positioning lenses:

      - Volume P/C ratio (today's fresh flow direction)
      - OI P/C ratio (accumulated positioning by contract count)
      - Delta-weighted skew (-1 to +1, dealer-book exposure — accounts for
        moneyness so 5Δ wing OI counts less than ATM OI)

    Plus a 5-tier regime classifier (Concentrated Bull / Tilted Bull / Balanced /
    Tilted Bear / Concentrated Bear) keyed off delta-skew, and a per-expiration
    term-structure breakdown that shows whether front-week positioning
    (event-driven) diverges from back-month positioning (structural).

    symbol: underlying ticker (e.g. 'SNOW').
    expiration: option expiration date (YYYY-MM-DD). If set, restricts to that
      single expiration (skips term-structure view). If None, aggregates across
      all expirations within dte_max.
    dte_max: maximum days to expiration to include when expiration is None
      (default 60). Ignored if expiration is set.
    atm_band_pct: half-width of the ATM band as % of spot (default 2.0).

    Requires [tradier] section in ~/.tradingrc.
    """
    tradier = _tradier(ctx)

    today = date.today()
    if expiration is not None:
        target_exps = [expiration]
    else:
        exp_resp = await tradier.get(t.EXPIRATIONS, t.GetExpirationsRequest(symbol))
        if not exp_resp.dates:
            return f"(no expirations for {symbol})"
        target_exps = [
            d for d in exp_resp.dates if 1 <= (date.fromisoformat(d) - today).days <= dte_max
        ]
        if not target_exps:
            return f"(no expirations for {symbol} within {dte_max} DTE)"

    quote_resp, *chain_resps = await asyncio.gather(
        tradier.get(t.QUOTES, t.GetQuotesRequest(symbol, greeks=False)),
        *[tradier.get(t.CHAIN, t.GetChainRequest(symbol, exp, greeks=True)) for exp in target_exps],
    )

    if not quote_resp.quotes:
        return f"(no quote for {symbol})"
    stock_price = float(quote_resp.quotes[0].get("last") or quote_resp.quotes[0].get("close", 0))
    if not stock_price:
        return f"(no usable price for {symbol})"

    per_exp: list[tuple[str, int, dict]] = []
    for exp, chain_resp in zip(target_exps, chain_resps, strict=True):
        if not chain_resp.options:
            continue
        p = opts.options_positioning(chain_resp.options, stock_price, atm_band_pct)
        try:
            dte = (date.fromisoformat(exp) - today).days
        except ValueError:
            dte = 0
        per_exp.append((exp, dte, p))

    if not per_exp:
        return f"(no option chains for {symbol})"

    if len(per_exp) == 1:
        agg = per_exp[0][2]
    else:
        agg = opts.aggregate_positioning([p for _e, _d, p in per_exp], stock_price, atm_band_pct)

    def _ratio(v: float | int | None) -> str:
        if v is None:
            return "n/a"
        return f"{float(v):.2f}"

    def _skew(v: float | int | None) -> str:
        if v is None:
            return "n/a"
        return f"{float(v):+.2f}"

    def _divergence_tag(vol_pc: float | None, oi_pc: float | None) -> str | None:
        if vol_pc is None or oi_pc is None or oi_pc <= 0:
            return None
        ratio = vol_pc / oi_pc
        if ratio > 1.3:
            return "fresh flow tilting put-heavy vs accumulated OI"
        if ratio < 0.77:
            return "fresh flow tilting call-heavy vs accumulated OI"
        return None

    vol_pc = agg["volume_pc_ratio"]
    oi_pc = agg["oi_pc_ratio"]
    tier = opts.classify_positioning(agg)
    divergence = _divergence_tag(vol_pc, oi_pc)
    read = tier + (f"; {divergence}" if divergence else "")

    if expiration is not None:
        dte_label = f"{per_exp[0][0]} ({per_exp[0][1]} DTE)"
    else:
        dte_label = f"{len(per_exp)} expirations, {per_exp[0][1]}-{per_exp[-1][1]} DTE"

    summary: dict[str, str] = {
        "Underlying": f"${fmt_number(stock_price)}",
        "Coverage": dte_label,
        "Volume P/C": _ratio(vol_pc),
        "OI P/C": _ratio(oi_pc),
        "Δ-Skew": _skew(agg["delta_skew"]),
        "Call Volume / OI": f"{agg['call_volume']:,} / {agg['call_oi']:,}",
        "Put Volume / OI": f"{agg['put_volume']:,} / {agg['put_oi']:,}",
        "ATM Band": (
            f"${fmt_number(agg['band_low'])} – ${fmt_number(agg['band_high'])} "
            f"(±{atm_band_pct:.1f}%)"
        ),
        "Read": read,
    }

    otm_call_oi = agg["otm_call_oi"]
    otm_put_oi = agg["otm_put_oi"]
    if otm_call_oi and otm_put_oi:
        wing_ratio = float(otm_put_oi) / float(otm_call_oi)
        if wing_ratio > 2.0:
            summary["Wing Skew"] = f"{wing_ratio:.2f}x OTM puts vs calls (fat put tail)"
        elif wing_ratio < 0.5:
            summary["Wing Skew"] = f"{1 / wing_ratio:.2f}x OTM calls vs puts (fat call tail)"
        else:
            summary["Wing Skew"] = f"{wing_ratio:.2f}x OTM puts/calls (balanced)"

    bin_rows = [
        {
            "Bin": "OTM",
            "Call Vol": f"{agg['otm_call_vol']:,}",
            "Call OI": f"{agg['otm_call_oi']:,}",
            "Put Vol": f"{agg['otm_put_vol']:,}",
            "Put OI": f"{agg['otm_put_oi']:,}",
        },
        {
            "Bin": "ATM",
            "Call Vol": f"{agg['atm_call_vol']:,}",
            "Call OI": f"{agg['atm_call_oi']:,}",
            "Put Vol": f"{agg['atm_put_vol']:,}",
            "Put OI": f"{agg['atm_put_oi']:,}",
        },
        {
            "Bin": "ITM",
            "Call Vol": f"{agg['itm_call_vol']:,}",
            "Call OI": f"{agg['itm_call_oi']:,}",
            "Put Vol": f"{agg['itm_put_vol']:,}",
            "Put OI": f"{agg['itm_put_oi']:,}",
        },
    ]

    sections = [
        f"## {symbol.upper()} Options Positioning",
        "",
        kv_table(summary),
        "",
        "### Volume / OI by Moneyness",
        list_table(bin_rows),
    ]

    if len(per_exp) > 1:
        term_rows = [
            {
                "Expiration": exp,
                "DTE": str(dte),
                "Vol P/C": _ratio(p["volume_pc_ratio"]),
                "OI P/C": _ratio(p["oi_pc_ratio"]),
                "Δ-Skew": _skew(p["delta_skew"]),
                "Tier": opts.classify_positioning(p),
            }
            for exp, dte, p in per_exp
        ]
        sections.extend(["", "### Term Structure", list_table(term_rows)])

    return "\n".join(sections)


@mcp.tool()
async def get_gamma_profile(
    ctx: Context,
    symbol: str,
    expiration: str | None = None,
    dte_max: int = 7,
) -> str:
    """Dealer gamma-exposure (GEX) profile for an underlying: walls + zero-gamma flip.

    Computes signed dollar gamma per strike from the option chain (+call / -put),
    then surfaces the regime sign, the call wall (largest positive call gamma), the
    put wall (largest put gamma magnitude), and the zero-gamma flip (the price where
    net dealer gamma changes sign — cross it and the regime flips from pinning to
    trending). Positive total => dealers net long gamma => vol-suppressing /
    mean-reverting; negative => vol-amplifying / trending.

    For SPY/QQQ this is the regime input the /scalp prep level map keys off: in +GEX
    fade the walls back toward the flip; in -GEX trade the break, never fade.

    In aggregate mode (expiration=None) the **regime sign and the zero-gamma flip are
    taken from the front (0-1DTE) expiration** — the positioning that drives intraday
    behavior and where the flip sits cleanly near spot — while the **walls come from
    the ≤dte_max aggregate** (persistent high-OI round strikes are the structural
    magnets; 0DTE gamma collapses onto ATM so its walls sit on spot and can't be
    pre-mapped). When the aggregate sign disagrees with the front sign — the 6/16
    mislabel, where the aggregate read +GEX/fade while the front had flipped to
    trending — a ⚠ Regime Conflict row surfaces it so prep trusts the front label.
    A single explicit expiration computes everything from that one chain.

    Caveats: the open-interest base is daily-settled (OCC), so positioning is one
    session stale; the gammas re-anchor to the current spot on each call. The
    zero-gamma level is a cumulative-crossing proxy, not a re-priced surface.

    symbol: underlying (e.g. QQQ, SPY).
    expiration: a single expiration (YYYY-MM-DD). If None, regime+flip come from the
      front expiration and walls from the chain aggregated within dte_max (default 7).
    dte_max: max DTE to include when expiration is None.

    Requires [tradier] section in ~/.tradingrc.
    """
    tradier = _tradier(ctx)
    today = date.today()
    if expiration is not None:
        target_exps = [expiration]
    else:
        exp_resp = await tradier.get(t.EXPIRATIONS, t.GetExpirationsRequest(symbol))
        if not exp_resp.dates:
            return f"(no expirations for {symbol})"
        target_exps = [
            d for d in exp_resp.dates if 0 <= (date.fromisoformat(d) - today).days <= dte_max
        ]
        if not target_exps:
            return f"(no expirations for {symbol} within {dte_max} DTE)"

    quote_resp, *chain_resps = await asyncio.gather(
        tradier.get(t.QUOTES, t.GetQuotesRequest(symbol, greeks=False)),
        *[tradier.get(t.CHAIN, t.GetChainRequest(symbol, exp, greeks=True)) for exp in target_exps],
    )
    if not quote_resp.quotes:
        return f"(no quote for {symbol})"
    spot = float(quote_resp.quotes[0].get("last") or quote_resp.quotes[0].get("close", 0))
    if not spot:
        return f"(no usable price for {symbol})"

    chains_by_exp: dict[str, list[dict]] = {}
    for exp, chain_resp in zip(target_exps, chain_resps, strict=True):
        if chain_resp.options:
            chains_by_exp[exp] = chain_resp.options
    if not chains_by_exp:
        return f"(no option chains for {symbol})"
    aggregate_chain = [o for opts_list in chains_by_exp.values() for o in opts_list]

    conflict: str | None = None
    if expiration is not None:
        # single expiration: walls + regime + flip all from this one chain
        p = opts.gamma_exposure_profile(aggregate_chain, spot)
        regime, total_gex = p.regime, p.total_gex
        zero_gamma, call_wall, put_wall = p.zero_gamma, p.call_wall, p.put_wall
        coverage = target_exps[0]
    else:
        # scalp default: regime + flip from the FRONT expiration (the intraday-honest
        # read — the ≤N-DTE aggregate smears the sign and the flip), structural walls
        # from the aggregate. This is the gate, not the human reconciling two pulls.
        front_exp = min(chains_by_exp, key=date.fromisoformat)
        read = opts.scalp_regime_read(
            opts.gamma_exposure_profile(chains_by_exp[front_exp], spot),
            opts.gamma_exposure_profile(aggregate_chain, spot),
        )
        regime, total_gex = read.regime, read.front_total_gex
        zero_gamma, call_wall, put_wall = read.zero_gamma, read.call_wall, read.put_wall
        conflict = read.conflict
        coverage = f"front {front_exp} regime/flip + {len(chains_by_exp)} exp ≤{dte_max}DTE walls"

    playbook = (
        "dealers net long gamma — vol-suppressing / pinning; fade the walls back to the flip"
        if regime == "positive"
        else "dealers net short gamma — vol-amplifying / trending; trade the break, don't fade"
    )

    def _lvl(v: float | None) -> str:
        return f"${fmt_number(v)}" if v is not None else "n/a"

    summary = {
        "Underlying": f"${fmt_number(spot)}",
        "Coverage": coverage,
        "Regime": f"{regime.upper()} GEX" + (" (front-exp)" if expiration is None else ""),
        "Total GEX": f"{total_gex / 1e9:+.2f} $Bn / 1% move",
        "Call Wall": _lvl(call_wall),
        "Put Wall": _lvl(put_wall),
        "Zero-Gamma Flip": _lvl(zero_gamma),
        "Read": playbook,
    }
    if conflict is not None:
        summary["⚠ Regime Conflict"] = conflict
    return f"## {symbol.upper()} Gamma Exposure\n\n{kv_table(summary)}"


# ── Strategy + roll analysis ────────────────────────────────


@mcp.tool()
async def analyze_option_strategy(
    ctx: Context,
    symbol: str,
    legs: list[dict],
    shares: int | None = None,
    cost_basis: float | None = None,
) -> str:
    """Analyze an option strategy's risk/reward profile.

    Computes max profit, max loss, breakeven points, probability of profit,
    and risk/reward ratio for any single or multi-leg option strategy.

    Supports both single-expiration strategies (verticals, iron condors, etc.) and
    multi-expiration strategies (calendar spreads, diagonal spreads, PMCC, double
    diagonals). For multi-expiration, uses Black-Scholes to value the far-dated leg
    at the near-term expiration.

    symbol: underlying ticker symbol (e.g. 'AAPL').
    legs: list of leg dicts, each with:
      - strike: strike price (e.g. 250)
      - option_type: 'call' or 'put'
      - side: 'buy' or 'sell'
      - quantity: number of contracts (default 1)
      - expiration: option expiration date (YYYY-MM-DD)
    shares: number of shares held (e.g. 100 for covered call). Omit for option-only.
    cost_basis: per-share cost basis (e.g. 150.00). Required when shares is provided.

    Premiums and deltas are auto-fetched from the live option chain.

    Common strategies:
      CSP: [{"strike": 250, "option_type": "put", "side": "sell",
             "expiration": "2026-06-18"}]
      Bull put spread:
           [{"strike": 250, "option_type": "put", "side": "sell",
             "expiration": "2026-06-18"},
            {"strike": 240, "option_type": "put", "side": "buy",
             "expiration": "2026-06-18"}]
      Calendar spread:
           [{"strike": 100, "option_type": "call", "side": "sell",
             "expiration": "2026-05-15"},
            {"strike": 100, "option_type": "call", "side": "buy",
             "expiration": "2026-06-18"}]
      Diagonal / PMCC:
           [{"strike": 90, "option_type": "call", "side": "buy",
             "expiration": "2027-01-15"},
            {"strike": 110, "option_type": "call", "side": "sell",
             "expiration": "2026-05-15"}]

    Requires [tradier] section in ~/.tradingrc.
    """
    tradier = _tradier(ctx)

    for i, leg in enumerate(legs):
        if "expiration" not in leg:
            return f"(leg {i + 1} missing required 'expiration' field)"

    equity_position = None
    if shares is not None or cost_basis is not None:
        if shares is None or cost_basis is None:
            return "(both shares and cost_basis are required together)"
        if shares <= 0:
            return "(shares must be positive)"
        if cost_basis <= 0:
            return "(cost_basis must be positive)"
        equity_position = {"shares": shares, "cost_basis": cost_basis}

    quote = await tradier.get(t.QUOTES, t.GetQuotesRequest(symbol, greeks=False))
    if not quote.quotes:
        return f"(no quote for {symbol})"
    stock_price = float(quote.quotes[0].get("last") or quote.quotes[0].get("close", 0))

    unique_exps = sorted({leg["expiration"] for leg in legs})
    chains: dict[str, list[dict]] = {}
    for exp_date in unique_exps:
        chain = await tradier.get(t.CHAIN, t.GetChainRequest(symbol, exp_date, greeks=True))
        if not chain.options:
            return f"(no option chain for {symbol} at {exp_date})"
        chains[exp_date] = chain.options

    enriched_legs: list[EnrichedLeg] = []
    for leg in legs:
        strike = float(leg["strike"])
        otype = leg["option_type"]
        leg_exp = leg["expiration"]
        chain_options = chains[leg_exp]
        matches = [
            o
            for o in chain_options
            if o.get("option_type") == otype and abs(o["strike"] - strike) < 0.01
        ]
        if not matches:
            return f"(no {otype} at strike {strike} for {leg_exp})"
        opt = matches[0]
        greeks_data = opt.get("greeks") or {}
        enriched_legs.append(
            {
                "strike": strike,
                "option_type": otype,
                "side": leg["side"],
                "quantity": leg.get("quantity", 1),
                "premium": opts.mid_price(opt),
                "delta": greeks_data.get("delta"),
                "iv": greeks_data.get("mid_iv"),
                "bid": opt.get("bid"),
                "ask": opt.get("ask"),
                "spread_pct": opts.bid_ask_spread_pct(opt),
                "occ_symbol": opt.get("symbol", ""),
                "expiration": leg_exp,
            }
        )

    is_multi_exp = len(unique_exps) > 1
    if is_multi_exp:
        from trading_clients.options_multi_exp import analyze_multi_exp_strategy

        risk_free_rate = await _fetch_risk_free_rate(ctx)
        result = analyze_multi_exp_strategy(enriched_legs, stock_price, risk_free_rate)
    else:
        result = opts.strategy_analysis(enriched_legs, stock_price, equity_position)

    leg_rows = []
    if equity_position:
        leg_rows.append(
            {
                "Side": "LONG",
                "Type": "EQUITY",
                "Strike": "",
                "Exp": "",
                "Bid": "",
                "Ask": "",
                "Mid": fmt_number(stock_price),
                "Delta": "1.000",
                "IV": "",
                "Qty": str(equity_position["shares"]),
            }
        )
    for el in enriched_legs:
        row: dict[str, str] = {
            "Side": el["side"].upper(),
            "Type": el["option_type"].upper(),
            "Strike": fmt_number(el["strike"]),
        }
        if is_multi_exp:
            row["Exp"] = el["expiration"]
        row["Bid"] = fmt_number(el["bid"])
        row["Ask"] = fmt_number(el["ask"])
        row["Mid"] = fmt_number(el["premium"])
        sp = el.get("spread_pct")
        row["Spread"] = f"{sp:.0f}%" if sp is not None else ""
        row["Delta"] = fmt_number(el["delta"], 3) if el["delta"] else ""
        row["IV"] = f"{el['iv'] * 100:.1f}%" if el["iv"] else ""
        row["Qty"] = str(el["quantity"])
        leg_rows.append(row)

    data: dict[str, str] = {
        "Strategy": result.get("strategy_type", ""),
        "Stock Price": fmt_number(stock_price),
    }
    dte: int | None = None
    if is_multi_exp:
        data["Near Expiration"] = result.get("near_exp", unique_exps[0])
        data["Far Expiration"] = result.get("far_exp", unique_exps[-1])
    else:
        data["Expiration"] = unique_exps[0]
        try:
            dte = (date.fromisoformat(unique_exps[0]) - date.today()).days
            if dte >= 0:
                data["DTE"] = str(dte)
        except ValueError:
            dte = None

    if equity_position:
        data["Cost Basis"] = fmt_number(equity_position["cost_basis"])
        data["Shares"] = str(equity_position["shares"])

    net = result["net_premium"]
    leg_qtys = [el.get("quantity", 1) for el in enriched_legs]
    units = gcd(*leg_qtys) if leg_qtys else 1
    per_share = net / units
    total = net * CONTRACT_MULTIPLIER
    if net >= 0:
        data["Net Credit"] = f"${fmt_number(per_share)} per share (${fmt_number(total)} total)"
    else:
        data["Net Debit"] = (
            f"${fmt_number(abs(per_share))} per share (${fmt_number(abs(total))} total)"
        )

    data["Max Profit"] = f"${fmt_number(result['max_profit'])}"
    data["Max Loss"] = f"${fmt_number(result['max_loss'])}"

    strategy_type = result.get("strategy_type", "")
    if strategy_type in opts.CREDIT_SPREAD_STRATEGIES and net > 0:
        strikes = sorted({el["strike"] for el in enriched_legs})
        if len(strikes) >= 2:
            if strategy_type in ("Iron Condor", "Iron Butterfly"):
                width = (strikes[-1] - strikes[-2] + strikes[1] - strikes[0]) / 2
            else:
                width = strikes[-1] - strikes[0]
            if width > 0:
                ratio = per_share / width * 100
                data["Credit/Width"] = f"{ratio:.0f}%"

    if not is_multi_exp and net > 0 and dte is not None and dte > 0:
        capital_at_risk: float | None = None
        if strategy_type == "Cash-Secured Put":
            capital_at_risk = sum(
                el["strike"] * el["quantity"] * CONTRACT_MULTIPLIER
                for el in enriched_legs
                if el["side"] == "sell" and el["option_type"] == "put"
            )
        elif strategy_type in opts.CREDIT_SPREAD_STRATEGIES:
            capital_at_risk = abs(result["max_loss"])
        if capital_at_risk and capital_at_risk > 0:
            total_credit = result["max_profit"]
            ann_yld = total_credit / capital_at_risk * 365 / dte * 100
            data["Ann Yield"] = f"{ann_yld:.1f}%"

    if result["breakevens"]:
        data["Breakeven"] = ", ".join(f"${fmt_number(b)}" for b in result["breakevens"])

    if result["risk_reward_ratio"] is not None:
        data["Risk/Reward"] = f"{result['risk_reward_ratio']:.2f}"

    lognormal_pop_value: float | None = None
    ev_result: tuple[float, float] | None = None
    if not is_multi_exp and dte is not None and dte > 0:
        rfr = await _fetch_risk_free_rate(ctx)
        if result["breakevens"]:
            lognormal_pop_value = opts.lognormal_pop(
                strategy_type=strategy_type,
                breakevens=result["breakevens"],
                enriched_legs=enriched_legs,
                stock_price=stock_price,
                dte=dte,
                risk_free_rate=rfr,
            )
        if strategy_type in opts.EV_STRATEGIES:
            ev_result = opts.lognormal_ev(
                enriched_legs=enriched_legs,
                strategy_type=strategy_type,
                stock_price=stock_price,
                max_loss=result["max_loss"],
                dte=dte,
                risk_free_rate=rfr,
            )

    pop_value = (
        lognormal_pop_value if lognormal_pop_value is not None else result["probability_of_profit"]
    )
    if pop_value is not None:
        data["P(Profit)"] = f"{pop_value * 100:.0f}%"

    if ev_result is not None:
        expected_pnl, ev_pct = ev_result
        data["Expected Value"] = f"${fmt_number(expected_pnl)}"
        data["EV / $"] = f"{ev_pct:+.2f}%"

    if result.get("if_called_return") is not None:
        data["If-Called Return"] = f"{result['if_called_return'] * 100:.2f}%"
    if result.get("static_return") is not None:
        data["Static Return"] = f"{result['static_return'] * 100:.2f}%"

    if is_multi_exp:
        rfr_pct = f"{risk_free_rate * 100:.2f}%"
        data["Note"] = (
            f"P&L evaluated at near expiration using Black-Scholes (r={rfr_pct}) for far-dated legs"
        )

    wide_spread_legs = [el for el in enriched_legs if (el.get("spread_pct") or 0) > 10]

    sections = [
        f"## {symbol} {result.get('strategy_type', 'Strategy')} Analysis",
        "",
        "### Legs",
        list_table(leg_rows),
        "",
        "### Summary",
        kv_table(data),
    ]
    if wide_spread_legs:
        warnings = []
        for el in wide_spread_legs:
            warnings.append(
                f"- {el['option_type'].upper()} {fmt_number(el['strike'])} {el['expiration']}"
                f": {el['spread_pct']:.0f}% spread (bid {fmt_number(el['bid'])}"
                f" / ask {fmt_number(el['ask'])})"
            )
        sections.extend(
            [
                "",
                "### Liquidity Warning",
                "Wide bid-ask spread (>10% of ask) — mid price may be unreliable:",
                *warnings,
            ]
        )
    return "\n".join(sections)


@mcp.tool()
async def analyze_roll(
    ctx: Context,
    current_symbol: str,
    target_expiration: str,
    target_strike: float | None = None,
    quantity: int = 1,
    chain_credits: float | None = None,
) -> str:
    """Analyze rolling an option position to a new expiration and/or strike.

    Computes cost to close, premium for new position, net credit/debit, DTE change,
    and greek comparison. Designed for covered calls and CSPs that need regular rolling.

    When the roll is a net debit, runs a debit budget analysis with two gates:
    Gate 1 (chain budget): debit must not exceed 50% of accumulated chain credits.
    Gate 2 (vs assignment): debit must be less than the intrinsic value lost at assignment.

    current_symbol: OCC option symbol of current position
      (e.g. 'SMH260501C00410000'). Use get_webull_positions to find it,
      or get_option_lookup to construct it.
    target_expiration: expiration date for the new position (YYYY-MM-DD).
      Use get_option_expirations to find available dates.
    target_strike: strike price for new position. Omit to keep same strike
      (horizontal roll). Change for diagonal rolls (roll up/down).
    quantity: number of contracts being rolled (default 1).
    chain_credits: total accumulated chain credits in dollars (from get_cc_chain_pnl).
      Required for Gate 1 debit budget check on net-debit rolls.

    Requires [tradier] section in ~/.tradingrc.
    """
    tradier = _tradier(ctx)

    try:
        underlying, current_exp, option_type, current_strike = opts.parse_occ(current_symbol)
    except (IndexError, ValueError):
        return f"(invalid OCC symbol: {current_symbol})"

    if target_strike is None:
        target_strike = current_strike

    cur_resp, stock_resp, chain = await asyncio.gather(
        tradier.get(t.QUOTES, t.GetQuotesRequest(current_symbol, greeks=True)),
        tradier.get(t.QUOTES, t.GetQuotesRequest(underlying, greeks=False)),
        tradier.get(t.CHAIN, t.GetChainRequest(underlying, target_expiration, greeks=True)),
    )

    if not cur_resp.quotes:
        return f"(no quote for {current_symbol})"

    stock_price = 0.0
    if stock_resp.quotes:
        stock_price = float(
            stock_resp.quotes[0].get("last") or stock_resp.quotes[0].get("close", 0)
        )

    if not chain.options:
        return f"(no option chain for {underlying} at {target_expiration})"

    matches = [
        o
        for o in chain.options
        if o.get("option_type") == option_type and abs(o["strike"] - target_strike) < 0.01
    ]
    if not matches:
        typed = [o for o in chain.options if o.get("option_type") == option_type]
        if not typed:
            return f"(no {option_type} options at {target_expiration})"
        matches = [min(typed, key=lambda o: abs(o["strike"] - target_strike))]
    new_opt = matches[0]
    actual_strike = new_opt["strike"]

    per_contract_chain = chain_credits / (quantity * CONTRACT_MULTIPLIER) if chain_credits else None
    r = opts.roll_analysis(
        cur_resp.quotes[0],
        new_opt,
        stock_price,
        current_exp,
        target_expiration,
        current_strike,
        actual_strike,
        option_type=option_type,
        chain_credits=per_contract_chain,
    )

    type_label = option_type.upper()
    title = (
        f"## {underlying} Roll: "
        f"{current_exp} {type_label[0]}{current_strike:g} → "
        f"{target_expiration} {type_label[0]}{actual_strike:g}"
    )

    cur_data: dict[str, str] = {
        "Symbol": current_symbol,
        "Type": type_label,
        "Strike": fmt_number(current_strike),
        "Expiration": current_exp,
        "DTE": str(r["cur_dte"]),
        "Bid": fmt_number(r["cur_bid"]),
        "Ask": fmt_number(r["cur_ask"]),
    }
    new_data: dict[str, str] = {
        "Symbol": new_opt.get("symbol", ""),
        "Type": type_label,
        "Strike": fmt_number(actual_strike),
        "Expiration": target_expiration,
        "DTE": str(r["new_dte"]),
        "Bid": fmt_number(r["new_bid"]),
        "Ask": fmt_number(r["new_ask"]),
    }
    for label, d, prefix in [
        ("cur", cur_data, "cur_"),
        ("new", new_data, "new_"),
    ]:
        if r.get(f"{prefix}delta") is not None:
            d["Delta"] = fmt_number(r[f"{prefix}delta"], 4)
        if r.get(f"{prefix}theta") is not None:
            d["Theta"] = fmt_number(r[f"{prefix}theta"], 4)
        if r.get(f"{prefix}mid_iv") is not None:
            d["IV"] = f"{r[f'{prefix}mid_iv'] * 100:.1f}%"

    net = r["net"]
    net_total = net * quantity * CONTRACT_MULTIPLIER
    roll_data: dict[str, str] = {
        "Stock Price": fmt_number(stock_price),
        "Roll Type": r["roll_type"],
        "Cost to Close": f"${fmt_number(r['close_cost'])} (buy at ask)",
        "New Premium": f"${fmt_number(r['open_premium'])} (sell at bid)",
    }
    if net >= 0:
        roll_data["Net Credit"] = f"${fmt_number(net)}/sh (${fmt_number(net_total)} total)"
    else:
        roll_data["Net Debit"] = f"${fmt_number(abs(net))}/sh (${fmt_number(abs(net_total))} total)"
    roll_data["DTE Change"] = (
        f"{r['cur_dte']} → {r['new_dte']} (+{r['new_dte'] - r['cur_dte']} days)"
    )

    for key, label in [("delta", "Delta"), ("theta", "Theta")]:
        if r.get(f"cur_{key}") is not None:
            diff = r[f"new_{key}"] - r[f"cur_{key}"]
            sign = "+" if diff >= 0 else ""
            roll_data[f"{label} Change"] = (
                f"{fmt_number(r[f'cur_{key}'], 4)} → "
                f"{fmt_number(r[f'new_{key}'], 4)} ({sign}{fmt_number(diff, 4)})"
            )
    if r.get("cur_mid_iv") is not None:
        iv_diff = (r["new_mid_iv"] - r["cur_mid_iv"]) * 100
        sign = "+" if iv_diff >= 0 else ""
        roll_data["IV Change"] = (
            f"{r['cur_mid_iv'] * 100:.1f}% → {r['new_mid_iv'] * 100:.1f}% ({sign}{iv_diff:.1f}%)"
        )

    sections = [
        title,
        "",
        "### Current Position",
        kv_table(cur_data),
        "",
        "### New Position",
        kv_table(new_data),
        "",
        "### Roll Summary",
        kv_table(roll_data),
    ]

    if net < 0:
        debit = abs(net)
        debit_total = debit * quantity * CONTRACT_MULTIPLIER
        assignment_cost = r["assignment_cost"]
        assignment_total = assignment_cost * quantity * CONTRACT_MULTIPLIER
        budget_data: dict[str, str] = {}

        if chain_credits is not None:
            budget = chain_credits * 0.5
            budget_data["Chain Credits"] = f"${fmt_number(chain_credits)}"
            budget_data["Debit Budget (50%)"] = f"${fmt_number(budget)}"
            budget_data["Roll Debit"] = f"${fmt_number(debit_total)}"
            gate1 = r.get("gate1_pass", False)
            budget_data["Gate 1: Chain Budget"] = (
                "PASS — debit within budget" if gate1 else "FAIL — debit exceeds 50% of chain"
            )
        else:
            budget_data["Chain Credits"] = "(not provided — run get_cc_chain_pnl)"
            budget_data["Gate 1: Chain Budget"] = "SKIP — no chain data"

        type_label_lower = "called away" if option_type == "call" else "assigned"
        budget_data["Assignment Cost"] = (
            f"${fmt_number(assignment_total)} "
            f"(${fmt_number(assignment_cost)}/sh if {type_label_lower})"
        )
        budget_data["Roll Debit"] = f"${fmt_number(debit_total)}"
        gate2 = r.get("gate2_pass", False)
        if assignment_cost <= 0:
            budget_data["Gate 2: vs Assignment"] = "N/A — option is OTM, no assignment risk"
        else:
            budget_data["Gate 2: vs Assignment"] = (
                "PASS — debit < assignment cost"
                if gate2
                else f"FAIL — cheaper to let {type_label_lower}"
            )

        g1 = r.get("gate1_pass")
        g2 = r.get("gate2_pass", False)
        if g1 is None:
            verdict = "PARTIAL — provide chain_credits to complete analysis" if g2 else "FAIL"
        elif g1 and g2:
            verdict = "PASS — debit roll justified"
        else:
            verdict = "FAIL — let assign or accept the cap"
        budget_data["Verdict"] = verdict

        sections.append("")
        sections.append("### Debit Roll Analysis")
        sections.append(kv_table(budget_data))

    return "\n".join(sections)


# ── Cross-stock comparators ─────────────────────────────────


@dataclass
class _OptionMatch:
    symbol: str
    stock_price: float
    strike: float
    exp: str
    dte: int
    delta: float
    bid: float
    ask: float
    mid: float


async def _gather_option_matches(
    tradier: TradierClient,
    tickers: list[str],
    opt_type: str,
    target_delta: float,
    min_dte: int,
    max_dte: int,
) -> tuple[list[_OptionMatch], list[str]]:
    today = date.today()
    mid_dte = (min_dte + max_dte) / 2

    results = await asyncio.gather(
        tradier.get(t.QUOTES, t.GetQuotesRequest(",".join(tickers), greeks=False)),
        *[tradier.get(t.EXPIRATIONS, t.GetExpirationsRequest(sym)) for sym in tickers],
        return_exceptions=True,
    )

    quote_resp = results[0]
    if isinstance(quote_resp, BaseException):
        return [], tickers

    prices: dict[str, float] = {}
    for q in quote_resp.quotes:
        sym = q.get("symbol", "")
        last = to_float(q.get("last"))
        if sym and last:
            prices[sym] = last

    selected: dict[str, tuple[str, int]] = {}
    for i, sym in enumerate(tickers):
        exp_resp = results[i + 1]
        if isinstance(exp_resp, BaseException) or not exp_resp.dates:
            continue
        best_exp = None
        best_score = float("inf")
        for d_str in exp_resp.dates:
            dte = (date.fromisoformat(d_str) - today).days
            if dte < 1:
                continue
            in_window = min_dte <= dte <= max_dte
            score = abs(dte - mid_dte) if in_window else 1000 + abs(dte - mid_dte)
            if score < best_score:
                best_score = score
                best_exp = d_str
        if best_exp:
            selected[sym] = (best_exp, (date.fromisoformat(best_exp) - today).days)

    chain_syms = [sym for sym in tickers if sym in selected and sym in prices]
    if not chain_syms:
        return [], tickers

    chain_results = await asyncio.gather(
        *[
            tradier.get(t.CHAIN, t.GetChainRequest(sym, selected[sym][0], greeks=True))
            for sym in chain_syms
        ],
        return_exceptions=True,
    )

    matches: list[_OptionMatch] = []
    skipped: list[str] = []
    for sym, chain_resp in zip(chain_syms, chain_results):
        if isinstance(chain_resp, BaseException) or not chain_resp.options:
            skipped.append(sym)
            continue

        options = [
            o
            for o in chain_resp.options
            if o.get("option_type") == opt_type and (to_float(o.get("bid")) or 0) > 0
        ]
        if not options:
            skipped.append(sym)
            continue

        best_opt = None
        best_dist = float("inf")
        for o in options:
            greeks_d = o.get("greeks") or {}
            delta = to_float(greeks_d.get("delta"))
            if delta is None:
                continue
            dist = abs(abs(delta) - target_delta)
            if dist < best_dist:
                best_dist = dist
                best_opt = o

        if not best_opt:
            skipped.append(sym)
            continue

        bid = to_float(best_opt.get("bid")) or 0
        ask = to_float(best_opt.get("ask")) or 0
        strike = to_float(best_opt.get("strike")) or 0
        delta = to_float((best_opt.get("greeks") or {}).get("delta")) or 0
        mid = (bid + ask) / 2

        if mid <= 0 or strike <= 0:
            skipped.append(sym)
            continue

        exp_str, dte = selected[sym]
        matches.append(
            _OptionMatch(
                symbol=sym,
                stock_price=prices[sym],
                strike=strike,
                exp=exp_str,
                dte=dte,
                delta=delta,
                bid=bid,
                ask=ask,
                mid=mid,
            )
        )

    skipped.extend(sym for sym in tickers if sym not in prices and sym not in skipped)
    return matches, skipped


@mcp.tool()
async def compare_credit_efficiency(
    ctx: Context,
    symbols: str,
    option_type: str = "put",
    target_delta: float = 0.25,
    min_dte: int = 30,
    max_dte: int = 45,
) -> str:
    """Compare credit strategy premium efficiency across multiple stocks to
    prioritize capital allocation when conviction is similar.

    Finds the option closest to target_delta for each symbol and computes:
    - Annualized Yield: premium collected / capital at risk, annualized by DTE.
      Uses bid price (conservative — what you'd actually collect). Capital at
      risk = strike (puts/CSPs) or stock price (calls/CCs). Higher = richer.
    - Cushion/Yield: OTM distance (%) per unit of annualized yield. Higher = more
      margin of safety per unit of return.
    - Spread: bid/ask spread as % of mid price (informational — already reflected
      in the yield via bid pricing).

    symbols: comma-separated tickers (e.g. 'MU,ADBE,NVDA,LRCX').
    option_type: 'put' for CSPs (default), 'call' for covered calls.
    target_delta: absolute delta to target (default 0.25).
    min_dte: minimum days to expiration (default 30).
    max_dte: maximum days to expiration (default 45).

    Requires [tradier] section in ~/.tradingrc.
    """
    tradier = _tradier(ctx)
    tickers = [s.strip().upper() for s in symbols.split(",") if s.strip()]
    if not tickers:
        return "(no symbols provided)"
    opt_type = option_type.lower()
    if opt_type not in ("put", "call"):
        return "(option_type must be 'put' or 'call')"

    matches, skipped = await _gather_option_matches(
        tradier, tickers, opt_type, target_delta, min_dte, max_dte
    )
    if not matches:
        return "(no options found matching criteria)"

    rows: list[dict[str, str]] = []
    for m in matches:
        base = m.strike if opt_type == "put" else m.stock_price
        ann_yield = (m.bid / base) * (365 / m.dte) * 100

        if opt_type == "put":
            otm_pct = (m.stock_price - m.strike) / m.stock_price * 100
        else:
            otm_pct = (m.strike - m.stock_price) / m.stock_price * 100

        c_over_y = otm_pct / ann_yield if ann_yield > 0 else 0
        spread = (m.ask - m.bid) / m.mid * 100 if m.mid > 0 else 0

        rows.append(
            {
                "Symbol": m.symbol,
                "Price": fmt_number(m.stock_price, 2),
                "Strike": fmt_number(m.strike, 0),
                "Exp": m.exp,
                "DTE": str(m.dte),
                "Delta": fmt_number(m.delta, 2),
                "Bid": fmt_number(m.bid, 2),
                "Ann Yld %": fmt_number(ann_yield, 1),
                "OTM %": fmt_number(otm_pct, 1),
                "C/Y": fmt_number(c_over_y, 2),
                "Spread %": fmt_number(spread, 1),
            }
        )

    rows.sort(key=lambda r: to_float(r["Ann Yld %"]) or 0, reverse=True)
    columns = [
        "Symbol",
        "Price",
        "Strike",
        "Exp",
        "DTE",
        "Delta",
        "Bid",
        "Ann Yld %",
        "OTM %",
        "C/Y",
        "Spread %",
    ]
    out = list_table(rows, columns)
    if skipped:
        out += f"\n\nSkipped (no chain/delta match): {', '.join(skipped)}"
    return out


@mcp.tool()
async def compare_debit_efficiency(
    ctx: Context,
    symbols: str,
    option_type: str = "call",
    target_delta: float = 0.30,
    min_dte: int = 30,
    max_dte: int = 45,
) -> str:
    """Compare debit strategy cost efficiency across multiple stocks to
    prioritize capital allocation when conviction is similar.

    Finds the option closest to target_delta for each symbol and computes:
    - Cost/Exposure: premium paid as % of delta-adjusted notional exposure.
      Uses ask price (conservative — what you'd actually pay). Lower = cheaper
      leverage (more directional bang per dollar).
    - Spread: bid/ask spread as % of mid price (informational — already reflected
      in the cost via ask pricing).

    symbols: comma-separated tickers (e.g. 'MU,ADBE,NVDA,LRCX').
    option_type: 'call' for long calls (default), 'put' for long puts.
    target_delta: absolute delta to target (default 0.30).
    min_dte: minimum days to expiration (default 30).
    max_dte: maximum days to expiration (default 45).

    Requires [tradier] section in ~/.tradingrc.
    """
    tradier = _tradier(ctx)
    tickers = [s.strip().upper() for s in symbols.split(",") if s.strip()]
    if not tickers:
        return "(no symbols provided)"
    opt_type = option_type.lower()
    if opt_type not in ("put", "call"):
        return "(option_type must be 'put' or 'call')"

    matches, skipped = await _gather_option_matches(
        tradier, tickers, opt_type, target_delta, min_dte, max_dte
    )
    if not matches:
        return "(no options found matching criteria)"

    rows: list[dict[str, str]] = []
    for m in matches:
        abs_delta = abs(m.delta)
        cost_exp = (m.ask / (abs_delta * m.stock_price) * 100) if abs_delta > 0 else 0
        spread = (m.ask - m.bid) / m.mid * 100 if m.mid > 0 else 0

        rows.append(
            {
                "Symbol": m.symbol,
                "Price": fmt_number(m.stock_price, 2),
                "Strike": fmt_number(m.strike, 0),
                "Exp": m.exp,
                "DTE": str(m.dte),
                "Delta": fmt_number(m.delta, 2),
                "Ask": fmt_number(m.ask, 2),
                "Cost/Exp %": fmt_number(cost_exp, 1),
                "Spread %": fmt_number(spread, 1),
            }
        )

    rows.sort(key=lambda r: to_float(r["Cost/Exp %"]) or 0)
    columns = [
        "Symbol",
        "Price",
        "Strike",
        "Exp",
        "DTE",
        "Delta",
        "Ask",
        "Cost/Exp %",
        "Spread %",
    ]
    out = list_table(rows, columns)
    if skipped:
        out += f"\n\nSkipped (no chain/delta match): {', '.join(skipped)}"
    return out


# ── Scenario projection ─────────────────────────────────────


def _parse_csv_floats(value: str | None, default: list[float]) -> list[float]:
    if not value:
        return default
    out: list[float] = []
    for part in value.split(","):
        s = part.strip()
        if s:
            try:
                out.append(float(s))
            except ValueError:
                continue
    return out or default


@mcp.tool()
async def project_option_grid(
    ctx: Context,
    contract_symbol: str | None = None,
    underlying: str | None = None,
    strike: float | None = None,
    expiration: str | None = None,
    option_type: str | None = None,
    as_of_date: str | None = None,
    spot_pct_changes: str | None = None,
    iv_levels: str | None = None,
    contracts: int | None = None,
    risk_free_rate: float | None = None,
) -> str:
    """Project an option's theoretical value across a grid of (spot price × IV) scenarios.

    Use case: tail-hedge management — see the full distribution of hedge value under
    different SPY drawdown + VIX-spike combinations to inform harvest/maintenance roll
    timing. Also useful for any what-if scenario modeling on existing option positions.

    Modes:
    - Pass `contract_symbol` (OCC, e.g. 'SPY260821P00540000') to auto-detect strike,
      expiration, and option_type. Current spot/IV pulled from get_quote.
    - Or pass `underlying` + `strike` + `expiration` + `option_type` manually.

    Optional params:
    - as_of_date: project to this date (YYYY-MM-DD; default: today). Use to model
      time decay — e.g., "what's this worth in 30 days if X happens?"
    - spot_pct_changes: comma-separated % changes (default: '-30,-25,-20,-15,-10,-5,0,5')
    - iv_levels: comma-separated IV % (default: '20,30,40,50,60,70')
    - contracts: position size — when set, output also shows aggregate $ P&L per cell
    - risk_free_rate: annualized rate (default: pulled from FRED FEDFUNDS series)

    Returns a markdown grid: rows = spot prices, columns = IV levels, cells = option
    value (and multiple from current value).

    Requires [tradier] section in ~/.tradingrc. FRED is optional (falls back to 0%).
    """
    if contract_symbol:
        try:
            underlying, expiration, option_type, strike = opts.parse_occ(contract_symbol)
        except Exception as e:
            return f"Could not parse contract_symbol '{contract_symbol}': {e}"
    if underlying is None or strike is None or expiration is None or option_type is None:
        return (
            "Specify either contract_symbol or all of: underlying, strike, expiration, option_type"
        )
    option_type = option_type.lower()

    if option_type not in ("call", "put"):
        return f"option_type must be 'call' or 'put', got '{option_type}'"

    tradier = _tradier(ctx)

    spot_task = tradier.get(t.QUOTES, t.GetQuotesRequest(underlying, greeks=False))
    occ = contract_symbol or opts.build_occ(underlying, expiration, option_type, strike)
    option_task = tradier.get(t.QUOTES, t.GetQuotesRequest(occ, greeks=True))
    rate_task = (
        asyncio.sleep(0, result=risk_free_rate)
        if risk_free_rate is not None
        else _fetch_risk_free_rate(ctx)
    )

    spot_resp, option_resp, rate = await asyncio.gather(
        spot_task, option_task, rate_task, return_exceptions=False
    )

    current_spot = spot_resp.quotes[0].get("last", 0) if spot_resp.quotes else 0
    if not current_spot:
        return f"Could not get current quote for {underlying}"

    current_option_q = option_resp.quotes[0] if option_resp.quotes else {}
    current_value = current_option_q.get("last", 0) or current_option_q.get("ask", 0) or 0
    current_iv_raw = current_option_q.get("greeks", {}).get("mid_iv", "")
    current_iv = float(current_iv_raw) if current_iv_raw else 0.0
    current_delta = current_option_q.get("greeks", {}).get("delta", "")

    if as_of_date:
        try:
            ref_date = date.fromisoformat(as_of_date)
        except ValueError:
            return f"Invalid as_of_date '{as_of_date}' (use YYYY-MM-DD)"
    else:
        ref_date = date.today()
    exp_date = date.fromisoformat(expiration)
    dte_remaining = (exp_date - ref_date).days

    if dte_remaining <= 0:
        return f"Option has expired (or expires today) as of {ref_date}"

    tte_years = dte_remaining / 365.0

    pct_changes = _parse_csv_floats(spot_pct_changes, [-30, -25, -20, -15, -10, -5, 0, 5])
    ivs_pct = _parse_csv_floats(iv_levels, [20, 30, 40, 50, 60, 70])
    ivs_decimal = [iv / 100.0 for iv in ivs_pct]

    header_meta = {
        "Contract": occ,
        "Underlying": f"{underlying} @ ${current_spot:,.2f}",
        "Strike": f"${strike:,.2f} ({option_type})",
        "Expiration": expiration,
        "DTE remaining (as of grid date)": f"{dte_remaining} days",
        "Grid date": ref_date.isoformat(),
        "Current option value": f"${current_value:.2f}",
        "Current IV": f"{current_iv * 100:.1f}%" if current_iv else "N/A",
        "Current delta": str(current_delta) if current_delta else "N/A",
        "Risk-free rate": f"{rate * 100:.2f}% (FRED FEDFUNDS)"
        if risk_free_rate is None
        else f"{rate * 100:.2f}% (override)",
    }
    if contracts:
        header_meta["Contracts"] = str(contracts)

    lines = [kv_table(header_meta), ""]

    iv_header = " | ".join(f"IV {iv:.0f}%" for iv in ivs_pct)
    lines.append(f"| Spot \\ IV | {iv_header} |")
    lines.append("| --- | " + " | ".join("---" for _ in ivs_pct) + " |")

    for pct in pct_changes:
        scen_spot = current_spot * (1 + pct / 100.0)
        if scen_spot <= 0:
            continue
        row_label = f"${scen_spot:,.0f} ({pct:+.0f}%)"
        cells: list[str] = []
        for iv in ivs_decimal:
            value = bsm_price(scen_spot, strike, tte_years, iv, option_type, rate)
            cell = f"${value:.2f}"
            if current_value > 0:
                multiple = value / current_value
                cell += f" ({multiple:.1f}x)"
            if contracts:
                pnl = (value - current_value) * contracts * CONTRACT_MULTIPLIER
                cell += f" / ${pnl:,.0f}"
            cells.append(cell)
        lines.append(f"| {row_label} | " + " | ".join(cells) + " |")

    if contracts:
        lines.append("")
        lines.append(
            "_Cell format: option_value (multiple_from_current) / position_pnl "
            f"for {contracts} contracts._"
        )
    else:
        lines.append("")
        lines.append(
            "_Cell format: option_value (multiple_from_current). "
            "Pass `contracts` to also see position P&L._"
        )

    return "\n".join(lines)


# ── Covered-call overlay analytics ──────────────────────────


@mcp.tool()
async def get_cc_coverage(
    ctx: Context,
    account_id: str,
) -> str:
    """Calculate covered call coverage ratio per underlying in a Webull account.

    For each stock position with short calls, shows total shares, covered shares,
    uncovered shares, and coverage %. Use before writing new CCs to decide how
    many contracts to sell.

    Coverage guidance from the decision framework:
    - 0-25%: High conviction hold (minimal income, max upside)
    - 50-75%: Growth with income (balanced)
    - 75-100%: Exit/neutral (max income, capped upside)

    account_id: Webull account ID.
    """
    client = _webull(ctx)
    aid = client.ensure_account_id(account_id)

    pos_resp = await _retry(_webull(ctx).get, POSITIONS, AccountRequest(aid))
    positions = pos_resp.to_normalized()

    shares_by_sym: dict[str, float] = {}
    calls_by_sym: dict[str, list[dict]] = {}

    for p in positions:
        if p.get("is_cash"):
            continue
        if p.get("is_option"):
            if p.get("option_type") == "call" and p.get("quantity", 0) < 0:
                sym = p.get("underlying", "")
                calls_by_sym.setdefault(sym, []).append(p)
        else:
            sym = p.get("symbol", "")
            qty = p.get("quantity", 0)
            if qty > 0:
                shares_by_sym[sym] = shares_by_sym.get(sym, 0) + qty

    all_syms = sorted(set(shares_by_sym) | set(calls_by_sym))
    if not all_syms:
        return "(no stock or short call positions found)"

    cc_rows: list[dict[str, str]] = []
    for sym in all_syms:
        total_shares = shares_by_sym.get(sym, 0)
        calls = calls_by_sym.get(sym, [])
        covered_contracts = sum(abs(c.get("quantity", 0)) for c in calls)
        covered_shares = covered_contracts * CONTRACT_MULTIPLIER
        uncovered = max(0, total_shares - covered_shares)
        coverage_pct = (covered_shares / total_shares * 100) if total_shares > 0 else 0

        if coverage_pct == 0:
            label = "None"
        elif coverage_pct <= 25:
            label = "High conviction"
        elif coverage_pct <= 50:
            label = "Moderate"
        elif coverage_pct <= 75:
            label = "Growth + income"
        else:
            label = "Exit/neutral"

        row: dict[str, str] = {
            "Symbol": sym,
            "Shares": fmt_number(total_shares, 0),
            "Covered": fmt_number(covered_shares, 0),
            "Uncovered": fmt_number(uncovered, 0),
            "Coverage": f"{coverage_pct:.0f}%",
            "Label": label,
        }

        if calls:
            call_details = ", ".join(
                f"${fmt_number(c.get('strike'))} {c.get('expiration', '')}" for c in calls
            )
            row["Calls"] = call_details

        cc_rows.append(row)

    return f"## CC Coverage Ratio\n\n{list_table(cc_rows)}"


@mcp.tool()
async def get_cc_chain_pnl(
    ctx: Context,
    account_id: str,
    symbol: str,
    option_type: str = "call",
    start_date: str | None = None,
) -> str:
    """Calculate the running P&L of a covered call or CSP roll chain.

    Traces all filled option orders for a symbol, sums credits (SELL) and
    debits (BUY), and shows the chain P&L. Useful before rolling to see
    whether the chain is profitable or underwater.

    account_id: Webull account ID.
    symbol: underlying ticker (e.g. 'AMZN').
    option_type: 'call' for covered calls, 'put' for CSPs (default 'call').
    start_date: earliest date to search (YYYY-MM-DD). Defaults to 90 days ago.
    """
    client = _webull(ctx)
    aid = client.ensure_account_id(account_id)

    if not start_date:
        start_date = (date.today().replace(day=1) - timedelta(days=90)).isoformat()

    response = await client.get(
        ORDER_HISTORY,
        GetOrderHistoryRequest(
            aid, page_size=100, start_date=start_date, end_date=date.today().isoformat()
        ),
    )

    opt_type = option_type.lower()
    chain_orders: list[dict] = []
    for combo in response.combos:
        for o in combo.get("orders", []):
            if o.get("status") != "FILLED":
                continue
            if o.get("instrument_type") != "OPTION":
                continue
            if (o.get("symbol") or "").upper() != symbol.upper():
                continue
            order_legs = o.get("legs", [])
            if not order_legs:
                continue
            leg = order_legs[0]
            if (leg.get("option_type") or "").lower() != opt_type:
                continue
            chain_orders.append(o)

    if not chain_orders:
        return f"(no filled {opt_type} orders for {symbol} since {start_date})"

    chain_orders.sort(key=lambda o: o.get("filled_time_at") or o.get("place_time_at") or "")

    chain_rows: list[dict[str, str]] = []
    total_credit = 0.0
    total_debit = 0.0

    for o in chain_orders:
        side = o.get("side", "")
        qty = to_float_zero(o.get("filled_quantity"))
        price = to_float_zero(o.get("filled_price"))
        amount = price * qty * CONTRACT_MULTIPLIER
        leg = o.get("legs", [{}])[0]

        if side == "SELL":
            total_credit += amount
        else:
            total_debit += amount

        chain_rows.append(
            {
                "Date": (o.get("filled_time_at") or o.get("place_time_at") or "")[:10],
                "Side": side,
                "Strike": fmt_number(leg.get("strike_price")),
                "Exp": leg.get("option_expire_date", ""),
                "Qty": fmt_number(qty, 0),
                "Fill": fmt_number(price),
                "Amount": f"{'+' if side == 'SELL' else '-'}${fmt_number(amount)}",
            }
        )

    chain_pnl = total_credit - total_debit
    pnl_sign = "+" if chain_pnl >= 0 else ""

    type_label = "Covered Call" if opt_type == "call" else "CSP"
    summary = kv_table(
        {
            "Symbol": symbol.upper(),
            "Chain Type": type_label,
            "Total Credits (SELL)": f"+${fmt_number(total_credit)}",
            "Total Debits (BUY)": f"-${fmt_number(total_debit)}",
            "Chain P&L": f"{pnl_sign}${fmt_number(chain_pnl)}",
            "Orders": str(len(chain_orders)),
        }
    )

    sections = [f"## {symbol.upper()} {type_label} Chain P&L\n\n{summary}"]
    sections.append(f"\n### Order History\n\n{list_table(chain_rows)}")

    return "\n".join(sections)
