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


# Press-release exhibit naming varies by filer: abbreviated ('ex-99.1.htm',
# 'a8-kex991q.htm') or spelled out ('exhibit99.1.htm', 'exhibit991earnings.htm').
# After stripping separators both collapse to a substring matching ex(hibit)?99.
# The spelled-out form is now common — matching only 'ex99' silently misses it.
_PRESS_RELEASE_RE = re.compile(r"ex(?:hibit)?99")


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
        """Locate the press-release exhibit (Exhibit 99.x) among the filing's files.

        Normalizes separators, then matches either the abbreviated ('ex99') or
        spelled-out ('exhibit99') naming form via _PRESS_RELEASE_RE.
        """
        for name in self.files:
            lower = name.lower()
            if not lower.endswith((".htm", ".html")):
                continue
            normalized = lower.replace("-", "").replace("_", "").replace(".", "")
            if _PRESS_RELEASE_RE.search(normalized):
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


# ═══════════════════════════════════════════════════════════════
# Section extraction (10-Q / 10-K narrative)
# ═══════════════════════════════════════════════════════════════
#
# After our HTML parser flattens the filing, sections are bounded by
# Item-numbered headers ("Item 1A. Risk Factors", "Item 2.", etc.) or by
# named subsection headers ("Management's Discussion and Analysis",
# "Liquidity and Capital Resources"). The exact wording and capitalization
# vary by issuer, so we anchor on flexible regex patterns.
#
# A 10-Q/10-K usually contains TWO matches for each Item header: one in the
# table of contents at the top, and one at the actual section start. The TOC
# entry is short (next sibling is right behind it); the body section is long.
# We pick the candidate whose span is largest.


@dataclass(frozen=True)
class SectionAnchors:
    """Anchor patterns for a named section within a 10-Q / 10-K."""

    starts: tuple[str, ...]
    ends: tuple[str, ...] = ()
    max_len: int = 30_000


SECTION_ANCHORS: dict[str, SectionAnchors] = {
    "mda": SectionAnchors(
        starts=(
            "management's discussion and analysis",
            "managements discussion and analysis",
        ),
        ends=(
            "quantitative and qualitative disclosures about market risk",
            "item 3. quantitative",
            "item 7a.",
            "item 4. controls and procedures",
        ),
        max_len=80_000,
    ),
    "risk_factors": SectionAnchors(
        starts=(
            "item 1a. risk factors",
            "item 1a risk factors",
        ),
        ends=(
            "item 1b.",
            "item 2. properties",
            "unresolved staff comments",
        ),
        max_len=200_000,
    ),
    "segments": SectionAnchors(
        starts=(
            "segment information",
            "disaggregation of revenue",
            "operating segments",
            "reportable segments",
        ),
        max_len=10_000,
    ),
    "cash_flow": SectionAnchors(
        starts=("liquidity and capital resources",),
        ends=(
            "critical accounting",
            "off-balance sheet",
            "contractual obligations",
            "recent accounting pronouncements",
            "item 3.",
            "item 7a.",
            "item 4. controls",
        ),
        max_len=20_000,
    ),
    "business": SectionAnchors(
        starts=("item 1. business",),
        ends=("item 1a.", "risk factors"),
        max_len=80_000,
    ),
}


def _section_pattern(phrase: str) -> re.Pattern[str]:
    """Build a regex that tolerates whitespace variation between tokens."""
    parts = [re.escape(t) for t in phrase.split()]
    return re.compile(r"\s+".join(parts), re.IGNORECASE)


