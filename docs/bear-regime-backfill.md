# Bear Regime Score — Historical Backfill

Validation of the `get_bear_regime_score` composite (v1 weights) against
four historical bear-precursor episodes: 2007 H2 / 2008 GFC, 2018 Q4
correction, 2020 COVID crash, 2022 H1 bear setup.

Script: `packages/trading-mcp/scripts/backfill_bear_regime.py` (one-shot,
not a recurring tool). Run with `--episode <key>` for one or `--episode all`.

## Methodology

For each episode, the script fetches ~2 years of historized inputs ending
at episode close, then walks weekly snapshots from before the peak through
after the bottom. At every as-of date it slices each series to data ≤ that
date and calls the same `regime.score_bear_*` and `synthesize_bear_regime`
functions the live MCP tool uses.

The composite normalizes over available dimensions (missing dims drop out
of both numerator and denominator). When coverage falls below 60%, the
tier label is suffixed `(incomplete data — N/9 dimensions)`.

## Data coverage per episode

| Episode | Available dims | Missing |
|---------|----------------|---------|
| 2018 Q4 | 8/9 (89%) | Valuation (ERP) |
| 2020 Q1 | 8/9 (89%) | Valuation (ERP) |
| 2022 Q1 | 8/9 (89%) | Valuation (ERP) |
| 2007 H2 | 5/9 (56%) | Valuation, Credit (HY OAS), Breadth, Dealer Flow |

Data gaps discovered during the backfill:

- **Valuation (ERP)** — FactSet Earnings Insight PDF is current-only; no
  forward 12M P/E history. Permanent gap until a substitute series (e.g.
  Bloomberg ESTIMATES or a Damodaran reconstruction) is wired in.
