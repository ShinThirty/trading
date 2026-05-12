"""IPO analysis tools — locate and parse S-1 / F-1 / 424B prospectuses.

These tools support running the pre-profit speculative-growth framework
(docs/pre-profit-growth-framework.md) against an upcoming or recent IPO.

Pipeline:
  get_ipo_s1(ticker) -> latest filing accession + primary doc
  get_ipo_section(ticker, accession, document, section) -> one named section
  get_ipo_concentration(ticker, accession, document) -> customer concentration
                                                        disclosures across
                                                        MDA + Risk Factors + Business
"""

import re

from fastmcp import Context, FastMCP
from trading_clients.endpoints import edgar as e

from trading_mcp.helpers import _edgar, _exc_summary

mcp = FastMCP("ipo-tools")


# Form-preference order for choosing "the" filing to read. Final prospectuses
# (424B*) supersede S-1 amendments which supersede the original S-1.
_FORM_PREFERENCE: tuple[str, ...] = (
    "424B4",
    "424B3",
    "424B2",
    "424B1",
    "424B5",
    "S-1/A",
    "F-1/A",
    "S-1",
    "F-1",
)


@mcp.tool()
async def get_ipo_s1(ctx: Context, symbol: str) -> str:
    """Locate the latest S-1 / F-1 / 424B prospectus for a ticker.

    Returns the chosen filing's accession + primary document filename plus the
    full list of S-1-family filings on file (so amendment history is visible).
    Final prospectuses (424B4 etc.) are preferred over S-1/A which are preferred
    over S-1, then by date within each tier.

    symbol: ticker symbol that has been assigned (must exist in EDGAR's ticker
        map — recently-priced IPOs may take a day to appear).

    Use the returned accession + primary document with get_ipo_section or
    get_ipo_concentration to read specific parts of the prospectus.
    """
    edgar = _edgar(ctx)
    ticker = symbol.upper()

    try:
        cik = await edgar.lookup_cik(ticker)
    except ValueError as ex:
        return f"⚠ {ex}"
    except Exception as ex:
        return f"⚠ {_exc_summary('EDGAR ticker→CIK lookup', ex)}"

    try:
        sub = await edgar.get(e.SUBMISSIONS, e.CikRequest(cik=cik))
    except Exception as ex:
        return f"⚠ {_exc_summary('EDGAR submissions fetch', ex)}"

    s1_filings = [f for f in sub.filings if f.form in e.S1_FAMILY_FORMS]
    if not s1_filings:
        return (
            f"⚠ No S-1 / F-1 / 424B filings found for {ticker} (CIK {cik}). "
            f"Either the company is not pre-IPO / recently-IPO'd, or all "
            f"S-1-family filings predate the recent-1000-filings window."
        )

    s1_filings.sort(key=lambda f: f.filing_date, reverse=True)

    # Pick preferred filing.
    chosen: e.Filing | None = None
    for pref in _FORM_PREFERENCE:
        for f in s1_filings:
            if f.form == pref:
                chosen = f
                break
        if chosen:
            break

    if chosen is None:
        chosen = s1_filings[0]

    lines = [
        f"# {ticker} S-1 family filings",
        f"CIK: {cik}",
        f"Total S-1-family filings: {len(s1_filings)}",
        "",
        "## Chosen for analysis",
        f"- Form: {chosen.form}",
        f"- Filed: {chosen.filing_date}",
        f"- Accession: {chosen.accession_number}",
        f"- Primary document: {chosen.primary_document}",
        "",
        "## Full filing history",
        "| Filed | Form | Accession | Primary Doc |",
        "|-------|------|-----------|-------------|",
    ]
    for f in s1_filings[:10]:
        marker = " ← chosen" if f.accession_number == chosen.accession_number else ""
        lines.append(
            f"| {f.filing_date} | {f.form} | {f.accession_number} | {f.primary_document}{marker} |"
        )
    if len(s1_filings) > 10:
        lines.append(f"| ... | (+{len(s1_filings) - 10} older) | | |")

    return "\n".join(lines)


_VALID_SECTION_IDS: frozenset[str] = frozenset(sid for sid, _ in e.SECTION_CATALOG_S1)


