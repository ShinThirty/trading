"""Generic SEC EDGAR primitives: filings index + filing-content fetcher.

These two tools cover everything a public company files (8-K, 10-Q, 10-K, 13D,
Form 4, S-3, DEF 14A, 20-F, 6-K, …). Earnings-specific helpers live in
tools/earnings.py and compose these primitives.
"""

import asyncio
from collections import defaultdict
from datetime import date

from fastmcp import Context, FastMCP
from trading_clients.endpoints import edgar as e
from trading_clients.table_helpers import md_table

from trading_mcp.db.pipeline import list_entries
from trading_mcp.helpers import _db, _edgar, _exc_summary

mcp = FastMCP("edgar-tools")


def _fmt_items(items: list[str]) -> str:
    return ", ".join(items) if items else "—"


@mcp.tool()
async def get_recent_filings(
    ctx: Context,
    symbol: str,
    days: int = 30,
    forms: list[str] | None = None,
) -> str:
    """List recent SEC filings for a ticker, grouped by signal-severity tier.

    Source: SEC EDGAR submissions feed. Covers all forms (8-K, 10-Q, 10-K, 13D,
    Form 4, S-3, DEF 14A, 20-F, 6-K, etc.). 8-K Item codes are pre-extracted so
    you can spot material events (5.02 executive change, 4.02 restatement, 1.01
    material agreement, …) without a second fetch.

    Pair with get_filing_content(symbol, accession_number, document) to read the
    actual text of any filing surfaced here.

    symbol: ticker symbol (e.g. 'NVDA'). Case-insensitive.
    days: lookback window in calendar days (default 30).
    forms: optional list of form codes to include (e.g. ['8-K', '10-Q']). If
        None, all forms within the window are returned.

    Tiers (ordered by signal severity):
      MATERIAL — 8-K with items {1.01, 1.02, 2.01, 2.05, 2.06, 4.01, 4.02, 5.02,
                 7.01, 8.01}; SC 13D activist filings; NT late-filings.
      EARNINGS — 8-K Item 2.02; 10-Q; 10-K; 20-F.
      INTERIM  — 6-K (foreign issuer interim disclosure — variable content).
      INSIDER  — Form 4 (officer/director/10%+ holder transactions).
      GOVERNANCE — DEF 14A and amendments.
      CAPITAL — S-1/S-3/S-4 shelf and equity raises.
      ROUTINE — everything else (S-8, Form 3/5, Form 144, SC 13G, prospectus
                supplements, etc.).
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
        subs = await edgar.get(e.SUBMISSIONS, e.CikRequest(cik))
    except Exception as ex:
        return f"⚠ {_exc_summary(f'EDGAR submissions for CIK {cik}', ex)}"

    today = date.today().isoformat()
    window = subs.within_window(today, days)
    if forms:
        wanted = {f.upper() for f in forms}
        window = [f for f in window if f.form.upper() in wanted]

    if not window:
        scope = f" (forms={forms})" if forms else ""
        return f"No SEC filings for {ticker} in the last {days} days{scope}"

    grouped: dict[str, list[e.Filing]] = defaultdict(list)
    for filing in window:
        grouped[filing.tier].append(filing)

    sections: list[str] = []
    sections.append(f"# {ticker} recent SEC filings (last {days} days)")
    sections.append(f"CIK {cik:010d} · {len(window)} filings across {len(grouped)} tier(s)")

    for tier in e.TIER_ORDER:
        rows_data = grouped.get(tier)
        if not rows_data:
            continue
        rows = [
            [
                f.filing_date,
                f.form,
                _fmt_items(f.items),
                f.primary_document or "—",
                f.accession_number,
            ]
            for f in rows_data
        ]
        sections.append(f"\n## {tier} ({len(rows_data)})")
        sections.append(md_table(["Date", "Form", "Items", "Primary Doc", "Accession #"], rows))

    return "\n".join(sections)


_DEFAULT_MAX_CHARS = 100_000


@mcp.tool()
async def get_filing_content(
    ctx: Context,
    symbol: str,
    accession_number: str,
    document: str,
    max_chars: int = _DEFAULT_MAX_CHARS,
    offset: int = 0,
) -> str:
    """Fetch and parse the text of a specific document inside an SEC filing.

    Use after get_recent_filings to read the actual contents of any filing.
    Strips HTML/scripts/styles and returns clean text.

    symbol: ticker symbol (used to resolve CIK).
    accession_number: with or without dashes (e.g. '0000320193-26-000011').
    document: filename to fetch — use the 'Primary Doc' shown in
        get_recent_filings output, or any exhibit name from the filing index
        (e.g. 'ex99-1.htm' for a press release attachment).
    max_chars: cap on returned text (default 100k chars ≈ 25k tokens). 8-K
        press releases easily fit; 10-Q/10-K primary docs are typically
        300k-1M chars and will be truncated. Re-call with a larger
        max_chars or a non-zero offset to read further.
    offset: number of chars to skip from the start. Useful for paging through
        long 10-Q/10-K filings — the first ~15-20k chars of these are
        inline-XBRL tag soup, so offset=20000 gets you straight to the
        narrative.

    For multi-document filings (8-K with exhibits, 10-K with segments) you may
    need separate calls — start with the primary document, then drill into
    exhibits if relevant.
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

    full_text = doc.text or ""
    total = len(full_text)
    start = max(0, min(offset, total))
    end = min(total, start + max(0, max_chars))
    body = full_text[start:end] or "(no content)"

    notes: list[str] = []
    if start > 0:
        notes.append(f"skipped first {start:,} chars (offset)")
    if end < total:
        notes.append(f"truncated at {end:,}/{total:,} chars; re-call with offset={end} to continue")
    note_line = f"Note: {'; '.join(notes)}\n" if notes else ""

    url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{accession_no_dashes}/{document}"
    return (
        f"# {ticker} filing content — {document}\n"
        f"Accession: {accession_number}\n"
        f"Source: {url}\n"
        f"{note_line}\n"
        f"{body}"
    )


