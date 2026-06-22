"""FactSet Earnings Insight — weekly S&P 500 earnings season pulse.

FactSet publishes the Earnings Insight PDF every Friday afternoon ET. URL pattern:

  https://advantage.factset.com/hubfs/Website/Resources%20Section/
    Research%20Desk/Earnings%20Insight/EarningsInsight_<MMDDYY>.pdf

The PDF is ~36 pages but the structured data lives in narrative pages 1 and
6-15 (extractable text). Pages 16+ are chart images that pdfplumber can't read,
and we don't need them — the narrative covers every metric.

This module defines the response model parsed from those page-text bundles.
The client (FactsetClient) handles date-walking, fetch, and pdfplumber
extraction.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date


@dataclass
class SectorRevision:
    """One sector's blended growth revision since quarter-end."""

    name: str
    quarter_end_pct: float  # estimate as of quarter-end (e.g. -3.7)
    current_pct: float  # blended growth today (e.g. 48.8)

    @property
    def delta_pp(self) -> float:
        return self.current_pct - self.quarter_end_pct


@dataclass
class FactsetEarningsInsightResponse:
    """Parsed FactSet Earnings Insight summary + raw narrative.

    Numeric fields are parsed best-effort from narrative regex; missing values
    stay None and we still surface the raw narrative so a reader can fall back
    to the source. The raw narrative is the load-bearing piece — it's what the
    LLM and user actually read. Parsed metrics are convenience surfacers.
    """

    publish_date: str = ""  # e.g. "May 8, 2026"
    quarter_label: str = ""  # e.g. "Q1 2026"

    # Beat rate texture (current quarter, in-season)
    pct_reported: float | None = None  # e.g. 89% have reported
    eps_beat_rate: float | None = None  # e.g. 84%
    rev_beat_rate: float | None = None  # e.g. 80%
    eps_beat_5y_avg: float | None = None  # e.g. 78%
    rev_beat_5y_avg: float | None = None
    eps_surprise_pct: float | None = None  # e.g. +18.2%
    eps_surprise_5y_avg: float | None = None  # e.g. +7.3%

    # Blended growth (current quarter)
    blended_eps_growth: float | None = None  # e.g. 27.7%
    blended_eps_growth_quarter_end: float | None = None  # e.g. 13.1%
    blended_rev_growth: float | None = None  # e.g. 11.3%

    # Forward growth (next 3 quarters + CY)
    forward_q_growth: list[float] = field(default_factory=list)  # [Q+1, Q+2, Q+3]
    forward_q_labels: list[str] = field(default_factory=list)  # ["Q2 2026", "Q3 2026", ...]
    cy_growth: dict[str, float] = field(default_factory=dict)  # {"CY 2026": 21.0, "CY 2027": ...}

    # Valuation
    forward_pe: float | None = None  # e.g. 21.0
    forward_pe_5y_avg: float | None = None
    forward_pe_10y_avg: float | None = None
    forward_pe_quarter_end: float | None = None
    # Publish date of the edition the forward P/E came from, set only when it was
    # backfilled from a prior report (this issue omitted the Valuation section).
    forward_pe_as_of: str = ""

    # Market reaction asymmetry (beats vs misses, +/- 2 days around print)
    beat_reaction_pct: float | None = None  # e.g. +1.1%
    beat_reaction_5y_avg: float | None = None  # e.g. +1.0%
    miss_reaction_pct: float | None = None  # e.g. -4.9%
    miss_reaction_5y_avg: float | None = None  # e.g. -2.9%

    # Guidance counts (next quarter)
    guidance_positive: int | None = None
    guidance_negative: int | None = None
    guidance_quarter_label: str = ""

    # Sector revisions since quarter-end
    sector_revisions: list[SectorRevision] = field(default_factory=list)

    # Raw narrative — pages 1 + 6-15 concatenated, header/footer stripped.
    # This is the load-bearing field for LLM judgment.
    narrative: str = ""

    @classmethod
    def from_response(cls, pages_text: dict[int, str]) -> FactsetEarningsInsightResponse:
        """Build from a {page_number: text} mapping. Page numbers are 1-indexed."""
        narrative = _build_narrative(pages_text)
        # PDFs wrap mid-sentence; flatten all whitespace for regex matching so
        # patterns like `For Q1 2026 was also 13.1%` work even when the source
        # broke the line between `Q1` and `2026`.
        page1_flat = _flatten(pages_text.get(1, ""))
        body_flat = _flatten("\n".join(pages_text.get(p, "") for p in sorted(pages_text) if p != 1))

        out = cls(narrative=narrative)
        _parse_publish_date_and_quarter(page1_flat, out)
        _parse_beat_rates(page1_flat, body_flat, out)
        _parse_blended_growth(page1_flat, body_flat, out)
        _parse_forward_growth(body_flat, out)
        _parse_forward_pe(page1_flat, body_flat, out)
        _parse_reaction(body_flat, out)
        _parse_guidance(page1_flat, out)
        _parse_sector_revisions(body_flat, out)
        return out

    def to_output(self) -> str:
        if not self.narrative and self.publish_date == "":
            return "(no FactSet data parsed)"
        lines: list[str] = []
        header = "## Earnings Season Pulse (FactSet Earnings Insight"
        if self.publish_date:
            header += f", {self.publish_date}"
        header += ")"
        lines.append(header)
        lines.append("")

        # Headline metrics
        if self.quarter_label:
            lines.append(f"**Quarter:** {self.quarter_label}")
        if self.pct_reported is not None:
            lines.append(f"**Reported:** {self.pct_reported:.0f}% of S&P 500 companies")

        beat_parts = []
        if self.eps_beat_rate is not None:
            avg = (
                f" (5y avg {self.eps_beat_5y_avg:.0f}%)" if self.eps_beat_5y_avg is not None else ""
            )
            beat_parts.append(f"EPS beat {self.eps_beat_rate:.0f}%{avg}")
        if self.rev_beat_rate is not None:
            avg = (
                f" (5y avg {self.rev_beat_5y_avg:.0f}%)" if self.rev_beat_5y_avg is not None else ""
            )
            beat_parts.append(f"Rev beat {self.rev_beat_rate:.0f}%{avg}")
        if beat_parts:
            lines.append(f"**Beat rates:** {' | '.join(beat_parts)}")

        if self.eps_surprise_pct is not None:
            avg = (
                f" (5y avg {self.eps_surprise_5y_avg:+.1f}%)"
                if self.eps_surprise_5y_avg is not None
                else ""
            )
            lines.append(f"**EPS surprise magnitude:** {self.eps_surprise_pct:+.1f}%{avg}")

        if self.blended_eps_growth is not None:
            qe = self.blended_eps_growth_quarter_end
            qe_part = (
                f" (vs +{qe:.1f}% at quarter-end → {self.blended_eps_growth - qe:+.1f}pp revision)"
                if qe is not None
                else ""
            )
            lines.append(f"**Blended EPS growth:** {self.blended_eps_growth:+.1f}% YoY{qe_part}")
        if self.blended_rev_growth is not None:
            lines.append(f"**Blended revenue growth:** {self.blended_rev_growth:+.1f}% YoY")

        # Forward growth
        if self.forward_q_growth and self.forward_q_labels:
            forward = " | ".join(
                f"{lbl} {val:+.1f}%"
                for lbl, val in zip(self.forward_q_labels, self.forward_q_growth, strict=False)
            )
            lines.append(f"**Forward quarterly EPS growth:** {forward}")
        if self.cy_growth:
            cy_parts = " | ".join(f"{lbl} {val:+.1f}%" for lbl, val in self.cy_growth.items())
            lines.append(f"**Forward annual EPS growth:** {cy_parts}")

        # Valuation
        if self.forward_pe is not None:
            avgs = []
            if self.forward_pe_5y_avg is not None:
                avgs.append(f"5y avg {self.forward_pe_5y_avg:.1f}")
            if self.forward_pe_10y_avg is not None:
                avgs.append(f"10y avg {self.forward_pe_10y_avg:.1f}")
            if self.forward_pe_quarter_end is not None:
                avgs.append(f"quarter-end {self.forward_pe_quarter_end:.1f}")
            avg_part = f" ({' | '.join(avgs)})" if avgs else ""
            asof_part = f" _(as of {self.forward_pe_as_of})_" if self.forward_pe_as_of else ""
            lines.append(f"**Forward 12M P/E:** {self.forward_pe:.1f}{avg_part}{asof_part}")

        # Reaction asymmetry
        if self.beat_reaction_pct is not None and self.miss_reaction_pct is not None:
            beat_avg = (
                f" (5y {self.beat_reaction_5y_avg:+.1f}%)"
                if self.beat_reaction_5y_avg is not None
                else ""
            )
            miss_avg = (
                f" (5y {self.miss_reaction_5y_avg:+.1f}%)"
                if self.miss_reaction_5y_avg is not None
                else ""
            )
            lines.append(
                f"**Reaction asymmetry:** beats {self.beat_reaction_pct:+.1f}%{beat_avg} | "
                f"misses {self.miss_reaction_pct:+.1f}%{miss_avg}"
            )

        # Guidance
        if self.guidance_positive is not None and self.guidance_negative is not None:
            lbl = f" for {self.guidance_quarter_label}" if self.guidance_quarter_label else ""
            lines.append(
                f"**Guidance{lbl}:** {self.guidance_positive} positive | "
                f"{self.guidance_negative} negative"
            )

        # Sector revisions
        if self.sector_revisions:
            lines.append("")
            lines.append("**Sector blended-growth revisions since quarter-end:**")
            ups = [r for r in self.sector_revisions if r.delta_pp > 0]
            downs = [r for r in self.sector_revisions if r.delta_pp < 0]
            ups.sort(key=lambda r: r.delta_pp, reverse=True)
            downs.sort(key=lambda r: r.delta_pp)
            for r in ups[:6]:
                lines.append(
                    f"  ↑ {r.name}: {r.quarter_end_pct:+.1f}% → {r.current_pct:+.1f}% "
                    f"({r.delta_pp:+.1f}pp)"
                )
            for r in downs[:6]:
                lines.append(
                    f"  ↓ {r.name}: {r.quarter_end_pct:+.1f}% → {r.current_pct:+.1f}% "
                    f"({r.delta_pp:+.1f}pp)"
                )

        # Raw narrative for LLM judgment
        if self.narrative:
            lines.append("")
            lines.append("=== Raw narrative (pages 1, 6-15) ===")
            lines.append(self.narrative)

        return "\n".join(lines)