- **Credit (HY OAS)** — FRED rotated `BAMLH0A0HYM2` to a 3-year rolling
  window in April 2026 ("Starting in April 2026, this series will only
  include 3 years of observations. For more data, go to the source.").
  Pre-2023 HY OAS history is no longer fetchable via FRED. The 2018/2020/2022
  episodes also lose this dim in current backfill runs.

  > ⚠ This is a permanent platform issue. The live `get_bear_regime_score`
  > tool still works (HY OAS is current-day-to-3-years-ago, which covers
  > all the rolling history the credit-trap detector needs), but historical
  > validation of the Credit dim requires a different data source.

- **Breadth** — Tradier history for XLY begins 2015-01-02; pre-2015 fetches
  return zero bars. SPY/IWM/XLU/RSP all go back further but the
  `classify_breadth` 4-ETF requirement gates the dim off.
- **Dealer Flow (DIX/GEX)** — SqueezeMetrics public CSV starts 2011-05-02.

- **Sentiment** — NAAIM-only in backfill (AAII / CBOE p/c aren't historized
  via current clients). NAAIM-only means the `classify_sentiment` "2+ extreme
  sources required" rule almost always returns Neutral, so the dim
  effectively scores Safe across backfill. Live tool is healthier here
  because AAII + CBOE p/c via Playwright fill in.

## Tier-crossing summary

Crossings shown at v1 thresholds in effect when this run was captured
(Crisis was 8.0; lowered to 7.0 on 2026-05-16). Crisis "never" entries
remain accurate at the new 7.0 threshold for this backfill — peak scores
were 6.0 (2008) and 6.4 (2020), still under 7.0 without ERP.

| Episode | Watchful | Building | Defensive | Crisis | Peak | Bottom |
|---------|----------|----------|-----------|--------|------|--------|
| 2007 H2 | 2007-06-22 (-109d peak) | 2007-08-03 (-67d peak) | 2008-01-18 (+101d peak, -416d bottom) | never | 2007-10-09 | 2009-03-09 |
| 2018 Q4 | 2018-08-03 (-48d peak) | 2018-10-12 (+22d peak, -73d bottom) | never | never | 2018-09-20 | 2018-12-24 |
| 2020 Q1 | 2019-10-08 (-134d peak) | 2020-03-03 (+13d peak, -20d bottom) | 2020-03-17 (+27d peak, -6d bottom) | never | 2020-02-19 | 2020-03-23 |
| 2022 Q1 | 2021-09-01 (-124d peak) | 2022-01-05 (+2d peak, -280d bottom) | never | never | 2022-01-03 | 2022-10-12 |

## Calibration findings

### What works

**Building tier is the actionable signal.** Across all four episodes,
Building (≥4.0) fired within 3 weeks of the peak (or earlier in 2007 GFC)
and gave 20-280 days of lead time to the eventual bottom. The current
playbook gating "Building = pause new entries in high-multiple names"
matches what the backfill suggests: it's far enough out to act on, close
enough that the regime change is real.

**Watchful tier is genuine but whipsawy.** Watchful (≥2.0) fires in normal
periods too (e.g. multiple Clear→Watchful→Clear oscillations in mid-2019
and mid-2018) without a bear following. The playbook's "Watchful = verify
tail hedge sized, prefer CCs on extended winners" gate is appropriately
soft — Watchful is a "stay alert" signal, not an action trigger. The 1-week
persistence rule (from the playbook's "When to override" section)
is validated by the whipsaw count.

**Top contributors are consistent.** Across all four episodes the dimensions
that did the most work were:
1. Technicals (SPY) — fires once trend breaks, persists through the move
2. Curve — fires sustained periods (2007 inverted ~14 months; 2022 inverted Q2+)
3. Breadth — intermittent but punchy when it fires
4. Volatility (VIX) — fires at the panic moments only

### What needs tuning

**Crisis tier (originally ≥8.0) was unreachable. Lowered to ≥7.0 on
2026-05-16.** Never crossed at 8.0 in any episode, including at the 2008
panic lows (peak score 6.0) and the 2020 COVID trough (peak score 6.4).
With v1 weights and v1 coverage, 8.0 is unreachable. Two reasons:

1. The composite is normalized over available dims; even when 4-5 dims
   are Risk (1.0) simultaneously, the other dims at Safe (0.0) pull the
   normalized average down. To hit 8.0 you'd need 8/9 dims at Risk
   simultaneously, which is closer to "1987-style sudden derivatives
   crash" than to any of the historical bears in the backfill.
2. ERP/Valuation is currently always missing in backfill (omitted). When
   live, a Compressed-Negative ERP at the 2007 / late-2024 megacap-
   multiple condition would add another Risk (1.0) — bringing peak
   scores up by ~0.5-1.0 (estimated 2020 → ~6.9-7.4, 2008 → ~6.5-7.0).

**Resolution:** Crisis threshold lowered from 8.0 → 7.0 on 2026-05-16
to make Crisis reachable in future 2020-magnitude events when ERP is
live. Defensive band tightens to 6-6.99. The decision is forward-looking:
backfill itself can't validate (ERP gap persists in historical runs), but
ERP-adjusted peak estimates put 2020 and 2008 within reach of the new
threshold. If a future sub-2008-magnitude bear hits sustained Defensive
without ever crossing 7.0, revisit with a further cut to 6.5 (which
would break the symmetric 2-point spacing, so prefer keeping 7.0 unless
data forces otherwise).

**Defensive tier (≥6.0) only fires in crisis-magnitude events.** Hit in
2008 (sustained 6.0 for 6+ months) and briefly in 2020 (one snapshot at
6.4, right before the bottom). Did NOT fire in 2018 Q4 despite a -20%
correction, and did NOT fire in 2022 H1 despite the slow-bleed bear that
extended to October. This is arguably correct: -20% corrections shouldn't
auto-trigger trims; trend-following grind-down bears (2022) are hard for
any composite to catch in real time.

**Recommendation:** Leave Defensive threshold at 6.0; the bar should be
high. Accept that 2022-style bears won't hit Defensive until late in the
sequence (and possibly never). This is a known false-negative pattern,
documented in the playbook's "What the score is and isn't" section.

**Sentiment dim under-contributes in backfill.** NAAIM-only floors the
classifier at Neutral → Safe. In the live tool with CBOE p/c + AAII, the
dim does fire. This is a backfill-only limitation; no production action
needed.

### What we still don't know

- **2024 H1 melt-up** — the bear regime score would have been Watchful
  through this period (consistent with the live readings we've been
  taking). The backfill doesn't extend through 2024-25 because that's
  not a bear precursor; it's a melt-up. Future work: walk 2024 H2 →
  2025 H1 to check the "score persisting at Watchful for a long time
  in a melt-up" failure mode.
- **2015-16 China devaluation scare** — not in the backfill but a known
  Watchful-tier false positive period in equities. Worth a future spot check.
- **Late 2018** — the backfill captures the Q4 correction but not the
  preceding February 2018 volmageddon vol-spike. Worth a future spot check.

## Practical recommendations

1. **v1.1 thresholds: Building 4.0, Defensive 6.0, Crisis 7.0.** Building
   and Defensive are well-calibrated from backfill. Crisis was lowered
   from 8.0 → 7.0 on 2026-05-16 to make it reachable in future
   2020-magnitude events once ERP/Valuation is contributing (ERP-adjusted
   peak estimates put 2020 at ~6.9-7.4 and 2008 at ~6.5-7.0). The
   structural-hedge program's vol-Crisis gate (`/hedge` Trigger 2)
   remains the practical max-action trigger regardless of where Crisis
   sits — Crisis tier reinforces, doesn't replace, that gate.
2. **Don't act on Watchful alone.** Re-confirm crossings hold for ≥1 week
   before adjusting positions, per the playbook's "Recent score whipsaw"
   override condition.
3. **Building → full position cross-ref every time.** The lead-time data
   says you have weeks-to-months to act once Building fires. Don't rush.
4. **Defensive → execute the playbook.** When Defensive fires it's
   meaningful — the backfill shows it persisting only in genuine bear
   environments, not corrections.
5. **Address the Credit dim data gap.** The FRED `BAMLH0A0HYM2` 3-year
   rolling restriction means we now have only ~3 years of HY OAS history
   for any future backfill. Consider wiring a substitute series (ICE BofA
   direct, or CDX HY proxy) if backfill validation becomes a recurring need.

## Per-episode walks (raw output)

Run `uv run --package trading-mcp python packages/trading-mcp/scripts/backfill_bear_regime.py`
to regenerate. Per-snapshot table is in the script's stdout; for the most
recent dated capture, see git history (this doc is updated when weights
change, not on every script run).