@mcp.tool()
async def get_ipo_section(
    ctx: Context,
    symbol: str,
    accession_number: str,
    document: str,
    section: str,
) -> str:
    """Extract one named section from an S-1 / F-1 / 424B prospectus.

    S-1s use named section headers (not 10-K Item-numbers), so this is the
    S-1-family analog of get_filing_section. Same docs format applies — pass
    the accession + primary document from get_ipo_s1.

    Available sections: prospectus_summary, the_offering, summary_financial_data,
    risk_factors, special_note_forward_looking, market_industry_data,
    use_of_proceeds, dividend_policy, capitalization, dilution, mda, business,
    management, executive_compensation, related_party, principal_stockholders,
    description_of_capital_stock, underwriting.

    Returns the cleaned section text. Foreign issuers (F-1) use the same
    section ids — the catalog includes name variants ("share capital" vs
    "capital stock", "remuneration" vs "compensation", etc.).
    """
    if section not in _VALID_SECTION_IDS:
        choices = ", ".join(sorted(_VALID_SECTION_IDS))
        return f"⚠ Unknown S-1 section {section!r}. Choose from: {choices}"

    edgar = _edgar(ctx)
    ticker = symbol.upper()
    accession_no_dashes = accession_number.replace("-", "")

    try:
        cik = await edgar.lookup_cik(ticker)
    except ValueError as ex:
        return f"⚠ {ex}"
    except Exception as ex:
        return f"⚠ {_exc_summary('EDGAR ticker→CIK lookup', ex)}"

    try:
        doc = await edgar.get(
            e.FILING_DOC,
            e.FilingDocRequest(cik, accession_no_dashes, document),
        )
    except Exception as ex:
        return (
            f"⚠ Failed to fetch {document} from accession {accession_number}: "
            f"{_exc_summary('EDGAR filing doc', ex)}"
        )

    extracted = e.extract_s1_section(doc.text or "", section)
    url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{accession_no_dashes}/{document}"
    if not extracted:
        return (
            f"⚠ S-1 section {section!r} not found in {ticker} {document}. "
            f"Issuer may use non-standard heading or this section was renamed. "
            f"Source: {url}"
        )
    return (
        f"# {ticker} S-1 section: {section}\n"
        f"Accession: {accession_number}\n"
        f"Source: {url}\n"
        f"Section length: {len(extracted):,} chars\n\n"
        f"{extracted}"
    )


# ═══════════════════════════════════════════════════════════════════════
# Customer concentration extraction
# ═══════════════════════════════════════════════════════════════════════
#
# Concentration disclosures appear in MDA (specific numbers in results-of-ops
# discussion), Risk Factors (narrative warnings), and Business (customer-mix
# overview). All three are searched.
#
# Patterns capture the percentage and surrounding context. The "who" capture
# is intentionally lenient because the LLM downstream needs full sentence
# context anyway — the regex's job is to surface candidate disclosures, not
# to perfectly tokenize the customer name.

_CONCENTRATION_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    # A: "<who> accounted for X.X% [and Y.Y% [and Z.Z%]] of our revenue"
    (
        "named",
        re.compile(
            r"""
            (?P<who>[A-Z][\w&,.\-\s\(\)\"‘’]{2,80}?)
            \s+(?:accounted\s+for|represented|generated|made\s+up|comprised)\s+
            (?:approximately\s+)?
            (?P<pct1>\d{1,2}(?:\.\d{1,2})?)\%
            (?:\s+(?:and|,)\s+(?:approximately\s+)?(?P<pct2>\d{1,2}(?:\.\d{1,2})?)\%)?
            (?:\s+(?:and|,)\s+(?:approximately\s+)?(?P<pct3>\d{1,2}(?:\.\d{1,2})?)\%)?
            \s+of\s+our\s+(?:total\s+|net\s+|consolidated\s+)?(?:revenue|revenues|net\s+revenue)
            """,
            re.IGNORECASE | re.VERBOSE,
        ),
    ),
    # B: "X.X% of our revenue ... from <who>."
    (
        "reverse",
        re.compile(
            r"""
            (?P<pct1>\d{1,2}(?:\.\d{1,2})?)\%
            \s+of\s+our\s+(?:total\s+|net\s+|consolidated\s+)?(?:revenue|revenues)
            \s+(?:was|came|were|is|are)\s+
            (?:generated\s+|attributable\s+|derived\s+)?from\s+
            (?P<who>[A-Z][\w&,.\-\s\(\)\"‘’]{2,80}?)[\.\,]
            """,
            re.IGNORECASE | re.VERBOSE,
        ),
    ),
    # C: "(largest|top|principal) customer ... X.X% of revenue"
    (
        "ranked",
        re.compile(
            r"""
            (?:our\s+)?(?:single\s+)?(?:largest|top|principal|primary|key)\s+customer
            [^.]{0,80}?
            (?P<pct1>\d{1,2}(?:\.\d{1,2})?)\%
            \s+of\s+our\s+(?:total\s+|net\s+|consolidated\s+)?(?:revenue|revenues)
            """,
            re.IGNORECASE | re.VERBOSE,
        ),
    ),
    # D: Tabular introducer — section is followed by a table the regex can't parse.
    (
        "table_intro",
        re.compile(
            r"""
            Customers?\s+(?:that|who)\s+(?:each\s+)?(?:accounted\s+for|represented)
            \s+(?P<pct1>\d{1,2}(?:\.\d{1,2})?)\%\s+or\s+more
            \s+of\s+our\s+(?:total\s+|net\s+|consolidated\s+)?revenues?
            """,
            re.IGNORECASE | re.VERBOSE,
        ),
    ),
)

# Sections searched for concentration — order is presentation, not priority.
_CONCENTRATION_SOURCE_SECTIONS: tuple[str, ...] = ("mda", "risk_factors", "business")