# ---- Parsers (best-effort regex over narrative text) ---------------------


_NARRATIVE_PAGES = (1, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15)


def _flatten(text: str) -> str:
    """Collapse all whitespace runs (incl. newlines) to single spaces."""
    return re.sub(r"\s+", " ", text)


def _build_narrative(pages_text: dict[int, str]) -> str:
    chunks: list[str] = []
    for p in _NARRATIVE_PAGES:
        text = pages_text.get(p, "")
        if not text:
            continue
        # Strip boilerplate header/footer lines.
        cleaned: list[str] = []
        for ln in text.split("\n"):
            s = ln.strip()
            if not s:
                continue
            if s == "EARNINGS INSIGHT":
                continue
            if s.startswith("Copyright ©") and "FactSet" in s:
                continue
            if s.startswith("To receive this report") or s.startswith("To learn more"):
                continue
            cleaned.append(ln)
        if cleaned:
            chunks.append(f"--- Page {p} ---")
            chunks.append("\n".join(cleaned))
    return "\n\n".join(chunks)


def _parse_publish_date_and_quarter(page1: str, out: FactsetEarningsInsightResponse) -> None:
    # Publish date: a standalone "Month Day, Year" near the top.
    m = re.search(
        r"\b(?:January|February|March|April|May|June|July|August|"
        r"September|October|November|December)\s+\d{1,2},\s+\d{4}\b",
        page1,
    )
    if m:
        out.publish_date = m.group(0)
    # Quarter label, e.g. "Q1 2026"
    m = re.search(r"For (Q[1-4] \d{4})", page1)
    if m:
        out.quarter_label = m.group(1)


