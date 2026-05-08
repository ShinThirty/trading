"""BLS endpoint definitions for monthly economic releases.

The Employment Situation press release contains the qualitative texture (industry
mix narrative, revisions wording, U-6 / participation commentary) that journalists
quote — the same data is in FRED as separate series, but only this document carries
the revisions narrative and the precise wording around month-over-month dynamics.
"""

import re
from dataclasses import dataclass
from html.parser import HTMLParser

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


class _PressReleaseHTMLParser(HTMLParser):
    SKIP_TAGS = {"script", "style", "noscript", "header", "footer", "nav", "svg", "form", "aside"}
    BLOCK_TAGS = {"p", "div", "br", "h1", "h2", "h3", "h4", "li", "tr", "table"}

    def __init__(self) -> None:
        super().__init__()
        self._skip = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self.SKIP_TAGS:
            self._skip += 1
        elif tag in self.BLOCK_TAGS and self._skip == 0:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in self.SKIP_TAGS and self._skip > 0:
            self._skip -= 1
        elif tag in self.BLOCK_TAGS and self._skip == 0:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip == 0:
            self.parts.append(data)


@dataclass
class EmploymentSituationResponse:
    """Narrative section of the BLS Employment Situation press release.

    Trimmed to the prose discussion (NFP headline, household survey commentary,
    establishment industry detail, average workweek/earnings, revisions). The
    data tables that follow ("HOUSEHOLD DATA" onward) are excluded — those numbers
    are cleaner via FRED.
    """

    text: str

    @classmethod
    def from_response(cls, html: str) -> "EmploymentSituationResponse":
        if not html:
            return cls(text="")
        parser = _PressReleaseHTMLParser()
        parser.feed(html)
        raw = "".join(parser.parts)
        lines = [re.sub(r"\s+", " ", line).strip() for line in raw.split("\n")]
        cleaned = "\n".join(line for line in lines if line)

        # Trim to just the narrative. The release leads with site-chrome and ends
        # with a long block of data tables we don't need (FRED has the precise numbers).
        start = cleaned.find("THE EMPLOYMENT SITUATION")
        if start >= 0:
            cleaned = cleaned[start:]
        end = cleaned.find("HOUSEHOLD DATA")
        if end > 0:
            cleaned = cleaned[:end].rstrip()
        return cls(text=cleaned)

    def to_output(self) -> str:
        return self.text or "(no content)"


# ═══════════════════════════════════════════════════════════════
# Endpoint Definitions
# ═══════════════════════════════════════════════════════════════

# Released monthly. Once the URL flips to the new month's release (8:30 ET on
# release day), the content is stable. 1h TTL is short enough to catch the flip
# on release morning if we run the briefing twice (pre/post).
EMPLOYMENT_SITUATION = Endpoint(
    "/news.release/empsit.htm",
    cache_ttl=3600,
    response_model=EmploymentSituationResponse,
)