@mcp.tool()
async def get_filing_section(
    ctx: Context,
    symbol: str,
    accession_number: str,
    document: str,
    section: str,
) -> str:
    """Fetch a 10-Q / 10-K and return only one named section.

    Targeted alternative to get_filing_content when you know which section
    you want — avoids paging through XBRL tag soup and the rest of the doc.

    symbol: ticker symbol (used to resolve CIK).
    accession_number: with or without dashes.
    document: filing primary document filename (use the 'Primary Doc' from
        get_recent_filings output).
    section: one of mda, risk_factors, segments, cash_flow, business.

    Section meanings:
      mda — Management's Discussion and Analysis (10-Q Item 2 / 10-K Item 7);
      risk_factors — Item 1A (10-K only, 10-Q usually defers);
      segments — Segment Information / Disaggregation of Revenue;
      cash_flow — Liquidity and Capital Resources subsection of MD&A;
      business — Item 1 Business overview (10-K).

    Returns just that section's cleaned text. Returns an explicit message if
    the anchor wasn't found (issuer formatting varies — fall back to
    get_filing_content with offset for hand navigation).
    """
    if section not in e.SECTION_ANCHORS:
        choices = ", ".join(e.SECTION_ANCHORS)
        return f"⚠ Unknown section {section!r}. Choose one of: {choices}"

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

    extracted = e.extract_section(doc.text or "", section)
    url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{accession_no_dashes}/{document}"
    if not extracted:
        return (
            f"⚠ Section {section!r} not found in {ticker} {document}. "
            f"Issuer may use a non-standard heading. Source: {url}"
        )
    return (
        f"# {ticker} {section} — {document}\n"
        f"Accession: {accession_number}\n"
        f"Source: {url}\n"
        f"Section length: {len(extracted):,} chars\n\n"
        f"{extracted}"
    )


