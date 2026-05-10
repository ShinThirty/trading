"""EIA Weekly Petroleum Status Report (WPSR) tool.

The WPSR publishes Wednesday 10:30 AM ET and is the single highest-frequency
read on the US oil/products complex: crude inventories (commercial + SPR),
refined-product stocks (gasoline / distillate / jet fuel), refinery
utilization, crude imports/exports, refiner crude input, and the EIA's
weekly retail gasoline pump price.

Built originally for the May 2026 Iran conflict — Hormuz at -93% transit
volume sustained over weeks, oil persistently $100+, and consumer demand
destruction starting to show up (McDonald's Q2 commentary, UK housing).
The WPSR closes the loop: are US inventories drawing to compensate for
disrupted imports? Is the SPR being tapped? Are refining margins / pump
prices passing through? That texture informs three concerns at once —
CPI energy read, consumer discretionary demand, and Fed policy path.

Single tool, single call: surfaces headline + crude + products + refinery +
8-week trend table. Skips interpretation; judgment happens in conversation.
"""

import asyncio

from fastmcp import Context, FastMCP
from trading_clients.endpoints import eia
from trading_clients.table_helpers import md_table

from trading_mcp.helpers import _eia, _exc_summary

mcp = FastMCP("eia-tools")

# Series catalog — curated for trading-relevant signal, not exhaustive.
# IDs follow EIA v2 /seriesid/ format: PET.<name>.<freq>. PET = petroleum
# dataset; .W = weekly. The bare WPSR series names (WCESTUS1 etc.) are not
# accepted by /seriesid/ — they need the dataset prefix and frequency suffix.
# All series are weekly and publish Wednesday 10:30 ET, EXCEPT retail
# gasoline (PET.EMM_EPMR_PTE_NUS_DPG.W) which publishes Monday afternoon.
#
# Stocks (units: thousand barrels — convert to million in display)
_STOCK_SERIES: list[tuple[str, str]] = [
    ("PET.WCESTUS1.W", "Crude oil (commercial, ex SPR)"),
    ("PET.WCSSTUS1.W", "Strategic Petroleum Reserve"),
    ("PET.WGTSTUS1.W", "Total motor gasoline"),
    ("PET.WDISTUS1.W", "Distillate fuel oil"),
    ("PET.WKJSTUS1.W", "Kerosene-type jet fuel"),
]
# Flow series (units: thousand barrels per day). Order matters — net-imports
# math below indexes positionally on imports[0] and exports[1].
_FLOW_SERIES: list[tuple[str, str]] = [
    ("PET.WCRIMUS2.W", "Crude imports"),
    ("PET.WCREXUS2.W", "Crude exports"),
    ("PET.WCRFPUS2.W", "US crude production"),
    ("PET.WCRRIUS2.W", "Refiner net crude input"),
]
# Refinery utilization (units: %)
_UTILIZATION_SERIES = ("PET.WPULEUS3.W", "Refinery utilization")
# Retail gasoline (units: $/gal). Long history — bump length so YoY is
# computable (52 weekly obs ≈ 1 year).
_RETAIL_GAS_SERIES = ("PET.EMM_EPMR_PTE_NUS_DPG.W", "US regular retail gasoline")


def _wow(values: list[float | None]) -> float | None:
    """Latest minus prior, when both are present."""
    if len(values) < 2 or values[0] is None or values[1] is None:
        return None
    return values[0] - values[1]


def _wow_pct(values: list[float | None]) -> float | None:
    if len(values) < 2 or values[0] is None or values[1] is None or values[1] == 0:
        return None
    return (values[0] - values[1]) / values[1] * 100


def _yoy_pct(values: list[float | None], weeks: int = 52) -> float | None:
    if len(values) <= weeks:
        return None
    cur = values[0]
    prior = values[weeks]
    if cur is None or prior is None or prior == 0:
        return None
    return (cur - prior) / prior * 100


def _values(resp: eia.EiaSeriesResponse | None) -> list[float | None]:
    if resp is None:
        return []
    return [p.value for p in resp.data]


def _latest_period(resp: eia.EiaSeriesResponse | None) -> str | None:
    if resp is None or not resp.data:
        return None
    return resp.data[0].period


def _kbbl_to_mbbl(v: float | None) -> float | None:
    """Stock series come in thousand barrels (kbbl). Convert to million (mbbl)
    so the headline reads 440.1 mbbl, not 440,100 kbbl."""
    return None if v is None else v / 1000.0


def _stock_line(label: str, vals: list[float | None]) -> str:
    cur = _kbbl_to_mbbl(vals[0]) if vals else None
    wow_kbbl = _wow(vals)
    wow = None if wow_kbbl is None else wow_kbbl / 1000.0
    pct = _wow_pct(vals)
    if cur is None:
        return f"  {label:42s}  (unavailable)"
    wow_str = f"WoW {wow:+.2f} mbbl" if wow is not None else "WoW —"
    pct_str = f" ({pct:+.2f}%)" if pct is not None else ""
    return f"  {label:42s}  {cur:>7.1f} mbbl   {wow_str}{pct_str}"


