"""Treasury home.treasury.gov endpoint definitions for the Quarterly
Refunding Announcement (QRA) Policy Statement.

Discovery flow:
  1. Fetch /policy-issues/financing-the-government/quarterly-refunding/
     most-recent-quarterly-refunding-documents — the public landing page
     that always points at the current quarter's docs. Extract the latest
     "Policy Statement" press release URL (e.g. /news/press-releases/sb0489).
  2. Fetch the official-remarks-on-quarterly-refunding archive page —
     extract historical Policy Statement URLs (year + quarter labels) so we
     can find the prior one for language-diff comparison.
  3. Fetch the press release page(s) and extract the article body.

QRA cadence: 4x/year (early Feb / May / Aug / Nov), Wednesday 8:30 AM after
Monday's borrowing estimate. Statements are immutable once published.
"""

import re
from dataclasses import dataclass, field
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
class StatementPathRequest(PathRequest, ParamsRequest):
    """Fetch a specific Treasury press release by its post-base path, e.g.
    '/news/press-releases/sb0489'.
    """

    path: str

    def to_path_params(self) -> dict[str, str]:
        return {"path": self.path.lstrip("/")}

    def to_params(self) -> dict[str, str]:
        return {}


# ═══════════════════════════════════════════════════════════════
# Response Models
# ═══════════════════════════════════════════════════════════════

# Latest Policy Statement on the most-recent-documents page. Treasury links
# the Wednesday refunding announcement as: <a ...>Policy Statement: YYYY -
# Nth Quarter</a>. Take the first match (the page only shows one quarter).
_LATEST_POLICY_STMT_RE = re.compile(
    r'<a\s+href="(/news/press-releases/[a-z0-9_-]+)"[^>]*>'
    r"\s*Policy Statement:\s*\d{4}\s*-\s*\d+\w+\s+Quarter",
    re.IGNORECASE,
)

# Archive entries on the official-remarks-on-quarterly-refunding page — each
# quarter is a table cell with aria-label "YYYY Nth Quarter".
_ARCHIVE_ENTRY_RE = re.compile(
    r'href="(/news/press-releases/[^"]+)"[^>]*aria-label="(\d{4})\s+(\d+)(?:st|nd|rd|th)\s+Quarter"',
    re.IGNORECASE,
)

# Body opens with "Month DD, YYYY WASHINGTON — ..." (em dash). Use this both
# to locate the start of substantive prose and to extract the release date.
_RELEASE_DATE_RE = re.compile(
    r"\b(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{1,2}),\s+(\d{4})\s+WASHINGTON",
)

_MONTHS = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
}


@dataclass
class QraIndexResponse:
    """Latest QRA Policy Statement URL discovered from the most-recent-
    quarterly-refunding-documents page."""

    latest_path: str | None = None

    @classmethod
    def from_response(cls, html: str) -> "QraIndexResponse":
        if not html:
            return cls()
        m = _LATEST_POLICY_STMT_RE.search(html)
        return cls(latest_path=m.group(1) if m else None)

    def latest(self) -> str | None:
        return self.latest_path

    def to_output(self) -> str:
        return self.latest_path or "(no Policy Statement link found)"


@dataclass
class QraArchiveEntry:
    path: str
    year: int
    quarter: int

    @property
    def label(self) -> str:
        return f"{self.year} Q{self.quarter}"


@dataclass
class QraArchiveResponse:
    """Historical Policy Statement entries parsed from the official-remarks
    archive page. Sorted newest first by (year, quarter)."""

    entries: list[QraArchiveEntry] = field(default_factory=list)

    @classmethod
    def from_response(cls, html: str) -> "QraArchiveResponse":
        if not html:
            return cls()
        seen: set[str] = set()
        items: list[QraArchiveEntry] = []
        for m in _ARCHIVE_ENTRY_RE.finditer(html):
            path = m.group(1)
            if path in seen:
                continue
            seen.add(path)
            items.append(
                QraArchiveEntry(path=path, year=int(m.group(2)), quarter=int(m.group(3)))
            )
        items.sort(key=lambda e: (e.year, e.quarter), reverse=True)
        return cls(entries=items)

    def prior_to(self, latest_path: str | None) -> QraArchiveEntry | None:
        """Return the newest archive entry whose path != latest_path. The
        archive may lag the most-recent-documents page (so its first entry IS
        the prior), or it may already contain the latest (so its second is
        the prior). Filtering by path covers both cases."""
        for e in self.entries:
            if e.path != latest_path:
                return e
        return None

    def to_output(self) -> str:
        if not self.entries:
            return "(no archive entries found)"
        return f"{len(self.entries)} entries; newest: {self.entries[0].label}"


