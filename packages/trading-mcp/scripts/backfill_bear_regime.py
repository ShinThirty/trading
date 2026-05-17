#!/usr/bin/env python3
"""One-shot backfill of the bear regime composite score against historical
bear-precursor episodes.

For each episode, walks weekly snapshots and scores the composite using
the same `regime.score_bear_*` and `regime.synthesize_bear_regime`
functions the live `get_bear_regime_score` MCP tool uses. Inputs are
historized — FRED observations, Tradier history, NAAIM XLSX,
SqueezeMetrics CSV, CFTC Socrata.

ERP/Valuation is omitted: FactSet Earnings Insight PDF is not historized
and reconstructing forward 12M P/E for 2007/2018/2020/2022 would require
a separate data project. The composite normalizes over available dims, so
the score is comparable across episodes even with one dim absent.

Sentiment uses NAAIM only (AAII / CBOE p/c not historized via current
clients) — single-source sentiment will almost always score Neutral,
which understates bear pressure in capitulation phases. Treat that as a
floor on the composite.

Dealer flow (DIX/GEX) is unavailable before 2011-05-02 (SqueezeMetrics
history start). The 2007/2008 GFC episode runs without that dimension.

Usage:
  uv run --package trading-mcp python packages/trading-mcp/scripts/backfill_bear_regime.py
  uv run --package trading-mcp python packages/trading-mcp/scripts/backfill_bear_regime.py \
      --episode 2018-q4
"""

from __future__ import annotations

import argparse
import asyncio
from bisect import bisect_right
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from statistics import mean, pstdev

from trading_clients import indicators as ta
from trading_clients import regime
from trading_clients.cftc_client import CftcClient
from trading_clients.config import load_config
from trading_clients.endpoints import cftc, fred, squeeze_metrics
from trading_clients.endpoints import tradier as t
from trading_clients.fred_client import FredClient
from trading_clients.naaim_client import NaaimClient
from trading_clients.squeeze_metrics_client import SqueezeMetricsClient
from trading_clients.tradier_client import TradierClient

# ─────────────────────────────────────────────────────────────────────
# Episode definitions
# ─────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Episode:
    key: str
    name: str
    walk_start: date
    peak: date
    bottom: date
    walk_end: date


EPISODES: dict[str, Episode] = {
    "2007": Episode(
        "2007",
        "2007 H2 / 2008 GFC",
        walk_start=date(2007, 6, 1),
        peak=date(2007, 10, 9),
        bottom=date(2009, 3, 9),
        walk_end=date(2008, 12, 31),
    ),
    "2018-q4": Episode(
        "2018-q4",
        "2018 Q4 correction",
        walk_start=date(2018, 6, 1),
        peak=date(2018, 9, 20),
        bottom=date(2018, 12, 24),
        walk_end=date(2019, 1, 31),
    ),
    "2020-q1": Episode(
        "2020-q1",
        "2020 COVID crash",
        walk_start=date(2019, 10, 1),
        peak=date(2020, 2, 19),
        bottom=date(2020, 3, 23),
        walk_end=date(2020, 5, 1),
    ),
    "2022-q1": Episode(
        "2022-q1",
        "2022 bear setup",
        walk_start=date(2021, 9, 1),
        peak=date(2022, 1, 3),
        bottom=date(2022, 10, 12),
        walk_end=date(2022, 7, 1),
    ),
}


# ─────────────────────────────────────────────────────────────────────
# Historized data containers (everything indexed by trade date)
# ─────────────────────────────────────────────────────────────────────


@dataclass
class DatedSeries:
    """Date-ordered (oldest-first) float series for slicing by as-of date."""

    dates: list[date] = field(default_factory=list)
    values: list[float] = field(default_factory=list)

    def slice_until(self, asof: date) -> tuple[list[date], list[float]]:
        """Return (dates, values) for all observations with date <= asof."""
        idx = bisect_right(self.dates, asof)
        return self.dates[:idx], self.values[:idx]

    def latest_until(self, asof: date) -> float | None:
        _, vals = self.slice_until(asof)
        return vals[-1] if vals else None


