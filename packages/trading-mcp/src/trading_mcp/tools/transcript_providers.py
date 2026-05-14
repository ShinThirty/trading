"""Earnings transcript provider registry.

Each provider is a small `TranscriptProvider(name, fetch)` record. `fetch` is
an async function taking `(ctx, ticker)` and returning a `TranscriptResult`
that signals whether the transcript was found, where it came from, and any
non-fatal errors encountered along the way.

The orchestrator (`get_earnings_transcript` in tools/earnings.py) walks
`PROVIDERS` in order and returns the first hit. Order = preference: cheapest
and broadest-coverage source first, slower / niche fallbacks after.

Adding a new provider:
  1. Write `async def _<name>_fetch(ctx, ticker) -> TranscriptResult`.
  2. Append `TranscriptProvider("<Display Name>", _<name>_fetch)` to PROVIDERS.

The `TranscriptProvider.__call__` wrapper catches unexpected exceptions and
folds them into `errors` so one provider's bug never kills the whole tool —
the next provider still gets a chance.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import date

from fastmcp import Context
from trading_clients.endpoints import fool as f
from trading_clients.endpoints import morningstar as m

from trading_mcp.helpers import _exc_summary, _fool, _morningstar
from trading_mcp.yfinance_helper import _yfc

# ═══════════════════════════════════════════════════════════════
# Result + Provider types
# ═══════════════════════════════════════════════════════════════


@dataclass
class TranscriptResult:
    """One provider's attempt at a transcript fetch.

    `text is None` means the provider couldn't find or fetch the transcript;
    `errors` lists per-step issues (sitemap fetch failed, exchange unmapped,
    HTTP 404, …) so the final fall-through message can show what was tried.
    """

    text: str | None
    source_url: str | None
    errors: list[str] = field(default_factory=list)

    @property
    def found(self) -> bool:
        return self.text is not None


@dataclass
class TranscriptProvider:
    name: str
    fetch: Callable[[Context, str], Awaitable[TranscriptResult]]

    async def __call__(self, ctx: Context, ticker: str) -> TranscriptResult:
        """Invoke the provider with a top-level safety net so an unexpected
        exception turns into a normal `errors` entry rather than crashing the
        whole tool — the next provider still gets a chance."""
        try:
            return await self.fetch(ctx, ticker)
        except Exception as ex:
            return TranscriptResult(
                text=None,
                source_url=None,
                errors=[_exc_summary(self.name, ex)],
            )


# ═══════════════════════════════════════════════════════════════
# Provider: Motley Fool
# ═══════════════════════════════════════════════════════════════


def _month_offsets(today: date, n: int) -> list[tuple[int, int]]:
    """Return [(year, month)] for the current and `n - 1` preceding months."""
    out: list[tuple[int, int]] = []
    y, mo = today.year, today.month
    for _ in range(n):
        out.append((y, mo))
        mo -= 1
        if mo == 0:
            mo = 12
            y -= 1
    return out


async def _fool_fetch(ctx: Context, ticker: str) -> TranscriptResult:
    """Walk the Fool monthly sitemap (current + 2 prior months) for the latest
    transcript URL, then fetch the transcript page."""
    fool = _fool(ctx)
    errors: list[str] = []
    last_seen_path: str | None = None
    for year, month in _month_offsets(date.today(), 3):
        try:
            sitemap = await fool.get(f.MONTHLY_SITEMAP, f.MonthlySitemapRequest(year, month))
        except Exception as ex:
            errors.append(_exc_summary(f"sitemap {year}-{month:02d}", ex))
            continue
        path = sitemap.find_latest_transcript(ticker)
        if path:
            last_seen_path = path
            break
    if not last_seen_path:
        return TranscriptResult(text=None, source_url=None, errors=errors)
    try:
        transcript = await fool.get(f.TRANSCRIPT_PAGE, f.TranscriptPageRequest(last_seen_path))
    except Exception as ex:
        errors.append(_exc_summary("transcript page", ex))
        return TranscriptResult(text=None, source_url=None, errors=errors)
    return TranscriptResult(
        text=transcript.to_output(),
        source_url=f"https://www.fool.com{last_seen_path}",
        errors=errors,
    )


# ═══════════════════════════════════════════════════════════════
# Provider: Morningstar
# ═══════════════════════════════════════════════════════════════

# Yahoo's internal exchange code → Morningstar URL segment (lowercase MIC).
# yfinance reports e.g. 'ASE' / 'NMS' / 'NYQ'; Morningstar URLs use
# xase / xnas / xnys. Other Yahoo codes (ARCA, BATS, OTC, foreign) don't have
# a US-equity transcript page on this Morningstar host — fall through to None.
_YF_TO_MORNINGSTAR_EXCHANGE = {
    "ASE": "xase",  # NYSE American (formerly AMEX)
    "NYQ": "xnys",  # NYSE
    "NMS": "xnas",  # Nasdaq Global Select
    "NCM": "xnas",  # Nasdaq Capital Market
    "NGM": "xnas",  # Nasdaq Global Market
    "NAS": "xnas",  # generic Nasdaq fallback
}


async def _morningstar_fetch(ctx: Context, ticker: str) -> TranscriptResult:
    """Resolve the ticker's exchange via yfinance, then fetch the Morningstar
    transcript page through Playwright."""
    client = _morningstar(ctx)
    if client is None:
        return TranscriptResult(
            text=None,
            source_url=None,
            errors=["Morningstar client unavailable (Playwright not started at lifespan init)"],
        )
    yf_code = await _yfc.exchange_code(ticker)
    if not yf_code:
        return TranscriptResult(
            text=None,
            source_url=None,
            errors=[f"Could not resolve exchange for {ticker} via yfinance"],
        )
    code = _YF_TO_MORNINGSTAR_EXCHANGE.get(yf_code)
    if code is None:
        return TranscriptResult(
            text=None,
            source_url=None,
            errors=[
                f"Yahoo exchange {yf_code!r} for {ticker} has no Morningstar mapping "
                "(non-US listing or ETF venue)"
            ],
        )
    try:
        resp = await client.get(
            m.EARNINGS_TRANSCRIPT,
            m.TranscriptRequest(exchange_code=code, symbol=ticker),
        )
    except Exception as ex:
        return TranscriptResult(
            text=None,
            source_url=None,
            errors=[_exc_summary(f"/{code}/{ticker.lower()}", ex)],
        )
    text = resp.to_output().strip()
    if not text:
        return TranscriptResult(
            text=None,
            source_url=None,
            errors=[f"empty transcript for {ticker} ({code})"],
        )
    return TranscriptResult(
        text=text,
        source_url=f"https://www.morningstar.com/stocks/{code}/{ticker.lower()}/earnings-transcript",
        errors=[],
    )


# ═══════════════════════════════════════════════════════════════
# Registry — order = preference (broadest coverage first)
# ═══════════════════════════════════════════════════════════════

PROVIDERS: list[TranscriptProvider] = [
    TranscriptProvider("Motley Fool", _fool_fetch),
    TranscriptProvider("Morningstar", _morningstar_fetch),
]