def _flow_line(label: str, vals: list[float | None]) -> str:
    cur = vals[0] if vals else None
    wow = _wow(vals)
    pct = _wow_pct(vals)
    if cur is None:
        return f"  {label:42s}  (unavailable)"
    # Flow units are kbbl/d; show as mbbl/d (divide by 1000) to match stocks.
    cur_m = cur / 1000.0
    wow_m = None if wow is None else wow / 1000.0
    wow_str = f"WoW {wow_m:+.3f} mbbl/d" if wow_m is not None else "WoW —"
    pct_str = f" ({pct:+.2f}%)" if pct is not None else ""
    return f"  {label:42s}  {cur_m:>7.3f} mbbl/d  {wow_str}{pct_str}"


def _format_trend(
    crude: eia.EiaSeriesResponse | None,
    gasoline: eia.EiaSeriesResponse | None,
    util: eia.EiaSeriesResponse | None,
    retail: eia.EiaSeriesResponse | None,
    weeks: int = 8,
) -> str:
    """8-week trend table. Each row is keyed by the WPSR week-ending date
    (Friday) — we index off the crude series since that's the canonical WPSR
    date. Retail gasoline publishes on a different cadence (Monday) so its
    column lines up by closest preceding row, with an em-dash if no point
    falls in the prior week."""
    if crude is None or not crude.data:
        return "(no data)"
    crude_pts = crude.data[:weeks]
    gas_by_period = {p.period: p.value for p in (gasoline.data if gasoline else [])}
    util_by_period = {p.period: p.value for p in (util.data if util else [])}
    # Retail is keyed off Monday-of-week; we won't match exact dates so just
    # walk it in parallel and use the most recent <= row date.
    retail_pts = list(retail.data) if retail else []

    rows: list[list[str]] = []
    for i, p in enumerate(crude_pts):
        crude_m = _kbbl_to_mbbl(p.value)
        gas_m = _kbbl_to_mbbl(gas_by_period.get(p.period))
        u = util_by_period.get(p.period)
        retail_v: float | None = None
        for rp in retail_pts:
            if rp.period <= p.period:
                retail_v = rp.value
                break
        rows.append(
            [
                p.period,
                f"{crude_m:.1f}" if crude_m is not None else "—",
                f"{gas_m:.1f}" if gas_m is not None else "—",
                f"{u:.1f}" if u is not None else "—",
                f"${retail_v:.3f}" if retail_v is not None else "—",
            ]
        )
        del i
    return md_table(
        ["Week ending", "Crude (mbbl)", "Gasoline (mbbl)", "Util (%)", "Pump ($/gal)"],
        rows,
    )


