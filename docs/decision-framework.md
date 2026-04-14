# Post-Screening Decision Framework

Every trade comes down to three questions: **Which**, **When**, and **How**.

- **Which** — What to trade. Driven by screening, thesis, and conviction. This happens upstream of this framework.
- **When** — When to enter or exit. Driven by signals: drawdown, IV environment, earnings proximity, momentum, thesis timeline.
- **How** — What structure to use. Driven by intent and signals: CSP vs direct buy, covered call vs hold, spread vs outright.

The relative weight of each question shifts by intent:

| Intent | Which | When | How |
|--------|-------|------|-----|
| Accumulate / Enter at discount | **Heaviest** | Important | Follows from signals |
| Directional leverage | Heavy | **Critical** | Follows from IV |
| Harvest premium | Lightest | **Heaviest** | Important |
| Bearish | Heavy | Important | Follows from IV |
| Covered call overlay | N/A (already own) | **Critical** | Follows from CC intent |

Conviction determines intent. Intent determines which signals matter (when). Signals determine strategy (how). The thesis is the thread connecting all three — and the hardest discipline is knowing when the thesis has genuinely evolved vs when greed or fear is rewriting it.

---

After screening confirms (or rejects) a thesis, run through these steps in order.

## Step 1: Determine Intent

Conviction drives intent. Intent drives strategy. Decide intent FIRST — everything else follows.

**Conviction inputs — what raises or lowers conviction:**

| Factor | High conviction | Low conviction |
|--------|----------------|----------------|
| **ROE** | >25% — elite capital efficiency (ADBE 62%). If D/E >3x, ROE is inflated by leverage — discount it (GDDY 384% ROE is buyback engineering, not profitability). | <15% — mediocre returns don't justify premium P/E |
| **Moat** | Monopoly/deep switching costs (ADBE creative suite) | Commodity, crowded market, active disruption threat |
| **Growth durability** | Recurring revenue, expanding TAM, secular tailwinds | Cyclical, geopolitical-dependent, or AI-threatened |

A stock can have a 50% drawdown and still deserve low conviction if the ROE is mediocre and the moat is under attack (WDAY, NOW). Conversely, a 30% drawdown on a 62% ROE monopoly is high conviction (ADBE). Drawdown alone is not conviction — the business quality determines whether the drawdown is an opportunity or a warning.

| Conviction | Intent | Goal | You're saying... |
|-----------|--------|------|-----------------|
| **Highest** | **Accumulate** | Own shares, full upside participation | "I want to own this stock now" |
| **High** | **Enter at discount** | Own shares at lower cost basis, premium is bonus | "I want to own this stock cheaper" |
| **High, time-specific** | **Directional leverage** | Leveraged bet on a near-term move with defined cost | "This stock is moving in the next 2-6 weeks" |
| **Moderate** | **Defined-risk exposure** | Bullish participation with capped downside | "I like this thesis but want to limit what I can lose" |
| **Low / Neutral** | **Harvest premium** | Extract income from range-bound or elevated IV | "I don't want to own this, I want to sell its volatility" |
| **Direction-agnostic** | **Bet on volatility** | Profit from large moves regardless of direction | "Something big is coming, I don't know which way" |
| **Negative** | **Bearish** | Profit from decline | "This stock is going down" |
| **N/A (existing position)** | **Hedge** | Protect current holdings | "I own this and want downside protection" |

## Step 2: Read the Signals

Collect these inputs — which ones matter depends on intent:

| Signal | How to measure | Source | Used by |
|--------|---------------|--------|---------|
| **Drawdown** | % below 52-week high | `get_quote` (52W High) | Accumulate, Enter at discount |
| **Revenue growth** | YoY quarterly revenue growth % | `get_income_statement` | Conviction (Step 1), Sizing via PEG (Step 4) |
| **Operating margin** | Operating income / revenue, and trend | `get_income_statement` | Conviction — expanding margins = moat, compressing = red flag |
| **ROE** | Net income / shareholders' equity | `get_basic_financials` | Conviction (Step 1) |
| **P/E** | Price / TTM earnings | `get_basic_financials` | Sizing via PEG (Step 4) |
| **IV-HV spread** | IV 30d minus HV 30d | `get_iv_metrics` | All option strategies |
| **IV Rank** | Current IV vs 52-week IV range | `get_iv_metrics` | Premium selling strategies |
| **Earnings proximity** | Days to next report | `get_iv_metrics` (Earnings) | All strategies |
| **Momentum** | RSI (14-day): <30 oversold/falling, >70 overbought. SMA 50 vs 200 for trend. | `get_technical_indicators` | Accumulate, Enter at discount |
| **Headwinds** | Active stock-specific risk | `get_company_news` | All strategies |
| **Expected move** | ATM straddle price at target expiry | `get_expected_move` | Vol bets, premium harvesting |

