---
description: Grade a software earnings name for the vol-mispricing basket (selection filter + Δ-Skew tier → A/B/Skip)
arguments:
  - name: symbol
    description: Ticker symbol with an upcoming earnings print (e.g. PATH, OKTA, MDB)
    required: true
---

Grade **$ARGUMENTS.symbol** against the software vol-mispricing playbook (`memory/project_software_vol_mispricing.md`). Walks the full selection filter, assigns the bucket, reads positioning, and outputs a grade + structure recommendation. Built around the 2026-05 SNOW/INTU/ZS regime where implied:realized runs ~1:3 on clean-bucket prints with concentrated positioning.

Do NOT skip steps or summarize — run every tool call and present every result. Fail-fast: if any hard exclusion fires, state **Skip** and stop.

## Step 1: Eligibility Gate (selection filter — hard exclusions)

Call in parallel:
- `get_company_profile` for $ARGUMENTS.symbol (market cap)
- `get_fmp_earnings_calendar` for $ARGUMENTS.symbol (next print date)
- `get_iv_metrics` for $ARGUMENTS.symbol (IV Rank, IV-HV, liquidity, implied move)
- `get_tradier_history` for $ARGUMENTS.symbol (YTD price change — for washout check)

Present as a single eligibility table:

| Filter | Threshold | Value | Pass/Fail |
|---|---|---|---|
| Market cap | $5-50B (mid-cap) | $X | ✅/❌ |
| Earnings within 14 days | print date set, ≤14 DTE | YYYY-MM-DD (N DTE) | ✅/❌ |
| Weekly expiration covers print | event-week expiry exists | [check via `get_option_expirations`] | ✅/❌ |
| IV Rank | 40-90% | X% | ✅/❌ |
| Implied move | <12% | X% | ✅/❌ |
| Liquidity rating | ≥ 2 | Liq X | ✅/❌ |
| Not YTD washed out | YTD > -30% | X% | ✅/❌ |

**If any row fails → state "Skip — [reason]" and stop.** Do not proceed to bucket assignment.

Also flag if any of these apply (qualitative — note even if quantitative passes):
- Mega-cap with concurrent capital return announcement (CRM failure mode)
- Beat-and-raise with marginal guide miss pattern (the CRM Q2 trap)

## Step 2: Bucket Assignment

Call `get_company_news` for $ARGUMENTS.symbol (last 14 days) and `get_basic_financials` for $ARGUMENTS.symbol.

Apply the 3-bucket framework from `memory/project_software_positioning_regime.md`:

| Bucket | Bear thesis | Directional bias on print |
|---|---|---|
| **AI-enabler** | None — AI workloads run *through* them | Bullish |
| **AI-displacement target** | Agentic AI eats the workflow | Bearish |
| **AI-commoditization risk** | Hyperscaler bundles it free | Bearish |
| **Bucket ambiguous** | Multiple buckets straddle (CRM pattern) | **Skip** |

State: "**Bucket: [X]** — [one sentence: which AI thesis applies and why]".

**If bucket ambiguous → Skip per CRM failure mode (`feedback_crm_failure_mode.md`).**

## Step 3: Positioning Read (the magnitude generator)

Call `get_options_positioning` for $ARGUMENTS.symbol (default `dte_max=60`, multi-expiration mode).

Apply the 5-tier classifier on **both** aggregate Δ-Skew AND the event-week expiration:

| Aggregate Δ-Skew | Tier | Grade contribution |
|---|---|---|
| ≥ +0.25 or ≤ -0.25 | **Concentrated** | A — full basket weight |
| ±0.10 to ±0.25 | **Tilted** | B — half size |
| within ±0.10 | **Balanced** | **Skip** — no unwind fuel |

Term-structure check: back-month concentration (>30 DTE Concentrated) is structurally heavier than front-week. PATH 2026-05-27 was Concentrated Bull at 16/36/51 DTE → A++. Note if event-week tier disagrees with aggregate.

**Directional read:** Δ-Skew sign × bucket bias →
- Concentrated Bull + bear-bucket = bearish (bull positioning unwinds on miss)
- Concentrated Bear + bull-bucket = bullish (bear positioning squeezes on beat)
- Aligned (Concentrated Bull + bull-bucket OR Concentrated Bear + bear-bucket) = magnitude there but no clear direction unwind — use ATM straddle

## Step 4: Grade

Combine eligibility + bucket + tier:

