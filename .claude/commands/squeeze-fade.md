---
description: Assess squeeze state and re-entry timing for a bearish post-squeeze fade
arguments:
  - name: symbol
    description: Ticker symbol of a short-squeezed stock (e.g. CAR, GME)
    required: true
---

Assess the current squeeze state for **$ARGUMENTS.symbol** and determine whether re-entry conditions are met for a bearish fade trade. This skill picks up where `/analyze` leaves off when the bearish framework verdict was "WAIT — active squeeze."

Do NOT skip steps or summarize — run every tool call and present every result.

## Step 1: Squeeze State Assessment

1. Call `get_short_interest` for $ARGUMENTS.symbol.
2. Call `get_entry_signals` for $ARGUMENTS.symbol.
3. Call `get_company_news` for $ARGUMENTS.symbol (last 7 days).

From these results, classify the squeeze into one of three states:

### Active Squeeze
ALL of these present:
- Short % of float >30%
- RSI >60 OR making new highs in the past week
- 2-week price change >+20%
- News dominated by squeeze/meme coverage

**Verdict: WAIT. Do not enter. Squeeze momentum can persist far longer than fundamentals justify.**

### Exhausting Squeeze
TWO or more of these present:
- RSI declining from a recent peak above 70 (currently 50-70 range)
- 2-week price change flattening or turning negative
- Volume declining from squeeze peak (check news for "cooling" / "easing" language)
- Price failing to make new highs despite short interest remaining elevated
- News shifting from "squeeze" to "what's next" / "post-squeeze" framing

**Verdict: MONITOR. Getting closer but not yet safe. Check again in 3-5 trading days. Note which conditions are met and which remain.**

### Exhausted Squeeze
THREE or more of these present:
- RSI <50
- Price below SMA(50) or SMA(50) has started declining
- 2-week price change is negative
- IV Rank <70% (normalizing from squeeze peak)
- Short interest has dropped >10 percentage points from peak (covering completed)
- News coverage has faded or shifted to fundamentals

**Verdict: READY. Re-entry conditions met. Proceed to Step 2.**

Present the assessment as:

| Condition | Status | Value |
|-----------|--------|-------|
| Short % of float | [High/Moderate/Low] | [X%] |
| RSI(14) | [Rising/Flat/Declining] | [X] |
| 2-week price change | [Rallying/Flat/Declining] | [X%] |
| Price vs SMA(50) | [Above/Below] | [$X vs $Y] |
| IV Rank | [Extreme/Elevated/Normal/Low] | [X%] |
| News tone | [Squeeze frenzy/Cooling/Post-squeeze/Fundamental] | [summary] |

**State: "Squeeze State: [Active / Exhausting / Exhausted]"**

If Active or Exhausting, skip to the Final Output with a WAIT/MONITOR verdict and specific conditions to watch for. Do NOT recommend a trade.

## Step 2: Bearish Trade Setup (only if Exhausted)

If the squeeze is exhausted, determine the trade:

1. Call `get_iv_metrics` for $ARGUMENTS.symbol to get current IV Rank.
2. Call `get_option_expirations` for $ARGUMENTS.symbol.

### Strategy Selection (from bearish framework, L2)

| IV Rank | Earnings Timing | Strategy |
|---------|----------------|----------|
| <30% | 2-6 weeks out | Long put through earnings (-0.35 to -0.40 delta, expiry 2-4 weeks past earnings) |
| <30% | No near-term catalyst | Long put, 45-60 DTE, -0.35 to -0.40 delta |
| 30-70% | Any | Reduced-size long put (-0.30 to -0.35 delta, 45-60 DTE) |
| >70% | Any | WAIT — IV still too high. Puts are expensive. Re-check in 1 week. |

State: "**Strategy: [X]** — [rationale linking IV environment + timing]"

## Step 3: Strike Selection (only if Strategy is not WAIT)

1. Call `get_option_chain` for $ARGUMENTS.symbol with the chosen expiration, puts only.

2. Find the strike closest to the target delta. Present 3 candidates (one above, target, one below):

| Strike | Delta | Bid | Ask | Mid | OTM % | Break-Even |
|--------|-------|-----|-----|-----|-------|------------|
| ... | ... | ... | ... | ... | ... | ... |

3. Check liquidity: bid-ask spread should be <15% of mid price. If wider, flag "Liquidity warning — wide spreads will erode edge."

## Step 4: Position Sizing

Bearish sizing rules (from docs/bearish-framework.md):

| Rule | Limit |
|------|-------|
| Max single bearish position | 3% of portfolio (premium at risk) |
| Max total bearish allocation | 10% across all bearish positions |
| Max concurrent bearish positions | 2-3 names |

Before sizing, answer: "If this put expires worthless, does the loss change how I trade next month?" If the premium exceeds 3% of portfolio, reduce size.

Post-squeeze stocks carry re-squeeze risk — even after exhaustion, a second wave is possible. Size as if the stock could rally 50% from current levels before the thesis plays out.

## Step 5: Management Preview

| Rule | Trigger |
|------|---------|
| Take profit | 50% return on premium (stretch: 100%) |
| Time stop | Exit at 21 DTE if thesis hasn't played out |
| Re-squeeze stop | Close if stock rallies >30% from put entry (squeeze restarting) |
| Thesis check | Every 2 weeks: are fundamentals still deteriorating? If margins stabilize for 2 quarters, close. |
| Never hold through expiry | Close or roll by 14 DTE |

## Final Output

**$ARGUMENTS.symbol Squeeze Fade Status**
- **Squeeze state**: [Active / Exhausting / Exhausted]
- **Verdict**: [WAIT / MONITOR / READY]
- **Strategy**: [specific strategy with parameters, or "none — not yet"]
- **Key conditions to watch**: [what needs to change before re-entry, or N/A if ready]
- **Re-squeeze risk**: [High/Moderate/Low — based on remaining short interest and days to cover]
- **Next step**: [e.g., "re-run /squeeze-fade CAR in 5 trading days" or "preview order for June $X put"]