def _find_recent_10ks(filings: list[e.Filing], n: int = 2) -> list[e.Filing]:
    """Return the n most recent 10-K filings (already date-sorted in submissions)."""
    return [f for f in filings if f.form == "10-K"][:n]


def _format_risk_item(item: e.RiskItem, body_chars: int) -> str:
    body = item.body[:body_chars]
    if len(item.body) > body_chars:
        body += " …"
    return f"**{item.headline}**\n\n{body}"


@mcp.tool()
async def diff_risk_factors(
    ctx: Context,
    symbol: str,
    current_accession: str | None = None,
    prior_accession: str | None = None,
) -> str:
    """Diff Item 1A risk factors between the latest 10-K and the prior 10-K.

    The most underused signal in filings: companies rewrite risk factors
    annually but most language is reused. New or substantively rewritten
    items are where management is signalling something has changed.

    symbol: ticker.
    current_accession: optional override for the 'current' 10-K. If omitted,
        picks the most recent 10-K from EDGAR submissions.
    prior_accession: optional override for the 'prior' 10-K. If omitted,
        picks the second-most-recent 10-K.

    Output buckets:
      ADDED   — new items in current 10-K with no close prior match
      REMOVED — prior items dropped from current 10-K
      CHANGED — same-topic items with substantially reworded body
      UNCHANGED count — items reused largely verbatim

    Bias toward reading ADDED items — REMOVED is rarer and usually less
    actionable. CHANGED is worth scanning if the count is small (1-3),
    less so if many (suggests routine rewording).
    """
    edgar = _edgar(ctx)
    ticker = symbol.upper()

    try:
        cik = await edgar.lookup_cik(ticker)
    except ValueError as ex:
        return f"⚠ {ex}"
    except Exception as ex:
        return f"⚠ {_exc_summary('EDGAR ticker→CIK lookup', ex)}"

    # Resolve which two filings to compare. Either both supplied, or auto-pick.
    cur: e.Filing | None = None
    prior: e.Filing | None = None
    if current_accession and prior_accession:
        # Build minimal Filing stubs — we need primary_document, which we don't
        # have without hitting submissions. Just fetch submissions anyway.
        pass

    try:
        subs = await edgar.get(e.SUBMISSIONS, e.CikRequest(cik))
    except Exception as ex:
        return f"⚠ {_exc_summary(f'EDGAR submissions for CIK {cik}', ex)}"

    if current_accession:
        cur = next(
            (f for f in subs.filings if f.accession_number == current_accession),
            None,
        )
        if cur is None:
            return f"⚠ current_accession {current_accession} not found in {ticker} submissions"
    if prior_accession:
        prior = next(
            (f for f in subs.filings if f.accession_number == prior_accession),
            None,
        )
        if prior is None:
            return f"⚠ prior_accession {prior_accession} not found in {ticker} submissions"

    if cur is None or prior is None:
        recent = _find_recent_10ks(subs.filings, n=2)
        if len(recent) < 2:
            return (
                f"⚠ {ticker} has only {len(recent)} 10-K(s) in recent submissions; "
                "need 2 to diff. Pass explicit accessions if comparing to an older filing."
            )
        cur = cur or recent[0]
        prior = prior or recent[1]

    async def _fetch_section(filing: e.Filing) -> tuple[str, e.Filing]:
        doc = await edgar.get(
            e.FILING_DOC,
            e.FilingDocRequest(cik, filing.accession_no_dashes, filing.primary_document),
        )
        return e.extract_section(doc.text or "", "risk_factors"), filing

    try:
        (cur_text, _), (prior_text, _) = await asyncio.gather(
            _fetch_section(cur), _fetch_section(prior)
        )
    except Exception as ex:
        return f"⚠ {_exc_summary('EDGAR 10-K fetch for risk-factors diff', ex)}"

    if not cur_text:
        return (
            f"⚠ Could not extract Item 1A from current 10-K "
            f"({cur.accession_number}, {cur.filing_date})"
        )
    if not prior_text:
        return (
            f"⚠ Could not extract Item 1A from prior 10-K "
            f"({prior.accession_number}, {prior.filing_date})"
        )

    cur_items = e.split_risk_factor_items(cur_text)
    prior_items = e.split_risk_factor_items(prior_text)

    if not cur_items or not prior_items:
        return (
            f"⚠ Risk-factor splitter produced too few items "
            f"(current={len(cur_items)}, prior={len(prior_items)}). "
            "Issuer formatting may be non-standard."
        )

    diff = e.diff_risk_factor_items(cur_items, prior_items)

    header = (
        f"# {ticker} risk-factor diff: 10-K {cur.filing_date} vs {prior.filing_date}\n"
        f"Current: {cur.accession_number} ({len(cur_items)} items)\n"
        f"Prior:   {prior.accession_number} ({len(prior_items)} items)\n\n"
        f"**Summary** — added: {len(diff.added)}, removed: {len(diff.removed)}, "
        f"changed: {len(diff.changed)}, unchanged: {diff.unchanged_count}\n"
    )

    if not diff.has_changes:
        return header + "\nNo material additions, removals, or rewrites detected."

    parts = [header]

    if diff.added:
        parts.append(f"## ADDED ({len(diff.added)})\n")
        parts.extend(_format_risk_item(it, body_chars=800) for it in diff.added)

    if diff.removed:
        parts.append(f"\n## REMOVED ({len(diff.removed)})\n")
        # Headlines only — full body is rarely actionable.
        parts.extend(f"- {it.headline}" for it in diff.removed)

    if diff.changed:
        parts.append(f"\n## CHANGED ({len(diff.changed)})\n")
        for cur_it, prior_it, sim in diff.changed:
            parts.append(f"\n### similarity={sim:.2f}\n")
            parts.append(f"**Current**: {cur_it.headline}\n\n{cur_it.body[:400]}")
            parts.append(f"\n**Prior**:   {prior_it.headline}\n\n{prior_it.body[:400]}")

    return "\n".join(parts)