**Revenue growth and operating margin must be pulled from `get_income_statement`, not estimated from memory or articles.** These feed directly into PEG sizing (Step 4) and conviction (Step 1). Compare at least 2 quarters to identify the trend — a single quarter can mislead.

## Step 3: Choose Strategy

### Intent: Accumulate (highest conviction)

**Strategies:**

| Strategy | Mechanics | When to prefer | Capital required |
|----------|-----------|---------------|-----------------|
| **Direct buy** (scale-in tranches) | Buy shares in 2 tranches | Default for accumulation | Full notional |
| **LEAPS calls** (deep ITM, 80+ delta) | Buy 9-15 month calls | Capital-constrained, want leverage | ~20-30% of notional |
| **Synthetic long** (long call + short put, same strike) | Replicate ownership with options | Want share-equivalent exposure via options | Margin/collateral for short put |

**Decision matrix (Drawdown x IV-HV) — applies to direct buy and hybrid:**

|  | IV-HV < 5% (fair) | IV-HV 5-15% (moderate) | IV-HV > 15% (rich) |
|--|---|---|---|
| **>50% drawdown** | **Hybrid (direct-heavy)**: 60% shares + 40% CSP | **Hybrid (balanced)**: 40% shares + 60% CSP | **Hybrid (CSP-heavy)**: 30% shares + 70% CSP |
| **30-50% drawdown** | **Hybrid (light)**: 30% shares + 70% CSP | **CSP** | **CSP** |
| **<30% drawdown** | **Wait** or small starter only | **CSP** | **CSP** (best premium math) |

**Why hybrid is default for deep drawdowns:** Bounce timing is unknowable. Starter tranche captures unforecastable bounces; CSP provides discipline for the rest.

**Modifiers (shift within the matrix):**
- **Earnings <2 weeks**: Shift toward direct entry or wait for post-earnings
- **Earnings just passed**: Shift toward CSP — residual IV, event risk removed, best CSP window
- **Still falling**: Shift right (more CSP). No rush.
- **Bouncing**: Shift left (more direct). CSP risks missing the move.
- **Active headwind**: Shift right or wait entirely.

**When to use LEAPS instead of shares:**
- Multiple high-conviction names competing for same capital
- Stock price makes 100 shares expensive (>$15K notional) and you want exposure to several names
- Time horizon is 6-12+ months (LEAPS theta decay is slow)

**Auto-trigger: LEAPS vs shares comparison.** When Accumulate intent is selected and
100 shares would cost >$15K, proactively run a side-by-side comparison before
presenting the entry recommendation. Compare: capital required, delta exposure (per
dollar invested), break-even at expiry, theta cost per month, and max loss. The user
should not need to ask for this — surface it automatically.

### Intent: Enter at Discount (high conviction)

**Strategies:**

| Strategy | Mechanics | When to prefer | Capital required |
|----------|-----------|---------------|-----------------|
| **CSP** | Sell OTM put, collect premium | Default entry-at-discount method | Full strike notional (cash account) |
| **Wheel** (CSP -> CC -> repeat) | CSP -> assigned -> covered call -> called away -> CSP again | Ongoing income + entry/exit cycle on a name you'll keep trading | Full strike notional |
| **Put ratio spread** (sell 2 puts, buy 1 lower put) | Extra premium, partially defined risk | Aggressive discount, willing to own 200 shares | ~1.5x collateral |

**CSP strike selection by drawdown:**

| Drawdown | Strike target | Rationale |
|----------|--------------|-----------|
| >50% | **ATM to 5% OTM** | You want assignment. Deep discount already built in. |
| 30-50% | **5-10% OTM** | Balanced — assignment gives additional discount |
| <30% | **10-15% OTM** | Demand a real pullback before owning |

Conservative OTM strikes (>12%) on deeply drawdown stocks defeat the entry purpose — you likely expire worthless and just ran an income trade.

**Expiry rule:** Always sell THROUGH the nearest earnings date. Earnings IV is a feature — you either keep inflated premium or get assigned at an even better price. Never pick a pre-earnings expiry that wastes the IV.

| Earnings timing | Expiry selection |
|----------------|-----------------|
| Earnings within expiry window | Use it — capture the IV |
| Earnings >60 days away | Standard 30-45 DTE |
| Earnings just passed | 30-45 DTE from now (clean runway + residual IV) |

**CSP Roll Mechanics:**

Rolling CSPs follows the same principle as CCs — the decision comes before the economics. Ask: **should this CSP still exist?**

