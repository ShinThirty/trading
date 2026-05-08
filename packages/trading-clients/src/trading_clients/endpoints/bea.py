"""BEA endpoint definitions for the Personal Income and Outlays release (PCE).

Discovery flow:
  1. Fetch /news/current-releases — find the latest "Personal Income and Outlays
     -<month>-<year>" link (BEA dates the URL by reference period, not release date).
  2. Fetch that URL and extract the narrative section.
"""

import re
from dataclasses import dataclass
from html.parser import HTMLParser

from trading_clients.endpoint import Endpoint, ParamsRequest, PathRequest

# ═══════════════════════════════════════════════════════════════
# Request Models
# ═══════════════════════════════════════════════════════════════


@dataclass
class EmptyRequest(ParamsRequest):
    def to_params(self) -> dict[str, str]:
        return {}


@dataclass
class ReleasePathRequest(PathRequest, ParamsRequest):
    """Fetch a specific release page by its post-base path, e.g.
    '/news/2026/personal-income-and-outlays-march-2026'.
    """

    path: str

    def to_path_params(self) -> dict[str, str]:
        return {"path": self.path.lstrip("/")}

    def to_params(self) -> dict[str, str]:
        return {}


# ═══════════════════════════════════════════════════════════════
# Response Models
# ═══════════════════════════════════════════════════════════════


_PCE_LINK_RE = re.compile(
    r'href="(/news/\d{4}/personal-income-and-outlays-[a-z]+-\d{4})"'
)


@dataclass
class CurrentReleasesResponse:
    """Index page listing recent BEA news releases. We only care about the latest
    Personal Income and Outlays link.
    """

    pce_release_path: str | None

    @classmethod
    def from_response(cls, html: str) -> "CurrentReleasesResponse":
        if not html:
            return cls(pce_release_path=None)
        # The current-releases page lists newest first, so the first match is latest.
        m = _PCE_LINK_RE.search(html)
        return cls(pce_release_path=m.group(1) if m else None)

    def to_output(self) -> str:
        return self.pce_release_path or "(no PCE release link found)"


class _ReleaseHTMLParser(HTMLParser):
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
class PceReleaseResponse:
    """Narrative section of the BEA Personal Income and Outlays press release.

    Trimmed between "EMBARGOED UNTIL RELEASE" (start of the official content) and
    "Next release" (which marks the boundary into Technical Notes).
    """

    text: str

    @classmethod
    def from_response(cls, html: str) -> "PceReleaseResponse":
        if not html:
            return cls(text="")
        parser = _ReleaseHTMLParser()
        parser.feed(html)
        raw = "".join(parser.parts)
        lines = [re.sub(r"\s+", " ", line).strip() for line in raw.split("\n")]
        cleaned = "\n".join(line for line in lines if line)
        start = cleaned.find("EMBARGOED UNTIL RELEASE")
        if start >= 0:
            cleaned = cleaned[start:]
        end = cleaned.find("Next release")
        if end > 0:
            cleaned = cleaned[:end].rstrip()
        return cls(text=cleaned)

    def to_output(self) -> str:
        return self.text or "(no content)"


# ═══════════════════════════════════════════════════════════════
# Endpoint Definitions
# ═══════════════════════════════════════════════════════════════

# Index page; new releases appear here within minutes of publication.
CURRENT_RELEASES = Endpoint(
    "/news/current-releases",
    cache_ttl=3600,
    response_model=CurrentReleasesResponse,
)

# Specific release pages are immutable once published — long TTL.
PCE_RELEASE = Endpoint(
    "/{path}",
    cache_ttl=24 * 3600,
    response_model=PceReleaseResponse,
)