def _scan_section_for_concentration(section_text: str, section_id: str) -> list[dict[str, str]]:
    """Run all concentration patterns against one section's text."""
    hits: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    for pat_name, pat in _CONCENTRATION_PATTERNS:
        for m in pat.finditer(section_text):
            d = m.groupdict()
            who = (d.get("who") or "").strip() or "(table)"
            pcts = "/".join(p for p in (d.get("pct1"), d.get("pct2"), d.get("pct3")) if p)
            # Dedup on first 30 chars of who + pct combo
            key = (section_id, who[:30].lower(), pcts)
            if key in seen:
                continue
            seen.add(key)

            ctx_start = max(0, m.start() - 80)
            ctx_end = min(len(section_text), m.end() + 80)
            context = re.sub(r"\s+", " ", section_text[ctx_start:ctx_end]).strip()

            hits.append(
                {
                    "section": section_id,
                    "pattern": pat_name,
                    "who": who,
                    "pct": pcts,
                    "context": context,
                }
            )
    return hits


@mcp.tool()
async def get_ipo_concentration(
    ctx: Context,
    symbol: str,
    accession_number: str,
    document: str,
) -> str:
    """Surface customer-concentration disclosures from an S-1 / F-1 / 424B.

    Searches MDA, Risk Factors, and Business sections (concentration may be
    disclosed in any of them: MDA usually has the specific numbers, Risk
    Factors has the narrative warning, Business has customer-mix descriptions).

    For each disclosure found, returns: source section, customer (best-effort
    capture, may include preceding context), percentage(s) cited, and the
    sentence the disclosure appears in for verification.

    Important caveats:
    - The "who" capture is regex-driven and may include preceding lead-in text.
      Read the context sentence to confirm which entity is being referenced.
    - Some hits will be revenue-type concentration (e.g., interest income X% of
      revenue), not customer concentration. Filter using the framework's lens.
    - Tabular disclosures ("Customers that each accounted for 10% or more...")
      surface the introducer line; the actual table sits in the F-pages and
      requires a raw-filing read via get_filing_content.
    - Pre-profit-growth-framework gate: any single customer >10% of revenue
      fails the customer concentration hard requirement. Trajectory matters
      too — a name growing from 20% → 28% → 30% is more dangerous than 10%
      static.
    """
    edgar = _edgar(ctx)
    ticker = symbol.upper()
    accession_no_dashes = accession_number.replace("-", "")

    try:
        cik = await edgar.lookup_cik(ticker)
    except ValueError as ex:
        return f"⚠ {ex}"
    except Exception as ex:
        return f"⚠ {_exc_summary('EDGAR ticker→CIK lookup', ex)}"

    try:
        doc = await edgar.get(
            e.FILING_DOC,
            e.FilingDocRequest(cik, accession_no_dashes, document),
        )
    except Exception as ex:
        return (
            f"⚠ Failed to fetch {document} from accession {accession_number}: "
            f"{_exc_summary('EDGAR filing doc', ex)}"
        )

    sections = e.extract_s1_all_sections(doc.text or "")
    if not sections:
        return (
            f"⚠ Could not locate any S-1 sections in {ticker} {document}. "
            f"Filing may use non-standard heading conventions."
        )

    all_hits: list[dict[str, str]] = []
    sections_searched: list[str] = []
    for sid in _CONCENTRATION_SOURCE_SECTIONS:
        if sid not in sections:
            continue
        sections_searched.append(sid)
        all_hits.extend(_scan_section_for_concentration(sections[sid], sid))

    url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{accession_no_dashes}/{document}"

    lines = [
        f"# {ticker} customer concentration — {document}",
        f"Accession: {accession_number}",
        f"Source: {url}",
        f"Sections searched: {', '.join(sections_searched) or '(none — extraction failed)'}",
        "",
    ]

    if not all_hits:
        lines.extend(
            [
                "**No concentration disclosures matched.**",
                "",
                "This means EITHER (a) the company has no >10% customer concentration "
                "to disclose, OR (b) the disclosure uses phrasing not covered by the "
                "regex patterns. For high-stakes verification, read the Risk Factors "
                "and MDA sections directly via get_ipo_section.",
            ]
        )
        return "\n".join(lines)

    lines.append(f"**{len(all_hits)} disclosure(s) found:**")
    lines.append("")
    lines.append("| # | Section | Pattern | Customer (best-effort) | Pct(s) |")
    lines.append("|---|---------|---------|------------------------|--------|")
    for i, h in enumerate(all_hits, 1):
        who = h["who"][:60].replace("|", "\\|").replace("\n", " ")
        lines.append(f"| {i} | {h['section']} | {h['pattern']} | {who} | {h['pct']}% |")

    lines.append("")
    lines.append("## Disclosure context")
    for i, h in enumerate(all_hits, 1):
        lines.append(f"\n**[{i}] {h['section']} / {h['pattern']}** ({h['pct']}%)")
        lines.append(f"> {h['context']}")

    return "\n".join(lines)