def extract_section(text: str, section_id: str) -> str:
    """Extract a named section from a 10-Q or 10-K's cleaned text.

    Tries multiple start anchors. Among all (start, end) candidates, returns
    the slice with the largest span — this skips TOC entries (where sibling
    headers sit right next to each other) and selects the body section.
    """
    if section_id not in SECTION_ANCHORS:
        choices = ", ".join(SECTION_ANCHORS)
        raise ValueError(f"Unknown section_id {section_id!r}; choose from: {choices}")
    cfg = SECTION_ANCHORS[section_id]

    starts: list[tuple[int, int]] = []
    for phrase in cfg.starts:
        for m in _section_pattern(phrase).finditer(text):
            starts.append((m.start(), m.end()))
    if not starts:
        return ""

    end_patterns = [_section_pattern(p) for p in cfg.ends]

    spans: list[tuple[int, int, int]] = []
    for start_pos, after_match in starts:
        end_pos = min(len(text), start_pos + cfg.max_len)
        # Search end anchors strictly after the start match. For TOC matches
        # this returns a tiny span (next sibling header is right behind), so
        # the longest-span pick downstream prefers the body occurrence.
        for ep in end_patterns:
            m = ep.search(text, after_match)
            if m and m.start() < end_pos:
                end_pos = m.start()
        spans.append((start_pos, end_pos, end_pos - start_pos))

    best = max(spans, key=lambda s: s[2])
    return text[best[0] : best[1]].strip()


# ═══════════════════════════════════════════════════════════════
# Section extraction (S-1 / F-1 / 424B prospectus)
# ═══════════════════════════════════════════════════════════════
#
# S-1 / F-1 prospectuses don't use Item-numbered headers like 10-K/10-Q, so the
# 10-K extractor doesn't apply. Instead, body section headers appear as the
# section name on a line by itself (CBRS/KLAR use ALL-CAPS, RBRK uses Title
# Case — both work with case-insensitive whole-line matching). Cross-references
# in flowing text don't match because they're embedded in sentences.
#
# Algorithm:
#   1. For each section, find all whole-line matches (case-insensitive, MULTILINE).
#   2. Body header position = LAST match per section. TOC entries always come
#      first; the body header is strictly later in document order.
#   3. Section end = nearest body position greater than ours, REGARDLESS of
#      catalog order — KLAR (F-1) puts Market & Industry Data before Risk
#      Factors, opposite of CBRS/RBRK. End determination must be position-based.
#
# Sections deliberately omitted:
#   - "selected_financial" — SEC eliminated this requirement in 2021 (Reg S-K
#     Item 301). Modern S-1s have only summary financial data + MD&A.

# (section_id, name_variants) — order is informational; extraction is position-driven.
SECTION_CATALOG_S1: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("prospectus_summary", ("prospectus summary",)),
    ("the_offering", ("the offering",)),
    (
        "summary_financial_data",
        (
            "summary consolidated financial data",
            "summary consolidated financial and other data",
            "summary financial data",
        ),
    ),
    ("risk_factors", ("risk factors",)),
    (
        "special_note_forward_looking",
        (
            "special note regarding forward-looking statements",
            "cautionary note regarding forward-looking statements",
        ),
    ),
    (
        "market_industry_data",
        (
            "market, industry, and other data",
            "market and industry data",
        ),
    ),
    ("use_of_proceeds", ("use of proceeds",)),
    ("dividend_policy", ("dividend policy",)),
    ("capitalization", ("capitalization",)),
    ("dilution", ("dilution",)),
    (
        "mda",
        (
            "management’s discussion and analysis of financial condition and results of operations",
            "management's discussion and analysis of financial condition and results of operations",
            "management’s discussion and analysis",
            "management's discussion and analysis",
        ),
    ),
    ("business", ("business",)),
    ("management", ("management",)),
    (
        "executive_compensation",
        (
            "executive compensation",
            "executive and director remuneration",
            "executive and director compensation",
        ),
    ),
    (
        "related_party",
        (
            "certain relationships and related party transactions",
            "related party transactions",
        ),
    ),
    (
        "principal_stockholders",
        (
            "principal stockholders",
            "principal and selling shareholders",
            "principal and selling stockholders",
        ),
    ),
    (
        "description_of_capital_stock",
        (
            "description of capital stock",
            "description of share capital and articles of association",
            "description of share capital",
        ),
    ),
    (
        "underwriting",
        (
            "underwriting (conflicts of interest)",
            "underwriters",
            "underwriting",
            "plan of distribution",
        ),
    ),
)

# Forms this catalog applies to — domestic S-1, foreign F-1, and final prospectuses.
S1_FAMILY_FORMS: frozenset[str] = frozenset(
    {
        "S-1",
        "S-1/A",
        "F-1",
        "F-1/A",
        "424B1",
        "424B2",
        "424B3",
        "424B4",
        "424B5",
    }
)


