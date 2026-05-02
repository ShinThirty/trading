from datetime import date, timedelta

import httpx
from fastmcp import Context, FastMCP
from trading_clients.cache import TTLCache
from trading_clients.table_helpers import fmt_large, list_table

mcp = FastMCP("finra-tools")

_BASE_URL = "https://cdn.finra.org/equity/regsho/daily/CNMSshvol{date}.txt"
_cache = TTLCache()
_TTL_HISTORICAL = 86400 * 7


async def _fetch_day(client: httpx.AsyncClient, d: date) -> list[dict]:
    key = f"finra:{d.isoformat()}"
    hit = _cache.get(key, _TTL_HISTORICAL)
    if hit is not None:
        return hit

    url = _BASE_URL.format(date=d.strftime("%Y%m%d"))
    try:
        resp = await client.get(url)
        if resp.status_code == 403:
            return []
        resp.raise_for_status()
    except httpx.HTTPError:
        return []

    rows: list[dict] = []
    for line in resp.text.splitlines()[1:]:
        parts = line.split("|")
        if len(parts) < 5:
            continue
        rows.append(
            {
                "date": parts[0],
                "symbol": parts[1],
                "short_volume": float(parts[2]),
                "short_exempt_volume": float(parts[3]),
                "total_volume": float(parts[4]),
            }
        )

    _cache.put(key, rows)
    return rows


def _business_days(end: date, count: int) -> list[date]:
    days: list[date] = []
    d = end
    while len(days) < count:
        if d.weekday() < 5:
            days.append(d)
        d -= timedelta(days=1)
    days.reverse()
    return days


@mcp.tool()
async def get_short_volume(ctx: Context, symbol: str, days: int = 20) -> str:
    """Get daily short sale volume from FINRA for the last N trading days.

    Shows short volume, total volume, and short volume ratio (short / total)
    for each trading day. Useful for tracking squeeze dynamics between the
    bi-monthly short interest reports.

    symbol: ticker symbol (e.g. 'WOLF', 'GME').
    days: number of trading days to fetch (default 20, max 60).

    Source: FINRA Combined NMS short volume data (no API key required).
    """
    symbol = symbol.upper()
    days = min(days, 60)
    targets = _business_days(date.today() - timedelta(days=1), days)

    results: list[dict] = []
    async with httpx.AsyncClient(timeout=15) as client:
        for d in targets:
            rows = await _fetch_day(client, d)
            for r in rows:
                if r["symbol"] == symbol:
                    short_vol = r["short_volume"]
                    total_vol = r["total_volume"]
                    ratio = short_vol / total_vol * 100 if total_vol > 0 else 0
                    results.append(
                        {
                            "Date": d.strftime("%Y-%m-%d"),
                            "Short Vol": fmt_large(short_vol),
                            "Total Vol": fmt_large(total_vol),
                            "Short %": f"{ratio:.1f}%",
                            "Exempt Vol": fmt_large(r["short_exempt_volume"]),
                        }
                    )
                    break

    if not results:
        return f"No FINRA short volume data found for {symbol}."

    short_pcts = []
    for r in results:
        try:
            short_pcts.append(float(r["Short %"].rstrip("%")))
        except ValueError:
            pass
    avg_pct = sum(short_pcts) / len(short_pcts) if short_pcts else 0

    header = f"## {symbol} Daily Short Volume ({len(results)} days)\n\n"
    header += f"Average short volume ratio: {avg_pct:.1f}%\n\n"
    return header + list_table(results)
