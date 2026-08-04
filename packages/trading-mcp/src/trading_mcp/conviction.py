"""Conviction scoring for the post-screening decision framework.

Computes the four quantitative conviction inputs (ROE, Growth, Margins, Cash
Flow) plus PEG, drawdown, and position-size tier from Finnhub fundamentals
and Tradier quote data. Used by tools/signals.py to produce
get_conviction_metrics and get_entry_signals.
"""

import asyncio
from typing import Any

from fastmcp import Context
from trading_clients import fcf
from trading_clients.endpoints import finnhub as fh
from trading_clients.endpoints import tradier as t
from trading_clients.table_helpers import to_float

from trading_mcp.helpers import _finnhub, _tradier

# Percentage points of sequential operating-margin change before the move is
# called a trend rather than ordinary quarterly variation.
#
# Calibrated on |QoQ margin change| across 20 large caps (n=325 quarter pairs,
# discrete quarters): median 1.91pp, p60 2.75pp, p70 3.90pp. Structurally stable
# businesses sit well below (COST 0.22, WMT 0.40, AMAT 0.56, GOOGL 1.47), while
# seasonal ones swing 2.5-4pp with nothing changing (AAPL 2.66, META 2.95,
# NVDA 3.01, AMD 3.64). At 3.0pp a "trend" means the move is larger than ~60% of
# ordinary quarterly variation, while genuine cyclicals still trip it (INTC 7.36,
# MU 10.23). The old 0.5pp band labelled nearly every quarter pair a trend, which
# was harmless only while the underlying rows were cumulative and incomparable.
#
# Residual: a slow bleed just under the band (say 2.9pp every quarter) reads
# Stable indefinitely. A band cannot catch that; a persistence rule would.
_MARGIN_TREND_BAND_PP = 3.0


