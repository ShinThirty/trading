# Bear Regime Score — Historical Backfill

Validation of the `get_bear_regime_score` composite (v1 weights) against
historical episodes: four bear-precursor walks (2007 H2 / 2008 GFC, 2018
Q4 correction, 2020 COVID crash, 2022 H1 bear setup) plus a melt-up
false-positive check (2024 H2 → 2025 H1, which also captures the April
2025 tariff drawdown).

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
| 2024-meltup | 8/9 (89%) | Valuation (ERP) |
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
| 2024-meltup | 2024-08-05 (-198d peak) | 2025-04-07 (+47d peak, -1d bottom) | never | never | 2025-02-19 | 2025-04-08 |

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

- ✅ **2024 H2 → 2025 H1 melt-up + tariff drawdown** — done 2026-05-17. See
  "Melt-up false-positive check" section below. Headline: zero false
  Building crossings in the 12-month walk; April 2025 tariff drawdown
  surfaced a new failure mode (exogenous-shock drawdowns get coincident
  not leading signals).
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

## Price-action cross-check

The backfill script overlays SPY close / drawdown-from-peak / days-from-peak
on every weekly snapshot. This validates *what the score was telling you
while price was actually moving* — not just "did the threshold cross" but
"what was SPY doing when it did".

### Tier crossing vs drawdown

| Episode | Building cross DD | Defensive cross DD | Max score | Max-score DD | Days max→bottom |
|---------|-------------------|--------------------|-----------|--------------|-----------------|
| 2007 H2 | **-8.1%** (67d before peak) | -15.6% (101d after peak) | 6.0 (saturated) | -15.6% | +416d |
| 2018 Q4 | -5.6% (22d after peak) | never | 4.3 | -17.6% | +3d |
| 2020 Q1 | -11.3% (13d after peak) | -25.3% (27d after peak) | 6.4 | -25.3% | +6d |
| 2022 H1 | **-2.0%** (2d after peak) | never | 5.0 | -2.0% | +280d |
| 2024-meltup | -17.7% (47d after peak) | never | 5.0 | -17.7% | +1d |

### What the price overlay reveals

**Building tier fires at small drawdowns and is the actionable signal.**
Across all four episodes Building fired between -2% and -11% from peak:

- 2007 fired *before the peak* at -8% from a prior high (caught the
  deteriorating internals during the topping process)
- 2022 fired at the actual peak with SPY -2% — *the cleanest top-tick of
  the four*, beating any human framework
- 2020 fired at -11%, 20 days before the COVID bottom
- 2018 fired at -5.6%, 73 days before the December low

This validates "Building = pause new entries" as a real-money signal —
the score is calling regime change while there's still room to act, not
in the rear-view.

**Defensive tier is coincident with capitulation, not leading.** When
Defensive fires it's typically in the meat of the crash, not before:

- 2008: fired at -15.6% (Jan 2008), then SPY went to -49% (additional
  -33pp damage). Useful lead, but actionable months earlier from Building.
- 2020: fired at -25.3%, just **6 days before the actual bottom**. By the
  time Defensive triggered, most of the COVID move was done.
- 2018 / 2022: never fired despite -19.8% drawdowns. The composite needs
  panic vol or multi-dim convergence to escalate past Building; slow
  bears don't supply that.

**Read:** Defensive is the "this is bad now" gate, not the "this will get
worse" gate. The lead-time value is at Building; Defensive justifies the
heavier playbook actions (hedge ramp, trim plan) once they're already
warranted by price action.

**Score saturates in real crashes.** The 2007/2008 walk is the most
striking: score sat at 6.0 (Defensive) continuously from January 2008
through year-end at *every* drawdown level from -15% to -49%. There's no
information past Defensive in a sustained crash because Curve + Vol +
Technicals are all already firing at max — additional price damage
doesn't add new dimensions. Implication: **don't expect the score to
"keep going up" as the bear deepens** — once it hits Defensive in a real
crisis, the signal is sticky-flat, not progressive.