def _parse_beat_rates(page1: str, body: str, out: FactsetEarningsInsightResponse) -> None:
    text = page1 + "\n" + body
    # "(with 89% of S&P 500 companies reporting actual results)"
    m = re.search(r"with (\d{1,3})% of S&P 500 companies reporting actual results", text)
    if m:
        out.pct_reported = float(m.group(1))
    # "84% of S&P 500 companies have reported a positive EPS surprise"
    m = re.search(
        r"(\d{1,3})% of S&P 500 companies (?:have|has) reported a positive EPS surprise",
        text,
    )
    if m:
        out.eps_beat_rate = float(m.group(1))
    # "80% of S&P 500 companies has reported a positive revenue surprise"
    m = re.search(
        r"(\d{1,3})% of S&P 500 companies (?:have|has) reported a positive revenue surprise", text
    )
    if m:
        out.rev_beat_rate = float(m.group(1))
    # "above the 5-year average of 78%"  — the first occurrence after EPS beat narrative
    # We pin to the 5-year average in the EPS beat passage on page 6/7.
    m = re.search(
        r"above estimates,.{0,80}5-year average of (\d{1,3})%",
        text,
        re.DOTALL,
    )
    if m:
        out.eps_beat_5y_avg = float(m.group(1))
    # Revenue 5y avg: appears as either "5-year average of 70%" or
    # "5-year average (70%)" after the revenue beat narrative.
    m = re.search(
        r"reporting (?:actual )?revenues above (?:estimated revenues|estimates).{0,200}"
        r"5-year average (?:of |\()(\d{1,3})%\)?",
        text,
        re.DOTALL,
    )
    if m:
        out.rev_beat_5y_avg = float(m.group(1))
    # EPS surprise magnitude: "earnings that are 18.2% above"
    m = re.search(r"earnings that are ([+-]?\d+\.\d+)% above (?:expectations|estimates)", text)
    if m:
        out.eps_surprise_pct = float(m.group(1))
    # 5y avg surprise: appears as "above the 5-year average of +7.3%" in surprise context
    m = re.search(
        r"surprise percentage is above.{0,80}5-year average \(([+-]?\d+\.\d+)%\)",
        text,
        re.DOTALL,
    )
    if m:
        out.eps_surprise_5y_avg = float(m.group(1))


