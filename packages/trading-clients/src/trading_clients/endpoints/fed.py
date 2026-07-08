"""Federal Reserve endpoint definitions for FOMC statements and minutes.

Discovery flow:
  1. Fetch /monetarypolicy/fomccalendars.htm — find the latest two FOMC statement
     URLs (pattern: monetary{YYYYMMDD}a.htm) and minutes URLs (pattern:
     fomcminutes{YYYYMMDD}.htm; published ~3 weeks after each meeting).
  2. Fetch the statement/minutes page(s) and extract the narrative.
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
    """Fetch a specific FOMC statement or minutes page by its post-base path,
    e.g. '/newsevents/pressreleases/monetary20260429a.htm' or
    '/monetarypolicy/fomcminutes20260617.htm'.
    """

    path: str

    def to_path_params(self) -> dict[str, str]:
        return {"path": self.path.lstrip("/")}

    def to_params(self) -> dict[str, str]:
        return {}


# ═══════════════════════════════════════════════════════════════
# Response Models
# ═══════════════════════════════════════════════════════════════


_STMT_LINK_RE = re.compile(r'href="(/newsevents/pressreleases/monetary\d{8}a\.htm)"')
_MIN_LINK_RE = re.compile(r'href="(/monetarypolicy/fomcminutes\d{8}\.htm)"')
# Meeting date embedded in either a statement path (monetary{YYYYMMDD}a.htm)
# or a minutes path (fomcminutes{YYYYMMDD}.htm).
_DATE_RE = re.compile(r"(?:monetary|fomcminutes)(\d{4})(\d{2})(\d{2})a?\.htm")

# Year section header on /monetarypolicy/fomccalendars.htm — e.g.
# "<a id="42828"></a>2026 FOMC Meetings". Captures the year.
_YEAR_HEADER_RE = re.compile(r"(\d{4})\s+FOMC\s+Meetings", re.IGNORECASE)
# Footnote / metadata that appears after the date list in each year section
# (e.g. "* Meeting associated with..." or "Note: A two-day meeting is
# scheduled for January 25-26, 2028."). Strip these before scanning so the
# footnote dates aren't misattributed to the current year.
_YEAR_FOOTNOTE_RE = re.compile(r"\*\s*Meeting\s+associated|Note:\s*A\s+two-day", re.IGNORECASE)
_MONTH_NAMES = (
    "January|February|March|April|May|June|July|August|September|October|November|December"
)
_MONTH_ABBR = "Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec"
# Same-month meeting: "January 27-28" or "December 8-9*" — captures month
# and the SECOND day (the decision/statement day).
_MEETING_RE = re.compile(
    rf"\b({_MONTH_NAMES})\s+\d{{1,2}}[-–](\d{{1,2}})\*?",
    re.IGNORECASE,
)
# Cross-month meeting: "Jan/Feb 31-1" or "Apr/May 30-1*" — captures the
# SECOND month and SECOND day (decision day in the later month).
_MEETING_CROSS_RE = re.compile(
    rf"\b(?:{_MONTH_ABBR})/({_MONTH_ABBR})\s+\d{{1,2}}[-–](\d{{1,2}})\*?",
    re.IGNORECASE,
)
_MONTHS = {
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "may": 5,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
}


def extract_meeting_date(path: str) -> str:
    """Parse YYYY-MM-DD out of a statement or minutes URL path."""
    m = _DATE_RE.search(path)
    if not m:
        return "?"
    return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"


def parse_scheduled_meetings(html: str) -> list[str]:
    """Extract scheduled FOMC meeting decision dates from the calendar page.

    Returns YYYY-MM-DD strings using the SECOND day of each two-day meeting
    (when the statement is released and the press conference happens). Includes
    both past and future scheduled meetings — caller filters by date.
    """
    if not html:
        return []
    # Strip tags so the year header and "Month Day-Day" text sit adjacent.
    text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"\s+", " ", text)
    # Split into per-year chunks. We walk year headers and slice between them.
    headers = list(_YEAR_HEADER_RE.finditer(text))
    dates: list[str] = []
    for i, hdr in enumerate(headers):
        year = int(hdr.group(1))
        chunk_end = headers[i + 1].start() if i + 1 < len(headers) else len(text)
        chunk = text[hdr.end() : chunk_end]
        # Trim trailing footnotes ("* Meeting associated with...", "Note: A
        # two-day meeting is scheduled for January 25-26, 2028.") so dates
        # mentioned there aren't attributed to this year.
        fn = _YEAR_FOOTNOTE_RE.search(chunk)
        if fn:
            chunk = chunk[: fn.start()]
        for m in _MEETING_RE.finditer(chunk):
            month = _MONTHS[m.group(1).lower()]
            day = int(m.group(2))
            dates.append(f"{year:04d}-{month:02d}-{day:02d}")
        for m in _MEETING_CROSS_RE.finditer(chunk):
            month = _MONTHS[m.group(1).lower()]
            day = int(m.group(2))
            dates.append(f"{year:04d}-{month:02d}-{day:02d}")
    # De-dup while preserving order, then sort ascending.
    return sorted(set(dates))


def _dedup_sorted_paths(html: str, link_re: re.Pattern[str]) -> list[str]:
    """Collect unique link paths, sorted by embedded meeting date newest-first.

    Fed lists meetings chronologically within each year section, so document
    order is not date order. _DATE_RE is guaranteed to match (the link regexes
    require 8 digits) so the sort key is always defined.
    """
    seen: set[str] = set()
    paths: list[str] = []
    for m in link_re.finditer(html):
        p = m.group(1)
        if p not in seen:
            seen.add(p)
            paths.append(p)
    paths.sort(key=lambda p: extract_meeting_date(p), reverse=True)
    return paths


@dataclass
class FomcCalendarResponse:
    """FOMC statement + minutes URLs (past meetings only, sorted newest-first)
    plus scheduled meeting decision dates (past + future, chronological)."""

    statement_paths: list[str] = field(default_factory=list)
    minutes_paths: list[str] = field(default_factory=list)
    meeting_dates: list[str] = field(default_factory=list)

    @classmethod
    def from_response(cls, html: str) -> "FomcCalendarResponse":
        if not html:
            return cls()
        return cls(
            statement_paths=_dedup_sorted_paths(html, _STMT_LINK_RE),
            minutes_paths=_dedup_sorted_paths(html, _MIN_LINK_RE),
            meeting_dates=parse_scheduled_meetings(html),
        )

    def latest(self) -> str | None:
        return self.statement_paths[0] if self.statement_paths else None

    def prior(self) -> str | None:
        return self.statement_paths[1] if len(self.statement_paths) >= 2 else None

    def latest_minutes(self) -> str | None:
        return self.minutes_paths[0] if self.minutes_paths else None

    def prior_minutes(self) -> str | None:
        return self.minutes_paths[1] if len(self.minutes_paths) >= 2 else None

    def to_output(self) -> str:
        if not self.statement_paths and not self.minutes_paths:
            return "(no FOMC statements found)"
        parts = []
        if self.statement_paths:
            parts.append(
                f"{len(self.statement_paths)} statements; latest: {self.statement_paths[0]}"
            )
        if self.minutes_paths:
            parts.append(f"{len(self.minutes_paths)} minutes; latest: {self.minutes_paths[0]}")
        return " | ".join(parts)


class _StatementHTMLParser(HTMLParser):
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


def _html_to_text(html: str) -> str:
    """Strip an HTML fragment to cleaned narrative lines (blank lines dropped)."""
    parser = _StatementHTMLParser()
    parser.feed(html)
    raw = "".join(parser.parts)
    lines = [re.sub(r"\s+", " ", line).strip() for line in raw.split("\n")]
    return "\n".join(line for line in lines if line)


@dataclass
class FomcStatementResponse:
    """FOMC statement narrative trimmed between 'For release at' (marks the
    start of the actual statement body) and 'Last Update' (the page footer).
    Includes the policy paragraphs, voting tally with named dissents, and the
    Implementation Note pointer at the end.
    """

    text: str

    @classmethod
    def from_response(cls, html: str) -> "FomcStatementResponse":
        if not html:
            return cls(text="")
        cleaned = _html_to_text(html)
        start = cleaned.find("For release at")
        if start >= 0:
            cleaned = cleaned[start:]
        end = cleaned.find("Last Update")
        if end > 0:
            cleaned = cleaned[:end].rstrip()
        return cls(text=cleaned)

    def to_output(self) -> str:
        return self.text or "(no content)"


# Minutes content starts at the article div (everything before is site chrome).
_MINUTES_ARTICLE_RE = re.compile(r'<div[^>]*id="article"[^>]*>')
# A section heading is a paragraph that opens with a lone <strong> terminated
# by a line break or the paragraph end — the section body follows in the same
# <p> after the <br>. Inline bold runs like
# "<strong>Voting for this action</strong><strong>: </strong>Name, ..." don't
# match (the strong is followed by another tag, not <br>/</p>), so vote
# tallies stay inside the Committee Policy Actions body.
_MINUTES_HEADING_RE = re.compile(
    r"<p[^>]*>\s*<strong>\s*([^<]{3,120}?)\s*</strong>\s*(?:<br[^>]*>|</p>)"
)


@dataclass
class FomcMinutesResponse:
    """FOMC minutes split into their named sections in document order
    (Developments in Financial Markets…, Staff Review of the Economic/Financial
    Situation, Staff Economic Outlook, Participants' Views…, Committee Policy
    Actions, Notation Vote, Attendance). The unlabeled text before the first
    heading (meeting title + agenda) is stored under "Preamble".
    """

    sections: list[tuple[str, str]] = field(default_factory=list)

    @classmethod
    def from_response(cls, html: str) -> "FomcMinutesResponse":
        if not html:
            return cls()
        m = _MINUTES_ARTICLE_RE.search(html)
        if m:
            html = html[m.end() :]
        # Page footer; headings never appear after it. Cutting raw HTML mid-tree
        # is fine — each slice gets its own tolerant HTMLParser pass.
        cut = html.find("Last Update")
        if cut > 0:
            html = html[:cut]
        heads = list(_MINUTES_HEADING_RE.finditer(html))
        sections: list[tuple[str, str]] = []
        preamble = _html_to_text(html[: heads[0].start()] if heads else html)
        if preamble:
            sections.append(("Preamble", preamble))
        for i, h in enumerate(heads):
            body_end = heads[i + 1].start() if i + 1 < len(heads) else len(html)
            body = _html_to_text(html[h.end() : body_end])
            sections.append((h.group(1).strip(), body))
        return cls(sections=sections)

    def section_names(self) -> list[str]:
        return [name for name, _ in self.sections]

    def section(self, name: str) -> tuple[str, str] | None:
        """First section whose heading contains `name` (case-insensitive)."""
        needle = name.lower()
        for heading, body in self.sections:
            if needle in heading.lower():
                return heading, body
        return None

    def to_output(self) -> str:
        if not self.sections:
            return "(no content)"
        out: list[str] = []
        for heading, body in self.sections:
            out.append(f"=== {heading} ===")
            out.append(body)
            out.append("")
        return "\n".join(out).rstrip()


# ═══════════════════════════════════════════════════════════════
# Endpoint Definitions
# ═══════════════════════════════════════════════════════════════

# Calendar page lists all scheduled and historical meetings; updated when new
# meetings are added. 1h TTL is plenty.
FOMC_CALENDAR = Endpoint(
    "/monetarypolicy/fomccalendars.htm",
    cache_ttl=3600,
    response_model=FomcCalendarResponse,
)

# Statement pages are immutable once published.
FOMC_STATEMENT = Endpoint(
    "/{path}",
    cache_ttl=30 * 24 * 3600,
    response_model=FomcStatementResponse,
)

# Minutes pages (released ~3 weeks after each meeting, Wed 2 PM ET) are
# likewise immutable once published.
FOMC_MINUTES = Endpoint(
    "/{path}",
    cache_ttl=30 * 24 * 3600,
    response_model=FomcMinutesResponse,
)