**Grind-down bears whipsaw the score.** 2022 is the canonical failure
mode: Building fired 2 days after the January peak (a perfect top-tick
signal), then *decayed* through the actual bear. By June, with SPY at
-21% and still 105 days from the eventual October bottom, the score
was back to 3.6 (Watchful). The grind-down regime doesn't generate the
panic vol or breadth capitulation that escalates the composite — so the
score *de-escalates* even while price continues lower. Implication:
**once Building fires in a grind-down setup, the right action is to
maintain posture even if the score decays** — the absence of a Defensive
re-print isn't an all-clear, it's the regime not having a vol spike.

### Additional drawdown after tier cross (forward-return proxy)

| Episode | Future DD from Building cross | Future DD from Defensive cross |
|---------|-------------------------------|---------------------------------|
| 2007 H2 | -41pp (-8% → -49%) | -33pp (-16% → -49%) |
| 2018 Q4 | -14pp (-6% → -20%) | n/a |
| 2020 Q1 | -23pp (-11% → -34%) | -9pp (-25% → -34%) |
| 2022 H1 | -23pp* (-2% → -25% by Oct) | n/a |
| 2024-meltup | -1pp (-17.7% → -19.0%) | n/a |

\*2022 Building cross to October 2022 bottom, beyond the walk window.

**Average additional drawdown after Building cross: ~20pp** (excluding
2024-meltup) / **~16pp including 2024-meltup**. The four bear episodes
gave Building meaningful lead time — pausing accumulation at the cross
historically avoided ~25% additional downside on average. The 2024-meltup
result (Building fired 1 day before the actual bottom) drags the average
down and reflects the new failure mode documented below: exogenous-shock
drawdowns don't supply the macro deterioration the score's leading
dimensions (Curve, Positioning) track, so Building only fires coincident
once Tech/Vol/Credit confirm the move.

**Average additional drawdown after Defensive cross: ~21pp** (only 2007
and 2020 fired). Skewed by 2007's -33pp; 2020 was only -9pp because the
crash was nearly over. Treat Defensive as confirmation-of-bear, not
forward predictor.

## Practical decision rules — updated from cross-check

1. **Building cross = act.** Across all 4 episodes, Building fired at a
   drawdown where meaningful action was still possible (-2% to -11% from
   peak) and historically avoided ~25pp of further downside. The 1-week
   persistence rule still applies for whipsaws, but treat persistent
   Building as a real decision checkpoint, not a yellow flag.
2. **Defensive cross = execute hedge ramp + trim, but don't expect to
   sell the top.** Defensive historically fires in the meat of the crash
   (sometimes within days of the bottom). The action is right (trim,
   raise hedge); the timing expectation should be "limit further damage"
   not "exit at favorable prices".
3. **Score saturation ≠ regime topping.** If the score sits flat at
   6.0-7.0 for weeks while price continues lower, that's the composite
   maxing out — not a sign the bear is exhausted. Use price action and
   the `/hedge` Trigger 2 (vol Crisis) gate for capitulation timing, not
   the composite level.
4. **Score decay in grind-down bears ≠ all-clear.** If Building fires
   and then the score decays back to Watchful while SPY is still
   trending down, hold the Building-tier playbook actions in place. The
   absence of vol/breadth re-print doesn't reset the regime — it's just
   a slow-bear pattern the composite under-weights.
5. **Crisis tier at the new 7.0 threshold:** in this backfill, only 2020
   would have crossed 7.0 (with ERP wired) and only momentarily. Treat
   Crisis as confirmation-the-hedge-program-should-be-firing rather than
   an independent gate.
6. **Exogenous-shock drawdowns get coincident, not leading, signals.**
   When a drawdown is policy/event-driven rather than macro-driven, the
   leading dims (Curve, Positioning, Sentiment) stay quiet — Building
   only crosses when Tech/Vol/Credit confirm (April 2025: +1d before
   bottom). Use active-overhang memory files for forward visibility on
   shock regimes; the composite under-warns.

