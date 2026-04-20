import asyncio
from dataclasses import dataclass
from datetime import date

from fastmcp import Context, FastMCP
from trading_clients.endpoints import tradier as t
from trading_clients.table_helpers import fmt_number, list_table, to_float
from trading_clients.tradier_client import TradierClient

from trading_mcp.helpers import _tradier

mcp = FastMCP("pipeline-tools")


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
