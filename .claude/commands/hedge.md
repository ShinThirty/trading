---
description: Analyze hedge timing — should I open, hold, or close a portfolio hedge?
---

Evaluate whether the portfolio needs a hedge, or whether an existing hedge should be held or closed. This is a regime-driven decision, not a gut call.

## Step 1: Regime Snapshot

Call these in parallel:
- `get_market_regime` — volatility, trend, breadth, macro, sectors, IV context
- `get_quote` for `SPY,IWM,QQQ,XLU,XLY,VIX,VIX3M,USO` — price, volume, intraday ranges
- `get_tradier_history` for SPY, last 10 trading days — volume trend
- `get_tradier_history` for USO, last 10 trading days — commodity divergence check

## Step 2: Reversal Signal Checklist

Score each signal as CLEAR / WATCHING / ACTIVE / FIRING based on the data from Step 1.

| Signal | Category | Condition | Status |
|--------|----------|-----------|--------|
| **VIX creep** | Early warning | VIX trending up while SPY holds highs; sustained above 20 | |
| **VIX term structure** | Early warning | Backwardation (VIX > VIX3M) = market pricing near-term stress above long-term. One of the strongest "hedge now" signals. Contango is normal. | |
| **Intraday IWM fade** | Early warning | IWM closing red or significantly lagging SPY/QQQ | |
| **Defensive rotation** | Early warning | XLU outperforming XLY on multi-day basis (>2pp spread) | |
| **Commodity divergence** | Early warning | USO/WTI grinding higher (>5% over 5+ sessions) while SPY makes new highs and VIX stays sub-20. Inflationary supply shock not being priced in equity vol = late-cycle complacency. The grind (steady up) is more dangerous than a single-day spike — the grind means the market is choosing to ignore it. Historical analogs: 2008 May-Jun (oil $120→$147 then SPY -50%); 2022 Feb (Russia/Ukraine, SPY -13% in 6 weeks after 3-week shrug). Only relevant in cycles with active supply shocks. | |
| **High-volume down day** | Trigger | SPY drops >1.5% on 100M+ volume (vs ~83M avg) | |
| **VIX can't reset** | Trigger | After a bounce, VIX stays elevated (doesn't return to pre-spike level) | |
| **IWM divergence** | Confirmation | IWM peaks and declines while SPY makes new highs | |
| **Volume returns with selling** | Confirmation | Multiple consecutive above-avg volume days with negative closes | |

Count signals by category:
- **Early warnings active:** X/5
- **Triggers fired:** X/2
- **Confirmations:** X/2

## Step 3: Current Hedge Status

Call `get_portfolio_greeks` (ask user for Fidelity CSVs if relevant) and `get_account_positions` for the cash account (`5GJ21MGS53M5FU0T8TQN6PEGQA`) to find any existing SPY/QQQ puts.

If hedge positions exist, present:

| Field | Value |
|-------|-------|
| Position | (contracts, strike, expiry) |
| Current P&L | (mark vs cost) |
| DTE remaining | |
| Distance to strike | (% OTM) |
| Portfolio beta | |
| Hedge ratio | |

If no hedge exists, note "Unhedged" and proceed to Step 4.

### Crisis Beta Adjustment

The `calculate_hedge` tool uses trailing 90-day beta, but during crashes correlations spike toward 1.0. For a tech/semi-heavy portfolio, effective crisis beta can be 20-30% higher than trailing beta. When sizing a new hedge:
- Use `crisis_beta = trailing_beta * 1.25` as the mental model
- If trailing beta is 1.60, size as if it's 2.0 during a real selloff
- This means rounding UP on contract count when `calculate_hedge` gives a borderline number

### Convexity Check

Tail-risk hedging is about buying convexity — disproportionate payoff during large moves. Evaluate the current or proposed hedge strike:

| Strike depth | Convexity | Cost | Best for |
|-------------|-----------|------|----------|
| 2-3% OTM | Low — near-linear payoff | High | Correction protection, not tail risk |
| 5% OTM | Moderate | Moderate | Balanced — current default |
| 7-10% OTM | High — gamma accelerates hard when breached | Low | True tail-risk (Universa-style) |

If the goal is tail protection (crash insurance, not correction hedging), prefer 7-10% OTM. These puts expire worthless more often but cost 40-60% less and pay out 3-5x more per dollar in a real crash. Flag to the user if the current strike is <5% OTM — it's expensive correction insurance, not a tail hedge.

## Step 4: Decision Matrix

Apply this decision matrix based on signal count and current hedge status:

