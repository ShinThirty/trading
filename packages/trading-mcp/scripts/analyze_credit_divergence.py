#!/usr/bin/env python3
"""Measure the base rate of the 144A credit-breadth divergence.

The claim under test, from the alarm-window playbook: *144A high-yield breadth
turning negative while broad high yield holds up means the speculative funding
channel is cracking before the market at large.* 144A is where unrated and
speculative issuers place paper, so it should narrow first if funding is what
gives way.

That claim is unproven, and this script exists to stop the threshold from being
a number someone picked. It answers two separate questions:

  1. **How often does the pattern fire in a market that turns out fine?**
     Pure base rate. A signal that fires 30 times a year is noise no matter how
     good its story; one that fires twice is worth wiring to an alert.

  2. **Does firing precede credit widening?** Forward HY OAS change after each
     episode, against the unconditional distribution over the same window.

The stored history begins 2023-07-28 and **does** contain one real widening
episode — HY OAS ran 2.65% to 4.61% into 2025-04-07, roughly 200bp — so question
2 has at least one true positive to test against. It is still only one, which
is why the forward test reports per-episode detail and a hit rate against the
unconditional base rate rather than a mean: a single large hit sitting among
several non-events is invisible in an average, and an average is the wrong
summary for a tripwire that is meant to be rare, often wrong, and big when right.

The window also contains the Oct-2023 duration selloff, which doubles as a
control: the IG-negative / HY-positive signature should light up there, because
that episode was rates, not credit. If it doesn't, the discriminator is broken.

RESULT (first full run, 2026-08-14, 765 sessions) — **the signal does not clear
a promotion bar; do not wire it to an alert.**

  - Count-based version: 7 firings at the ≥4-session threshold, **0** followed
    by a ≥50bp widening inside 60d, against a 27% unconditional base rate.
    Lift 0.0x. It also missed the one real event: nothing fired at ≥4 before
    the April-2025 widening (a ≥3 run did fire 2025-03-17, 21 days ahead — but
    ≥3 is the threshold the false-positive criterion rejects, so picking it
    after seeing the answer would be fitting to one observation).
  - The reason is a **composition artifact**. The 144A universe grew 1,305 →
    1,604 bonds/day (+23%) while its 52-week-high rate fell to 3.06 per 100
    bonds in 2026 against a stable ~15.7 for the broad market. Newly issued
    bonds cannot print a 52-week high, so heavy 144A issuance mechanically
    depresses the leg the signal reads as distress. That inverts the meaning:
    it fires hardest when the speculative funding channel is *busiest*.
  - The A/D variant removes the artifact (firings spread 16/37/46/29 across
    years rather than clustering in 2026) but shows no edge either — best case
    35% hit rate vs 27% base on n=23, which is noise at that sample size.

Keep recording. Re-run when the sample contains a genuine credit cycle; one
widening episode cannot settle this either way.

Usage:
  uv run --package trading-mcp python packages/trading-mcp/scripts/analyze_credit_divergence.py
"""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass
from datetime import date
from statistics import mean, median

from trading_clients.config import load_config
from trading_clients.endpoints import finra, fred
from trading_clients.fred_client import FredClient
from trading_clients.table_helpers import md_table
from trading_mcp.db import open_db
from trading_mcp.db.credit_breadth import (
    UNIVERSE_144A,
    UNIVERSE_ALL,
    init_schema,
    select_grade_series,
)

HY_OAS_SERIES = "BAMLH0A0HYM2"
FORWARD_WINDOWS = (20, 60)
MAX_RUN = 10

# What "fires 2-3 times a year in a calm tape" translates to. Above this the
# alert is noise; the smallest run length that clears it is the threshold.
TARGET_FIRINGS_PER_YEAR = 3.0

# A HY OAS move worth calling a credit event. Roughly a quarter of the full
# peak-to-trough range in the stored window — big enough to matter for a
# financing-dependent thesis, small enough to give more than one sample.
MATERIAL_WIDENING_BP = 50.0


@dataclass
class Session:
    day: date
    broad_hy_net: int
    a144_hy_net: int
    broad_ig_net: int
    broad_hy_ad: float | None = None
    a144_hy_ad: float | None = None
    a144_bonds: int = 0
    a144_highs: int = 0

    @property
    def diverging(self) -> bool:
        """The claim as originally specified, on 52-week high/low counts.

        Carries a composition artifact — see `diverging_ad`.
        """
        return self.a144_hy_net < 0 <= self.broad_hy_net

    @property
    def diverging_ad(self) -> bool:
        """Same claim on advance/decline instead of 52-week extremes.

        A bond issued last month cannot print a 52-week high but can perfectly
        well advance, so A/D is immune to the seasoning artifact that heavy new
        issuance introduces into the count-based version.
        """
        if self.a144_hy_ad is None or self.broad_hy_ad is None:
            return False
        return self.a144_hy_ad < 1.0 <= self.broad_hy_ad

    @property
    def duration_signature(self) -> bool:
        """IG making net new lows while HY makes net new highs — rates, not credit."""
        return self.broad_ig_net < 0 <= self.broad_hy_net