@dataclass
class DatedBars:
    """OHLCV daily bars for SPY/IWM/XLU/XLY/RSP/VIX, oldest-first."""

    dates: list[date] = field(default_factory=list)
    closes: list[float] = field(default_factory=list)
    volumes: list[float] = field(default_factory=list)

    def slice_until(self, asof: date) -> tuple[list[date], list[float], list[float]]:
        idx = bisect_right(self.dates, asof)
        return self.dates[:idx], self.closes[:idx], self.volumes[:idx]


@dataclass
class DatedDixRows:
    """SqueezeMetrics DIX/GEX rows, oldest-first."""

    dates: list[date] = field(default_factory=list)
    dix: list[float] = field(default_factory=list)
    gex: list[float] = field(default_factory=list)

    def slice_until(self, asof: date):
        idx = bisect_right(self.dates, asof)
        return self.dates[:idx], self.dix[:idx], self.gex[:idx]


@dataclass
class DatedCot:
    """COT records sorted oldest-first with parsed net positioning."""

    dates: list[date] = field(default_factory=list)
    nets: list[float] = field(default_factory=list)

    def z_score_until(self, asof: date) -> float | None:
        idx = bisect_right(self.dates, asof)
        sample = self.nets[max(0, idx - 53) : idx]
        if len(sample) < 8:
            return None
        mu = mean(sample)
        sd = pstdev(sample)
        if sd == 0:
            return None
        return (sample[-1] - mu) / sd


@dataclass
class BackfillInputs:
    """All historized inputs needed to score every snapshot in an episode."""

    spread: DatedSeries
    ff: DatedSeries
    credit: DatedSeries
    dgs2: DatedSeries
    dgs10: DatedSeries
    dgs30: DatedSeries
    vix: DatedSeries
    spy: DatedBars
    iwm: DatedBars
    xlu: DatedBars
    xly: DatedBars
    rsp: DatedBars | None  # None for episodes pre-2003-04
    naaim: DatedSeries
    dix: DatedDixRows | None  # None for episodes pre-2011-05
    cot: dict[str, DatedCot]


# ─────────────────────────────────────────────────────────────────────
# Fetch helpers
# ─────────────────────────────────────────────────────────────────────


def _parse_obs_to_series(obs: list[dict]) -> DatedSeries:
    pairs: list[tuple[date, float]] = []
    for o in obs:
        v = o.get("value", ".")
        if v == ".":
            continue
        try:
            d = datetime.strptime(o["date"], "%Y-%m-%d").date()
            pairs.append((d, float(v)))
        except (ValueError, KeyError, TypeError):
            continue
    pairs.sort(key=lambda p: p[0])
    return DatedSeries(
        dates=[p[0] for p in pairs],
        values=[p[1] for p in pairs],
    )


def _parse_tradier_bars(resp) -> DatedBars:
    if not resp or not resp.days:
        return DatedBars()
    pairs: list[tuple[date, float, float]] = []
    for bar in resp.days:
        try:
            d = datetime.strptime(bar["date"], "%Y-%m-%d").date()
            pairs.append((d, float(bar["close"]), float(bar.get("volume") or 0)))
        except (ValueError, KeyError, TypeError):
            continue
    pairs.sort(key=lambda p: p[0])
    return DatedBars(
        dates=[p[0] for p in pairs],
        closes=[p[1] for p in pairs],
        volumes=[p[2] for p in pairs],
    )


