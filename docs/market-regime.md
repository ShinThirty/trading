# Market Regime Framework

Use `get_market_regime` to get a quick snapshot before diving into individual signals. The tool produces a synthesized **verdict** plus seven dimensional labels — each maps to strategy preferences in the [decision framework](decision-framework.md). Read the verdict first; drop into dimensions when you need the *why*.

## Verdict

The verdict is a first-match-wins decision tree over the dimensions and warning flags. Treat it as the most actionable thing the tape is doing right now.

| Verdict | Trigger | What it means | Strategy implications |
|---------|---------|---------------|----------------------|
| **Crash Active** | Volatility = Crisis | Active panic | Cash is a position. Pause new accumulation. Aligns with Trigger 2 (harvest tranches) of the structural tail-hedge program — see [tail-hedge-playbook.md](tail-hedge-playbook.md). Verdict is informational; hedge triggers fire on P&L + price action, not the label. |
| **Pre-Crash Watch** | Vol Elevated + (Tape Fast OR Credit Widening), OR Vol Normal + (Tape Fast AND Credit Widening) | Leading indicators are firing ahead of vol expansion | Pause directional adds. Widen CSP strikes, prefer defined-risk on new exposure. Verify the tail hedge is in place — do not open new structural hedges reactively. |
| **Recovery** | Vol Elevated + Broadening breadth + Risk-On | Vol coming off elevated with broad participation | Best window to accumulate quality at discount. CSPs catch falling knives; direct buys catch the bottom. Premium still rich. |
| **Bear Setup** | bear_score ≥ 3 from: Downtrend (1), Narrowing (1), Risk-Off (1), un-inversion trap (2), semi divergence (1), credit trap (1) | Structural deterioration without vol Crisis | Defensive. Reduce concentration, favor bearish L2/L3 setups in deteriorating names, keep cash for the eventual vol expansion. |
| **Late Cycle** | late_score ≥ 2 from: Inverted (1), Narrowing (1), Rotation/Risk-Off (1), un-inversion trap (2), credit trap (1) — AND trend = Uptrend or Sideways | Warnings emerging but trend still up | Stay invested but rotate quality. Reduce position sizes, tighten new-entry filters, favor margin expansion over multiple expansion. |
| **Expansion** | Uptrend + (Healthy or Broadening) breadth + Risk-On | Clean bull tape | Default framework applies. Accumulate intent favored, directional leverage works. |
| **Mixed** | Signals don't cohere | No clean read | Trade the individual stock signal, not the regime. Don't size up based on regime context. |

Only **Crash Active** corresponds to a structural hedge program state (Trigger 2 conditions). All other verdicts are informational — they shape position sizing, accumulation cadence, and entry timing, not hedge open/close.

## Regime Dimensions

### Volatility: Low / Normal / Elevated / Crisis

Based on VIX level with a term structure override.

| Label | VIX Range | What it means | Strategy implications |
|-------|-----------|---------------|----------------------|
| **Low** | <15 | Complacency, cheap options | Buy vol (straddles/strangles). Options are cheap. |
| **Normal** | 15-25 | Typical trading environment | Default framework applies as-is |
| **Elevated** | 25-35 | Fear rising, rich premiums | Sell premium but reduce size by 50% and widen strikes. Vega expansion risk — if VIX spikes from 30→45, short options get crushed even without price movement. |
| **Crisis** | >=35 or backwardation | Active panic | Widen strikes, reduce size, favor defined-risk. Cash is a position. |

**Backwardation override:** If the 30-day VIX exceeds the 3-month VIX (VXVCLS), the term structure is inverted — the market is pricing more risk in the near term than further out. This signals active panic and overrides to Crisis regardless of the absolute VIX level. A VIX of 22 in backwardation is more dangerous than a VIX of 28 in normal contango.

### Trend: Uptrend / Sideways / Downtrend

Based on SPY price relative to 50-day and 200-day simple moving averages.