def _net(row: dict) -> int:
    return int(row["fifty_two_week_high"]) - int(row["fifty_two_week_low"])


def _ad(row: dict) -> float | None:
    return row["advances"] / row["declines"] if row["declines"] else None


def _traded(row: dict) -> int:
    """Bonds that printed at all — the universe size proxy for this session."""
    return int(row["advances"]) + int(row["declines"]) + int(row["unchanged"])


async def load_sessions(conn) -> list[Session]:
    broad_hy = {
        r["trade_date"]: r
        for r in await select_grade_series(conn, UNIVERSE_ALL, finra.GRADE_HY, 10_000)
    }
    broad_ig = {
        r["trade_date"]: r
        for r in await select_grade_series(conn, UNIVERSE_ALL, finra.GRADE_IG, 10_000)
    }
    a144_hy = {
        r["trade_date"]: r
        for r in await select_grade_series(conn, UNIVERSE_144A, finra.GRADE_HY, 10_000)
    }
    common = sorted(set(broad_hy) & set(a144_hy) & set(broad_ig))
    return [
        Session(
            day=date.fromisoformat(d),
            broad_hy_net=_net(broad_hy[d]),
            a144_hy_net=_net(a144_hy[d]),
            broad_ig_net=_net(broad_ig[d]),
            broad_hy_ad=_ad(broad_hy[d]),
            a144_hy_ad=_ad(a144_hy[d]),
            a144_bonds=_traded(a144_hy[d]),
            a144_highs=int(a144_hy[d]["fifty_two_week_high"]),
        )
        for d in common
    ]


def runs(flags: list[bool]) -> list[tuple[int, int]]:
    """Consecutive True stretches as (start index, length)."""
    out: list[tuple[int, int]] = []
    i = 0
    while i < len(flags):
        if not flags[i]:
            i += 1
            continue
        j = i
        while j < len(flags) and flags[j]:
            j += 1
        out.append((i, j - i))
        i = j
    return out


async def load_hy_oas(limit: int = 1500) -> dict[date, float]:
    config = load_config()
    if config.fred is None:
        return {}
    client = FredClient(config.fred)
    try:
        resp = await client.get(
            fred.OBSERVATIONS, fred.GetObservationsRequest(HY_OAS_SERIES, limit)
        )
    finally:
        await client.close()
    out: dict[date, float] = {}
    for obs in resp.observations:
        raw = obs.get("value")
        if raw in (None, "", "."):
            continue
        try:
            out[date.fromisoformat(str(obs["date"]))] = float(raw)
        except (ValueError, KeyError):
            continue
    return out


def forward_change(oas: dict[date, float], days: list[date], i: int, horizon: int) -> float | None:
    """HY OAS change in bp from session i to `horizon` sessions later."""
    if i + horizon >= len(days):
        return None
    a, b = oas.get(days[i]), oas.get(days[i + horizon])
    if a is None or b is None:
        return None
    return (b - a) * 100.0


def peak_widening(oas: dict[date, float], days: list[date], i: int, horizon: int) -> float | None:
    """Largest HY OAS widening in bp reached at any point within the horizon.

    Endpoint-to-endpoint misses the case that matters most: a spread that blows
    out and then retraces inside the window shows up as roughly flat, even
    though it was a live credit event throughout.
    """
    if i >= len(days):
        return None
    start = oas.get(days[i])
    if start is None:
        return None
    ahead = [oas[d] for d in days[i : i + horizon + 1] if d in oas]
    if not ahead:
        return None
    return (max(ahead) - start) * 100.0