async def fetch_episode_inputs(
    fred_client: FredClient,
    tradier: TradierClient,
    naaim_client: NaaimClient,
    squeeze_client: SqueezeMetricsClient,
    cftc_client: CftcClient,
    episode: Episode,
) -> BackfillInputs:
    """Fetch ~2y of inputs ending at episode walk_end.

    Tradier history needs warmup for SMA200 + 53w COT z-scores. We pull
    from walk_start-300d through walk_end+5d.
    """
    fetch_start = episode.walk_start - timedelta(days=300)
    fetch_end = episode.walk_end + timedelta(days=5)
    start_str = fetch_start.isoformat()
    end_str = fetch_end.isoformat()

    rsp_supported = fetch_start >= date(2003, 4, 24)
    dix_supported = episode.walk_end >= date(2011, 5, 2)

    fred_tasks = [
        fred_client.get(fred.OBSERVATIONS, fred.GetObservationsRequest("T10Y2Y", limit=10000)),
        fred_client.get(fred.OBSERVATIONS, fred.GetObservationsRequest("FEDFUNDS", limit=10000)),
        fred_client.get(
            fred.OBSERVATIONS, fred.GetObservationsRequest("BAMLH0A0HYM2", limit=10000)
        ),
        fred_client.get(fred.OBSERVATIONS, fred.GetObservationsRequest("DGS2", limit=10000)),
        fred_client.get(fred.OBSERVATIONS, fred.GetObservationsRequest("DGS10", limit=10000)),
        fred_client.get(fred.OBSERVATIONS, fred.GetObservationsRequest("DGS30", limit=10000)),
        fred_client.get(fred.OBSERVATIONS, fred.GetObservationsRequest("VIXCLS", limit=10000)),
    ]
    tradier_tasks = [
        tradier.get(t.HISTORY, t.GetHistoryRequest("SPY", "daily", start=start_str, end=end_str)),
        tradier.get(t.HISTORY, t.GetHistoryRequest("IWM", "daily", start=start_str, end=end_str)),
        tradier.get(t.HISTORY, t.GetHistoryRequest("XLU", "daily", start=start_str, end=end_str)),
        tradier.get(t.HISTORY, t.GetHistoryRequest("XLY", "daily", start=start_str, end=end_str)),
    ]
    if rsp_supported:
        tradier_tasks.append(
            tradier.get(
                t.HISTORY, t.GetHistoryRequest("RSP", "daily", start=start_str, end=end_str)
            )
        )

    cftc_keys = list(cftc.CONTRACTS.keys())
    cftc_tasks = []
    for key in cftc_keys:
        report_key, pattern, _ = cftc.CONTRACTS[key]
        cftc_tasks.append(
            cftc_client.get(cftc.REPORTS[report_key], cftc.GetCotRequest(pattern, weeks=2000))
        )

    extra_tasks: list = [naaim_client.get_history()]
    if dix_supported:
        extra_tasks.append(
            squeeze_client.get(squeeze_metrics.DIX_HISTORY, squeeze_metrics.EmptyRequest())
        )

    all_tasks = fred_tasks + tradier_tasks + cftc_tasks + extra_tasks
    results = await asyncio.gather(*all_tasks, return_exceptions=True)

    def _ok(i: int):
        return results[i] if not isinstance(results[i], BaseException) else None

    spread = _parse_obs_to_series(_ok(0).observations if _ok(0) else [])
    ff = _parse_obs_to_series(_ok(1).observations if _ok(1) else [])
    credit = _parse_obs_to_series(_ok(2).observations if _ok(2) else [])
    dgs2 = _parse_obs_to_series(_ok(3).observations if _ok(3) else [])
    dgs10 = _parse_obs_to_series(_ok(4).observations if _ok(4) else [])
    dgs30 = _parse_obs_to_series(_ok(5).observations if _ok(5) else [])
    vix = _parse_obs_to_series(_ok(6).observations if _ok(6) else [])

    tradier_offset = len(fred_tasks)
    spy = _parse_tradier_bars(_ok(tradier_offset))
    iwm = _parse_tradier_bars(_ok(tradier_offset + 1))
    xlu = _parse_tradier_bars(_ok(tradier_offset + 2))
    xly = _parse_tradier_bars(_ok(tradier_offset + 3))
    rsp: DatedBars | None = None
    if rsp_supported:
        rsp = _parse_tradier_bars(_ok(tradier_offset + 4))

    cftc_offset = tradier_offset + len(tradier_tasks)
    cot: dict[str, DatedCot] = {}
    for i, key in enumerate(cftc_keys):
        resp = _ok(cftc_offset + i)
        if resp is None:
            continue
        pairs: list[tuple[date, float]] = []
        for rec in resp.weekly:
            raw_date = rec.get("report_date_as_yyyy_mm_dd", "")[:10]
            try:
                d = datetime.strptime(raw_date, "%Y-%m-%d").date()
            except (ValueError, TypeError):
                continue
            # _spec_net is a module-private helper in endpoints.cftc
            from trading_clients.endpoints.cftc import _spec_net

            n = _spec_net(rec)
            if n is None:
                continue
            pairs.append((d, n))
        pairs.sort(key=lambda p: p[0])
        cot[key] = DatedCot(
            dates=[p[0] for p in pairs],
            nets=[p[1] for p in pairs],
        )

    extras_offset = cftc_offset + len(cftc_tasks)
    naaim_resp = _ok(extras_offset)
    naaim = DatedSeries()
    if naaim_resp is not None:
        pairs = sorted(
            ((e.week_ending, e.exposure) for e in naaim_resp.entries), key=lambda p: p[0]
        )
        naaim = DatedSeries(
            dates=[p[0] for p in pairs],
            values=[p[1] for p in pairs],
        )

    dix: DatedDixRows | None = None
    if dix_supported:
        dix_resp = _ok(extras_offset + 1)
        if dix_resp is not None and dix_resp.rows:
            pairs3 = sorted(((r.date, r.dix, r.gex) for r in dix_resp.rows), key=lambda p: p[0])
            dix = DatedDixRows(
                dates=[p[0] for p in pairs3],
                dix=[p[1] for p in pairs3],
                gex=[p[2] for p in pairs3],
            )

    return BackfillInputs(
        spread=spread,
        ff=ff,
        credit=credit,
        dgs2=dgs2,
        dgs10=dgs10,
        dgs30=dgs30,
        vix=vix,
        spy=spy,
        iwm=iwm,
        xlu=xlu,
        xly=xly,
        rsp=rsp,
        naaim=naaim,
        dix=dix,
        cot=cot,
    )