| Label | Condition | Strategy implications |
|-------|-----------|----------------------|
| **Uptrend** | Price > SMA50 > SMA200 | Accumulate intent favored, directional leverage works |
| **Sideways** | Mixed SMA alignment | Harvest premium, iron condors, range-bound strategies |
| **Downtrend** | Price < SMA50 < SMA200 | CSPs shine (rich IV + falling prices = entry at discount). Avoid directional long calls. |

### Breadth: Broadening / Healthy / Mixed / Narrowing

Three sub-signals over a 20-day window: SPY vs IWM relative performance (large-vs-small divergence), XLU vs XLY (defensive-vs-cyclical rotation), and SPY 5d-vs-20d volume trend. Each sub-signal contributes a warning (≥3pp lag, ≥2pp defensive, <75% volume) or a strength (≥3pp lead, ≥2pp cyclical, >125% volume).

| Label | Condition | What it means | Strategy implications |
|-------|-----------|---------------|----------------------|
| **Broadening** | 0 warnings + ≥2 strengths | Recovery has legs — small caps and cyclicals participating on real volume | Favors Recovery and Expansion verdicts. Accumulate intent strongest here. |
| **Healthy** | 0 warnings + 0-1 strengths | Clean tape, mildly bullish | Default framework applies as-is |
| **Mixed** | ≥1 warning, <2 warnings | Genuine conflict — one breadth fault but not majority | Read the underlying sub-signal; don't size up on regime context |
| **Narrowing** | ≥2 warnings | Divergences emerging, defensive rotation, or thin volume | Adds 1 to bear_score and late_score. Reduce concentration; suspect rallies. |

### Macro: Steep / Flat / Inverted

Based on the 10-year minus 2-year Treasury yield spread, with Fed funds rate direction for context.

| Label | Spread | What it means | Strategy implications |
|-------|--------|---------------|----------------------|
| **Steep** | >1.0% | Normal expansion, banks lending | Favor growth names, Accumulate intent |
| **Flat** | 0.0-1.0% | Late cycle, tightening | Reduce concentration, favor defined-risk |
| **Inverted** | <=0.0% | Recession signal | Defensive posture — hedges, collars, smaller sizes |

Fed funds direction (rising / stable / falling) adds context: a falling rate in an inverted curve suggests the Fed is responding to recession risk.

**Un-inversion trap:** The recession signal is the inversion. The recession *itself* typically arrives when the curve un-inverts — the Fed panic-cuts the short end, steepening the curve rapidly. If the spread moves from Inverted to Steep (>1.0%) while Fed funds are falling, this is maximum danger — it looks like "normal expansion" but the rate cuts are confirming the recession has arrived. Override to defensive posture (hedges, cash, smaller sizes). Do not treat rapid un-inversion as a green light.

### Sectors: Risk-On / Rotation / Risk-Off

Multi-timeframe analysis of the 11 SPDR sector ETFs (XLK, XLF, XLE, XLV, XLC, XLI, XLB, XLRE, XLP, XLY, XLU). Computes 30d, 60d, and 90d returns for each sector, ranks them, and detects leadership shifts.

**Risk appetite label:** Based on 30d returns of high-beta ETFs (XLK, XLY, XLC) vs defensive ETFs (XLU, XLP, XLRE).

| Label | Condition | Strategy implications |
|-------|-----------|----------------------|
| **Risk-On** | High-beta outperforming, positive | Growth and tech names favored, momentum strategies |
| **Rotation** | Mixed or all negative | Be selective, don't chase sector momentum |
| **Risk-Off** | Defensives outperforming, positive | Reduce tech exposure, favor hedges and income strategies |

**Leadership ranking:** Top 3 and bottom 3 sectors by 30d return. Use this to identify which sectors have near-term momentum and which are lagging — if your pipeline stock's sector is in the bottom 3, that's a "delay entry" signal; if it's in the top 3, momentum supports entering now.

