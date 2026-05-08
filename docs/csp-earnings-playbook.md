# CSP-as-Earnings-Play Playbook

The [decision framework](decision-framework.md) covers CSPs as an entry mechanism. This doc covers the specific tactical pattern of **using CSPs to capture event volatility** — selling premium into a known earnings catalyst with the intent to either keep the premium (vega/theta tailwind from IV crush) or get assigned at an acceptable cost basis.

This is a different optimization than a "regular" CSP. The catalyst window changes the variables: vol expands and crushes, the directional uncertainty is concentrated, and the optimal DTE/strike differ from the standard 30-45 DTE / 0.20-0.30 delta default.

## When CSP works for an earnings catalyst

CSPs are a favorable risk/reward earnings structure relative to long calls/puts/straddles because they're vega-positive (IV crush helps), theta-positive (time decay helps), and have a defined acceptable secondary outcome (assignment). But "favorable" requires several conditions to hold simultaneously.

**Required conditions:**

| Factor | Required | Why |
|---|---|---|
| **Conviction** | Genuinely want to own at the strike | Assignment is plan B, not disaster — this is a hard gate |
| **IV Rank** | >50%, ideally 70%+ | Pre-event vol expansion = pumped premium; below 50% premium isn't worth the event risk |
| **DTE** | 30-50 days | Captures vega exposure for IV crush + post-event theta runway |
| **Strike** | At or below 1 expected move OTM | Cushion against the adverse move; "happy to own" pricing |
| **Entry timing** | 1-2 weeks pre-event | Peak vol, fresh setup signals, not too far out |
| **2W tape** | Flat to negative | A pre-print rally has already reset expectations (see disqualifiers) |

**Strong fit names:**
- Mature companies with structural moats (margins, distribution, switching costs)
- Stable cash generation (FCF positive, growing)
- Bear narrative active but not yet validated by financials
- Down 30%+ from highs (premium is fattest when fear is highest)

## When CSP DOES NOT work for an earnings catalyst

Five disqualifiers — any one of these kills the trade regardless of how good the other conditions look:

1. **Front-Run Catalyst** (>8% rally in the 2 weeks before earnings)
   - Expectations have already moved. The print needs to surprise the new bar, not the old depressed bar.
   - Canonical example: **NOW Apr 22, 2026** — strong print (beat high end, raised FY) crashed -17.7% next day because stock had rallied +20% from $83 to $103 in the prior 2 weeks. The +20% pre-print rally disqualified the bounce setup despite the -52% longer-term drawdown.
   - Action: skip the trade or wait for post-event reset.

2. **Binary tail risk in the underlying**
   - Biotech with FDA catalyst, single-product company with regulatory cliff, or other names where one event can move the stock 50%+
   - CSPs don't protect against a -50% gap; the assignment-as-plan-B logic breaks
   - Action: defined-risk structure (bull put spread) or skip.

3. **Thesis materially deteriorating**
   - If recent industry data (peer earnings, macro signals, regulatory news) actively confirms the bear case, "I'd happily own" doesn't hold.
   - Action: re-evaluate position sizing first; CSP is downstream of conviction.

4. **IV Rank <50%**
   - Premium isn't pumped enough to compensate for event risk.
   - Action: skip, or wait for pre-event vol expansion.

5. **No genuine want to own at the strike**
   - The "I'd happily own" gate is non-negotiable. If the strike is below your real conviction price, you're not selling a CSP — you're selling a naked put with optimism.
   - Action: lower the strike until "happily own" is true, or skip.

## Optimal DTE — why 30-50 days, not the shortest possible

A common misconception is "shortest DTE = max premium = best earnings play." The math says otherwise.

| DTE bucket | Premium ($) | Annualized yield | Vega exposure | Post-event theta runway | Trade quality |
|---|---|---|---|---|---|
| **0-14 DTE (next weekly post-event)** | Low absolute | High % annualized | Moderate vega — most crushed by IV crush | None | Binary on event outcome, no margin for error |
| **30-50 DTE** | Healthy | Strong annualized | High vega — captures IV crush as P&L | Meaningful runway if stock drifts | **Sweet spot** |
| **60-90 DTE** | Highest absolute | Lower annualized | Highest vega but more time exposed | Long runway | Ties up capital longer; better when IV is exceptionally rich |
| **>90 DTE** | Highest absolute | Weak annualized | Most vega exposure | Very long runway | Treat as standard CSP, not event play |

**Why 30-50 DTE wins:** meaningful vega (you actually capture IV crush as P&L), 3-4 week post-event theta runway if the stock drifts adversely, and management room (close at 50% early or roll if thesis breaks). Short DTE has high annualized yield but small absolute dollars — the "max premium" heuristic conflates the two.