# ─────────────────────────────────────────────────────────────────────
# Per-snapshot scoring
# ─────────────────────────────────────────────────────────────────────


def _curve_4w_change(series: DatedSeries, asof: date) -> float | None:
    """Match production: 4-week (20 business day) percent-point change."""
    dates, values = series.slice_until(asof)
    if len(values) < 21:
        return None
    return (values[-1] - values[-21]) * 100


def _detect_uninversion(spread: DatedSeries, ff: DatedSeries, asof: date) -> str | None:
    dates, values = spread.slice_until(asof)
    if not values:
        return None
    spread_val = values[-1]
    ff_dates, ff_values = ff.slice_until(asof)
    ff_val = ff_values[-1] if ff_values else None
    prev_ff = ff_values[-2] if len(ff_values) > 1 else None
    return regime.detect_uninversion_trap(values, spread_val, ff_val, prev_ff)


def score_snapshot(inputs: BackfillInputs, asof: date) -> tuple[float, str, list]:
    """Score the composite for one as-of date. Returns (score, tier, components)."""
    components: list[regime.BearScoreComponent] = []

    # Curve
    curve_label: str | None = None
    if inputs.dgs2.values or inputs.dgs10.values or inputs.dgs30.values:
        curve_label, _ = regime.classify_curve_regime(
            _curve_4w_change(inputs.dgs2, asof),
            _curve_4w_change(inputs.dgs10, asof),
            _curve_4w_change(inputs.dgs30, asof),
        )
    spread_dates, spread_values = inputs.spread.slice_until(asof)
    uninversion = _detect_uninversion(inputs.spread, inputs.ff, asof)
    components.append(regime.score_bear_curve(curve_label, uninversion, spread_values))

    # Valuation — not historized
    components.append(
        regime.BearScoreComponent(
            "Valuation (ERP)", 0.0, "Unknown", "FactSet PDF not historized", False
        )
    )

    # Credit
    credit_dates, credit_values = inputs.credit.slice_until(asof)
    current_credit = credit_values[-1] if credit_values else None
    # detect_credit_trap expects newest-first 30d history
    credit_history_newest_first = list(reversed(credit_values[-30:]))
    credit_trap = regime.detect_credit_trap(current_credit, credit_history_newest_first)
    components.append(
        regime.score_bear_credit(current_credit, credit_history_newest_first, credit_trap)
    )

    # Positioning (COT)
    contract_zs: dict[str, float | None] = {}
    for key, dc in inputs.cot.items():
        contract_zs[key] = dc.z_score_until(asof)
    positioning_label: str | None = None
    if any(z is not None for z in contract_zs.values()):
        positioning_label, _ = regime.classify_positioning(contract_zs)
    components.append(regime.score_bear_positioning(positioning_label))

    # Sentiment (NAAIM-only)
    naaim_val = inputs.naaim.latest_until(asof)
    sentiment_label: str | None = None
    if naaim_val is not None:
        sentiment_label, _ = regime.classify_sentiment(None, naaim_val, None)
    components.append(regime.score_bear_sentiment(sentiment_label))

    # Volatility
    vix_val = inputs.vix.latest_until(asof)
    _, vix_history_oldest_first = inputs.vix.slice_until(asof)
    components.append(regime.score_bear_volatility(vix_val, None, vix_history_oldest_first))

    # Technicals
    spy_dates, spy_closes, spy_volumes = inputs.spy.slice_until(asof)
    spy_rsi: float | None = None
    sma200: float | None = None
    if spy_closes:
        rsi_vals = ta.rsi(spy_closes)
        sma200_vals = ta.sma(spy_closes, 200)
        if rsi_vals:
            spy_rsi = rsi_vals[-1]
        if sma200_vals:
            sma200 = sma200_vals[-1]
    components.append(regime.score_bear_technicals(spy_closes, spy_volumes, spy_rsi, sma200))

    # Breadth
    _, iwm_closes, _ = inputs.iwm.slice_until(asof)
    _, xlu_closes, _ = inputs.xlu.slice_until(asof)
    _, xly_closes, _ = inputs.xly.slice_until(asof)
    rsp_closes: list[float] | None = None
    if inputs.rsp is not None:
        _, rsp_closes_full, _ = inputs.rsp.slice_until(asof)
        rsp_closes = rsp_closes_full or None
    breadth_label: str | None = None
    breadth_detail: str | None = None
    if spy_closes and iwm_closes and xlu_closes and xly_closes:
        breadth_label, breadth_detail = regime.classify_breadth(
            spy_closes,
            iwm_closes,
            spy_volumes,
            xlu_closes,
            xly_closes,
            rsp_closes=rsp_closes,
        )
    components.append(regime.score_bear_breadth(breadth_label, breadth_detail))

    # Dealer flow
    if inputs.dix is None:
        components.append(
            regime.BearScoreComponent(
                "Dealer Flow (DIX/GEX)", 0.0, "Unknown", "pre-2011 — no SqueezeMetrics", False
            )
        )
    else:
        ddates, dvals, gvals = inputs.dix.slice_until(asof)
        current_dix = dvals[-1] if dvals else None
        current_gex = gvals[-1] if gvals else None
        gex_history = gvals[-252:] if gvals else []
        components.append(regime.score_bear_dealer_flow(current_dix, current_gex, gex_history))

    composite, tier, top, _missing = regime.synthesize_bear_regime(components)
    return composite, tier, top


