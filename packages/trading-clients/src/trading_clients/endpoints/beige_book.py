"""Federal Reserve Beige Book endpoint definitions.

The Beige Book is the Fed's qualitative summary of economic conditions across
the 12 districts, published 8 times per year ~2 weeks before each FOMC meeting.

Discovery flow:
  1. Fetch /monetarypolicy/publications/beige-book-default.htm — index of all
     releases. Each release is linked as beigebook{YYYYMM}.htm. Sort the
     captured tokens descending to identify latest and prior.
  2. Fetch /monetarypolicy/beigebook{YYYYMM}-summary.htm — National Summary
     page with Overall Economic Activity / Labor Markets / Prices subsections
     plus 12 short district highlights (one paragraph each). The full per-
     district reports live at separate URLs and are intentionally not fetched
     here — the summary page already carries the texture worth surfacing.
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
class SummaryRequest(PathRequest, ParamsRequest):
    """Fetch a specific Beige Book National Summary by YYYYMM token (e.g. '202602')."""

    period: str

    def to_path_params(self) -> dict[str, str]:
        return {"period": self.period}

    def to_params(self) -> dict[str, str]:
        return {}


# ═══════════════════════════════════════════════════════════════
# Index page — discover release periods
# ═══════════════════════════════════════════════════════════════

# Matches both /monetarypolicy/beigebook202602.htm and the -summary variant.
_RELEASE_LINK_RE = re.compile(r"beigebook(20\d{4})(?:-summary)?\.htm")


@dataclass
class BeigeBookIndexResponse:
    """Discovered release periods (YYYYMM strings) sorted newest-first."""

    periods: list[str] = field(default_factory=list)

    @classmethod
    def from_response(cls, html: str) -> "BeigeBookIndexResponse":
        if not html:
            return cls()
        seen: set[str] = set()
        for m in _RELEASE_LINK_RE.finditer(html):
            seen.add(m.group(1))
        return cls(periods=sorted(seen, reverse=True))

    def latest(self) -> str | None:
        return self.periods[0] if self.periods else None

    def prior(self) -> str | None:
        return self.periods[1] if len(self.periods) >= 2 else None

    def to_output(self) -> str:
        if not self.periods:
            return "(no Beige Book releases found)"
        return f"{len(self.periods)} releases; latest: {self.periods[0]}"


# ═══════════════════════════════════════════════════════════════
# Summary page parser
# ═══════════════════════════════════════════════════════════════

# Three fixed subsection labels under <h3>National Summary</h3>.
_NATIONAL_SECTIONS = ("Overall Economic Activity", "Labor Markets", "Prices")

# Header that introduces the per-district roll-up.
_HIGHLIGHTS_HEADER = "Highlights by Federal Reserve District"

# Page H2 carries the human-readable period, e.g. "Beige Book - February 2026".
_PERIOD_RE = re.compile(r"Beige Book\s*[-–]\s*([A-Za-z]+\s+\d{4})")

# Footer "Note:" line that names the preparing bank and information cutoff date.
_NOTE_RE = re.compile(
    r"Note:\s*This report was prepared at the (Federal Reserve Bank of [^.]+)"
    r"\s*based on information collected on or before\s*([^.]+)\.",
    re.IGNORECASE,
)


class _SummaryHTMLParser(HTMLParser):
    """Streams the summary page into a list of (tag, text) tuples after
    skipping nav/script/style. Section assembly happens after parsing."""

    SKIP_TAGS = {"script", "style", "noscript", "header", "footer", "nav", "svg", "form", "aside"}
    KEEP_TAGS = {"h2", "h3", "h4", "h5", "p"}

    def __init__(self) -> None:
        super().__init__()
        self._skip = 0
        self._current_tag: str | None = None
        self._buf: list[str] = []
        self.events: list[tuple[str, str]] = []  # (tag, text)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self.SKIP_TAGS:
            self._skip += 1
            return
        if self._skip > 0:
            return
        if tag in self.KEEP_TAGS:
            self._flush()
            self._current_tag = tag

    def handle_endtag(self, tag: str) -> None:
        if tag in self.SKIP_TAGS and self._skip > 0:
            self._skip -= 1
            return
        if self._skip > 0:
            return
        if tag in self.KEEP_TAGS and self._current_tag == tag:
            self._flush()

    def handle_data(self, data: str) -> None:
        if self._skip == 0 and self._current_tag is not None:
            self._buf.append(data)

    def _flush(self) -> None:
        if self._current_tag is not None:
            text = re.sub(r"\s+", " ", "".join(self._buf)).strip()
            if text:
                self.events.append((self._current_tag, text))
        self._current_tag = None
        self._buf = []


@dataclass
class BeigeBookSummaryResponse:
    """Beige Book National Summary plus 12 district highlights."""

    period_label: str  # e.g. "February 2026"
    period_token: str  # e.g. "202602" — echoed for self-identification
    overall: str
    labor: str
    prices: str
    districts: list[tuple[str, str]] = field(default_factory=list)
    prepared_by: str | None = None  # "Federal Reserve Bank of Cleveland"
    information_cutoff: str | None = None  # raw date string from the note

    @classmethod
    def from_response(cls, html: str) -> "BeigeBookSummaryResponse":
        return cls._parse(html, period_token="?")

    @classmethod
    def parse(cls, html: str, period_token: str) -> "BeigeBookSummaryResponse":
        return cls._parse(html, period_token=period_token)

    @classmethod
    def _parse(cls, html: str, period_token: str) -> "BeigeBookSummaryResponse":
        if not html:
            return cls(
                period_label="?",
                period_token=period_token,
                overall="",
                labor="",
                prices="",
            )

        parser = _SummaryHTMLParser()
        parser.feed(html)

        # Extract period from H2 (most reliable — page title is generic).
        period_label = "?"
        for tag, text in parser.events:
            if tag == "h2":
                m = _PERIOD_RE.search(text)
                if m:
                    period_label = m.group(1).strip()
                    break

        # National sections: walk events, when we hit an h4 matching one of the
        # three known section names, accumulate following <p> text until the
        # next header.
        sections: dict[str, list[str]] = {name: [] for name in _NATIONAL_SECTIONS}
        districts: list[tuple[str, str]] = []
        current_section: str | None = None
        current_district: str | None = None
        in_highlights = False

        for tag, text in parser.events:
            if tag in ("h2", "h3"):
                # Section transitions reset the per-section accumulator.
                current_section = None
                current_district = None
                continue
            if tag == "h4":
                if text.strip() == _HIGHLIGHTS_HEADER:
                    in_highlights = True
                    current_section = None
                    current_district = None
                elif text.strip() in _NATIONAL_SECTIONS:
                    in_highlights = False
                    current_section = text.strip()
                    current_district = None
                else:
                    current_section = None
                    current_district = None
                continue
            if tag == "h5":
                if in_highlights:
                    current_district = text.strip()
                    districts.append((current_district, ""))
                continue
            if tag == "p":
                if in_highlights and current_district is not None:
                    # Append to the most recent district entry.
                    name, existing = districts[-1]
                    districts[-1] = (
                        name,
                        (existing + " " + text).strip() if existing else text.strip(),
                    )
                elif current_section is not None:
                    sections[current_section].append(text.strip())

        # Footer note: scrape from raw text (it sits in a <p> at end).
        note_match = _NOTE_RE.search(re.sub(r"\s+", " ", "\n".join(t for _, t in parser.events)))
        prepared_by = note_match.group(1).strip() if note_match else None
        information_cutoff = note_match.group(2).strip() if note_match else None

        return cls(
            period_label=period_label,
            period_token=period_token,
            overall=" ".join(sections["Overall Economic Activity"]).strip(),
            labor=" ".join(sections["Labor Markets"]).strip(),
            prices=" ".join(sections["Prices"]).strip(),
            districts=districts,
            prepared_by=prepared_by,
            information_cutoff=information_cutoff,
        )

    def to_output(self) -> str:
        # Default rendering — the MCP tool composes its own header but this
        # keeps the response model self-contained for direct printing.
        lines = [f"Beige Book — {self.period_label}", ""]
        if self.prepared_by:
            cutoff = f", info as of {self.information_cutoff}" if self.information_cutoff else ""
            lines.append(f"_Prepared at {self.prepared_by}{cutoff}._")
            lines.append("")
        lines += [
            "## National Summary",
            "",
            "**Overall Economic Activity.** " + (self.overall or "(missing)"),
            "",
            "**Labor Markets.** " + (self.labor or "(missing)"),
            "",
            "**Prices.** " + (self.prices or "(missing)"),
            "",
        ]
        if self.districts:
            lines.append("## District Highlights")
            lines.append("")
            for name, text in self.districts:
                lines.append(f"- **{name}.** {text}")
        return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════
# Endpoint Definitions
# ═══════════════════════════════════════════════════════════════

# Index page is updated when a new Beige Book is published — 1h TTL is plenty.
INDEX = Endpoint(
    "/monetarypolicy/publications/beige-book-default.htm",
    cache_ttl=3600,
    response_model=BeigeBookIndexResponse,
)

# Summary pages are immutable once published.
SUMMARY = Endpoint(
    "/monetarypolicy/beigebook{period}-summary.htm",
    cache_ttl=30 * 24 * 3600,
    response_model=BeigeBookSummaryResponse,
)