def _whole_line_pattern(phrase: str) -> re.Pattern[str]:
    """Match the phrase as a complete trimmed line (case-insensitive, MULTILINE)."""
    parts = re.split(r"\s+", phrase.strip())
    inner = r"\s+".join(re.escape(p) for p in parts)
    return re.compile(rf"^[\s]*{inner}[\s]*$", re.IGNORECASE | re.MULTILINE)


def _find_s1_body_positions(text: str) -> dict[str, int]:
    """Locate the body header position for each section in SECTION_CATALOG_S1.

    Body position = last whole-line match per section. Sections with no match
    are omitted from the result.
    """
    out: dict[str, int] = {}
    for sid, variants in SECTION_CATALOG_S1:
        latest = -1
        for phrase in variants:
            for m in _whole_line_pattern(phrase).finditer(text):
                if m.start() > latest:
                    latest = m.start()
        if latest >= 0:
            out[sid] = latest
    return out


def extract_s1_all_sections(text: str) -> dict[str, str]:
    """Extract every detectable section from an S-1/F-1/424B prospectus.

    Returns {section_id: section_text}. Sections capped at 300K chars to bound
    a runaway last-section span.
    """
    body = _find_s1_body_positions(text)
    if not body:
        return {}
    sorted_positions = sorted(body.values())
    out: dict[str, str] = {}
    for sid, start in body.items():
        next_positions = [p for p in sorted_positions if p > start]
        end = next_positions[0] if next_positions else len(text)
        end = min(end, start + 300_000)
        out[sid] = text[start:end].strip()
    return out


def extract_s1_section(text: str, section_id: str) -> str:
    """Extract one named S-1 section by id. Returns '' if not found.

    Valid section ids: see SECTION_CATALOG_S1.
    """
    valid_ids = {sid for sid, _ in SECTION_CATALOG_S1}
    if section_id not in valid_ids:
        choices = ", ".join(sid for sid, _ in SECTION_CATALOG_S1)
        raise ValueError(f"Unknown S-1 section_id {section_id!r}; choose from: {choices}")
    return extract_s1_all_sections(text).get(section_id, "")


# ═══════════════════════════════════════════════════════════════
# Risk-factor item splitting + Jaccard diff
# ═══════════════════════════════════════════════════════════════


@dataclass
class RiskItem:
    """One discrete risk factor parsed from Item 1A."""

    headline: str
    body: str

    @property
    def fingerprint(self) -> str:
        return f"{self.headline}\n{self.body[:500]}"


def split_risk_factor_items(text: str) -> list[RiskItem]:
    """Split risk-factors text into items.

    Heuristic: long paragraphs (>=400 chars) anchor item bodies. A short
    paragraph (<400 chars, >=20 chars) immediately preceding a long one is
    treated as the item's headline. Standalone long paragraphs use their
    first sentence as the headline. Continuation paragraphs (mid-length)
    after a body get folded in.

    Issuer formatting varies — this is intentionally pragmatic, not perfect.
    What matters is that the same company filed in the same style year over
    year, so item boundaries align between current and prior 10-K.
    """
    paragraphs = [p.strip() for p in re.split(r"\n+", text) if p.strip()]
    items: list[RiskItem] = []
    i = 0
    while i < len(paragraphs):
        p = paragraphs[i]
        if len(p) < 20:
            i += 1
            continue
        if len(p) >= 400:
            # Long paragraph standing on its own — extract first sentence as headline.
            sentence = re.match(r"^[^.!?]{20,300}[.!?]", p)
            headline = sentence.group(0).rstrip(".!?").strip() if sentence else p[:200]
            body_parts = [p]
            j = i + 1
            while j < len(paragraphs) and 100 <= len(paragraphs[j]) < 400:
                body_parts.append(paragraphs[j])
                j += 1
            items.append(RiskItem(headline=headline, body="\n".join(body_parts)))
            i = j
            continue
        # Medium paragraph — treat as headline if next paragraph is body-length.
        if i + 1 < len(paragraphs) and len(paragraphs[i + 1]) >= 400:
            headline = p
            body_parts = [paragraphs[i + 1]]
            j = i + 2
            while j < len(paragraphs) and 100 <= len(paragraphs[j]) < 400:
                body_parts.append(paragraphs[j])
                j += 1
            items.append(RiskItem(headline=headline, body="\n".join(body_parts)))
            i = j
            continue
        i += 1
    return items