@mcp.tool()
async def get_8k_exhibit(ctx: Context, symbol: str, accession_number: str) -> str:
    """Fetch the press release exhibit (Ex 99.x) of an 8-K — full text, cleaned.

    For 8-Ks where the substance lives in the attached press release rather
    than the cover page (most material 8-Ks: Item 1.01 agreements, 5.02
    departures, 7.01 Reg FD, 8.01 other events). Falls back to the primary
    document if no Ex 99 is attached.

    For Item 2.02 earnings 8-Ks specifically, prefer get_earnings_release —
    it auto-discovers the latest one without needing the accession number.

    symbol: ticker.
    accession_number: with or without dashes.
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
        index = await edgar.get(e.FILING_INDEX, e.FilingIndexRequest(cik, accession_no_dashes))
    except Exception as ex:
        return (
            f"⚠ Failed to fetch filing index for {accession_number}: "
            f"{_exc_summary('EDGAR filing index', ex)}"
        )

    filename = index.find_press_release()
    fallback_used = False
    if not filename:
        # Fall back to the first .htm in the index (usually the primary 8-K cover doc).
        for name in index.files:
            if name.lower().endswith((".htm", ".html")):
                filename = name
                fallback_used = True
                break
    if not filename:
        return (
            f"⚠ No HTML document found in 8-K {accession_number}. "
            f"Index files: {', '.join(index.files) or '(empty)'}"
        )

    try:
        doc = await edgar.get(
            e.FILING_DOC,
            e.FilingDocRequest(cik, accession_no_dashes, filename),
        )
    except Exception as ex:
        return f"⚠ Found {filename} but doc fetch failed: {_exc_summary('EDGAR filing doc', ex)}"

    url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{accession_no_dashes}/{filename}"
    label = "primary 8-K document (no Ex 99 attached)" if fallback_used else filename
    return (
        f"# {ticker} 8-K exhibit — {label}\n"
        f"Accession: {accession_number}\n"
        f"Source: {url}\n\n"
        f"{doc.to_output()}"
    )


_TIER_RANKS: dict[str, int] = {tier: rank for rank, tier in enumerate(e.TIER_ORDER)}


def _tier_at_or_above(tier: str, min_tier: str) -> bool:
    """True when `tier` is at or above `min_tier` in TIER_ORDER (lower index = more severe)."""
    return _TIER_RANKS.get(tier, 999) <= _TIER_RANKS.get(min_tier, -1)


@mcp.tool()
async def scan_pipeline_filings(
    ctx: Context,
    days: int = 14,
    min_tier: str = "CAPITAL",
) -> str:
    """Sweep all active pipeline tickers for recent filings at or above a tier.

    Use case: biweekly review punch list — surface only material events (8-K
    items 1.01/2.05/4.02/5.02/7.01/8.01, 13D activist filings, restatements,
    earnings releases, equity raises) since the last sweep, across the whole
    pipeline.

    days: lookback window in calendar days (default 14, matches biweekly review).
    min_tier: include tiers at or above this severity. Tiers in order:
        MATERIAL > EARNINGS > INTERIM > INSIDER > GOVERNANCE > CAPITAL > ROUTINE.
        Default CAPITAL surfaces everything except ROUTINE.

    Tickers not present in the EDGAR map (foreign issuers, ETFs, recent IPOs
    not yet indexed) are listed under a Skipped section rather than failing
    the whole scan.
    """
    if min_tier not in _TIER_RANKS:
        return f"⚠ Unknown min_tier {min_tier!r}. Choose from: " + ", ".join(e.TIER_ORDER)

    conn = _db(ctx)
    entries = await list_entries(conn)
    if not entries:
        return "(no active pipeline entries)"

    edgar = _edgar(ctx)
    today = date.today().isoformat()
    tickers = sorted({entry["ticker"].upper() for entry in entries})

    async def _scan_one(ticker: str) -> tuple[str, list[e.Filing] | str]:
        try:
            cik = await edgar.lookup_cik(ticker)
        except ValueError as ex:
            return ticker, str(ex)
        except Exception as ex:
            return ticker, _exc_summary("EDGAR ticker→CIK", ex)
        try:
            subs = await edgar.get(e.SUBMISSIONS, e.CikRequest(cik))
        except Exception as ex:
            return ticker, _exc_summary(f"EDGAR submissions {cik}", ex)
        window = subs.within_window(today, days)
        kept = [f for f in window if _tier_at_or_above(f.tier, min_tier)]
        return ticker, kept

    results = await asyncio.gather(*(_scan_one(t) for t in tickers))

    hits: dict[str, list[e.Filing]] = {}
    skipped: list[tuple[str, str]] = []
    for ticker, payload in results:
        if isinstance(payload, str):
            skipped.append((ticker, payload))
        elif payload:
            hits[ticker] = payload

    sections: list[str] = []
    sections.append(
        f"# Pipeline filings sweep — last {days}d, tier ≥ {min_tier}\n"
        f"Scanned {len(tickers)} ticker(s); {len(hits)} have hits."
    )

    if hits:
        rows: list[list[str]] = []
        for ticker in sorted(hits):
            for f in hits[ticker]:
                rows.append(
                    [
                        ticker,
                        f.filing_date,
                        f.form,
                        f.tier,
                        ", ".join(f.items) if f.items else "—",
                        f.accession_number,
                    ]
                )
        sections.append(
            "\n## Hits\n"
            + md_table(
                ["Ticker", "Date", "Form", "Tier", "Items", "Accession #"],
                rows,
            )
        )
    else:
        sections.append("\n_No filings at or above the tier threshold._")

    if skipped:
        sections.append("\n## Skipped (lookup failed)")
        sections.append(md_table(["Ticker", "Reason"], [[t, r] for t, r in skipped]))

    return "\n".join(sections)