# ─────────────────────────────────────────────────────────────────────
# Walk + output
# ─────────────────────────────────────────────────────────────────────


def weekly_snapshots(start: date, end: date) -> list[date]:
    out: list[date] = []
    cur = start
    while cur <= end:
        out.append(cur)
        cur += timedelta(days=7)
    return out


def walk_episode(episode: Episode, inputs: BackfillInputs) -> list[tuple[date, float, str, list]]:
    rows = []
    for asof in weekly_snapshots(episode.walk_start, episode.walk_end):
        score, tier, top = score_snapshot(inputs, asof)
        rows.append((asof, score, tier, top))
    return rows


TIER_ORDER = {"Clear": 0, "Watchful": 1, "Building": 2, "Defensive": 3, "Crisis": 4}


def _base_tier(tier: str) -> str:
    return tier.split(" (")[0]


def find_tier_crossings(rows: list[tuple[date, float, str, list]]) -> dict[str, date]:
    """First date each tier was reached during the walk."""
    seen: dict[str, date] = {}
    for asof, _score, tier, _top in rows:
        base = _base_tier(tier)
        if base not in seen and base in TIER_ORDER:
            seen[base] = asof
    return seen


def format_episode_report(episode: Episode, rows: list[tuple[date, float, str, list]]) -> str:
    lines = [
        f"## {episode.name}",
        "",
        f"- Walk window: {episode.walk_start} → {episode.walk_end}",
        f"- Peak: {episode.peak} | Bottom: {episode.bottom}",
        "",
        "| Date       | Score | Tier      | Top contributors |",
        "|------------|-------|-----------|-------------------|",
    ]
    for asof, score, tier, top in rows:
        if top:
            contrib = ", ".join(f"{c.name} {c.score:.1f}" for c in top[:3])
        else:
            contrib = "(none)"
        lines.append(f"| {asof.isoformat()} | {score:4.1f}  | {tier:<9} | {contrib} |")

    crossings = find_tier_crossings(rows)
    lines.extend(["", "**Tier crossings:**"])
    for tier in ("Watchful", "Building", "Defensive", "Crisis"):
        if tier in crossings:
            d = crossings[tier]
            lead_to_bottom = (episode.bottom - d).days
            lead_to_peak = (episode.peak - d).days
            if lead_to_peak >= 0:
                ctx = f"{lead_to_peak}d before peak, {lead_to_bottom}d before bottom"
            elif lead_to_bottom >= 0:
                ctx = f"{abs(lead_to_peak)}d after peak, {lead_to_bottom}d before bottom"
            else:
                ctx = f"{abs(lead_to_peak)}d after peak, {abs(lead_to_bottom)}d after bottom"
            lines.append(f"- **{tier}** first reached {d} ({ctx})")
        else:
            lines.append(f"- **{tier}** not reached during walk")
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────
# Driver
# ─────────────────────────────────────────────────────────────────────


