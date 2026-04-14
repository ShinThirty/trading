# Strategy Catalog

Detailed strategy mechanics for each intent. Referenced from [decision-framework.md](decision-framework.md) Step 3.

---

## Intent: Accumulate (highest conviction)

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

---

## Intent: Enter at Discount (high conviction)

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

---

## Intent: Directional Leverage (high conviction, time-specific)

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

---

## Intent: Defined-Risk Exposure (moderate conviction)

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

---

## Intent: Harvest Premium (low conviction / neutral)

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

---

## Intent: Bet on Volatility (direction-agnostic)

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

---

## Intent: Bearish (negative conviction)

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

---

## Intent: Hedge (existing positions)

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