def _parse_blended_growth(page1: str, body: str, out: FactsetEarningsInsightResponse) -> None:
    text = page1 + "\n" + body
    # "the blended (year-over-year) earnings growth rate for the S&P 500 is 27.7%"
    m = re.search(
        r"blended \(year-over-year\) earnings growth rate for the S&P 500 is "
        r"([+-]?\d+\.\d+)%",
        text,
    )
    if m:
        out.blended_eps_growth = float(m.group(1))
    # estimated YoY EPS growth at quarter-end, e.g.
    # "...growth rate for the S&P 500 for Q1 2026 was also 13.1%"
    m = re.search(
        r"estimated \(year-over-year\) earnings growth rate for the S&P 500 "
        r"for Q[1-4] \d{4} was (?:also )?([+-]?\d+\.\d+)%",
        text,
    )
    if m:
        out.blended_eps_growth_quarter_end = float(m.group(1))
    # "the blended revenue growth rate for the first quarter is 11.3%"
    m = re.search(
        r"blended revenue growth rate for (?:the first|the second|the third|the fourth) "
        r"quarter is ([+-]?\d+\.\d+)%",
        text,
    )
    if m:
        out.blended_rev_growth = float(m.group(1))


def _parse_forward_growth(body: str, out: FactsetEarningsInsightResponse) -> None:
    # "For Q2 2026 through Q4 2026, analysts are calling for earnings growth rates of
    #  19.9%, 23.2%, and 20.7%, respectively."
    m = re.search(
        r"For (Q[1-4]) (\d{4}) through (Q[1-4]) (\d{4}), analysts are calling for "
        r"earnings growth rates of ([+-]?\d+\.\d+)%, ([+-]?\d+\.\d+)%, and "
        r"([+-]?\d+\.\d+)%",
        body,
    )
    if m:
        start_q = int(m.group(1)[1])
        start_y = int(m.group(2))
        out.forward_q_growth = [float(m.group(5)), float(m.group(6)), float(m.group(7))]
        labels: list[str] = []
        q = start_q
        y = start_y
        for _ in range(3):
            labels.append(f"Q{q} {y}")
            q += 1
            if q > 4:
                q = 1
                y += 1
        out.forward_q_labels = labels
    # CY growth: "For CY 2026, analysts are predicting (year-over-year) earnings growth of 21.0%"
    for cy_match in re.finditer(
        r"For (CY \d{4}), analysts are predicting \(year-over-year\) earnings growth of "
        r"([+-]?\d+\.\d+)%",
        body,
    ):
        out.cy_growth[cy_match.group(1)] = float(cy_match.group(2))


def _parse_forward_pe(page1: str, body: str, out: FactsetEarningsInsightResponse) -> None:
    text = page1 + "\n" + body
    # "The forward 12-month P/E ratio for the S&P 500 is 21.0"
    m = re.search(r"forward 12-month P/E ratio for the S&P 500 is (\d+\.\d+)", text)
    if m:
        out.forward_pe = float(m.group(1))
    # 5-year avg + 10-year avg appear in the same sentence
    m = re.search(
        r"5-year average \((\d+\.\d+)\).{0,80}10-year average \((\d+\.\d+)\)",
        text,
        re.DOTALL,
    )
    if m:
        out.forward_pe_5y_avg = float(m.group(1))
        out.forward_pe_10y_avg = float(m.group(2))
    # "above the forward P/E ratio of 19.7 recorded at the end of the first quarter"
    m = re.search(
        r"forward P/E ratio of (\d+\.\d+) recorded at the end of (?:the first|the second|"
        r"the third|the fourth) quarter",
        text,
    )
    if m:
        out.forward_pe_quarter_end = float(m.group(1))