| Configuration | Grade |
|---|---|
| All filters pass + clean bucket + **Concentrated** tier + back-month concentration | **A++** — full size (1% portfolio) |
| All filters pass + clean bucket + **Concentrated** tier (front-week only) | **A** — full size |
| All filters pass + clean bucket + **Tilted** tier | **B** — half size (0.5%) |
| Any filter fails OR ambiguous bucket OR **Balanced** tier | **Skip** |

State: "**Grade: [X]**" with the limiting factor if not A++.

## Step 5: Structure

Structure is grade × IV-HV × bucket-direction:

| Setup | Default structure |
|---|---|
| A++ / A + IV-HV < +5% (options cheap vs HV) | Long ATM straddle, event-week expiry |
| A++ / A + IV-HV > +5% (options rich) | Bear/bull put/call spread (40Δ / 20Δ), event-week — reduces vega |
| B grade | Same as above but half size; prefer spread over straddle |
| Aligned directional (Δ-Skew sign matches bucket bias) | ATM straddle (no clear unwind direction) |
| Directional unwind setup | Single-direction spread matching bucket bias |

Specify:
- Long strike(s) at ATM (closest to current price)
- Short leg (if spread) at 20Δ
- Expiry = first weekly covering the print
- Entry day = the trading day before the print (Tue/Wed for Thu AH, Mon for Tue AH)

## Step 6: Sizing & Management

| Rule | Limit |
|---|---|
| Max per trade | 1% portfolio (premium at risk) |
| Half size for B grade | 0.5% |
| Assume total loss possible | ~30-50% of straddles expire inside implied |

### The 9:30 exit decision (do NOT default to "sell at the open")

Sell-at-open is correct only for a **gap-and-stall** print. It destroyed the OKTA 2026-05-29 straddle, whose gap *equalled* the implied move (a scratch at the open) but then trended cleanly to +28% intraday — the entire profit lived in the post-open trend, not the gap. The print before this (PATH 5/29) gapped −8% vs ~15% implied and reverted to green — there the open-sell *saved* the trade. Two prints, opposite right answers. Run the tree, don't reflex-sell.

**At 9:30, measure the realized gap** = (open − pre-print close) / pre-print close, and compare to the **implied move** (straddle debit ÷ spot, ≈ the Step-1 `get_iv_metrics` implied move). Then:

| At 9:30, the print... | Action |
|---|---|
| Gapped **inside** implied (\|gap\| < implied move) | **Close immediately.** The move didn't clear; crush + theta erode the rest. Accept 50-70% loss. *(PATH 5/29: −8% gap vs ~15% implied → loss at every width.)* |
| Gapped **≈ implied** AND stalling / fading off the open | **Sell at the open.** You captured the crush; no continuation juice left. *(Gap-and-fade — the open-sell saves you.)* |
| Gapped **≈ implied** BUT trending in the gap direction on strong volume, no reversal | **Hold / ride into the morning** (cap 1-2 days). The trend is the trade, not the gap. *(OKTA 5/29: +13.5% gap = straddle scratch → rode to +28% = +107% on the straddle; even one 15-min bar flipped it from scratch to ~+50%.)* |
| Gapped **>> implied** (already well past the move) | **Lock the win** — sell or trail a stop; the magnitude bet already paid. Optionally ride a clean trend ≤ 1-2 days. |

**Decision logic:** *gap clearing implied* is the go/no-go (inside → close, no exceptions); *momentum after the open* decides ride-vs-sell on everything that cleared. Confirm the trend with intraday tape (`get_timesales`, 15min) before riding. **Never hold to expiry; cap any ride at 1-2 days.** Source lesson: `memory/project_software_vol_mispricing.md` (Exit rules + 5/28 basket reconstruction).

## Final Output

**$ARGUMENTS.symbol Vol-Mispricing Grade**
- **Grade**: [A++ / A / B / Skip]
- **Bucket**: [enabler / displacement / commoditization]
- **Aggregate Δ-Skew**: [+X.XX] ([tier])
- **Event-week Δ-Skew**: [+X.XX] ([tier])
- **Directional read**: [bullish / bearish / symmetric vol]
- **Structure**: [specific: e.g., "Long 6/6 $90 / -$85 put spread, entry Wed 6/4 AM"]
- **Size**: [Full 1% / Half 0.5% / Skip]
- **Key risk**: [the one thing — bucket reclassification on the print, capital return surprise, etc.]
- **Add to basket**: Y/N — only Y if grade is A or A++ (B grade is judgment call when basket needs filling)