## Strike selection

The strike is where you'd genuinely want to own the stock — not where the premium looks fattest. Three checks:

1. **Delta target**: 0.25-0.40 for event CSPs (slightly more aggressive than standard 0.20-0.30 because the IV crush is part of the P&L)
2. **Cushion**: at least 1 expected move OTM (read from `get_expected_move`)
3. **Bid-ask spread**: strikes with wide spreads (>10%) eat into the math; prefer round-number strikes with deep open interest

Example for INTU $360P Jun 19 ($388.50 spot, 50 DTE):
- Delta: -0.32 (just inside the 0.25-0.40 band)
- Cushion: 7.4% OTM (above the ~6% expected move)
- Spread: $1.30 wide (6.7% of mid — clean)
- Premium: $19.45 mid = $1,945 per contract
- Annualized: 39.5%

The $370P would have collected more premium ($24.15) but the bid-ask spread was $3.30 (14% of mid) and cushion was thinner. Net risk-adjusted yield was actually better at $360.

## Entry timing — wait for vol expansion

Pre-event IV typically peaks 7-14 days before the event. Selling earlier than that leaves premium on the table; selling later than that compresses your management runway.

**Optimal window:** event date - 14 days through event date - 7 days.

This window also coincides with when the **2W tape disqualifier check** is most informative (the rolling 2W rally is being measured against the moment of entry).

**Process:**
1. Identify candidates 4-6 weeks pre-event (drawdown + narrative + IV signals)
2. Hold for 2-3 weeks while monitoring the 2W tape
3. Enter the CSP in the optimal window if the disqualifiers haven't fired
4. Hold through the event (this is the whole point — IV crush is the alpha)
5. Manage post-event per management rules below

## Sizing

Standard tier per the [decision framework](decision-framework.md) Step 4. Event CSPs do NOT justify upsizing because the asymmetry IS the conviction — you're already getting more for the trade than a regular CSP would offer.

If the name is already in the portfolio (existing shares, LEAPS, or a CSP at a different strike), the event CSP is **incremental exposure to manage**, not a fresh sleeve. Verify that total notional + delta exposure stays within tier limits.

CSP collateral discipline still applies: total CSP collateral ≤60% of cash account.

## Management

The event CSP has a different management profile than a standard 30-DTE CSP:

| Trigger | Action | Why |
|---|---|---|
| **50% profit hit pre-event** | Hold through event anyway | The IV crush is the alpha you sold for; closing pre-event leaves it on the table |
| **50% profit hit immediately post-event** | Close | IV crush captured, no reason to stay short the residual |
| **Stock drops to strike pre-event** | Hold; reassess after event | Vol may compress your loss after the event removes uncertainty |
| **Stock crashes >15% pre-event** | Reassess thesis; consider rolling down/out for credit if thesis intact | Front-running thesis breakdown; don't add to a losing thesis |
| **Stock at strike at expiry** | Take assignment | Assignment is the plan B — execute it |
| **Stock above strike at expiry** | Let expire worthless | Full premium captured |

**Hard rule: never close a winning event CSP pre-event for "safety."** The whole reason you sold the CSP was to capture the IV crush. Closing pre-event for a 30% gain locks in the wrong half of the trade.

## Cross-reference

This is the structural recommendation for: the **Expectation Reset Pattern** (depressed quality + known catalyst), **Accumulate intent with elevated IV** (per the Decision Matrix when IV-HV >15% and drawdown meaningful), and **wheel strategy entries** with assignment-as-feature.

Does NOT apply to: premium harvesting on neutral-conviction names (use iron condors), bearish setups (bear call spreads), or highest-conviction Accumulate where you want shares immediately (direct buy or share-dominated hybrid).

## Worked examples

**TEAM Apr 2026 (qualified):** -72% drawdown, IV Rank 94%, 2W tape +2.5% (no Front-Run), "AI Casualty" narrative active. Print: +24% AH gap, IV crushed ~80% → ~35%. A 30-50 DTE CSP at -8 to -12% cushion would have captured most premium overnight.

**NOW Apr 2026 (disqualified — Front-Run):** -52% drawdown ✓, IV elevated ✓, but **2W tape +20%** killed the setup. Stock had rallied $83 → $103 pre-print on AI narrative; the objectively strong print (beat high end, raised FY) still crashed -17.7% next day because cRPO deceleration hit re-inflated expectations. Lesson: the 2W tape disqualifier overrides an attractive long-term drawdown.