| Situation | Right move | Wrong move |
|-----------|-----------|------------|
| Stock approaching strike, thesis intact, want lower entry | **Roll down and out** for credit | Letting assign when better entry exists below |
| Stock approaching strike, you want assignment | **Let assign** — this was the plan | Rolling away from assignment when the CSP was an entry mechanism |
| Thesis broken, stock falling | **Buy back and walk away** — don't own this name | Rolling down to a lower strike on a broken thesis |
| Stock well above strike, CSP at >50% profit | **Buy back, write next cycle** | Holding for remaining pennies of premium |

**Roll direction:**
- **Roll down** when stock is falling toward strike and you want a better entry price
- **Roll out** (same strike, later expiry) when you want more time for the thesis to develop
- **Diagonal roll** (down + out) is most common — lower strike funded by additional time value

**Roll timing — the credit sweet spot (same as CCs):**
The best CSP roll credits happen when the stock is **near the put strike**. ATM puts have maximum extrinsic value — the old put is expensive to buy back, but the new put at a lower strike and later expiry collects enough premium from the extra time to produce a net credit. If the stock has already blown through the strike and is deep ITM, the roll becomes expensive or requires a debit.

**CSP roll rules:**
- **Always roll for a credit.** If the roll requires a debit, the stock moved too far — either take assignment or buy back and reassess.
- **Roll before earnings** if the CSP goes through an earnings date and you want to avoid assignment on a gap down without knowing fundamentals.
- **Don't roll a broken thesis.** Rolling down from $110P to $100P on a name you no longer want to own just moves the problem. Buy back and redeploy elsewhere.
- **Use `analyze_roll` to compare scenarios** — check 2-3 strike/expiry combinations.

### Intent: Directional Leverage (high conviction, time-specific)

The key difference from Accumulate/Enter at Discount: you have **timing conviction**, not just directional conviction. You believe a specific catalyst will move the stock within weeks, and you want leveraged exposure to that move without committing to long-term ownership.

**Strategies:**

| Strategy | Mechanics | When to prefer | Capital required |
|----------|-----------|---------------|-----------------|
| **Long call** | Buy OTM or ATM call | Clean directional bet, defined cost | Premium paid |
| **Call backspread** (buy 2 calls, sell 1 lower call) | Convex upside — small debit/credit, profits from explosive move up | Expect outsized move, want asymmetric payoff | Small net debit or credit |

**When to use:**
- Specific catalyst with timing (earnings beat, product launch, FDA ruling)
- Capital is constrained — CSPs tying up cash, can't commit $10K+ for shares
- Recovery snap play on deeply hammered name — want leveraged participation in a bounce
- L2-only environment — long calls are your only leveraged bullish tool before L3

**Key decision factors:**
- **IV-HV < 5%**: Options are fairly priced or cheap — long calls offer good value. This is the sweet spot.
- **IV-HV > 10%**: Options are expensive — you're overpaying for the call. Prefer CSP/BPS instead (sell the rich premium, don't buy it).
- **IV Rank < 30%**: Cheap vol environment — buying options is favorable.
- **IV Rank > 50%**: Expensive vol — selling strategies are better unless you have very high catalyst conviction.
- Long call: choose 40-60 delta for balanced leverage/probability. ATM for highest delta exposure, OTM for max leverage.
- Call backspread: best when IV is low and you expect a violent move. The sold call partially funds the 2 bought calls.
- **Expiry:** 2-4 weeks past the expected catalyst. Gives time for the move to play out without excessive theta decay.

**Critical distinction from LEAPS:** LEAPS (9-15 month, 80+ delta) replicate ownership. Near-term long calls (2-8 week, 40-60 delta) are directional bets. Don't confuse the two — LEAPS belong under Accumulate, long calls belong here.

**Management:**
- Set profit target at entry (e.g. 50-100% return on premium). Take profits — don't hold hoping for more.
- Time decay accelerates inside 14 DTE. If thesis hasn't played out by then, cut losses.
- If catalyst disappoints, exit immediately. Don't hold hoping for recovery — theta is destroying your position daily.

### Intent: Defined-Risk Exposure (moderate conviction)

**Strategies:**

| Strategy | Mechanics | When to prefer | Capital required |
|----------|-----------|---------------|-----------------|
| **Bull put spread** (credit) | Sell put + buy lower put | Bullish thesis, cap downside | Spread width |
| **Bull call spread** (debit) | Buy call + sell higher call | Bullish directional bet, defined cost | Net debit |
| **Poor man's covered call** (diagonal) | Buy LEAPS call + sell near-term OTM call | CC economics without owning shares | LEAPS cost |
| **Collar** (on existing shares) | Own shares + buy put + sell call | Lock in gains / protect existing position, cap both sides | Shares + net debit/credit |

**When BPS works as entry:** If stock finishes between strikes, short put assigns and long put expires worthless — same as CSP. Only diverges if stock blows through both strikes (max loss, no shares). Wide spreads ($30-40 wide) behave like CSP-with-a-floor for most scenarios.

