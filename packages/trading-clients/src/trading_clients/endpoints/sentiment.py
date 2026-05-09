"""Sentiment endpoint definitions: CBOE equity p/c, AAII bull/bear.

Both are fetched via SentimentClient (Playwright). Each endpoint declares its
base URL (since the two sources span two hosts) and parses the rendered body
inner_text returned by the client.

NAAIM exposure used to live here too but moved to a dedicated NaaimClient that
pulls the since-inception XLSX (httpx, no Playwright) — gives the same latest
reading plus full history for z-score / percentile.

Parser inputs are body inner_text (visible text after JS render), which is
more stable than raw HTML — selectors don't break when sites tweak class names,
and table cells come out as tab-separated values.
"""

import re
from dataclasses import dataclass

from trading_clients.endpoint import Endpoint, ParamsRequest

# ═══════════════════════════════════════════════════════════════
# Request Models
# ═══════════════════════════════════════════════════════════════


@dataclass
class EmptyRequest(ParamsRequest):
    def to_params(self) -> dict[str, str]:
        return {}


# ═══════════════════════════════════════════════════════════════
# Response Models
# ═══════════════════════════════════════════════════════════════


@dataclass
class CboeEquityPcResponse:
    """Latest CBOE equity put/call ratio.

    Page renders as a table; inner_text shows tab-separated rows like
    'EQUITY PUT/CALL RATIO\\t0.53'. We pick the equity row specifically — the
    page also lists Index, ETP, VIX, and several SPX-family p/c ratios.
    """

    value: float | None

    @classmethod
    def from_response(cls, body_text: str) -> "CboeEquityPcResponse":
        # Anchor on the exact label so we don't pick up "EXCHANGE TRADED PRODUCTS
        # PUT/CALL RATIO" or "VIX PUT/CALL RATIO" by accident. The numeric is a
        # 1-2 digit integer with 2 decimal places, separated by whitespace (tab).
        m = re.search(
            r"(?:^|\n)\s*EQUITY\s+PUT/CALL\s+RATIO\s+([0-9]+\.[0-9]{2})",
            body_text,
            re.IGNORECASE,
        )
        if not m:
            return cls(value=None)
        try:
            return cls(value=float(m.group(1)))
        except ValueError:
            return cls(value=None)

    def to_output(self) -> str:
        if self.value is None:
            return "(CBOE equity p/c unavailable)"
        return f"CBOE equity p/c: {self.value:.2f}"


@dataclass
class AaiiSentimentResponse:
    """Latest AAII Investor Sentiment Survey (bull/neutral/bear, weekly).

    Page renders a table:
      Bullish Neutral Bearish
      <date>
      <bull%>
      <neutral%>
      <bear%>
      <date>
      <bull%>
      ...

    The first row is the most recent week. Spread is bullish minus bearish —
    the contrarian indicator: extreme bullish-bearish spread reads as crowded;
    extreme negative spread reads as capitulation.
    """

    week_ending: str
    bullish_pct: float
    neutral_pct: float
    bearish_pct: float

    @property
    def spread(self) -> float:
        return self.bullish_pct - self.bearish_pct

    @classmethod
    def from_response(cls, body_text: str) -> "AaiiSentimentResponse | None":
        m = re.search(
            r"Bullish\s+Neutral\s+Bearish\s+(\d+/\d+/\d+)\s+"
            r"([0-9.]+)%\s+([0-9.]+)%\s+([0-9.]+)%",
            body_text,
        )
        if not m:
            return None
        try:
            return cls(
                week_ending=m.group(1),
                bullish_pct=float(m.group(2)),
                neutral_pct=float(m.group(3)),
                bearish_pct=float(m.group(4)),
            )
        except ValueError:
            return None

    def to_output(self) -> str:
        return (
            f"AAII (week ending {self.week_ending}): "
            f"bull {self.bullish_pct:.1f}% / neutral {self.neutral_pct:.1f}% / "
            f"bear {self.bearish_pct:.1f}% (spread {self.spread:+.1f})"
        )


# ═══════════════════════════════════════════════════════════════
# Endpoint Definitions
# ═══════════════════════════════════════════════════════════════

# CBOE equity p/c is republished at end of trading day. 1h TTL is short enough
# to refresh during a daily briefing; longer than the regime tool's typical
# call frequency.
CBOE_EQUITY_PC = Endpoint(
    "/us/options/market_statistics/daily/",
    cache_ttl=3600,
    response_model=CboeEquityPcResponse,
    base_url="https://www.cboe.com",
)

# AAII publishes Thursday afternoons. 1h TTL is generous; the page is stable
# between weekly updates.
AAII_SENTIMENT = Endpoint(
    "/sentimentsurvey",
    cache_ttl=3600,
    response_model=AaiiSentimentResponse,
    base_url="https://www.aaii.com",
)
