import asyncio
import sqlite3
import tempfile
from datetime import date
from typing import Any

from fastmcp import Context
from trading_clients.alphavantage_client import AlphaVantageClient
from trading_clients.endpoint import CONTRACT_MULTIPLIER
from trading_clients.endpoints import finnhub as fh
from trading_clients.endpoints import tradier as t
from trading_clients.endpoints.webull import (
    ACCOUNT_LIST,
    BALANCE,
    POSITIONS,
    AccountRequest,
    EmptyRequest,
)
from trading_clients.finnhub_client import FinnhubClient
from trading_clients.fmp_client import FmpClient
from trading_clients.fred_client import FredClient
from trading_clients.portfolio import AccountSummary, parse_fidelity_folder
from trading_clients.reddit_client import RedditClient
from trading_clients.table_helpers import to_float, to_float_zero
from trading_clients.tastytrade_client import TastyTradeClient
from trading_clients.tradier_client import TradierClient
from trading_clients.webull_client import WebullClient


def _year_ago(d: date) -> date:
    try:
        return d.replace(year=d.year - 1)
    except ValueError:
        return d.replace(year=d.year - 1, day=28)


def _db(ctx: Context) -> sqlite3.Connection:
    return ctx.lifespan_context["db"]


def _webull(ctx: Context) -> WebullClient:
    return ctx.lifespan_context["webull"]


def _tradier(ctx: Context) -> TradierClient:
    client = ctx.lifespan_context.get("tradier")
    if client is None:
        raise RuntimeError("Tradier not configured. Add [tradier] section to ~/.tradingrc")
    return client


def _finnhub(ctx: Context) -> FinnhubClient:
    client = ctx.lifespan_context.get("finnhub")
    if client is None:
        raise RuntimeError("Finnhub not configured. Add [finnhub] section to ~/.tradingrc")
    return client


def _fmp(ctx: Context) -> FmpClient:
    client = ctx.lifespan_context.get("fmp")
    if client is None:
        raise RuntimeError("FMP not configured. Add [fmp] section to ~/.tradingrc")
    return client


def _fred(ctx: Context) -> FredClient:
    client = ctx.lifespan_context.get("fred")
    if client is None:
        raise RuntimeError("FRED not configured. Add [fred] section to ~/.tradingrc")
    return client


def _alphavantage(ctx: Context) -> AlphaVantageClient:
    client = ctx.lifespan_context.get("alphavantage")
    if client is None:
        raise RuntimeError(
            "Alpha Vantage not configured. Add [alphavantage] section to ~/.tradingrc"
        )
    return client


def _tastytrade(ctx: Context) -> TastyTradeClient:
    client = ctx.lifespan_context.get("tastytrade")
    if client is None:
        raise RuntimeError(
            "TastyTrade not configured. Add [tastytrade] section to ~/.tradingrc "
            "with client_secret and refresh_token."
        )
    return client


def _reddit(ctx: Context) -> RedditClient:
    return ctx.lifespan_context["reddit"]


async def _check_market(ctx: Context, order_type: str, extended_hours: bool) -> None:
    tradier = ctx.lifespan_context.get("tradier")
    if tradier is None:
        return
    clock = await tradier.get(t.CLOCK, t.EmptyRequest())
    state = clock.data.get("state", "closed")
    if order_type == "MARKET" and state != "open" and not extended_hours:
        raise RuntimeError(
            f"MARKET orders require regular hours (state: {state}). "
            "Use a LIMIT order, or wait for market open."
        )


async def _cached(
    cache: Any, key: str, ttl: int, fn: Any, *args: Any, **kwargs: Any
) -> Any:
    hit = cache.get(key, ttl)
    if hit is not None:
        return hit
    result = await asyncio.to_thread(fn, *args, **kwargs)
    cache.put(key, result)
    return result


async def _retry(fn: Any, *args: Any, retries: int = 2, delay: float = 2, **kwargs: Any) -> Any:
    for attempt in range(retries + 1):
        try:
            return await fn(*args, **kwargs)
        except Exception:
            if attempt < retries:
                await asyncio.sleep(delay)
                continue
            raise


async def _write_temp_file(content: str, suffix: str, prefix: str) -> str:

    def _sync_write() -> str:
        f = tempfile.NamedTemporaryFile(mode="w", suffix=suffix, prefix=prefix, delete=False)
        f.write(content)
        f.close()
        return f.name

    return await asyncio.to_thread(_sync_write)


