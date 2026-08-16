import asyncio
import sqlite3
import tempfile
from collections.abc import Sequence
from datetime import date
from typing import Any, cast

from fastmcp import Context
from trading_clients import indicators as ta
from trading_clients.alphavantage_client import AlphaVantageClient
from trading_clients.bea_client import BeaClient
from trading_clients.beige_book_client import BeigeBookClient
from trading_clients.bls_client import BlsClient
from trading_clients.cftc_client import CftcClient
from trading_clients.edgar_client import EdgarClient
from trading_clients.eia_client import EiaClient
from trading_clients.endpoints import tradier as t
from trading_clients.factset_client import FactsetClient
from trading_clients.fed_client import FedClient
from trading_clients.finnhub_client import FinnhubClient
from trading_clients.finra_client import FinraClient
from trading_clients.fmp_client import FmpClient
from trading_clients.fool_client import FoolClient
from trading_clients.fred_client import FredClient
from trading_clients.freightos_client import FreightosClient
from trading_clients.kalshi_client import KalshiClient
from trading_clients.morningstar_client import MorningstarClient
from trading_clients.naaim_client import NaaimClient
from trading_clients.openfigi_client import OpenFigiClient
from trading_clients.polymarket_client import PolymarketClient
from trading_clients.portwatch_client import PortwatchClient
from trading_clients.reddit_client import RedditClient
from trading_clients.sentiment_client import SentimentClient
from trading_clients.snaptrade_client import SnapTradeClient
from trading_clients.squeeze_metrics_client import SqueezeMetricsClient
from trading_clients.ssga_client import SsgaClient
from trading_clients.tastytrade_client import TastyTradeClient
from trading_clients.tradier_client import TradierClient
from trading_clients.treasury_client import TreasuryClient
from trading_clients.twse_client import TwseClient
from trading_clients.webull_client import WebullClient


def _year_ago(d: date) -> date:
    try:
        return d.replace(year=d.year - 1)
    except ValueError:
        return d.replace(year=d.year - 1, day=28)


def _lc(ctx: Context) -> dict[str, Any]:
    """Parent server's lifespan dict.

    Reads through ``request_context`` because tools registered on mounted
    subservers see their own (empty) ``ctx.lifespan_context``. The request
    context always belongs to the parent (MCP session owner), so its
    lifespan dict is the one populated by ``server.py:lifespan()``.
    """
    rc = ctx.request_context
    if rc is None:
        raise RuntimeError("No request context — helper called outside a tool handler")
    return rc.lifespan_context


def _db(ctx: Context) -> sqlite3.Connection:
    return _lc(ctx)["db"]


def _webull(ctx: Context) -> WebullClient:
    return _lc(ctx)["webull"]


def _tradier(ctx: Context) -> TradierClient:
    client = _optional_tradier(ctx)
    if client is None:
        raise RuntimeError("Tradier not configured. Add [tradier] section to ~/.tradingrc")
    return client


def _optional_tradier(ctx: Context) -> TradierClient | None:
    """Tradier client if [tradier] is configured, else None — for callers that
    can fall back to another provider instead of erroring."""
    return _lc(ctx).get("tradier")


def _snaptrade(ctx: Context) -> SnapTradeClient:
    client = _optional_snaptrade(ctx)
    if client is None:
        raise RuntimeError("SnapTrade not configured. Add [snaptrade] section to ~/.tradingrc")
    return client


def _optional_snaptrade(ctx: Context) -> SnapTradeClient | None:
    """SnapTrade client if [snaptrade] is configured, else None — the source for
    Fidelity/NetBenefits holdings in the portfolio aggregation."""
    return _lc(ctx).get("snaptrade")


def _finnhub(ctx: Context) -> FinnhubClient:
    client = _lc(ctx).get("finnhub")
    if client is None:
        raise RuntimeError("Finnhub not configured. Add [finnhub] section to ~/.tradingrc")
    return client


def _fmp(ctx: Context) -> FmpClient:
    client = _optional_fmp(ctx)
    if client is None:
        raise RuntimeError("FMP not configured. Add [fmp] section to ~/.tradingrc")
    return client