**When to prefer bull call spread over BPS:** When you want defined cost upfront rather than assignment risk. Better for names you'd rather not own 100 shares of but want upside exposure.

**Key decision factors:**
- IV-HV > 10%: Favor credit strategies (BPS) — sell overpriced premium
- IV-HV < 5%: Favor debit strategies (bull call spread) — buy fairly priced options
- Capital constrained: BPS/bull call spread over CSP (fraction of collateral)
- Multiple pipeline names: Spreads let you run 5-10 positions vs 2-3 CSPs

### Intent: Harvest Premium (low conviction / neutral)

**Strategies:**

| Strategy | Mechanics | When to prefer | Capital required |
|----------|-----------|---------------|-----------------|
| **Iron condor** | Sell OTM put spread + sell OTM call spread | Range-bound thesis, collect premium both sides | Wider spread width |
| **Iron butterfly** | Sell ATM put + ATM call, buy OTM wings | Tighter range, higher credit, more risk | Spread width |
| **Butterfly** (all calls or all puts) | Buy 1 lower + sell 2 middle + buy 1 upper | Target price bet — max profit if stock pins at middle strike | Small net debit |
| **Calendar spread** | Sell near-term option + buy same-strike later-term | IV term structure play — front month IV > back month | Net debit |
| **Double diagonal** | Calendar with different strikes on each side | Wider profit zone than calendar | Net debit |

**When to use:**
- IV Rank > 50% (premiums worth selling)
- Stock in a defined range (support/resistance levels visible)
- No strong directional thesis — you think it stays put
- Post-earnings IV crush plays (sell inflated near-term IV)

**Key decision factors:**
- Iron condor: wider wings = less premium but higher probability of profit
- Iron butterfly: max profit if stock pins at center strike — rare but lucrative
- Butterfly: cheapest of all neutral strategies. Very high reward-to-risk if stock pins, but narrow profit zone. Best for "I think ADBE settles around $240 by May expiry" type thesis.
- Calendar: profits from time decay differential + IV mean reversion
- Avoid these on stocks you'd be happy to own — use CSP/direct instead

### Intent: Bet on Volatility (direction-agnostic)

**Strategies:**

| Strategy | Mechanics | When to prefer | Capital required |
|----------|-----------|---------------|-----------------|
| **Long straddle** | Buy ATM call + ATM put | Expect big move, direction unknown | Net debit (expensive) |
| **Long strangle** | Buy OTM call + OTM put | Cheaper straddle, needs bigger move | Net debit |
| **Reverse calendar** | Buy near-term + sell far-term same strike | Expect near-term IV spike | Net debit |

**When to use:**
- Pre-earnings on volatile names where you expect a move larger than the expected move
- IV Rank < 30% (options are cheap, buying vol is favorable)
- Major catalyst imminent (FDA approval, legal ruling, M&A decision)

**Key decision factor:** Compare expected move (`get_expected_move`) to your estimate. If you think the stock will move MORE than the straddle price implies, buy vol. If less, sell vol (harvest premium).

### Intent: Bearish (negative conviction)

**Strategies:**

| Strategy | Mechanics | When to prefer | Capital required |
|----------|-----------|---------------|-----------------|
| **Bear put spread** (debit) | Buy put + sell lower put | Defined-cost downside bet | Net debit |
| **Bear call spread** (credit) | Sell call + buy higher call | Collect premium on bearish thesis | Spread width |
| **Long put** | Buy OTM put | Simple directional, unlimited profit | Premium paid |
| **Put backspread** (sell 1 put, buy 2 lower puts) | Crash bet, small credit or small debit | Tail risk / blowup thesis | Net credit or small debit |

**When to use:**
- Thesis is explicitly bearish (CRWV pattern)
- Hedging portfolio beta (index puts on SPY/QQQ)

**Key decision factors:**
- IV-HV > 10%: Favor credit strategies (bear call spread) — sell overpriced premium
- IV-HV < 5%: Favor debit strategies (bear put spread, long put) — buy fairly priced
- Post-earnings gap-down play: Buy puts AFTER the gap to avoid IV crush (L2 strategy)
- Crash conviction: Put backspread — pay little or nothing, profit big on blowup

### Intent: Hedge (existing positions)

**Strategies:**

| Strategy | Mechanics | When to prefer | Capital required |
|----------|-----------|---------------|-----------------|
| **Protective put** | Buy put on existing shares | Direct insurance | Premium paid |
| **Collar** | Own shares + buy put + sell call | Funded hedge — CC premium pays for put | Net credit/debit |
| **Index puts** (SPY/QQQ) | Buy OTM puts on broad index | Portfolio-wide protection | Premium paid |

