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


# 8-K item codes that meaningfully move the stock or change the thesis.
# 2.02 (Results of Operations) is treated separately as the EARNINGS tier.
MATERIAL_8K_ITEMS: frozenset[str] = frozenset(
    {
        "1.01",  # Material definitive agreement
        "1.02",  # Termination of material agreement
        "2.01",  # Acquisition / disposition of assets
        "2.05",  # Restructuring charges
        "2.06",  # Material impairment
        "4.01",  # Auditor change
        "4.02",  # Non-reliance on prior financials (restatement)
        "5.02",  # Officer/director departure or appointment
        "7.01",  # Reg FD disclosure
        "8.01",  # Other events
    }
)

# Tier labels — ordered roughly by signal severity (most actionable first).
TIER_MATERIAL = "MATERIAL"
TIER_EARNINGS = "EARNINGS"
TIER_INTERIM = "INTERIM"
TIER_INSIDER = "INSIDER"
TIER_GOVERNANCE = "GOVERNANCE"
TIER_CAPITAL = "CAPITAL"
TIER_ROUTINE = "ROUTINE"

TIER_ORDER: tuple[str, ...] = (
    TIER_MATERIAL,
    TIER_EARNINGS,
    TIER_INTERIM,
    TIER_INSIDER,
    TIER_GOVERNANCE,
    TIER_CAPITAL,
    TIER_ROUTINE,
)

_EARNINGS_FORMS = frozenset({"10-Q", "10-K", "20-F"})
_INTERIM_FOREIGN_FORMS = frozenset({"6-K"})
_ACTIVIST_FORMS = frozenset({"SCHEDULE 13D", "SCHEDULE 13D/A", "SC 13D", "SC 13D/A"})
_LATE_FILING_FORMS = frozenset({"NT 10-Q", "NT 10-K", "NT 20-F"})
_GOVERNANCE_FORMS = frozenset({"DEF 14A", "PRE 14A", "DEFA14A"})
_CAPITAL_FORMS = frozenset({"S-1", "S-3", "S-3ASR", "S-4", "424B2", "424B5"})


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

    @property
    def tier(self) -> str:
        """Classify the filing into a signal-severity tier for the index tool."""
        if self.form == "8-K":
            if set(self.items) & MATERIAL_8K_ITEMS:
                return TIER_MATERIAL
            if "2.02" in self.items:
                return TIER_EARNINGS
            return TIER_ROUTINE
        if self.form in _EARNINGS_FORMS:
            return TIER_EARNINGS
        if self.form in _INTERIM_FOREIGN_FORMS:
            return TIER_INTERIM
        if self.form in _ACTIVIST_FORMS or self.form in _LATE_FILING_FORMS:
            return TIER_MATERIAL
        if self.form == "4":
            return TIER_INSIDER
        if self.form in _GOVERNANCE_FORMS:
            return TIER_GOVERNANCE
        if self.form in _CAPITAL_FORMS:
            return TIER_CAPITAL
        return TIER_ROUTINE


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

    def within_window(self, today: str, days: int) -> list[Filing]:
        """Return filings dated within `days` of `today` (both YYYY-MM-DD strings).

        Lexicographic compare works because dates are zero-padded ISO format.
        """
        from datetime import date, timedelta

        cutoff = (date.fromisoformat(today) - timedelta(days=days)).isoformat()
        return [f for f in self.filings if f.filing_date >= cutoff]

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
# Form 4 (insider transaction) XML schema
# ═══════════════════════════════════════════════════════════════
#
# Form 4 ownership documents are XML, not HTML. The schema is unnamespaced;
# we only need a small subset to drive the insider_buying watcher: who filed,
# their relationship to the company, and their non-derivative purchases.
#
# Reference (informal): https://www.sec.gov/info/edgar/specifications/form345xml.htm

# Officer-title patterns that promote a filing into the CEO/CFO tier
# (lower $-threshold for single-large fires; "critical" alert level).
_FORM4_CEO_PATTERNS: tuple[str, ...] = (
    "chief executive",
    "chief financial",
    "principal financial",
    "principal executive",
    "ceo",
    "cfo",
)


def _form4_truthy(v: str | None) -> bool:
    if not v:
        return False
    return v.strip().lower() in {"1", "true"}


@dataclass
class Form4Transaction:
    """One non-derivative transaction parsed from a Form 4."""

    date: str  # YYYY-MM-DD (transaction date, not filing date)
    code: str  # P=open-market purchase, S=sale, A=grant, M=exercise, F=tax-withhold, ...
    shares: float
    price: float | None  # missing/zero for grants/exercises
    acquired_disposed: str  # "A" or "D"

    @property
    def value(self) -> float:
        return self.shares * (self.price or 0.0)