async def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.parse_args()

    conn = open_db()
    init_schema(conn)
    try:
        sessions = await load_sessions(conn)
    finally:
        conn.close()

    if len(sessions) < 60:
        print(
            f"Only {len(sessions)} sessions with both universes stored — "
            "run backfill_credit_breadth.py first."
        )
        return

    span_years = (sessions[-1].day - sessions[0].day).days / 365.25
    print(
        f"## Sample: {len(sessions)} sessions, {sessions[0].day} → {sessions[-1].day} "
        f"({span_years:.1f} years)\n"
    )

    # ── Control: does the duration signature show up where it should? ──
    dur = [s for s in sessions if s.duration_signature]
    print(
        f"**Control — IG-negative / HY-positive (duration, not credit):** "
        f"{len(dur)} of {len(sessions)} sessions ({len(dur) / len(sessions) * 100:.0f}%)."
    )
    by_year: dict[int, int] = {}
    for s in dur:
        by_year[s.day.year] = by_year.get(s.day.year, 0) + 1
    print("Per year: " + ", ".join(f"{y} {n}" for y, n in sorted(by_year.items())) + "\n")

    # ── Composition check: is the 52-week-high leg measuring issuance? ──
    # A bond issued this year cannot print a 52-week high. If the 144A universe
    # is growing, its high count falls for reasons that have nothing to do with
    # credit — and heavy 144A issuance is the *opposite* of a funding market
    # closing, so the signal would be reading backwards.
    print("### Composition check — is the 52-week-high leg tracking new issuance?\n")
    yearly: dict[int, list[Session]] = {}
    for s in sessions:
        yearly.setdefault(s.day.year, []).append(s)
    comp_rows = []
    for y, group in sorted(yearly.items()):
        bonds = mean(s.a144_bonds for s in group)
        highs = mean(s.a144_highs for s in group)
        comp_rows.append([str(y), f"{bonds:,.0f}", f"{highs:,.1f}", f"{highs / bonds * 100:.2f}"])
    print(
        md_table(
            ["Year", "144A bonds traded/day", "144A 52w highs/day", "Highs per 100 bonds"],
            comp_rows,
        )
    )
    print(
        "\n_A rising universe with a falling highs-per-100 rate is the artifact "
        "signature: more of the 144A pool is newly issued and structurally "
        "ineligible for a 52-week high. Compare the A/D variant below, which "
        "cannot be distorted this way._\n"
    )

    # ── Question 1: base rate of the 144A divergence ──
    flags = [s.diverging for s in sessions]
    fired = sum(flags)
    print(
        f"**144A HY negative while broad HY positive:** {fired} of {len(sessions)} "
        f"sessions ({fired / len(sessions) * 100:.1f}%), "
        f"{fired / span_years:.1f} per year on a single-session trigger.\n"
    )

    episodes = runs(flags)
    rows = []
    recommended: int | None = None
    for n in range(1, MAX_RUN + 1):
        qualifying = [e for e in episodes if e[1] >= n]
        per_year = len(qualifying) / span_years
        if recommended is None and per_year <= TARGET_FIRINGS_PER_YEAR:
            recommended = n
        rows.append(
            [
                f"≥{n}",
                str(len(qualifying)),
                f"{per_year:.1f}",
                "◄ threshold" if recommended == n else "",
            ]
        )
    print("### Firings by minimum consecutive-session run\n")
    print(md_table(["Run length", "Episodes", "Per year", ""], rows))
    print()

    if recommended is None:
        print(
            f"No run length up to {MAX_RUN} gets firings under "
            f"{TARGET_FIRINGS_PER_YEAR}/yr — the pattern is too common to alert on "
            "as specified; it needs a magnitude filter, not just persistence.\n"
        )
    else:
        print(
            f"**Threshold: {recommended} consecutive sessions** — fires "
            f"{len([e for e in episodes if e[1] >= recommended]) / span_years:.1f}x/yr "
            "in this sample.\n"
        )

    longest = sorted(episodes, key=lambda e: -e[1])[:5]
    if longest:
        print("### Longest episodes\n")
        print(
            md_table(
                ["Start", "End", "Sessions"],
                [
                    [
                        sessions[i].day.isoformat(),
                        sessions[i + ln - 1].day.isoformat(),
                        str(ln),
                    ]
                    for i, ln in longest
                ],
            )
        )
        print()

    # ── Question 2: does firing precede HY OAS widening? ──
    oas = await load_hy_oas()
    if not oas:
        print("_(FRED unavailable — skipping the forward HY OAS test.)_")
        return

    days = [s.day for s in sessions]
    n = recommended or 3
    starts = [i for i, ln in episodes if ln >= n]

    lo = min(oas.values())
    hi = max(oas.values())
    print(
        f"### Forward HY OAS after a ≥{n}-session firing\n\n"
        f"HY OAS over the window: {lo:.2f}% – {hi:.2f}% "
        f"(range {(hi - lo) * 100:.0f}bp), so this sample **does** contain a real "
        "widening episode to test against.\n"
    )

    # Per-episode, not just an average. One large hit buried among several
    # non-events is invisible in a mean but is exactly the shape a
    # regime tripwire is supposed to have — rare, wrong often, big when right.
    ep_rows = []
    for i in starts:
        cells = [days[i].isoformat()]
        for horizon in FORWARD_WINDOWS:
            c = forward_change(oas, days, i, horizon)
            cells.append(f"{c:+.0f}bp" if c is not None else "—")
        peak = peak_widening(oas, days, i, max(FORWARD_WINDOWS))
        cells.append(f"{peak:+.0f}bp" if peak is not None else "—")
        cells.append("◄ HIT" if peak is not None and peak >= MATERIAL_WIDENING_BP else "")
        ep_rows.append(cells)
    print(
        md_table(
            ["Firing date", *[f"{h}d Δ" for h in FORWARD_WINDOWS], "Peak widening", ""],
            ep_rows,
        )
    )
    print()

    # Hit rate against the unconditional rate: how often does *any* window see a
    # material widening? Without that denominator "1 of 7" means nothing.
    horizon = max(FORWARD_WINDOWS)
    cond_peaks = [p for i in starts if (p := peak_widening(oas, days, i, horizon)) is not None]
    uncond_peaks = [
        p for i in range(len(days)) if (p := peak_widening(oas, days, i, horizon)) is not None
    ]
    if cond_peaks and uncond_peaks:
        cond_hits = sum(1 for p in cond_peaks if p >= MATERIAL_WIDENING_BP)
        uncond_hits = sum(1 for p in uncond_peaks if p >= MATERIAL_WIDENING_BP)
        c_rate = cond_hits / len(cond_peaks) * 100
        u_rate = uncond_hits / len(uncond_peaks) * 100
        print(
            md_table(
                ["", "Firings", f"≥{MATERIAL_WIDENING_BP}bp within {horizon}d", "Rate"],
                [
                    ["After a firing", str(len(cond_peaks)), str(cond_hits), f"{c_rate:.0f}%"],
                    [
                        "Any session (base rate)",
                        str(len(uncond_peaks)),
                        str(uncond_hits),
                        f"{u_rate:.0f}%",
                    ],
                ],
            )
        )
        lift = c_rate / u_rate if u_rate else float("inf")
        print(
            f"\n**Lift: {lift:.1f}x** (median peak widening after a firing "
            f"{median(cond_peaks):+.0f}bp)."
        )
    print(
        f"\n_n={len(starts)} firings. Treat a positive lift as 'not yet falsified' "
        "rather than validation; treat a lift at or below 1.0x as the signal "
        "failing on the evidence available._"
    )

    # ── The artifact-free variant ──
    print("\n### Variant: A/D-based divergence (immune to the seasoning artifact)\n")
    ad_flags = [s.diverging_ad for s in sessions]
    ad_eps = runs(ad_flags)
    ad_by_year: dict[int, int] = {}
    for s, f in zip(sessions, ad_flags, strict=True):
        if f:
            ad_by_year[s.day.year] = ad_by_year.get(s.day.year, 0) + 1
    print(
        f"Fired {sum(ad_flags)} of {len(sessions)} sessions "
        f"({sum(ad_flags) / len(sessions) * 100:.1f}%). Per year: "
        + ", ".join(f"{y} {n}" for y, n in sorted(ad_by_year.items()))
        + "\n"
    )
    ad_rows = []
    for n in range(1, MAX_RUN + 1):
        q = [e for e in ad_eps if e[1] >= n]
        if not q:
            break
        starts_n = [i for i, ln in ad_eps if ln >= n]
        peaks = [p for i in starts_n if (p := peak_widening(oas, days, i, horizon)) is not None]
        hits = sum(1 for p in peaks if p >= MATERIAL_WIDENING_BP)
        rate = hits / len(peaks) * 100 if peaks else 0.0
        ad_rows.append(
            [
                f"≥{n}",
                str(len(q)),
                f"{len(q) / span_years:.1f}",
                str(hits),
                f"{rate:.0f}%" if peaks else "—",
                f"{rate / u_rate:.1f}x" if peaks and u_rate else "—",
            ]
        )
    print(
        md_table(
            ["Run", "Episodes", "Per year", "Hits", "Hit rate", "Lift vs base"],
            ad_rows,
        )
    )
    print(
        "\n_If this variant's firings spread evenly across years while the "
        "count-based version clusters in the heaviest-issuance year, the cluster "
        "was composition, not credit._"
    )


if __name__ == "__main__":
    asyncio.run(main())
