"""SEC EDGAR endpoint definitions for earnings 8-K press releases.

Discovery flow:
  1. Resolve ticker → CIK via the global company_tickers.json map (cached 24h).
  2. Fetch recent submissions for that CIK; find the most recent 8-K with item 2.02
     (Results of Operations and Financial Condition).
  3. Fetch the filing's index.json to locate the press-release exhibit (matches 'ex99').
  4. Fetch and clean the exhibit HTML.
"""

import json
import re
from dataclasses import dataclass, field
from html.parser import HTMLParser

from trading_clients.endpoint import Endpoint, ParamsRequest, PathRequest

# EDGAR uses two hosts: data.sec.gov for submissions, www.sec.gov for files+archives.
DATA_HOST = "https://data.sec.gov"
WWW_HOST = "https://www.sec.gov"

# ═══════════════════════════════════════════════════════════════
# Request Models
# ═══════════════════════════════════════════════════════════════


@dataclass
class EmptyRequest(ParamsRequest):
    def to_params(self) -> dict[str, str]:
        return {}


@dataclass
class CikRequest(PathRequest, ParamsRequest):
    """CIK is zero-padded to 10 digits in the submissions URL."""

    cik: int

    def to_path_params(self) -> dict[str, str]:
        return {"cik": f"{self.cik:010d}"}

    def to_params(self) -> dict[str, str]:
        return {}


@dataclass
class FilingIndexRequest(PathRequest, ParamsRequest):
    """Filing archive paths use the un-padded CIK and the accession number with no dashes."""

    cik: int
    accession_no_dashes: str

    def to_path_params(self) -> dict[str, str]:
        return {"cik": str(self.cik), "accession": self.accession_no_dashes}

    def to_params(self) -> dict[str, str]:
        return {}


@dataclass
class FilingDocRequest(PathRequest, ParamsRequest):
    cik: int
    accession_no_dashes: str
    filename: str

    def to_path_params(self) -> dict[str, str]:
        return {
            "cik": str(self.cik),
            "accession": self.accession_no_dashes,
            "filename": self.filename,
        }

    def to_params(self) -> dict[str, str]:
        return {}


# ═══════════════════════════════════════════════════════════════
# Response Models
# ═══════════════════════════════════════════════════════════════


@dataclass
class CompanyTickersResponse:
    by_ticker: dict[str, int] = field(default_factory=dict)

    @classmethod
    def from_response(cls, text: str) -> "CompanyTickersResponse":
        if not text:
            return cls()
        data = json.loads(text)
        m: dict[str, int] = {}
        for entry in data.values():
            ticker = str(entry.get("ticker", "")).upper()
            cik = entry.get("cik_str")
            if ticker and isinstance(cik, int):
                m[ticker] = cik
        return cls(by_ticker=m)

    def to_output(self) -> str:
        return f"{len(self.by_ticker)} tickers"


@dataclass
class Filing:
    form: str
    filing_date: str  # YYYY-MM-DD
    accession_number: str  # with dashes, e.g. "0000320193-26-000011"
    items: list[str]  # parsed from comma-separated string
    primary_document: str

    @property
    def accession_no_dashes(self) -> str:
        return self.accession_number.replace("-", "")


@dataclass
class SubmissionsResponse:
    filings: list[Filing] = field(default_factory=list)

    @classmethod
    def from_response(cls, text: str) -> "SubmissionsResponse":
        if not text:
            return cls()
        data = json.loads(text)
        recent = data.get("filings", {}).get("recent", {}) or {}
        forms = recent.get("form", [])
        out: list[Filing] = []
        for i, form in enumerate(forms):
            items_raw = recent.get("items", [""])[i] if i < len(recent.get("items", [])) else ""
            items_list = [s.strip() for s in items_raw.split(",") if s.strip()]
            out.append(
                Filing(
                    form=form,
                    filing_date=recent.get("filingDate", [""])[i],
                    accession_number=recent.get("accessionNumber", [""])[i],
                    items=items_list,
                    primary_document=recent.get("primaryDocument", [""])[i],
                )
            )
        return cls(filings=out)

    def find_latest_earnings_8k(self) -> Filing | None:
        """Most recent 8-K with item 2.02 (Results of Operations and Financial Condition)."""
        for f in self.filings:
            if f.form == "8-K" and "2.02" in f.items:
                return f
        return None

    def to_output(self) -> str:
        return f"{len(self.filings)} filings"


@dataclass
class FilingIndexResponse:
    files: list[str] = field(default_factory=list)

    @classmethod
    def from_response(cls, text: str) -> "FilingIndexResponse":
        if not text:
            return cls()
        data = json.loads(text)
        items = data.get("directory", {}).get("item", []) or []
        return cls(files=[str(i.get("name", "")) for i in items if i.get("name")])

    def find_press_release(self) -> str | None:
        """Press release exhibit follows naming like 'a8-kex991q...htm', 'ex-99.1.htm',
        'exhibit991.htm'. We normalize separators and look for 'ex99' substring.
        """
        for name in self.files:
            lower = name.lower()
            if not lower.endswith((".htm", ".html")):
                continue
            normalized = lower.replace("-", "").replace("_", "").replace(".", "")
            if "ex99" in normalized:
                return name
        return None

    def to_output(self) -> str:
        return ", ".join(self.files) if self.files else "(empty)"


class _PressReleaseHTMLParser(HTMLParser):
    SKIP_TAGS = {"script", "style", "noscript", "header", "footer", "nav", "svg", "form"}
    BLOCK_TAGS = {"p", "div", "br", "h1", "h2", "h3", "h4", "li", "tr", "table"}

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
class FilingDocResponse:
    text: str

    @classmethod
    def from_response(cls, html: str) -> "FilingDocResponse":
        if not html:
            return cls(text="")
        parser = _PressReleaseHTMLParser()
        parser.feed(html)
        raw = "".join(parser.parts)
        lines = [re.sub(r"[ \t]+", " ", line).strip() for line in raw.split("\n")]
        cleaned = "\n".join(line for line in lines if line)
        return cls(text=cleaned)

    def to_output(self) -> str:
        return self.text or "(no content)"


# ═══════════════════════════════════════════════════════════════
# Endpoint Definitions
# ═══════════════════════════════════════════════════════════════

# Ticker map is huge (~10K entries) but stable; long TTL.
COMPANY_TICKERS = Endpoint(
    "/files/company_tickers.json",
    cache_ttl=24 * 3600,
    response_model=CompanyTickersResponse,
    base_url=WWW_HOST,
)

# Submissions add new filings continuously; short TTL so post-earnings runs see fresh data.
SUBMISSIONS = Endpoint(
    "/submissions/CIK{cik}.json",
    cache_ttl=15 * 60,
    response_model=SubmissionsResponse,
    base_url=DATA_HOST,
)

# Filing contents are immutable once filed — long TTL.
FILING_INDEX = Endpoint(
    "/Archives/edgar/data/{cik}/{accession}/index.json",
    cache_ttl=30 * 24 * 3600,
    response_model=FilingIndexResponse,
    base_url=WWW_HOST,
)

FILING_DOC = Endpoint(
    "/Archives/edgar/data/{cik}/{accession}/{filename}",
    cache_ttl=30 * 24 * 3600,
    response_model=FilingDocResponse,
    base_url=WWW_HOST,
)