class _StatementHTMLParser(HTMLParser):
    SKIP_TAGS = {"script", "style", "noscript", "header", "footer", "nav", "svg", "form", "aside"}
    BLOCK_TAGS = {"p", "div", "br", "h1", "h2", "h3", "h4", "li"}

    def __init__(self) -> None:
        super().__init__()
        self._skip = 0
        # Table rendering. Treasury QRA statements include the auction-sizes
        # table inline; without explicit handling the column-major HTML dumps
        # cells onto their own lines and the grid is unreadable. We collect
        # cell text into a per-row buffer and emit "| c1 | c2 | ... |" rows
        # plus a markdown header separator after the first row of each table.
        self._table_depth = 0
        self._row_cells: list[str] = []
        self._cell_buf: list[str] | None = None
        self._first_row_pending: list[bool] = []
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self.SKIP_TAGS:
            self._skip += 1
            return
        if self._skip > 0:
            return
        if tag == "table":
            self._table_depth += 1
            self._first_row_pending.append(True)
            self.parts.append("\n")
            return
        if tag == "tr" and self._table_depth > 0:
            self._row_cells = []
            return
        if tag in ("td", "th") and self._table_depth > 0:
            self._cell_buf = []
            return
        if tag in self.BLOCK_TAGS and self._cell_buf is None:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in self.SKIP_TAGS and self._skip > 0:
            self._skip -= 1
            return
        if self._skip > 0:
            return
        if tag == "table" and self._table_depth > 0:
            self._table_depth -= 1
            if self._first_row_pending:
                self._first_row_pending.pop()
            self.parts.append("\n")
            return
        if tag == "tr" and self._table_depth > 0:
            if self._row_cells:
                self.parts.append("| " + " | ".join(self._row_cells) + " |\n")
                if self._first_row_pending and self._first_row_pending[-1]:
                    sep = "|" + "|".join(["---"] * len(self._row_cells)) + "|\n"
                    self.parts.append(sep)
                    self._first_row_pending[-1] = False
            self._row_cells = []
            return
        if tag in ("td", "th") and self._cell_buf is not None:
            cell_text = re.sub(r"\s+", " ", "".join(self._cell_buf)).strip()
            self._row_cells.append(cell_text)
            self._cell_buf = None
            return
        if tag in self.BLOCK_TAGS and self._cell_buf is None:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip > 0:
            return
        if self._cell_buf is not None:
            self._cell_buf.append(data)
        else:
            self.parts.append(data)


@dataclass
class QraStatementResponse:
    """Refunding Statement narrative scoped to the press release article body.

    Treasury press releases nest the body inside <article about="/news/
    press-releases/...">. We extract that article's text and trim leading
    boilerplate up to the date marker ("Month DD, YYYY WASHINGTON ..."),
    which is also what we parse for release_date.
    """

    text: str
    release_date: str | None = None

    @classmethod
    def from_response(cls, html: str) -> "QraStatementResponse":
        if not html:
            return cls(text="")
        # Scope to the press release article so we don't pull in sidebar
        # navigation. Falls back to the full page if the marker is missing.
        m = re.search(
            r'<article[^>]*about="/news/press-releases/[^"]+"[^>]*>(.*?)</article>',
            html,
            re.DOTALL,
        )
        body_html = m.group(1) if m else html
        parser = _StatementHTMLParser()
        parser.feed(body_html)
        raw = "".join(parser.parts).replace("\xa0", " ")
        lines = [re.sub(r"\s+", " ", line).strip() for line in raw.split("\n")]
        cleaned = "\n".join(line for line in lines if line)
        rd = _RELEASE_DATE_RE.search(cleaned)
        release_date: str | None = None
        if rd:
            month = _MONTHS[rd.group(1).lower()]
            day = int(rd.group(2))
            year = int(rd.group(3))
            release_date = f"{year:04d}-{month:02d}-{day:02d}"
            cleaned = cleaned[rd.start() :]
        # Trim Drupal field metadata at the tail (e.g. "Use featured image |
        # Off") that sits after the press release "30" marker.
        end_marker = re.search(r"^\s*###\s*$", cleaned, re.MULTILINE)
        if end_marker:
            cleaned = cleaned[: end_marker.start()].rstrip()
        return cls(text=cleaned, release_date=release_date)

    def to_output(self) -> str:
        return self.text or "(no content)"


# ═══════════════════════════════════════════════════════════════
# Endpoint Definitions
# ═══════════════════════════════════════════════════════════════

# Most-recent-documents landing page — refreshed each refunding cycle.
QRA_LATEST_INDEX = Endpoint(
    "/policy-issues/financing-the-government/quarterly-refunding/most-recent-quarterly-refunding-documents",
    cache_ttl=3600,
    response_model=QraIndexResponse,
)

# Historical Policy Statement archive — updated quarterly with a slight lag.
QRA_ARCHIVE = Endpoint(
    "/policy-issues/financing-the-government/quarterly-refunding/quarterly-refunding-archives/official-remarks-on-quarterly-refunding-by-calendar-year",
    cache_ttl=4 * 3600,
    response_model=QraArchiveResponse,
)

# Individual press release pages are immutable once published.
QRA_STATEMENT = Endpoint(
    "/{path}",
    cache_ttl=30 * 24 * 3600,
    response_model=QraStatementResponse,
)
