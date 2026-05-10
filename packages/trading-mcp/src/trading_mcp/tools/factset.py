"""FactSet Earnings Insight tool — weekly S&P 500 earnings season pulse.

FactSet publishes the Earnings Insight PDF every Friday afternoon ET. It's
the institutional benchmark for "what is earnings season actually saying" —
S&P 500 aggregate beat rates, surprise magnitudes, blended growth (current +
forward quarters + CY), forward 12M P/E with 5y/10y context, and sector-level
revision direction since quarter-end.

The tool surfaces the structured headline metrics + the raw narrative pages
1 and 6-15 from the PDF so the user can read FactSet's own commentary
verbatim — that's the load-bearing piece for judgment.

This is the closest thing we have to a single, authoritative read on
earnings-season tone. Use at biweekly review cadence; daily polling is wasted
since the PDF refreshes only on Fridays.
"""

from fastmcp import Context, FastMCP

from trading_mcp.helpers import _factset

mcp = FastMCP("factset-tools")


@mcp.tool()
async def get_earnings_season_pulse(ctx: Context) -> str:
    """Get the FactSet Earnings Insight summary — S&P 500 earnings season pulse.

    Surfaces in one read:
      - **Beat rate texture**: % of S&P 500 reported, % beating EPS / revenue,
        with 5-year averages for context.
      - **Surprise magnitude**: aggregate EPS surprise % vs 5y average — late-
        cycle markets often see large magnitudes that aren't being rewarded.
      - **Blended growth**: current-quarter EPS + revenue growth, plus the
        delta vs the quarter-end estimate (revisions to date).
      - **Forward growth**: next 3 quarters of EPS growth + CY estimates —
        the most-watched forward number.
      - **Forward 12M P/E**: current vs 5y avg, 10y avg, and quarter-end —
        valuation regime placement.
      - **Reaction asymmetry**: average ±2-day stock reaction for beats vs
        misses, with 5y baseline. Misses being punished much more than
        average is a late-cycle "no margin for error" signal.
      - **Guidance counts**: positive vs negative EPS guidance for next
        quarter — forward sentiment from companies themselves.
      - **Sector revisions**: which sectors moved blended growth up or down
        since quarter-end, ranked by magnitude. Identifies where surprise
        positive (or negative) flows concentrated.
      - **Raw narrative**: pages 1 + 6-15 of the FactSet PDF concatenated
        for readers who want the full commentary.

    The tool walks back from today to the most-recent Friday with a live PDF
    (up to 4 weeks back to handle holidays / late publishes). Cached 6h.

    Best fit at biweekly review cadence — daily calls add nothing since the
    PDF only refreshes on Fridays.
    """
    client = _factset(ctx)
    resp = await client.get_earnings_insight()
    return resp.to_output()


__all__ = ["mcp", "get_earnings_season_pulse"]