async def _fetch_accounts(
    ctx: Context,
    fidelity_folder: str | None = None,
) -> tuple[list, dict[str, str]]:
    webull = _webull(ctx)
    summaries: list[AccountSummary] = []
    errors: dict[str, str] = {}

    account_list = await webull.get(ACCOUNT_LIST, EmptyRequest())
    if not account_list.accounts:
        errors["Webull"] = "No accounts found"

    for acct in account_list.accounts:
        aid = acct.get("account_id", "")
        label = acct.get("account_label", acct.get("account_type", aid))
        atype = acct.get("account_type", "")

        try:
            bal = await _retry(webull.get,BALANCE, AccountRequest(aid))
        except Exception as e:
            errors[label] = str(e)
            continue

        nlv = to_float_zero(bal.net_liquidation)
        cash = to_float_zero(bal.cash_balance)
        mv = to_float_zero(bal.market_value)

        try:
            pos_resp = await _retry(webull.get,POSITIONS, AccountRequest(aid))
            positions = pos_resp.to_normalized()
        except Exception as e:
            positions = []
            errors[f"{label} (positions)"] = str(e)

        cash_equiv_value = sum(p["value"] for p in positions if p.get("is_cash"))
        cash += cash_equiv_value
        mv -= cash_equiv_value

        summaries.append(
            AccountSummary(
                account_id=aid,
                label=label,
                broker="Webull",
                account_type=atype,
                nlv=nlv,
                cash=cash,
                market_value=mv,
                day_pnl=to_float_zero(bal.day_pnl),
                unrealized_pnl=to_float_zero(bal.unrealized_pnl),
                positions=positions,
            )
        )

    if fidelity_folder:
        try:
            summaries.extend(await parse_fidelity_folder(fidelity_folder))
        except Exception as e:
            errors["Fidelity"] = str(e)

    return summaries, errors


async def _fetch_all_positions(
    ctx: Context,
    fidelity_folder: str | None = None,
) -> tuple[list[dict], list[str]]:
    webull = _webull(ctx)
    all_positions: list[dict] = []
    errors: list[str] = []

    account_list = await webull.get(ACCOUNT_LIST, EmptyRequest())
    for acct in account_list.accounts:
        aid = acct.get("account_id", "")
        label = acct.get("account_label", aid)
        try:
            pos_resp = await _retry(webull.get,POSITIONS, AccountRequest(aid))
            all_positions.extend(pos_resp.to_normalized())
        except Exception as e:
            errors.append(f"{label}: {e}")

    if fidelity_folder:
        for acct in await parse_fidelity_folder(fidelity_folder):
            all_positions.extend(acct.positions)

    return all_positions, errors


def _compute_csp_collateral(positions: list[dict]) -> float:
    total = 0.0
    for p in positions:
        if not p.get("is_option") or p.get("option_type") != "put":
            continue
        qty = p.get("quantity", 0)
        if qty >= 0:
            continue
        total += p.get("strike", 0) * CONTRACT_MULTIPLIER * abs(qty)
    return total


async def _fetch_total_nlv(ctx: Context, fidelity_folder: str | None = None) -> float:
    webull = _webull(ctx)
    account_list = await webull.get(ACCOUNT_LIST, EmptyRequest())
    total = 0.0
    for acct in account_list.accounts:
        aid = acct.get("account_id", "")
        try:
            bal = await _retry(webull.get,BALANCE, AccountRequest(aid))
            total += to_float_zero(bal.net_liquidation)
        except Exception:
            continue

    if fidelity_folder:
        try:
            for acct in await parse_fidelity_folder(fidelity_folder):
                total += acct.nlv
        except Exception:
            pass

    return total


async def _conviction_data(ctx: Context, symbol: str) -> dict[str, Any]:
    finnhub_client = _finnhub(ctx)
    tradier_client = _tradier(ctx)
    basics_r, fin_r, quote_r = await asyncio.gather(
        finnhub_client.get(fh.BASIC_FINANCIALS, fh.BasicFinancialsRequest(symbol)),
        finnhub_client.get(
            fh.FINANCIALS_REPORTED, fh.FinancialsReportedRequest(symbol, "quarterly")
        ),
        tradier_client.get(t.QUOTES, t.GetQuotesRequest(symbol)),
        return_exceptions=True,
    )

    basics = None if isinstance(basics_r, BaseException) else basics_r
    fin = None if isinstance(fin_r, BaseException) else fin_r
    quote_resp = None if isinstance(quote_r, BaseException) else quote_r

    metric = basics.data.get("metric", {}) if basics else {}
    pe = to_float(metric.get("peNormalizedAnnual"))
    roe = to_float(metric.get("roeTTM"))
    de = to_float(metric.get("totalDebt/totalEquityAnnual"))

    q = quote_resp.quotes[0] if quote_resp and quote_resp.quotes else {}
    price = to_float(q.get("last"))
    high_52w = to_float(q.get("week_52_high"))

    quarters = fin.income_numeric(8) if fin else []
    cf_quarters = fin.cf_numeric(4) if fin else []

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
        if margins[0][1] > margins[1][1] + 0.5:
            margin_trend = "Expanding"
        elif margins[0][1] < margins[1][1] - 0.5:
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
            fcf = op_cf - (capex or 0)
            fcf_values.append(fcf)
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