**When to use:**
- Approaching profit target but don't want to sell yet (tax reasons, thesis intact)
- Macro uncertainty — protect gains without exiting
- Collar: when you're willing to cap upside to fund the hedge

## Step 4: Size the Position

Base sizing on **growth-adjusted valuation** (PEG) and **portfolio concentration**:

**How to calculate PEG:**
1. Pull `get_income_statement` — get the most recent quarter's revenue and the same quarter from the prior year.
2. Calculate YoY revenue growth: `(current_quarter - same_quarter_prior_year) / same_quarter_prior_year × 100`.
3. PEG = P/E (from `get_basic_financials`) ÷ YoY revenue growth %.
4. Use **revenue growth**, not earnings growth — earnings are volatile on high-growth names due to stock comp, one-time charges, and investment cycles. Revenue growth is the more stable signal.
5. If growth is negative or near-zero, PEG is meaningless — fall back to raw P/E sizing (P/E <15x Full, 15-25x Standard, >25x Reduced).

| PEG | Position size | Rationale |
|-----|--------------|-----------|
| <1.5 | **Full** (2 contracts / 200 shares) | Paying less than fair value for growth (ADBE PEG ~1.2) |
| 1.5-3.0 | **Standard** (1 contract / 100 shares) | Fair value for growth (NOW PEG ~2.4) |
| >3.0 | **Reduced** (1 contract or 50 shares) | Overpaying for growth (PLTR PEG ~6.7) |

**P/E hard cap:** Regardless of PEG, never full-size above 80x P/E — extreme multiples amplify downside on any growth deceleration.

