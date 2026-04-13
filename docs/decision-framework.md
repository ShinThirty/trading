# Post-Screening Decision Framework

After screening confirms (or rejects) a thesis, run through these steps in order.

## Step 1: Determine Intent

Conviction drives intent. Intent drives strategy. Decide intent FIRST — everything else follows.

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
| **IV-HV spread** | IV 30d minus HV 30d | `get_iv_metrics` | All option strategies |
| **IV Rank** | Current IV vs 52-week IV range | `get_iv_metrics` | Premium selling strategies |
| **Earnings proximity** | Days to next report | `get_iv_metrics` (Earnings) | All strategies |
| **Momentum** | Recent price action — falling, flat, bouncing | `get_quote` + multi-day context | Accumulate, Enter at discount |
| **Headwinds** | Active stock-specific risk | `get_company_news` | All strategies |
| **Expected move** | ATM straddle price at target expiry | `get_expected_move` | Vol bets, premium harvesting |

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

**Why hybrid is default for deep drawdowns:** Bounce timing is unknowable. On April 10, 2026 (Friday), ADBE/WDAY/NOW/PAYC were grinding lower — CSPs looked right. By Monday April 13, all bounced 5-7%. Starter tranche captures unforecastable bounces; CSP provides discipline for the rest.

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

Base sizing on **valuation risk** (P/E) and **portfolio concentration**:

| P/E | Position size | Rationale |
|-----|--------------|-----------|
| <20x | **Full** (2 contracts / 200 shares) | Valuation provides margin of safety |
| 20-35x | **Standard** (1 contract / 100 shares) | Fair value — standard risk |
| >35x | **Reduced** (1 contract or 50 shares) | Paying a premium — limit exposure |

**Additional sizing rules:**
- Never allocate >15% of portfolio to a single name at entry
- Always reserve cash for T2 scale-in (don't deploy 100% on T1)
- If running multiple CSPs, total collateral should not exceed 60% of cash account
- Spreads allow more positions — reallocate freed capital across pipeline names

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

## Quick Reference: Case Studies

| Stock | Date | Drawdown | IV-HV | Method Used | Optimal Method | Lesson |
|-------|------|----------|-------|------------|----------------|--------|
| ADBE | 4/13 | -44% | -2.6% | Pure CSP $220P | Hybrid (direct-heavy) | Low IV-HV = CSP doesn't overpay you |
| WDAY | 4/13 | -56% | +4.8% | Pure CSP $105P | Hybrid (direct-heavy) | 12.6% OTM too conservative for entry intent |
| NOW | pipeline | -58% | -2.4% | Pending | Hybrid (direct-heavy) | Same pattern as ADBE — IV fairly priced |
| PAYC | pipeline | -56% | +15.9% | Pending | Hybrid (balanced) | Rich IV-HV justifies more CSP weight |
| QCOM | pipeline | -37% | +17.2% | Pending | Pure CSP | Moderate drawdown + rich premium |
| FTNT | pipeline | -28% | +18.6% | Pending | Pure CSP + wait | Shallowest drawdown + active headwind |