_RISK_STOPWORDS: frozenset[str] = frozenset(
    {
        "the",
        "and",
        "for",
        "that",
        "with",
        "this",
        "our",
        "not",
        "from",
        "may",
        "can",
        "are",
        "its",
        "was",
        "were",
        "have",
        "has",
        "had",
        "but",
        "such",
        "any",
        "all",
        "also",
        "including",
        "which",
        "other",
        "more",
        "than",
        "into",
        "their",
        "these",
        "those",
        "when",
        "could",
        "would",
        "should",
        "will",
        "been",
        "being",
        "there",
        "upon",
        "over",
        "under",
        "between",
        "among",
        "through",
        "during",
        "while",
        "because",
        "before",
        "after",
        "each",
        "every",
        "some",
        "most",
        "much",
        "many",
        "both",
        "either",
        "neither",
    }
)


def _tokenize_for_diff(text: str) -> frozenset[str]:
    """Lowercase 4+ char alphabetic tokens, stopwords removed."""
    return frozenset(w for w in re.findall(r"[a-z]{4,}", text.lower()) if w not in _RISK_STOPWORDS)


def _jaccard(a: frozenset[str], b: frozenset[str]) -> float:
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


@dataclass
class RiskFactorDiff:
    """Result of diffing two risk-factor item lists."""

    added: list[RiskItem]
    removed: list[RiskItem]
    changed: list[tuple[RiskItem, RiskItem, float]]
    unchanged_count: int

    @property
    def has_changes(self) -> bool:
        return bool(self.added or self.removed or self.changed)


def _pair_score(a: RiskItem, b: RiskItem) -> float:
    """Weighted Jaccard: headlines weigh 0.6, bodies 0.4.

    Headlines carry the topic; bodies carry the supporting language. Weighting
    the headline higher means a same-topic item with substantially reworded
    body still pairs (and gets bucketed as CHANGED), instead of being lost as
    REMOVED + ADDED.
    """
    h = _jaccard(_tokenize_for_diff(a.headline), _tokenize_for_diff(b.headline))
    body = _jaccard(_tokenize_for_diff(a.body[:500]), _tokenize_for_diff(b.body[:500]))
    return 0.6 * h + 0.4 * body


def diff_risk_factor_items(
    current: list[RiskItem],
    prior: list[RiskItem],
    *,
    match_threshold: float = 0.30,
    change_threshold: float = 0.80,
) -> RiskFactorDiff:
    """Diff two risk-factor lists by greedy bipartite matching.

    Each current item is matched to its best prior partner via _pair_score.
    Pairs scoring >= match_threshold are matched (rest are ADDED / REMOVED).
    Among matched pairs, those scoring < change_threshold are MATERIALLY
    CHANGED; the rest are UNCHANGED.

    Defaults are tuned for risk-factor reuse year-over-year: same-topic items
    with reworded bodies still pair (combined >= 0.30 once headlines align),
    and a material rewrite drops the combined score below 0.80.
    """
    pairs: list[tuple[int, int, float]] = []
    used_pri: set[int] = set()
    for ci, ct in enumerate(current):
        best_pi = -1
        best_score = 0.0
        for pi, pt in enumerate(prior):
            if pi in used_pri:
                continue
            s = _pair_score(ct, pt)
            if s > best_score:
                best_pi = pi
                best_score = s
        if best_pi >= 0 and best_score >= match_threshold:
            pairs.append((ci, best_pi, best_score))
            used_pri.add(best_pi)

    paired_cur = {p[0] for p in pairs}
    added = [current[i] for i in range(len(current)) if i not in paired_cur]
    removed = [prior[i] for i in range(len(prior)) if i not in used_pri]
    changed = [
        (current[ci], prior[pi], score) for ci, pi, score in pairs if score < change_threshold
    ]
    unchanged_count = sum(1 for _, _, s in pairs if s >= change_threshold)
    return RiskFactorDiff(
        added=added,
        removed=removed,
        changed=changed,
        unchanged_count=unchanged_count,
    )
