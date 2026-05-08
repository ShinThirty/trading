"""Motley Fool endpoint definitions for earnings call transcripts.

Discovery flow:
  1. Fetch the monthly sitemap (immutable for past months, ~1h refresh for current).
  2. Grep transcript URLs for the ticker; pick the most recent.
  3. Fetch the transcript page and extract clean text.
"""

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from html.parser import HTMLParser

from trading_clients.endpoint import Endpoint, ParamsRequest, PathRequest

# ═══════════════════════════════════════════════════════════════
# Request Models
# ═══════════════════════════════════════════════════════════════


@dataclass
class MonthlySitemapRequest(PathRequest, ParamsRequest):
    year: int
    month: int

    def to_path_params(self) -> dict[str, str]:
        return {"year": f"{self.year:04d}", "month": f"{self.month:02d}"}

    def to_params(self) -> dict[str, str]:
        return {}


@dataclass
class TranscriptPageRequest(PathRequest, ParamsRequest):
    """Fetch a transcript by its post-base path, e.g.
    '/earnings/call-transcripts/2025/01/30/apple-aapl-q1-2025-earnings-call-transcript/'.
    """

    path: str

    def to_path_params(self) -> dict[str, str]:
        return {"path": self.path.lstrip("/")}

    def to_params(self) -> dict[str, str]:
        return {}


# ═══════════════════════════════════════════════════════════════
# Response Models
# ═══════════════════════════════════════════════════════════════

_SITEMAP_NS = "{http://www.google.com/schemas/sitemap/0.84}"
_TRANSCRIPT_RE = re.compile(
    r"^https?://www\.fool\.com(/earnings/call-transcripts/\d{4}/\d{2}/\d{2}/[^/]+/)$"
)


@dataclass
class MonthlySitemapResponse:
    """Parsed monthly sitemap. Exposes only transcript URLs (the rest is irrelevant)."""

    transcript_paths: list[str] = field(default_factory=list)

    @classmethod
    def from_response(cls, text: str) -> "MonthlySitemapResponse":
        if not text:
            return cls()
        try:
            root = ET.fromstring(text)
        except ET.ParseError:
            return cls()
        paths: list[str] = []
        # Sitemap may be either a sitemapindex (links to sub-sitemaps) or urlset.
        # Fool's monthly sitemap is a urlset of <sitemap><loc>... entries.
        for loc in root.iter(f"{_SITEMAP_NS}loc"):
            url = (loc.text or "").strip()
            m = _TRANSCRIPT_RE.match(url)
            if m:
                paths.append(m.group(1))
        return cls(transcript_paths=paths)

    def find_latest_transcript(self, ticker: str) -> str | None:
        """Return the post-base path of the most recent transcript for ticker, or None.

        URL slug convention: '<company>-<ticker>-q<N>-<FY>-earnings-call-transcript'.
        We match '-<ticker>-' to avoid partial-symbol false positives (e.g. AAP vs AAPL).
        """
        needle = f"-{ticker.lower()}-"
        matches = [p for p in self.transcript_paths if needle in p.lower()]
        if not matches:
            return None
        # Path begins with /earnings/call-transcripts/YYYY/MM/DD/...; lex sort = date sort.
        matches.sort(reverse=True)
        return matches[0]

    def to_output(self) -> str:
        if not self.transcript_paths:
            return "(no transcripts)"
        return f"{len(self.transcript_paths)} transcript URLs in sitemap"


class _TranscriptHTMLParser(HTMLParser):
    """Strip nav/script/style/header/footer, keep paragraph and heading boundaries."""

    SKIP_TAGS = {"script", "style", "noscript", "header", "footer", "nav", "svg", "form", "aside"}
    BLOCK_TAGS = {"p", "div", "br", "h1", "h2", "h3", "h4", "li", "tr"}

    def __init__(self) -> None:
        super().__init__()
        self._skip_depth = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self.SKIP_TAGS:
            self._skip_depth += 1
        elif tag in self.BLOCK_TAGS and self._skip_depth == 0:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in self.SKIP_TAGS and self._skip_depth > 0:
            self._skip_depth -= 1
        elif tag in self.BLOCK_TAGS and self._skip_depth == 0:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth == 0:
            self.parts.append(data)


@dataclass
class TranscriptResponse:
    text: str

    @classmethod
    def from_response(cls, html: str) -> "TranscriptResponse":
        if not html:
            return cls(text="")
        parser = _TranscriptHTMLParser()
        parser.feed(html)
        raw = "".join(parser.parts)
        # Collapse whitespace within lines, then drop empty lines.
        lines = [re.sub(r"\s+", " ", line).strip() for line in raw.split("\n")]
        cleaned = "\n".join(line for line in lines if line)
        # Fool wraps the transcript in nav/ticker-tape (top) and a "Read Next"
        # recommendation list (bottom). Trim with stable anchors. If an anchor is
        # missing on a future layout change, leave that edge intact rather than fail.
        start = cleaned.find("Image source: The Motley Fool")
        if start >= 0:
            nl = cleaned.find("\n", start)
            cleaned = cleaned[nl + 1 :] if nl >= 0 else cleaned
        end = cleaned.find("Read Next")
        if end > 0:
            cleaned = cleaned[:end].rstrip()
        return cls(text=cleaned)

    def to_output(self) -> str:
        return self.text or "(no transcript content)"


# ═══════════════════════════════════════════════════════════════
# Endpoint Definitions
# ═══════════════════════════════════════════════════════════════

# Current-month sitemap grows as new posts land; 1h TTL is a reasonable balance.
# Past-month sitemaps are immutable but share the same TTL — re-fetch cost is one
# small request, not worth a per-month TTL strategy.
MONTHLY_SITEMAP = Endpoint(
    "/sitemap/{year}/{month}",
    cache_ttl=3600,
    response_model=MonthlySitemapResponse,
)

# Transcript pages are immutable once published — long TTL.
TRANSCRIPT_PAGE = Endpoint(
    "/{path}",
    cache_ttl=30 * 24 * 3600,
    response_model=TranscriptResponse,
)