**Additional sizing rules:**
- Never allocate >15% of portfolio to a single name at entry
- Always reserve cash for T2 scale-in (don't deploy 100% on T1)
- If running multiple CSPs, total collateral should not exceed 60% of cash account
- Spreads allow more positions — reallocate freed capital across pipeline names
- **Limit new entries to 5-7 names per month.** In March 2026, 18 names were bought in 10 days — the shotgun approach diluted conviction and made it impossible to size properly. Run each name through Steps 1-4 before adding the next.

**Size for the drawdown, not just the upside.** Before entering, ask: "If this drops 40% over 2 months, will the dollar loss force me to sell?" If yes, the position is too large. The ALAB lesson: a $182 entry on a volatile semi name should have been half-size or structured with a CC, because the eventual -45% drawdown created a $14K emotional breaking point that forced a thesis-correct exit. Size so that the worst-case drawdown is painful but survivable without triggering an emotional sell.

## Step 5: Set Management Rules

### Accumulate / Enter at discount:
- **CSP:** Close at 50% profit. If assigned, evaluate covered call overlay (wheel).
- **Direct shares:** No hard stop losses on high-conviction entries. Scale-in T2 triggers at 5-8% drop from T1.
- **If approaching CSP expiry ITM:** Let assignment happen if thesis intact. Only roll if thesis deteriorated.
- **Reassess thesis** if position drops >15% from entry — check fundamentals, not just price.

### Directional leverage:
- **Long call:** Set profit target at entry (50-100% return on premium). Take profits, don't diamond-hand.
- **Call backspread:** Let ride if move is developing. Close if stock stalls — time decay on 2 long legs hurts.
- **Both:** Exit immediately if catalyst disappoints. Cut losses inside 14 DTE — theta acceleration destroys value.

### Defined-risk exposure:
- **BPS:** Close at 50% of max profit or when short leg reaches 80% profit.
- **Bull call spread:** Let ride toward expiry if directional thesis intact. Close if underlying breaks below support.
- **PMCC:** Manage short call — roll up and out if challenged. LEAPS is the anchor.

### Harvest premium:
- **Iron condor/butterfly:** Close at 50% of max profit. Adjust or close tested side if underlying approaches short strike.
- **Calendar:** Close when near-term option decays to target or IV differential narrows.

### Bearish:
- **Bear spreads:** Close at 50-75% of max profit. Don't hold to expiry hoping for max.
- **Long puts:** Set profit target (e.g. 100% return on premium). Time decay is working against you.

### All strategies:
- **Exit signal:** Thesis broken (not price action). Revenue deceleration, margin collapse, competitive disruption, management change.
- **Covered call overlay** once shares are held: sell 30-45 DTE calls at 10-15% OTM for income.

### Thesis Checkpoint: When a Position Drops >15%

Don't watch the ticker and feel pain. Run this checklist:

1. **Is the end customer still spending?** Check the demand environment upstream of your company. If the buyers of your company's products are still deploying capital, the thesis is intact.
2. **Is this company-specific or sector-wide?** When the entire sector is down, the problem is macro, not your stock. Company-specific drawdowns need more scrutiny. Sector-wide drawdowns are usually noise.
3. **Has the competitive moat actually narrowed?** Check for concrete evidence: lost customers, cancelled contracts, actual product displacement by a competitor. A narrative shift in financial media is not the same as lost revenue. Narrative ≠ reality.
4. **Is the thesis timeline still valid?** A 2-month drawdown inside an 18-month thesis is noise, not signal. If the thesis hasn't had time to play out, price action alone isn't a reason to exit.
5. **Would I buy this at today's price if I had no position?** Strip away anchoring to your entry. If the thesis was buyable at $182, it's *more* buyable at $100. The only thing that changed is your P&L, not the company.

If all five pass → hold or add. If any fail → exit regardless of price.

**Example — ALAB (Apr 2026):** All five passed. Hyperscaler capex still growing, sector-wide drawdown (not ALAB-specific), no competitive moat change, thesis timeline intact (semi cycle through mid-2027), stock was cheaper by every metric. The exit at $125 was emotional, not analytical. Stock ripped 29% in the 4 days after selling.

**Example — CRDO (Mar 2026):** Arguably harder — had a specific narrative headwind ("optical replaces copper"). But all five still passed: customers still shipping AECs, Nvidia said "both copper AND optical," patent settlements proved the tech was valuable, semi cycle timeline intact. Held through -30%. Recovered +53% from the low. DustPhotonics acquisition later removed the narrative risk entirely.

### Selling Into Strength vs Selling Into Recovery

These look similar on a chart but are psychologically opposite:

**Selling into strength:** Your position is working. The stock is at or near highs, and you're taking profits because the price has reached a level where you're happy to sell. *You're selling because the stock went up.*

- LITE: Bought $650 → sold tranches at $692, $780, $790, $910. Each sell was higher than the last.
- XLE: Bought $56.60 → sold $60.30. Clean exit at a profit target.

**Selling into recovery:** Your position was deeply underwater. The stock bounced partially, and you sell because the bounce gave you a "chance to get out" — not because you've reached a profit target. *You're selling because the stock stopped going down.*

- ALAB: Bought $182 → ground to $100 (-45%) → bounced to $129 → sold. The recovery brought relief, not confidence. The sell was about exhaustion, not analysis.

**The diagnostic test:** "Am I selling because I've won, or because I've survived?"

| | Selling into strength | Selling into recovery |
|---|---|---|
| Position P&L | Green or solidly profitable | Still red or barely recovered |
| Motivation | "I've hit my target" | "I can finally get out" |
| Emotion | Confidence, maybe mild FOMO | Relief, exhaustion |
| Usually right? | Yes — disciplined profit-taking | Usually wrong — you paid the full emotional cost of the drawdown but captured none of the recovery |

**The rule:** If you held from $182 to $100 and survived the worst, a bounce to $129 should confirm the thesis, not trigger an exit. The crash is the tax. The recovery is the refund. Selling into a recovery is paying the tax and walking away before the refund arrives.

---

## Covered Call Overlay Framework

Once you own shares, the covered call decision is its own framework. Steps 1-5 above answer "how do I get in?" — this section answers "when and how do I sell calls against my holdings?"

The core tension: every covered call is a bet that the stock WON'T exceed the strike by expiry. If you're wrong, you left money on the table. If you're right, you collected free premium. The skill is knowing which regime you're in.

### CC Step 1: Determine CC Intent

CC intent is independent of entry intent. A stock you accumulated with highest conviction can later become a thesis exit. Intent can evolve.

| Intent | Goal | You're saying... |
|--------|------|-----------------|
| **Thesis exit** | Align exit timing with macro/sector/cycle thesis | "I want out by this date at this price" |
| **Income generation** | Recurring premium on range-bound or slow-growth names | "I'll collect rent while holding" |
| **Growth with income** | Premium income while maintaining partial upside on winners | "Still bullish but want to get paid while waiting" |
| **Orderly liquidation** | Exit a position efficiently with premium kicker | "I'm done with this name" |

### CC Step 2: When to Write

**Timing triggers:**
- **After accumulation is complete** — don't sell calls while still building a position. Finish buying first.
- **Post-earnings** — best CC window. Fundamentals are known, residual IV inflates premiums, no gap risk for 3 months.
- **IV Rank > 30%** — premiums worth the capped upside. Below 30%, you're giving away upside for pennies.
- **Thesis timeline becomes clear** — when you can articulate "I want out by [date]", that's a CC trigger.

**When NOT to write:**
- **Still accumulating** — competing with yourself. The CC caps the very upside you're buying into.
- **Pre-catalyst with bullish conviction** — earnings, product launch, macro shift. If you expect a pop, don't cap it.
- **IV Rank < 25%** — premiums too thin to justify capped upside. Exception: thesis exits where timeline matters more than premium.
- **Deep underwater (>20% below cost basis)** — you'd have to sell calls below cost to get meaningful premium. Wait for recovery or reassess the position entirely.
- **First 2 weeks after entry** — give the position time to breathe. Exception: buy-writes where the CC was always part of the plan.

### CC Step 3: Coverage Ratio

How many shares to cover determines how much upside you retain. This is the most underrated CC decision.

| Forward conviction | Coverage | Rationale |
|---|---|---|
| Exit / declining thesis | **100%** | Full exit intended — cap everything |
| Range-bound / neutral | **75-100%** | Income-focused, OK with full assignment |
| Still bullish, want income | **50-75%** | Uncovered shares ride freely |
| High conviction, expect breakout | **0-25%** or skip | Don't cap your winners |

**Rule of thumb:** If you'd be upset getting called away at the strike, you're covering too many shares.

**Partial coverage is a feature, not indecision.** Keeping 15-30% of shares uncovered on growth names gives you:
- Upside participation if the stock rips (CRDO +12% today — 86 uncovered shares captured it)
- Psychological comfort to hold the covered portion without second-guessing
- Flexibility to write additional CCs later if conviction changes

**CCs as emotional armor.** Beyond income and exit timing, CCs serve a critical psychological function: they make drawdowns survivable. CRDO with a $150C Jan '27 CC held through a -30% drawdown; ALAB with no CC was sold at -29% for a $14K loss. Same thesis quality, different outcome — because the CC premium cushioned the felt loss enough to prevent an emotional exit. For volatile positions where you intend to hold through a multi-month thesis, writing a CC at entry (or shortly after) isn't just about income — it's about ensuring you can stick to the plan.

### CC Step 4: Strike Selection

| CC Intent | Strike Target | Rationale |
|-----------|--------------|-----------|
| **Thesis exit** | **Your exit price** | The strike IS the exit — pick where you'd sell outright |
| **Income generation** | **10-15% OTM** | High probability of expiring worthless, small steady premium |
| **Growth with income** | **8-12% OTM** | Enough room for modest appreciation, decent premium |
| **Orderly liquidation** | **ATM to 5% OTM** | You want assignment — maximize premium on the way out |

**Modifiers:**
- **Underwater position (cost > current price):** Never sell calls below your cost basis unless you're intentionally liquidating at a loss. A CC that locks in a guaranteed loss is worse than no CC.
- **Post-earnings:** Strike can be tighter (closer to ATM) — event risk is gone, fundamentals are known, less chance of a gap.
- **Pre-earnings:** Sell THROUGH earnings to capture elevated IV — crush works in the CC seller's favor. Or wait until after. Never sell a pre-earnings expiry with a tight strike — gap risk.
- **Technical resistance:** If the stock has a clear ceiling (e.g., prior high, round number), use it as a natural strike.

### CC Step 5: Expiry Selection

| CC Intent | Expiry | Rationale |
|-----------|--------|-----------|
| **Thesis exit** | **Match thesis timeline** | Semi cycle = Dec 2026 / Jan 2027. Expiry IS the exit schedule. |
| **Income generation** | **30-45 DTE, rolling** | Theta decay sweet spot. Roll at 50% profit or 14 DTE remaining. |
| **Growth with income** | **45-90 DTE** | Longer than pure income — fewer rolls, more premium per cycle. |
| **Orderly liquidation** | **30-60 DTE** | Near-term, get it done in one cycle. |

**Earnings interaction:**

| Earnings timing | CC expiry rule |
|----------------|----------------|
| Earnings within 2 weeks | **Wait** — don't write before a potential gap up |
| Earnings 3-6 weeks away | Sell THROUGH earnings if income intent (capture IV premium) |
| Earnings just passed | **Best window** — write immediately. Known fundamentals + residual IV |

### CC Step 6: Management

| Situation | Action |
|-----------|--------|
| CC at **50% profit** (income intent) | Buy back, reassess, write next cycle |
| CC at **80%+ profit** (any intent) | Buy back — remaining premium isn't worth the risk of reversal |
| Stock **approaching strike** (income/growth) | Roll up and out for credit if still bullish. Let assign if neutral. |
| Stock **approaching strike** (thesis exit) | **Let it happen.** The strike was your target. Don't roll. |
| Stock **drops significantly** after writing | CC is winning. Buy back at 80%+ profit, reassess thesis before writing another at lower strike. |
| **Earnings approaching** with short-term CC | Buy back if <50% profit realized — gap risk isn't worth remaining premium |
| **Thesis changes** fundamentally | Roll strike/expiry to match new thesis, or buy back entirely to remove the cap |

**The cardinal sin: thesis drift disguised as conviction.**

Rolling a thesis-exit CC further out because the stock is doing well is not disciplined — it's FOMO. If your thesis said "exit by Dec 2026," don't roll to Jun 2027 because the stock pumped. You need a genuine NEW reason to stay (new product cycle, new market, changed competitive landscape), not just "it's going up."

The one valid exception: when your fundamental thesis has genuinely evolved. AMZN $225C Jun → $250C Dec was a valid roll because the broader AI capex thesis strengthened and the roll was done for a credit. But "CRDO ripped 12% today" is not a thesis change — it's a data point that confirms the existing thesis is working, which means the CC is doing exactly what it was designed to do.

**Practical test:** Before rolling a thesis-exit CC, ask: "Would I buy this stock at today's price with the same position size?" If the answer isn't an enthusiastic yes, let the CC do its job.

### CC Step 6b: Roll Mechanics

Rolling is a tool, not a reflex. Before looking at roll economics, ask: **should this CC still exist?**

| Situation | Right move | Wrong move |
|-----------|-----------|------------|
| Thesis exit, stock approaching strike | **Let assign** — the strike was your exit price | Rolling because "it's going up" (thesis drift) |
| Growth with income, stock approaching strike | **Roll up and out** — you want to keep the position | Letting assign when you still want the shares |
| Thesis broken, stock falling | **Buy back CC, sell shares** — exit the whole position | Rolling down to a lower strike on a broken thesis |
| Income/wheel, stock falling | **Roll down for credit** — reset the wheel at a lower strike | Holding a high strike that earns no premium |

**When to roll (direction):**
- **Roll up** when stock is rising and you want to keep the position (growth with income intent)
- **Roll down** when stock has fallen and you want to reset premium income (income/wheel intent)
- **Roll out** (same strike, later expiry) when you want more time for the thesis to play out
- **Diagonal roll** (up + out) is the most common — gives both more upside room and more time

**Roll timing — the credit sweet spot:**
The best roll credits happen when the stock is **near the current strike**. ATM options have the highest extrinsic (time) value, so the old CC is expensive to buy back — but the new CC at a higher strike and later expiry is even more expensive because of the additional time. The net difference is your credit.

If the stock is far below the strike, both the old and new CC are cheap OTM options — rolling from one cheap option to another produces a small credit. Don't wait for the stock to fall away from the strike before rolling; the economics get worse.

**Roll rules:**
- **Always roll for a credit** on CCs. If the roll requires a debit, the stock has moved too far past the strike — either let assign or accept the cap.
- **Roll before earnings** if the CC goes through an earnings date and you expect a beat. After a gap up, the cost to close spikes and the roll credit shrinks or becomes a debit.
- **Roll to a thesis-aligned expiry.** A roll that extends past your thesis end date is not a roll — it's a new position. Apply the practical test.
- **Use `analyze_roll` to compare scenarios.** Check 2-3 strike targets and pick the one that balances credit received vs upside room.

### Chain P&L: The Hidden Cost of Rolling

**The 50% rule on a rolled position can be misleading.** "50% profit on the current leg" is not the same as "profitable chain." When you roll multiple times, you must track the **total chain credits** — the sum of all net credits received across every roll — not just the current leg's premium.

**Chain P&L rules (applies to both CCs and CSPs):**

1. **Track total chain credits** for every rolled position: sum of original premium + all net roll credits.
2. **Chain breakeven** = total chain credits. If the buyback exceeds this, the option chain lost money regardless of what the current leg shows.
3. **A losing CC chain is fine if shares won more.** The total covered position (shares + CC chain) is what matters. Rolling up means you chose share upside over CC profit — that's intentional, not a mistake.
4. **A losing CSP chain is a warning.** Rolling a CSP down repeatedly means the stock kept falling through your strikes. If the total chain credits are less than the final buyback cost, you paid more to avoid assignment than you collected. Ask: would taking assignment at the original strike have been better?
5. **When the chain loss exceeds the benefit, stop rolling.** If the CC chain loss is larger than the additional upside room captured (stock didn't actually rally to justify the rolls), the rolls were a mistake. Let the next CC assign or buy back and reassess.

See [decision-framework-retro.md](decision-framework-retro.md) for the AMZN chain P&L worked example.

### CC Step 7: Interaction with Macro Thesis

When you have a sector-level thesis (like the semi cycle), covered calls become the execution mechanism for an orderly exit. The thesis sets the timeline, the CC enforces it.

**Key rules for thesis-driven CCs:**
- **Stagger expiries** across the thesis timeline — don't put everything in the same month
- **Don't roll past the thesis end date** — if AI capex peaks mid-2027, Jan 2027 is the latest CC expiry
- **Accept that some names will run past the strike** — that's the price of discipline. You can't time the exact top.
- **Redeploy proceeds into the next thesis** — when semis get called away, CSP into Phase 3 software/application winners