def _optional_fmp(ctx: Context) -> FmpClient | None:
    """FMP client if [fmp] is configured, else None — for callers that can
    fall back to another provider instead of erroring."""
    return _lc(ctx).get("fmp")


def _fred(ctx: Context) -> FredClient:
    client = _lc(ctx).get("fred")
    if client is None:
        raise RuntimeError("FRED not configured. Add [fred] section to ~/.tradingrc")
    return client


def _alphavantage(ctx: Context) -> AlphaVantageClient:
    client = _lc(ctx).get("alphavantage")
    if client is None:
        raise RuntimeError(
            "Alpha Vantage not configured. Add [alphavantage] section to ~/.tradingrc"
        )
    return client


def _eia(ctx: Context) -> EiaClient:
    client = _lc(ctx).get("eia")
    if client is None:
        raise RuntimeError(
            "EIA not configured. Add [eia] api_key=... to ~/.tradingrc "
            "(register free at https://www.eia.gov/opendata/register.php)."
        )
    return client


def _finra(ctx: Context) -> FinraClient:
    client = _lc(ctx).get("finra")
    if client is None:
        raise RuntimeError(
            "FINRA not configured. Add [finra] api_client_id/api_secret to ~/.tradingrc "
            "(free account at developer.finra.org), and accept the Fixed Income Data "
            "user agreement — corporate datasets 404 until you do."
        )
    return client


def _openfigi(ctx: Context) -> OpenFigiClient:
    return _lc(ctx)["openfigi"]


def _ssga(ctx: Context) -> SsgaClient:
    return _lc(ctx)["ssga"]


def _tastytrade(ctx: Context) -> TastyTradeClient:
    client = _optional_tastytrade(ctx)
    if client is None:
        raise RuntimeError(
            "TastyTrade not configured. Add [tastytrade] section to ~/.tradingrc "
            "with client_secret and refresh_token."
        )
    return client


def _optional_tastytrade(ctx: Context) -> TastyTradeClient | None:
    """TastyTrade client if [tastytrade] is configured, else None — for callers
    that can fall back to another provider instead of erroring."""
    return _lc(ctx).get("tastytrade")


def _reddit(ctx: Context) -> RedditClient:
    return _lc(ctx)["reddit"]


def _fool(ctx: Context) -> FoolClient:
    return _lc(ctx)["fool"]


def _edgar(ctx: Context) -> EdgarClient:
    return _lc(ctx)["edgar"]


def _bls(ctx: Context) -> BlsClient:
    return _lc(ctx)["bls"]


def _bea(ctx: Context) -> BeaClient:
    return _lc(ctx)["bea"]


def _fed(ctx: Context) -> FedClient:
    return _lc(ctx)["fed"]


def _cftc(ctx: Context) -> CftcClient:
    return _lc(ctx)["cftc"]


def _polymarket(ctx: Context) -> PolymarketClient:
    return _lc(ctx)["polymarket"]


def _kalshi(ctx: Context) -> KalshiClient:
    return _lc(ctx)["kalshi"]


def _twse(ctx: Context) -> TwseClient:
    return _lc(ctx)["twse"]


def _treasury(ctx: Context) -> TreasuryClient:
    return _lc(ctx)["treasury"]


def _freightos(ctx: Context) -> FreightosClient:
    return _lc(ctx)["freightos"]


def _portwatch(ctx: Context) -> PortwatchClient:
    return _lc(ctx)["portwatch"]


def _beige_book(ctx: Context) -> BeigeBookClient:
    return _lc(ctx)["beige_book"]


def _squeeze_metrics(ctx: Context) -> SqueezeMetricsClient:
    return _lc(ctx)["squeeze_metrics"]


def _naaim(ctx: Context) -> NaaimClient:
    return _lc(ctx)["naaim"]


def _factset(ctx: Context) -> FactsetClient:
    return _lc(ctx)["factset"]


def _sentiment(ctx: Context) -> SentimentClient | None:
    """Optional client. Returns None if Playwright failed to start at lifespan
    init (e.g. browser binary missing) — callers should treat the sentiment
    dimension as unavailable rather than erroring."""
    return _lc(ctx).get("sentiment")


