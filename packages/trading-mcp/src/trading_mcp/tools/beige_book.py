"""Federal Reserve Beige Book tool.

Surfaces the National Summary (Overall Activity / Labor / Prices) plus the
12 short district highlights from the most recent Beige Book release. Designed
for the biweekly review cadence — the Beige Book publishes 8x/year, ~2 weeks
before each FOMC, so over a typical biweekly window there is at most one new
release worth reading. The tool also exposes the prior release for delta
reads when language has visibly shifted.
"""

from fastmcp import Context, FastMCP
from trading_clients.endpoints import beige_book

from trading_mcp.helpers import _beige_book

mcp = FastMCP("beige-book-tools")


@mcp.tool()
async def get_beige_book(ctx: Context, release: str = "latest") -> str:
    """Get the latest (or prior) Beige Book National Summary + district highlights.

    release: "latest" (default) returns the most recent published release.
        "prior" returns the immediately-preceding release — useful for reading
        the change in tone (Fed staff make small but deliberate language
        shifts: "modest" → "slight" → "flat" → "declining").

    Returns a markdown document with:
      - Period header (e.g. "Beige Book — February 2026") + which Reserve Bank
        prepared it and the information cutoff date.
      - National Summary: three paragraphs (Overall Economic Activity,
        Labor Markets, Prices) — the headline read on the broad economy.
      - District Highlights: one paragraph per Federal Reserve District
        (12 lines) — surfaces regional divergence (e.g. Dallas energy vs
        San Francisco tech layoffs).

    The Beige Book is published 8 times per year, ~2 weeks before each FOMC
    meeting. It is qualitative — there are no numbers — but it captures
    on-the-ground commentary from business contacts and is read closely by
    Fed officials before each decision. Useful for the biweekly review:
    detect tone shifts ("modest growth" → "flat") that lead the hard data.
    """
    if release not in ("latest", "prior"):
        return "release must be 'latest' or 'prior'"

    client = _beige_book(ctx)
    index = await client.get(beige_book.INDEX, beige_book.EmptyRequest())

    period = index.latest() if release == "latest" else index.prior()
    if period is None:
        return f"No {release} Beige Book release found in index."

    summary = await client.get(beige_book.SUMMARY, beige_book.SummaryRequest(period))
    # The response_model parser only sees HTML, not the period token from the
    # request — patch it in so the rendered output identifies the release.
    summary.period_token = period

    if not summary.overall and not summary.districts:
        return f"Beige Book {period}: parser found no content"

    header = f"## Beige Book — {summary.period_label}"
    meta_bits: list[str] = []
    if summary.prepared_by:
        meta_bits.append(f"Prepared at {summary.prepared_by}")
    if summary.information_cutoff:
        meta_bits.append(f"information as of {summary.information_cutoff}")
    meta_bits.append(f"period token `{summary.period_token}`")
    meta = "_" + " · ".join(meta_bits) + "._"

    out = [header, "", meta, "", "### National Summary", ""]
    out.append(f"**Overall Economic Activity.** {summary.overall or '(missing)'}")
    out.append("")
    out.append(f"**Labor Markets.** {summary.labor or '(missing)'}")
    out.append("")
    out.append(f"**Prices.** {summary.prices or '(missing)'}")
    out.append("")
    if summary.districts:
        out.append("### District Highlights")
        out.append("")
        for name, text in summary.districts:
            out.append(f"- **{name}.** {text}")
    return "\n".join(out)


__all__ = ["mcp", "get_beige_book"]