## Melt-up false-positive check (2024 H2 → 2025 H1)

Added 2026-05-17. The first four backfill episodes were all real bears;
this walk tests the inverse — does the score false-alarm during a
sustained melt-up, and what does it do during the exogenous shock
drawdown that punctuated it?

**Walk window:** 2024-07-01 → 2025-06-30 (12 months)
**Local peak:** 2025-02-19 ($612.93)
**Local bottom:** 2025-04-08 ($496.48, -19.0% peak-to-trough)

### Phase 1 — melt-up (2024-07-01 → 2025-02-19)

**Zero Building crossings.** Across 33 weekly snapshots covering the
full melt-up from $545 → $613, the composite never reached Building
(≥4.0). This is the cleanest possible false-positive result.

**Score distribution during melt-up:**
- Clear (0-1.99): 22 snapshots (67%)
- Watchful (2-3.99): 11 snapshots (33%)
- Building+: 0 snapshots

Watchful fired at the Aug 2024 yen-carry vol spike (3.8, VIX 38), the
August aftermath, pre-election convergence in early November, and the
January 2025 pullback (2.5-3.8) — each had an identifiable real driver
and none bled into Building. Watchful is whipsawy but earns its prints.

### Phase 2 — tariff drawdown (2025-02-19 → 2025-04-08)

The April 2025 tariff drawdown is a new pattern the four-bear backfill
didn't capture: a fast, exogenous-shock-driven -19% drawdown not
preceded by macro deterioration.

**Score timeline during the drawdown:**

| Date | DD | Score | Tier | What fired |
|------|----|----|------|-----------|
| 2025-02-24 | -2.6% | 1.2 | Clear | Breadth only |
| 2025-03-03 | -4.8% | 2.5 | Watchful | Tech + Breadth |
| 2025-03-10 | -8.5% | 3.8 | Watchful | Tech + Breadth + Vol |
| 2025-03-31 | -8.7% | 2.5 | Watchful | Tech + Curve + Breadth |
| **2025-04-07** | **-17.7%** | **5.0** | **Building** | **Credit + Vol + Tech** |
| 2025-04-08 | -19.0% (bottom) | — | — | — |
| 2025-04-21 | -16.2% | 5.0 | Building | Credit + Tech + Breadth (re-test) |

**Building fired +47 days after the peak and +1 day before the bottom.**
Compare to the four-bear backfill where Building averaged ~10 days
after peak with weeks-to-months of lead time. The 2025 drawdown gave
essentially zero forward warning at the action threshold.

**Why the score lagged:** the dims that *lead* (Curve, Positioning,
Sentiment) stayed quiet because the dislocation wasn't macro-driven.
Tariff announcement → equity sell-off was a policy-channel shock, not
a credit/curve/positioning unwind. The composite waited until *Credit*
(HY OAS spike), *Vol* (VIX surge), and *Tech* (SMA200 break) confirmed
the move — and by then the bottom was a day away.

### Phase 3 — recovery (2025-04-08 → 2025-06-30)

**Score de-escalated cleanly.** From 5.0 (Building, 2025-04-21) to 0.0
(Clear, 2025-05-12) in 3 weeks. By the end of the walk, score was
sitting at 0.0 with SPY back to new highs at $618. No lingering
Watchful prints, no false-positive elevation post-recovery.

**Net read:** Building threshold validated as the action gate (zero false
crossings in 12 months); exogenous-shock drawdowns are a known blindspot
(use active-overhang memory for forward visibility); de-escalation is
clean (no stuck-Watchful residue).

## Per-episode walks (raw output)

Run `uv run --package trading-mcp python packages/trading-mcp/scripts/backfill_bear_regime.py`
to regenerate. Per-snapshot tables now include SPY close, drawdown from
peak, and days-from-peak columns; each episode ends with a
"Price-action alignment" summary. For the most recent dated capture, see
git history (this doc is updated when weights change or new findings land,
not on every script run).
