# Market Regime Framework

Use `get_market_regime` to get a quick snapshot before diving into individual signals. The tool classifies the market across 4 dimensions — each label maps to strategy preferences in the [decision framework](decision-framework.md).

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

## Regime Combinations

Some combinations are more actionable than others:

| Combination | Interpretation | Action |
|-------------|---------------|--------|
| Elevated vol + Downtrend + Risk-Off | Classic fear environment | Best CSP window — sell rich premium on high-conviction drawdowns |
| Low vol + Uptrend + Risk-On | Complacency rally | Ride momentum but buy cheap hedges (puts are cheap) |
| Crisis + Inverted + Risk-Off | Recession unfolding | Cash is a position. Only deploy on highest conviction. |
| Normal vol + Sideways + Rotation | Quiet chop | Harvest premium — iron condors, calendars |
| Elevated vol + Uptrend + Risk-On | Climbing a wall of worry | Accumulate with CSP-heavy hybrids (rich premium + bullish trend) |