def _morningstar(ctx: Context) -> MorningstarClient | None:
    """Optional client. Returns None if Playwright failed to start at lifespan
    init — callers should fall back to other transcript sources."""
    return _lc(ctx).get("morningstar")


async def _check_market(ctx: Context, order_type: str, extended_hours: bool) -> None:
    tradier = _optional_tradier(ctx)
    if tradier is None:
        return
    clock = await tradier.get(t.CLOCK, t.EmptyRequest())
    state = clock.data.get("state", "closed")
    if order_type == "MARKET" and state != "open" and not extended_hours:
        raise RuntimeError(
            f"MARKET orders require regular hours (state: {state}). "
            "Use a LIMIT order, or wait for market open."
        )


async def _cached(cache: Any, key: str, ttl: int, fn: Any, *args: Any, **kwargs: Any) -> Any:
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


def _result_or_warn[T](
    results: Sequence[Any],
    idx: int,
    source: str,
    warnings: list[str],
    expected_type: type[T],
) -> T | None:
    """Extract results[idx] from an asyncio.gather(..., return_exceptions=True) list.

    On BaseException, append a one-line warning and return None. Otherwise cast
    to expected_type so heterogeneous-gather callers get a usable static type.
    """
    val = results[idx]
    if isinstance(val, BaseException):
        warnings.append(_exc_summary(source, val))
        return None
    return cast(T, val)


def _exc_summary(source: str, exc: BaseException) -> str:
    """One-line description of a failed scrape/API call, suitable for surfacing
    in tool output as a warning or error message. Truncates long messages and
    drops multi-line tracebacks."""
    raw = str(exc).strip()
    msg = raw.splitlines()[0] if raw else ""
    return f"{source}: {type(exc).__name__}{f': {msg[:120]}' if msg else ''}"


async def _write_temp_file(content: str, suffix: str, prefix: str) -> str:

    def _sync_write() -> str:
        f = tempfile.NamedTemporaryFile(mode="w", suffix=suffix, prefix=prefix, delete=False)
        f.write(content)
        f.close()
        return f.name

    return await asyncio.to_thread(_sync_write)


# ── Short-window variance concentration ─────────────────────────────
# Shared by get_technical_indicators (which reports it) and get_expected_move (which
# uses it to escalate its stale-trailing-vol warning), so both quote the same number.
#
# Measured across 12 names (~1,000 windows each): a 10-bar squared-return window
# carries a MEDIAN effective 4.1 of its 10 bars, 1st percentile 1.7 — HV10 is
# structurally low-information for everyone, not only after a gap. So effN is reported
# as standing context and only the severe tail raises a warning.
#
# The floor is absolute, not percentile-ranked against the name's own history: a
# chronically gap-driven name (WDC) has no unusual windows, so self-calibration goes
# quiet exactly where the caveat matters most. <2.5 fires on 8.4% of windows at 99%
# precision (the dominant bar is a >=2x-median move); loosening to 3.5 fires on 33.6%
# for the same 98%, too noisy to keep meaning.
#
# Range and volume windows get no equivalent check: measured effN never approaches
# domination (range/14 1st pctile 9.1 of 14; volume/20 1st pctile 10.3 of 20), matching
# their small measured gap sensitivity. OBV is the exception, but its problem is sign
# persistence rather than magnitude concentration, and `obv_anchor_date` handles it.
_HV_EFF_WINDOW = 10
_HV_EFF_FLOOR = 2.5


def _hv_effective_n(closes: list[float]) -> tuple[float, float, int] | None:
    """(effective bars, dominant bar's share, its index into closes) for the HV10 window."""
    sq = [r * r for r in ta.log_returns(closes)]  # aligned to closes[1:]
    eff = ta.window_effective_n(sq, _HV_EFF_WINDOW)
    share = ta.window_concentration(sq, _HV_EFF_WINDOW)
    if not eff or eff[-1] is None or not share or share[-1] is None:
        return None
    recent = sq[-_HV_EFF_WINDOW:]
    offset = max(range(len(recent)), key=lambda j: recent[j])
    return eff[-1], share[-1], len(sq) - _HV_EFF_WINDOW + offset + 1