**Momentum shifts:** Compares 90d rank vs 30d rank for each sector. A sector that moved 4+ positions is flagged:
- **Emerging** (rank improved): leadership is rotating *into* this sector — favorable for new entries
- **Fading** (rank declined): leadership is rotating *away* — delay entries or tighten stops on existing positions

**Semi divergence check:** The high-beta sector basket includes broad Tech (AAPL, MSFT) which often acts as a safe haven in late-cycle environments due to massive cash piles. This can produce a false Risk-On signal while semiconductors are already rolling over. If your portfolio is semi-concentrated, cross-check SMH vs SPY relative strength. If semis are underperforming broad Tech, the cycle may be turning even if the sector label reads Risk-On.

### Credit: Widening / Stable / Tightening

Based on the 5-day delta of the BofA US High-Yield Index Option-Adjusted Spread (FRED `BAMLH0A0HYM2`). Credit spreads typically widen 100-300 bps in the first weeks of a crash, often before equity vol fully expands.

| Label | 5-day delta | What it means | Strategy implications |
|-------|-------------|---------------|----------------------|
| **Widening** | > +50 bps | Active credit stress | Pre-Crash Watch trigger when paired with elevated vol. Pause risk-on adds. |
| **Stable** | -50 to +50 bps | Normal range | Default framework applies |
| **Tightening** | < -50 bps | Risk-on / recovery | Confirms appetite — supports accumulate intent |

**Credit trap:** A separate detector flags slow leaks that don't trip the 5-day delta — current OAS sitting >100 bps above its trailing 1-month low. Catches setups like 2022 H1 and 2007 H2 where spreads grind wider over weeks while equity still grinds up. Adds 1 to both bear_score and late_score.

### Tape Speed: Fast / Normal

Based on SPY 5-day return and VIX 5-day rate-of-change. Crashes deliver vol expansion + speed together — speed is the leading half.

| Label | Trigger | What it means | Strategy implications |
|-------|---------|---------------|----------------------|
| **Fast** | SPY 5d return < -5% OR VIX 5d Δ > +50% | Tape regime shift toward crash territory | Pre-Crash Watch trigger when paired with elevated vol or widening credit. Pause directional adds. |
| **Normal** | Otherwise | Typical pace | Default framework applies |

## Regime Combinations

Some combinations are more actionable than others:

| Combination | Interpretation | Action |
|-------------|---------------|--------|
| Elevated vol + Downtrend + Risk-Off | Classic fear environment | Best CSP window — sell rich premium on high-conviction drawdowns |
| Low vol + Uptrend + Risk-On | Complacency rally | Ride momentum but buy cheap hedges (puts are cheap) |
| Crisis + Inverted + Risk-Off | Recession unfolding | Cash is a position. Only deploy on highest conviction. |
| Normal vol + Sideways + Rotation | Quiet chop | Harvest premium — iron condors, calendars |
| Elevated vol + Uptrend + Risk-On | Climbing a wall of worry | Accumulate with CSP-heavy hybrids (rich premium + bullish trend) |

## Companion regime reads

`get_market_regime` covers the tape, breadth, credit, vol, sentiment, and positioning dimensions. Two additional tools cover the **valuation regime** — how risk-free rates translate to equity multiples:

- **`get_equity_risk_premium`** — forward earnings yield − DGS10. Tier (Generous / Fair / Tight / Compressed / Compressed-Negative) determines whether multiples have room to expand and how much of returns will come from earnings vs multiples.
- **`get_yield_curve_state`** — 2Y / 10Y / 30Y levels and 4w / 12w changes, classified as Bear Steepener / Bear Flattener / Bull Steepener / Bull Flattener / Quiet / Mixed. Tells you which tenor is leading — i.e., *what* is repricing (term premium, Fed path, or duration bid).

See [valuation-regime.md](valuation-regime.md) for tier definitions and how these feed Step 1/2/3 of the decision framework.