async def run_episodes(episode_keys: list[str]) -> None:
    cfg = load_config()
    if not cfg.fred or not cfg.tradier:
        raise SystemExit("Need [fred] and [tradier] sections in ~/.tradingrc")

    fred_client = FredClient(cfg.fred)
    tradier = TradierClient(cfg.tradier)
    naaim_client = NaaimClient()
    squeeze_client = SqueezeMetricsClient()
    cftc_client = CftcClient()

    try:
        outputs = ["# Bear Regime Score — Historical Backfill", ""]
        outputs.append(
            "Composite score across 7-8 dimensions (ERP omitted: FactSet not historized;"
        )
        outputs.append("Sentiment NAAIM-only; DIX/GEX missing pre-2011).")
        outputs.append("")
        for key in episode_keys:
            episode = EPISODES[key]
            print(f"[fetch] {episode.name} ...", flush=True)
            inputs = await fetch_episode_inputs(
                fred_client, tradier, naaim_client, squeeze_client, cftc_client, episode
            )
            print(f"[walk] {episode.name} ...", flush=True)
            rows = walk_episode(episode, inputs)
            outputs.append(format_episode_report(episode, rows))
            outputs.append("")
        print("\n".join(outputs))
    finally:
        for client in (fred_client, tradier, naaim_client, squeeze_client, cftc_client):
            close = getattr(client, "close", None)
            if close is None:
                continue
            try:
                result = close()
                if asyncio.iscoroutine(result):
                    await result
            except Exception:  # noqa: BLE001
                pass


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--episode",
        choices=list(EPISODES.keys()) + ["all"],
        default="all",
        help="Episode to backfill (default: all)",
    )
    args = parser.parse_args()
    keys = list(EPISODES.keys()) if args.episode == "all" else [args.episode]
    asyncio.run(run_episodes(keys))


if __name__ == "__main__":
    main()