def _parse_reaction(body: str, out: FactsetEarningsInsightResponse) -> None:
    # "have seen an average price increase of +1.1% two days before"
    m = re.search(
        r"reported positive earnings surprises for Q[1-4] \d{4} have seen an average "
        r"price increase of ([+-]?\d+\.\d+)%",
        body,
    )
    if m:
        out.beat_reaction_pct = float(m.group(1))
    # "above the 5-year average price increase of +1.0%"
    m = re.search(
        r"5-year average price increase of ([+-]?\d+\.\d+)% during this same window for "
        r"companies reporting positive earnings surprises",
        body,
    )
    if m:
        out.beat_reaction_5y_avg = float(m.group(1))
    # "have seen an average price decrease of -4.9%"
    m = re.search(
        r"reported negative earnings surprises for Q[1-4] \d{4} have seen an average "
        r"price decrease of ([+-]?\d+\.\d+)%",
        body,
    )
    if m:
        # Source phrases the number as positive after "decrease of"; coerce sign.
        v = float(m.group(1))
        out.miss_reaction_pct = -abs(v)
    m = re.search(
        r"5-year average price decrease of ([+-]?\d+\.\d+)% during this same window for "
        r"companies reporting negative earnings surprises",
        body,
    )
    if m:
        v = float(m.group(1))
        out.miss_reaction_5y_avg = -abs(v)


def _parse_guidance(page1: str, out: FactsetEarningsInsightResponse) -> None:
    # "For Q2 2026, 38 S&P 500 companies have issued negative EPS guidance and
    #  39 S&P 500 companies have issued positive EPS guidance."
    m = re.search(
        r"For (Q[1-4] \d{4}), (\d+) S&P 500 companies have issued negative EPS guidance "
        r"and (\d+) S&P 500 companies have issued positive EPS guidance",
        page1,
    )
    if m:
        out.guidance_quarter_label = m.group(1)
        out.guidance_negative = int(m.group(2))
        out.guidance_positive = int(m.group(3))


_SECTOR_NAMES = (
    "Communication Services",
    "Consumer Discretionary",
    "Consumer Staples",
    "Energy",
    "Financials",
    "Health Care",
    "Industrials",
    "Information Technology",
    "Materials",
    "Real Estate",
    "Utilities",
)


def _parse_sector_revisions(body: str, out: FactsetEarningsInsightResponse) -> None:
    # The revisions narrative uses two patterns:
    #   "the Communication Services (to 48.8% vs. -3.7%)"
    #   "to 39.7% from 1.7%" / "to 0.7% from 8.2%"
    seen: set[str] = set()
    for sector in _SECTOR_NAMES:
        # Pattern A: "(to 48.8% vs. -3.7%)"
        pat_a = re.compile(
            re.escape(sector) + r"\s*\(to ([+-]?\d+\.\d+)% (?:vs\.|from) ([+-]?\d+\.\d+)%\)"
        )
        m = pat_a.search(body)
        if m:
            current = float(m.group(1))
            qe = float(m.group(2))
            out.sector_revisions.append(SectorRevision(sector, qe, current))
            seen.add(sector)
            continue
        # Pattern B: "Communication Services sector decreased to 48.8% from 53.1%" — that's
        # a week-over-week note, not quarter-end. We skip those.
        # Pattern C: "blended earnings growth rate for the X sector has increased
        #   to 39.7% from 1.7% over this period."
        pat_c = re.compile(
            r"blended earnings growth rate for the "
            + re.escape(sector)
            + r" sector has (?:increased|decreased) to ([+-]?\d+\.\d+)% from "
            r"([+-]?\d+\.\d+)% over this period"
        )
        m = pat_c.search(body)
        if m:
            current = float(m.group(1))
            qe = float(m.group(2))
            out.sector_revisions.append(SectorRevision(sector, qe, current))
            seen.add(sector)


@dataclass
class FactsetEarningsInsightRequest:
    """Optional override of which Friday's PDF to fetch.

    If `as_of_date` is None, the client walks back from today to the most-recent
    Friday with a published PDF.
    """

    as_of_date: date | None = None