async def _conviction_data(ctx: Context, symbol: str) -> dict[str, Any]:
    finnhub_client = _finnhub(ctx)
    tradier_client = _tradier(ctx)
    basics_r, fin_r, annual_r, quote_r = await asyncio.gather(
        finnhub_client.get(fh.BASIC_FINANCIALS, fh.BasicFinancialsRequest(symbol)),
        finnhub_client.get(
            fh.FINANCIALS_REPORTED, fh.FinancialsReportedRequest(symbol, "quarterly")
        ),
        finnhub_client.get(fh.FINANCIALS_REPORTED, fh.FinancialsReportedRequest(symbol, "annual")),
        tradier_client.get(t.QUOTES, t.GetQuotesRequest(symbol)),
        return_exceptions=True,
    )

    basics = None if isinstance(basics_r, BaseException) else basics_r
    fin = None if isinstance(fin_r, BaseException) else fin_r
    annual = None if isinstance(annual_r, BaseException) else annual_r
    quote_resp = None if isinstance(quote_r, BaseException) else quote_r

    metric = basics.data.get("metric", {}) if basics else {}
    pe = to_float(metric.get("peNormalizedAnnual"))
    roe = to_float(metric.get("roeTTM"))
    de = to_float(metric.get("totalDebt/totalEquityAnnual"))

    q = quote_resp.quotes[0] if quote_resp and quote_resp.quotes else {}
    price = to_float(q.get("last"))
    high_52w = to_float(q.get("week_52_high"))

    # Finnhub's quarterly rows are year-to-date cumulative (Q2 = six months, Q3 =
    # nine months, no Q4 at all), so every factor below has to run on de-cumulated
    # quarters. Left raw, "margin trend" would compare a six-month margin against
    # a three-month one and the burn check would hide a bad quarter inside a good
    # year-to-date. Q4 is recovered from the annual 10-K.
    annual_income = annual.income_numeric(5) if annual else []
    annual_cf = annual.cf_numeric(5) if annual else []
    quarters = fcf.to_discrete(fin.income_numeric(12), annual_income) if fin else []
    cf_quarters = fcf.to_discrete(fin.cf_numeric(12), annual_cf) if fin else []

    drawdown_pct = None
    if price and high_52w and high_52w > 0:
        drawdown_pct = (price - high_52w) / high_52w * 100

    rev_growth = None
    current_q = None
    prior_q = None
    if len(quarters) >= 2:
        current_q = quarters[0]
        current_rev = current_q.get("Revenue")
        cur_fy = current_q.get("fiscal_year")
        cur_fq = current_q.get("fiscal_quarter")
        if current_rev and cur_fy and cur_fq:
            for q_row in quarters[1:]:
                if q_row.get("fiscal_quarter") == cur_fq and q_row.get("fiscal_year") == cur_fy - 1:
                    prior_rev = q_row.get("Revenue")
                    if prior_rev and prior_rev > 0:
                        prior_q = q_row
                        rev_growth = (current_rev - prior_rev) / prior_rev * 100
                    break

    margins: list[tuple[str, float]] = []
    for q_row in quarters[:4]:
        rev = q_row.get("Revenue")
        op_inc = q_row.get("Operating Income")
        period = q_row.get("period", "")
        if rev and op_inc and rev > 0:
            margins.append((period, op_inc / rev * 100))

    margin_trend = None
    if len(margins) >= 2:
        delta = margins[0][1] - margins[1][1]
        if delta > _MARGIN_TREND_BAND_PP:
            margin_trend = "Expanding"
        elif delta < -_MARGIN_TREND_BAND_PP:
            margin_trend = "Compressing"
        else:
            margin_trend = "Stable"

    peg = None
    peg_valid = True
    peg_note = ""
    if pe is not None and rev_growth is not None:
        if pe < 0:
            peg_valid = False
            peg_note = "Negative P/E (unprofitable) — PEG not meaningful, use raw P/E"
        elif rev_growth <= 0:
            peg_valid = False
            peg_note = "Negative/zero growth — PEG not meaningful, use raw P/E"
        elif margin_trend == "Compressing":
            peg_valid = False
            peg_note = "Margins compressing — PEG unreliable, use raw P/E"
        else:
            peg = pe / rev_growth

    if peg is not None and peg_valid:
        if peg < 1.5:
            size = "Full — PEG < 1.5"
        elif peg <= 3.0:
            size = "Standard — PEG 1.5-3.0"
        else:
            size = "Reduced — PEG > 3.0"
        if pe and pe > 80:
            size = "Reduced — PEG > 3.0 | P/E >80 hard cap: never full-size"
    elif pe is not None and pe > 0:
        if pe < 15:
            size = "Full — P/E < 15"
        elif pe <= 25:
            size = "Standard — P/E 15-25"
        else:
            size = "Reduced — P/E > 25"
    elif pe is not None and pe < 0:
        size = "Reduced — negative P/E (unprofitable)"
    else:
        size = "Unable to determine — missing P/E data"

    factor_scores: dict[str, str] = {}

    leverage_inflated = de is not None and de > 3
    if roe is not None:
        if roe < 5 or (leverage_inflated and (pe is None or pe < 0)):
            detail = f"{roe:.0f}%"
            if leverage_inflated:
                detail += f", D/E {de:.0f}x"
            factor_scores["ROE"] = f"Negative ({detail})"
        elif roe < 15:
            factor_scores["ROE"] = f"Neutral ({roe:.0f}%)"
        elif roe >= 25 and not leverage_inflated:
            factor_scores["ROE"] = f"Bullish ({roe:.0f}%)"
        elif leverage_inflated:
            factor_scores["ROE"] = f"Neutral ({roe:.0f}%, D/E {de:.0f}x)"
        else:
            factor_scores["ROE"] = f"Moderate ({roe:.0f}%)"
    else:
        factor_scores["ROE"] = "N/A (no data)"

    if rev_growth is not None:
        if rev_growth < 0 or margin_trend == "Compressing":
            parts = []
            if rev_growth < 0:
                parts.append(f"rev {rev_growth:+.0f}%")
            if margin_trend == "Compressing":
                parts.append("margins compressing")
            factor_scores["Growth"] = f"Negative ({', '.join(parts)})"
        elif rev_growth > 10 and margin_trend != "Compressing":
            factor_scores["Growth"] = f"Bullish (rev +{rev_growth:.0f}%)"
        elif rev_growth > 5 and margin_trend != "Compressing":
            factor_scores["Growth"] = f"Moderate (rev +{rev_growth:.0f}%)"
        else:
            factor_scores["Growth"] = f"Neutral (rev +{rev_growth:.0f}%)"
    else:
        factor_scores["Growth"] = "N/A (no revenue data)"

    most_recent_margin = margins[0][1] if margins else None
    if most_recent_margin is not None:
        if most_recent_margin < 0:
            factor_scores["Margins"] = f"Negative ({most_recent_margin:.1f}%)"
        elif most_recent_margin < 10:
            factor_scores["Margins"] = f"Neutral ({most_recent_margin:.1f}%)"
        elif most_recent_margin < 20:
            factor_scores["Margins"] = f"Moderate ({most_recent_margin:.1f}%)"
        else:
            factor_scores["Margins"] = f"Bullish ({most_recent_margin:.1f}%)"
    else:
        factor_scores["Margins"] = "N/A (no data)"

    fcf_values: list[float] = []
    for cfq in cf_quarters[:2]:
        op_cf = cfq.get("Operating CF")
        capex = cfq.get("Capex")
        if op_cf is not None:
            # abs(): capex is an outflow either way, so a filer presenting it
            # negative can't flip the subtraction into an addition.
            fcf_values.append(op_cf - abs(capex or 0))
    if len(fcf_values) >= 1:
        latest_fcf = fcf_values[0]
        burning = all(f < 0 for f in fcf_values) and len(fcf_values) >= 2
        if burning:
            fmt = f"-${abs(latest_fcf) / 1e6:.0f}M"
            factor_scores["Cash Flow"] = f"Negative (FCF {fmt}, burning)"
        elif latest_fcf < 0:
            fmt = f"-${abs(latest_fcf) / 1e6:.0f}M"
            factor_scores["Cash Flow"] = f"Neutral (FCF {fmt})"
        else:
            fmt = f"${latest_fcf / 1e6:.0f}M"
            factor_scores["Cash Flow"] = f"Bullish (FCF {fmt})"
    else:
        factor_scores["Cash Flow"] = "N/A (no data)"

    neg_count = sum(1 for v in factor_scores.values() if v.startswith("Negative"))
    bull_count = sum(1 for v in factor_scores.values() if v.startswith("Bullish"))
    mod_count = sum(1 for v in factor_scores.values() if v.startswith("Moderate"))

    if neg_count >= 2:
        conviction = "Negative"
    elif neg_count == 1 and bull_count == 0 and mod_count == 0:
        conviction = "Low"
    elif bull_count >= 3 and neg_count == 0:
        conviction = "Highest"
    elif bull_count >= 2:
        conviction = "High"
    elif bull_count == 1 or mod_count >= 2:
        conviction = "Moderate"
    elif mod_count == 1:
        conviction = "Low"
    else:
        conviction = "Low"

    return {
        "pe": pe,
        "roe": roe,
        "de": de,
        "price": price,
        "high_52w": high_52w,
        "drawdown_pct": drawdown_pct,
        "rev_growth": rev_growth,
        "current_q": current_q,
        "prior_q": prior_q,
        "margins": margins,
        "margin_trend": margin_trend,
        "peg": peg,
        "peg_valid": peg_valid,
        "peg_note": peg_note,
        "size": size,
        "conviction": conviction,
        "factor_scores": factor_scores,
    }


def _format_conviction(d: dict[str, Any], data: dict[str, str]) -> None:
    conviction = d.get("conviction", "Unknown")
    factor_scores: dict[str, str] = d.get("factor_scores", {})
    scores_str = " | ".join(f"{k}: {v}" for k, v in factor_scores.items())
    if conviction == "Negative":
        data["Conviction"] = f"**{conviction}** — route to bearish framework"
    else:
        data["Conviction"] = conviction
    if scores_str:
        data["Conviction Inputs"] = scores_str
    if conviction == "Negative":
        pe = d.get("pe")
        rev_growth = d.get("rev_growth")
        disconnects: list[str] = []
        if pe is not None and pe > 50 and (rev_growth is None or rev_growth < 5):
            growth_str = f"{rev_growth:+.0f}%" if rev_growth is not None else "N/A"
            disconnects.append(f"P/E {pe:.0f}x with {growth_str} growth")
        if disconnects:
            data["Valuation Disconnect"] = " | ".join(disconnects)