@dataclass
class Form4Filing:
    """One Form 4 (insider transaction) filing parsed from XML."""

    person: str
    is_officer: bool
    is_director: bool
    is_ten_percent_owner: bool
    officer_title: str
    transactions: list[Form4Transaction] = field(default_factory=list)

    @property
    def role_tag(self) -> str:
        """Compact label for embeds: CEO / CFO / OFFICER / DIRECTOR / 10%+ / OTHER."""
        title = (self.officer_title or "").lower()
        if any(p in title for p in _FORM4_CEO_PATTERNS):
            if "financial" in title or "cfo" in title:
                return "CFO"
            return "CEO"
        if self.is_officer:
            return "OFFICER"
        if self.is_director:
            return "DIRECTOR"
        if self.is_ten_percent_owner:
            return "10%+"
        return "OTHER"

    @property
    def is_ceo_or_cfo(self) -> bool:
        return self.role_tag in {"CEO", "CFO"}

    def purchases(self) -> list[Form4Transaction]:
        """Open-market purchases only (Code=P) with usable share + price data."""
        return [
            t for t in self.transactions if t.code == "P" and t.shares > 0 and (t.price or 0) > 0
        ]

    @property
    def total_purchase_value(self) -> float:
        return sum(t.value for t in self.purchases())

    @property
    def total_purchase_shares(self) -> float:
        return sum(t.shares for t in self.purchases())

    @property
    def avg_purchase_price(self) -> float | None:
        shares = self.total_purchase_shares
        if shares <= 0:
            return None
        return self.total_purchase_value / shares

    @property
    def latest_purchase_date(self) -> str:
        # Lex-sorted ISO dates; latest wins.
        dates = [t.date for t in self.purchases() if t.date]
        return max(dates) if dates else ""


@dataclass
class Form4Response:
    filing: Form4Filing | None

    @classmethod
    def from_response(cls, xml: str) -> "Form4Response":
        if not xml:
            return cls(filing=None)
        from xml.etree import ElementTree as ET

        try:
            root = ET.fromstring(xml)
        except ET.ParseError:
            return cls(filing=None)

        owner_id = root.find("./reportingOwner/reportingOwnerId")
        if owner_id is None:
            return cls(filing=None)
        rel = root.find("./reportingOwner/reportingOwnerRelationship")

        person = (owner_id.findtext("rptOwnerName") or "").strip()
        is_officer = _form4_truthy(rel.findtext("isOfficer") if rel is not None else "")
        is_director = _form4_truthy(rel.findtext("isDirector") if rel is not None else "")
        is_10pct = _form4_truthy(rel.findtext("isTenPercentOwner") if rel is not None else "")
        officer_title = ((rel.findtext("officerTitle") if rel is not None else "") or "").strip()

        transactions: list[Form4Transaction] = []
        for tx in root.findall("./nonDerivativeTable/nonDerivativeTransaction"):
            date = (tx.findtext("./transactionDate/value") or "").strip()
            code = (tx.findtext("./transactionCoding/transactionCode") or "").strip().upper()
            shares_s = tx.findtext("./transactionAmounts/transactionShares/value") or ""
            price_s = tx.findtext("./transactionAmounts/transactionPricePerShare/value") or ""
            ad = tx.findtext("./transactionAmounts/transactionAcquiredDisposedCode/value") or ""
            try:
                shares = float(shares_s) if shares_s else 0.0
            except ValueError:
                shares = 0.0
            try:
                price: float | None = float(price_s) if price_s else None
            except ValueError:
                price = None
            transactions.append(
                Form4Transaction(
                    date=date,
                    code=code,
                    shares=shares,
                    price=price,
                    acquired_disposed=ad.strip().upper(),
                )
            )

        return cls(
            filing=Form4Filing(
                person=person,
                is_officer=is_officer,
                is_director=is_director,
                is_ten_percent_owner=is_10pct,
                officer_title=officer_title,
                transactions=transactions,
            )
        )

    def to_output(self) -> str:
        if self.filing is None:
            return "(empty)"
        f = self.filing
        return f"{f.person} ({f.role_tag}) — {len(f.transactions)} tx"


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

# Same path as FILING_DOC but parses the response as Form 4 XML rather than
# HTML. Form 4 schema is unnamespaced; we extract reporting owner relationship
# + non-derivative transactions to power the insider_buying watcher.
FILING_FORM4 = Endpoint(
    "/Archives/edgar/data/{cik}/{accession}/{filename}",
    cache_ttl=30 * 24 * 3600,
    response_model=Form4Response,
    base_url=WWW_HOST,
)