@mcp.tool()
async def get_eia_petroleum(ctx: Context) -> str:
    """Latest EIA Weekly Petroleum Status Report — US oil/products complex.

    Surfaces, in one call:
      - Headline week ending date (WPSR publishes Wednesday 10:30 ET)
      - Crude oil: commercial stocks (ex SPR) and SPR levels with WoW Δ
      - Crude flow: imports, exports, refiner net input (mbbl/d) with WoW Δ
      - Refined products: motor gasoline, distillate, jet fuel stocks with WoW Δ
      - Refinery utilization (%) with WoW Δ
      - Consumer pump: US regular retail gasoline ($/gal) with WoW + YoY Δ
      - 8-week trend table (crude, gasoline, utilization, pump)

    Use cadence: weekly on Wednesday afternoon for the prior week's print, or
    on demand when an oil/inflation thesis is in play (geopolitical disruption,
    SPR policy, refining outage, gasoline-led CPI surprise). The report
    informs three concerns at once: CPI energy read, consumer discretionary
    demand destruction, and Fed policy path on inflation persistence.

    Source: EIA Open Data API v2 (api.eia.gov). Requires [eia] api_key=... in
    ~/.tradingrc — free signup at https://www.eia.gov/opendata/register.php.
    """
    client = _eia(ctx)

    # Fetch every series we need in parallel. Length 20 covers 8w trend + WoW;
    # retail gasoline gets 60 so YoY is computable.
    stock_tasks = [client.get(eia.SERIES, eia.EiaSeriesRequest(sid)) for sid, _ in _STOCK_SERIES]
    flow_tasks = [client.get(eia.SERIES, eia.EiaSeriesRequest(sid)) for sid, _ in _FLOW_SERIES]
    util_task = client.get(eia.SERIES, eia.EiaSeriesRequest(_UTILIZATION_SERIES[0]))
    retail_task = client.get(eia.SERIES, eia.EiaSeriesRequest(_RETAIL_GAS_SERIES[0], length=60))

    results = await asyncio.gather(
        *stock_tasks,
        *flow_tasks,
        util_task,
        retail_task,
        return_exceptions=True,
    )

    warnings: list[str] = []

    def _ok(idx: int, label: str) -> eia.EiaSeriesResponse | None:
        r = results[idx]
        if isinstance(r, BaseException):
            warnings.append(_exc_summary(f"EIA {label}", r))
            return None
        return r  # type: ignore[return-value]

    n_stocks = len(_STOCK_SERIES)
    n_flows = len(_FLOW_SERIES)
    stock_responses = [_ok(i, _STOCK_SERIES[i][0]) for i in range(n_stocks)]
    flow_responses = [_ok(n_stocks + i, _FLOW_SERIES[i][0]) for i in range(n_flows)]
    util_response = _ok(n_stocks + n_flows, _UTILIZATION_SERIES[0])
    retail_response = _ok(n_stocks + n_flows + 1, _RETAIL_GAS_SERIES[0])

    # Headline period — anchor off the first stock series (crude). All WPSR
    # rows share the same week-ending date.
    headline_period = _latest_period(stock_responses[0]) or "?"

    out: list[str] = []
    if warnings:
        out.append("⚠ Data source warnings (some fetches failed):")
        for w in warnings:
            out.append(f"  • {w}")
        out.append("")

    out.append("=== Headline ===")
    out.append(f"WPSR week ending: {headline_period}")
    out.append("")

    out.append("=== Crude oil (stocks in million barrels, flows in mbbl/d) ===")
    for i, (_sid, label) in enumerate(_STOCK_SERIES[:2]):  # crude commercial + SPR
        out.append(_stock_line(label, _values(stock_responses[i])))
    for i, (_sid, label) in enumerate(_FLOW_SERIES):
        out.append(_flow_line(label, _values(flow_responses[i])))
    # Net imports for the trade-balance view.
    imp_vals = _values(flow_responses[0])
    exp_vals = _values(flow_responses[1])
    if imp_vals and exp_vals and imp_vals[0] is not None and exp_vals[0] is not None:
        net_now = (imp_vals[0] - exp_vals[0]) / 1000.0
        net_prior: float | None = None
        if len(imp_vals) > 1 and len(exp_vals) > 1:
            if imp_vals[1] is not None and exp_vals[1] is not None:
                net_prior = (imp_vals[1] - exp_vals[1]) / 1000.0
        wow_str = f"WoW {net_now - net_prior:+.3f} mbbl/d" if net_prior is not None else "WoW —"
        out.append(f"  {'Net crude imports (imp − exp)':42s}  {net_now:>7.3f} mbbl/d  {wow_str}")

    out.append("")
    out.append("=== Refined products (stocks in million barrels) ===")
    for i, (_sid, label) in enumerate(_STOCK_SERIES[2:], start=2):
        out.append(_stock_line(label, _values(stock_responses[i])))

    out.append("")
    out.append("=== Refinery ===")
    util_vals = _values(util_response)
    if util_vals and util_vals[0] is not None:
        wow_pp = _wow(util_vals)
        wow_str = f"WoW {wow_pp:+.2f} pp" if wow_pp is not None else "WoW —"
        out.append(f"  {'Refinery utilization':42s}  {util_vals[0]:>7.1f}%      {wow_str}")
    else:
        out.append(f"  {'Refinery utilization':42s}  (unavailable)")

    out.append("")
    out.append("=== Consumer pump ===")
    retail_vals = _values(retail_response)
    if retail_vals and retail_vals[0] is not None:
        wow = _wow(retail_vals)
        yoy = _yoy_pct(retail_vals)
        wow_str = f"WoW {wow:+.3f}" if wow is not None else "WoW —"
        yoy_str = f"YoY {yoy:+.2f}%" if yoy is not None else "YoY —"
        out.append(
            f"  {'US regular gasoline':42s}  ${retail_vals[0]:>6.3f}/gal  {wow_str}  {yoy_str}"
        )
    else:
        out.append(f"  {'US regular gasoline':42s}  (unavailable)")

    out.append("")
    out.append("=== 8-week trend ===")
    out.append("")
    out.append(
        _format_trend(
            stock_responses[0],  # crude
            stock_responses[2],  # gasoline
            util_response,
            retail_response,
        )
    )
    out.append("")
    out.append(
        "_Source: EIA Open Data API (api.eia.gov). Weekly Petroleum Status Report "
        "publishes Wednesday 10:30 ET; retail gasoline publishes Monday afternoon. "
        "Use this when an oil/inflation thesis is in play — informs CPI energy, "
        "consumer demand destruction, and Fed policy path simultaneously._"
    )

    return "\n".join(out)


__all__ = ["mcp", "get_eia_petroleum"]