### If UNHEDGED:

| Condition | Action |
|-----------|--------|
| 0 early warnings | **No hedge needed.** Market is clean. |
| 1-2 early warnings, 0 triggers | **Watch.** Check again in the next briefing. Note which signals are building. |
| 3-4 early warnings OR 1+ trigger | **Open hedge.** Run `calculate_hedge` with 50% ratio, tail-risk mode. Present the trade for approval. |
| Any confirmation signals | **Urgent — open hedge immediately.** Reversal may already be underway. Consider delta-adjusted sizing if VIX is still <25. |

### If HEDGED:

| Condition | Action |
|-----------|--------|
| 0 early warnings + 0 triggers | **Close hedge.** Signals have cleared. Reclaim remaining time value. |
| SPY breaks to new highs on above-avg volume (>80M) + VIX drops below 17 | **Close hedge.** Healthy buying invalidates exhaustion thesis. |
| 1-2 early warnings, 0 triggers | **Hold.** Hedge is working as insurance. Check DTE — if <14, evaluate roll. |
| 1+ triggers fired | **Hold and tighten.** Consider rolling to a closer strike if puts are >5% OTM. |
| Confirmations firing | **Hold — this is what you bought it for.** Do NOT close during the selloff. Set profit target (50-100% return on premium). |
| DTE <14, no signals active | **Let expire.** Don't roll into a clean regime. |
| DTE <14, signals still active | **Roll to next monthly.** Run `calculate_hedge` to re-price. |

### IV-Adjusted Entry Timing

| SPY IV Rank | Hedge timing |
|-------------|-------------|
| <30% | Best window to buy puts — cheap insurance |
| 30-50% | Acceptable if signals warrant |
| >50% | Expensive — prefer collar (sell upside call to fund put) or reduce position sizes instead |

## Step 5: Cost Tracking & Strategic Escalation

### Cumulative Hedge Cost

Check recent hedge history by calling `get_order_history` for the cash account and filtering for SPY/QQQ put trades. Calculate:

| Metric | Value |
|--------|-------|
| Current hedge cost | (cost basis of open puts) |
| Hedges closed YTD | (count) |
| Total hedge P&L YTD | (sum of realized + unrealized) |
| Annual hedge drag | (total cost / portfolio value, as %) |

Guideline: 1-3% annual drag is acceptable for tail protection. Above 3%, the hedging program is too expensive — either the timing is off (buying when IV is high) or you're hedging too frequently.

### Strategic Escalation

If any of these conditions are true, flag explicitly — hedging may be the wrong tool:

- **3+ consecutive hedge rolls** without a payoff: "You've rolled this hedge 3 times. If the risk is persistent enough to hedge for 3+ months, consider reducing position sizes or raising cash instead — it's cheaper than perpetual insurance."
- **Annual hedge drag >3%**: "Hedge spending exceeds 3% of portfolio this year. Review whether tactical timing can improve, or whether position-level risk reduction is more efficient."
- **Hedge ratio >50% for >60 days**: "You've been >50% hedged for 2+ months. At this point, the hedge IS the position. Either the risk is real (reduce exposure) or it's passed (close the hedge)."

## Step 6: Recommendation

Present a single clear recommendation:

**Hedge Action: [OPEN / HOLD / ROLL / CLOSE / WATCH]**

| Field | Value |
|-------|-------|
| Signal score | X/9 active |
| Early warnings | X/5 |
| Triggers | X/2 |
| Confirmations | X/2 |
| VIX term structure | Contango / Flat / Backwardation |
| IV Rank | X% (cheap / acceptable / expensive) |
| Current hedge | (position or "none") |
| Strike depth | X% OTM (correction / balanced / tail-risk) |
| Crisis-adjusted beta | trailing beta * 1.25 |
| Hedge cost YTD | $X (X% of portfolio) |
| Action | (specific: open X contracts, hold, roll to Y, close for $Z, or watch until next briefing) |

**Rationale:** One sentence on why — e.g., "Early warnings intensifying but no trigger yet — hold existing hedge and reassess if high-volume down day occurs."

**Next check:** When to re-run this analysis (e.g., "next briefing" or "immediately if SPY drops >1.5% on high volume").

If the action is OPEN, run `calculate_hedge` and present the trade details (contracts, strike, expiry, cost, % of portfolio) for approval. Note strike convexity — if the default 5% OTM strike is selected, mention that 7-10% OTM would be cheaper with higher convexity for true tail protection. If the action is CLOSE, show the current mark and how much time value can be reclaimed.
