# Strategy Catalog

Detailed strategy mechanics for each intent. Referenced from [decision-framework.md](decision-framework.md) Step 3.

---

## Intent: Accumulate (highest conviction)

**Strategies:**

| Strategy | Mechanics | When to prefer | Capital required |
|----------|-----------|---------------|-----------------|
| **Direct buy** (scale-in tranches) | Buy shares in 2 tranches | Default for accumulation | Full notional |
| **LEAPS calls** (deep ITM, 80+ delta) | Buy 9-15 month calls | Capital-constrained, want leverage | ~20-30% of notional |
| **Poor man's covered call** (diagonal) | Buy LEAPS call + sell near-term OTM call | Capital-efficient accumulation with income overlay | LEAPS cost |
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

**Binary events (earnings is a feature, not a threat):**
At highest conviction, both outcomes serve you — a beat accelerates the thesis, a miss gives a cheaper entry. The modifiers above already handle timing (shift toward direct entry or wait pre-earnings, shift toward CSP post-earnings). One addition: **LEAPS through earnings** carry vega risk. Deep ITM LEAPS (80+ delta) have lower vega than ATM, but a 10-point IV crush still hits. If holding LEAPS through earnings, verify that your break-even can absorb the expected move's worth of IV crush — don't assume high delta insulates you completely.

---

## Intent: Enter at Discount (high conviction)

**Strategies:**

| Strategy | Mechanics | When to prefer | Capital required |
|----------|-----------|---------------|-----------------|
| **CSP** | Sell OTM put, collect premium | Default entry-at-discount method | Full strike notional (cash account) |
| **Wide BPS as entry** | Sell put + buy lower put ($30-40 wide) | CSP with a floor — want assignment but cap worst-case | Spread width |
| **Put ratio spread** (sell 2 puts, buy 1 lower put) | Extra premium, partially defined risk | Aggressive discount, willing to own 200 shares | ~1.5x collateral |

**CSP-as-entry intent check:** The CSP here is a limit order that pays you to wait — you *want* assignment. If you find yourself picking far-OTM strikes to maximize probability of expiring worthless, you've drifted into income mode. Reclassify to Harvest Premium and use the Wheel or iron condor instead. The diagnostic question: **do you want to own the shares at this strike?** If yes, this is the right section. If no, you're selling volatility, not entering a position.

**Wide BPS as entry:** If the stock finishes between strikes, the short put assigns and the long put expires worthless — identical to a CSP. The long put only matters if the stock blows through both strikes, capping your max loss. Use $30-40 wide spreads for CSP-like behavior with a floor. Narrower spreads shift toward defined-risk (see Defined-Risk section).

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
- **Roll for a credit when possible.** If the roll requires a debit, run the debit budget analysis (see [covered-call-overlay.md](covered-call-overlay.md#debit-roll-rules)) — same three gates apply: chain budget ≤ 50%, debit < assignment cost, thesis intact.
- **Roll before earnings** if the CSP goes through an earnings date and you want to avoid assignment on a gap down without knowing fundamentals.
- **Don't roll a broken thesis.** Rolling down from $110P to $100P on a name you no longer want to own just moves the problem. Buy back and redeploy elsewhere.
- **Use `analyze_roll` to compare scenarios** — check 2-3 strike/expiry combinations. Pass `chain_credits` for automatic debit budget verdicts.

**Binary events (earnings is a feature, not a threat):**
The "sell through earnings" expiry rule already captures this — earnings IV is premium you get paid for. Both outcomes serve the entry intent: stock holds up and you keep inflated premium, or stock gaps down and you get assigned at a deeper discount. The only risk is a thesis-breaking report. After every earnings report that your CSP spans, re-check the thesis (margins, guidance, revenue trajectory). If the thesis survived, the CSP is working as designed. If the thesis broke, buy back immediately — don't let a broken CSP assign you on a name you no longer want to own.

---

## Intent: Directional Leverage (high conviction, time-specific)

The key difference from Accumulate/Enter at Discount: you have **timing conviction**, not just directional conviction. You believe a specific catalyst will move the stock within weeks, and you want leveraged exposure to that move without committing to long-term ownership.

**Strategies:**

| Strategy | Mechanics | When to prefer | Capital required |
|----------|-----------|---------------|-----------------|
| **Long call** | Buy OTM or ATM call | Clean directional bet, defined cost | Premium paid |
| **Bull call spread** (debit) | Buy call + sell higher call | Reduce cost and vega exposure on a catalyst bet | Net debit |
| **Call backspread** (buy 2 calls, sell 1 lower call) | Convex upside — small debit/credit, profits from explosive move up | Expect outsized move, want asymmetric payoff | Small net debit or credit |

**When to use:**
- Specific catalyst with timing (earnings beat, product launch, FDA ruling)
- Capital is constrained — CSPs tying up cash, can't commit $10K+ for shares
- Recovery snap play on deeply hammered name — want leveraged participation in a bounce
- L2-only environment — long calls are your only leveraged bullish tool before L3

**Key decision factors:**
- **IV-HV < 5%**: Options are fairly priced or cheap — long calls offer good value. This is the sweet spot.
- **IV-HV > 10%**: Options are expensive — use bull call spread to reduce vega exposure, or reconsider whether this is really a directional leverage trade (CSP/BPS under a different intent may fit better).
- **IV Rank < 30%**: Cheap vol environment — buying options is favorable.
- **IV Rank > 50%**: Expensive vol — selling strategies are better unless you have very high catalyst conviction.
- Long call: choose 40-60 delta for balanced leverage/probability. ATM for highest delta exposure, OTM for max leverage.
- Call backspread: best when IV is low and you expect a violent move. The sold call partially funds the 2 bought calls.
- **Expiry:** 2-4 weeks past the expected catalyst. Gives time for the move to play out without excessive theta decay.

**Critical distinction from LEAPS:** LEAPS (9-15 month, 80+ delta) replicate ownership. Near-term long calls (2-8 week, 40-60 delta) are directional bets. Don't confuse the two — LEAPS belong under Accumulate, long calls belong here.

**Binary events (the event IS your catalyst):**
Earnings is the most common catalyst here. The trap is IV crush — you can be right on direction and still lose money if the stock moves less than the expected move implies.

- **Entry timing:** Enter 5-10 trading days before the event, not the day before. IV is still building but hasn't peaked — you get a better price. Day-of entry means you're buying at peak IV.
- **IV crush math:** Run `get_expected_move` before entry. Your thesis must imply a move LARGER than the expected move for a long call to profit through earnings. If you think the move equals or is smaller than expected, this is a Vol Bet (sell vol) or skip.
- **Post-event alternative:** If you want to trade the *reaction* rather than the event itself, wait until the morning after. IV has crushed, options are cheaper, and you have the information. This converts from a binary bet to a momentum trade.

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

**When to prefer bull call spread over BPS:** When you want defined cost upfront rather than assignment risk. Better for names you'd rather not own 100 shares of but want upside exposure. For BPS used as an entry mechanism (wide spreads, want assignment), see Wide BPS under Enter at Discount.

**Credit-to-width ratio (all credit spreads):** Collect at least **30% of the strike width** in net credit, or reject the trade. On a $10-wide BPS, the minimum acceptable credit is $3.00 — anything less means poor risk-to-reward (risking $7 to make $3). If the ratio is below 30%, either widen the spread, move closer to ATM, or wait for higher IV.

**Key decision factors:**
- IV-HV > 10%: Favor credit strategies (BPS) — sell overpriced premium
- IV-HV < 5%: Favor debit strategies (bull call spread) — buy fairly priced options
- Capital constrained: BPS/bull call spread over CSP (fraction of collateral)
- Multiple pipeline names: Spreads let you run 5-10 positions vs 2-3 CSPs

**Binary events (event is a threat — close before or open after):**
Moderate conviction + binary event risk + capped upside = inconsistent. You chose defined-risk because you're not fully convinced — don't then gamble that conviction on a coin-flip event.

- **BPS through earnings:** A gap down can blow through both strikes for max loss. On a $10-wide BPS, that's $1,000 per contract lost on a name you had only moderate conviction on. Close before earnings or choose strikes that expire before the event.
- **Bull call spread through earnings:** Same IV crush risk as long calls (debit strategy), but the short call offsets some vega. Still, a muted earnings reaction kills both legs. Not worth holding through unless the spread is already profitable and you're playing with house money.
- **Post-earnings is the sweet spot:** Open spreads AFTER earnings. IV has crushed, event risk is removed, and the post-earnings price action gives you a cleaner directional read. This is where defined-risk strategies shine — you have information, not hope.

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
| **Wheel** (CSP → CC → repeat) | CSP → assigned → covered call → called away → CSP again | Ongoing income cycle on a range-bound name | Full strike notional |

**When to use:**
- IV Rank > 50% (premiums worth selling)
- Stock in a defined range (support/resistance levels visible)
- No strong directional thesis — you think it stays put
- Post-earnings IV crush plays (sell inflated near-term IV)

**Key decision factors:**
- Iron condor: wider wings = less premium but higher probability of profit
- Iron butterfly: max profit if stock pins at center strike — rare but lucrative
- Butterfly: cheapest of all neutral strategies. Very high reward-to-risk if stock pins, but narrow profit zone. Best for pinning-at-a-price thesis.
- Calendar: profits from time decay differential + IV mean reversion
- Wheel: the only directional-looking strategy in this section, but the intent is income, not ownership. You're comfortable repeatedly entering and exiting around a price band. Assignment is part of the cycle, not the goal. The CC leg caps upside by design — if you expect significant appreciation, use CSP → hold with selective CC overlay (see [covered-call-overlay.md](covered-call-overlay.md)) under Enter at Discount instead.
- Avoid iron condors/butterflies/calendars on stocks you'd be happy to own — use CSP/direct instead

**Binary events (event is a threat — never hold through):**
Every strategy in this section is short gamma. Earnings is a gamma event. Short gamma through a gamma event is how max losses happen.

- **Iron condor / iron butterfly:** The expected move often exceeds the short strike width. A 5% earnings move on a name where your short strikes are 3% OTM = max loss on one side. Close iron condors 1-2 days before earnings, no exceptions.
- **Calendar / double diagonal:** Earnings IV crush collapses the back-month option you own faster than you expect — the term structure inverts. Close before earnings.
- **Wheel:** If you have a CSP open going into earnings, a gap down assigns you shares you're only holding for income — now you're an involuntary owner of a name you have low conviction on. If you have shares + CC, a gap up calls shares away (fine, part of the cycle), but a gap down gives you an unrealized loss on income-intent shares. Close or roll the CSP before earnings; accept CC assignment risk since it's part of the wheel.
- **Post-earnings is the prime window:** Open premium-selling trades AFTER earnings. IV has crushed but residual IV remains elevated, event risk is gone, and you're selling into a clean runway. This is the best setup for every strategy in this section.

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

**Binary events (the event IS the trade):**
This is the canonical earnings play. Tactical timing matters more here than in any other intent.

- **Entry:** 5-10 trading days before the event. IV is building but hasn't peaked — you're buying vol on the way up, not at the top. Day-before entry means paying peak IV and needing an even bigger move to profit.
- **Exit:** The morning after the event. The overnight gap IS your move — don't hold hoping for follow-through. IV crushes immediately after the event, and theta resumes destroying your position. Take what the gap gives you.
- **Reverse calendar exception:** Enter closer to the event (3-5 days). The structure profits from near-term IV spiking relative to back-month — the closer to the event, the steeper the term structure distortion you're exploiting.

---

## Intent: Bearish (negative conviction)

See [bearish-framework.md](bearish-framework.md) for the full bearish analysis process: how to score bearish conviction (deterioration signals + valuation disconnect), entry timing, L2 strategy selection matrix, sizing limits, and management rules. This section covers strategy mechanics; the bearish framework covers when and why to use them.

**Strategies:**

| Strategy | Mechanics | When to prefer | Capital required |
|----------|-----------|---------------|-----------------|
| **Bear put spread** (debit) | Buy put + sell lower put | Defined-cost downside bet | Net debit |
| **Bear call spread** (credit) | Sell call + buy higher call | Collect premium on bearish thesis | Spread width |
| **Long put** | Buy OTM put | Simple directional, unlimited profit | Premium paid |
| **Put backspread** (sell 1 put, buy 2 lower puts) | Crash bet, small credit or small debit | Tail risk / blowup thesis | Net credit or small debit |

**Put backspread management:** This structure has a "Valley of Death" — if the stock drifts slowly into the long put strikes (instead of crashing through them), the short put is at max loss while the long puts have little intrinsic value. The backspread requires a *violent* move, not a slow bleed. Close early if the underlying is grinding toward the long strikes without momentum. The worst outcome is a slow decline that pins between your short and long strikes at expiry.

**When to use:**
- Thesis is explicitly bearish
- Hedging portfolio beta (index puts on SPY/QQQ)

**Key decision factors:**
- IV-HV > 10%: Favor credit strategies (bear call spread) — sell overpriced premium
- IV-HV < 5%: Favor debit strategies (bear put spread, long put) — buy fairly priced
- Post-earnings gap-down play: Buy puts AFTER the gap to avoid IV crush (L2 strategy)
- Crash conviction: Put backspread — pay little or nothing, profit big on blowup
- **Credit-to-width ratio applies** to bear call spreads — same 30% minimum as BPS (see Defined-Risk section)

**Binary events (event confirms or denies the thesis):**
Earnings is a confirmation event for bearish trades, not the trade itself. The thesis is that the business is deteriorating — earnings either confirms that (enter or add) or contradicts it (reassess).

- **Debit strategies (long put, bear put spread):** Don't buy before earnings — you're paying peak IV, and IV crush eats your gains even if the stock drops. The one-liner already in this section is right: buy puts AFTER the gap. The gap confirms the thesis, IV crushes to a fair level, and you're positioned for the continued decline, not the initial move.
- **Credit strategies (bear call spread):** Opposite — holding through earnings is favorable. If the stock gaps down or stays flat, the short call decays and you keep the credit. If it gaps up, your long call limits the loss. Bear call spreads are the best bearish structure to hold through earnings.
- **Put backspread:** Pre-earnings is actually a good entry — you're buying more options than you're selling, so you want IV to expand, and the gamma event can produce the violent move the structure needs. But only if your thesis predicts a blowup, not a slow bleed.

---

## Intent: Hedge (existing positions)

**Strategies:**

| Strategy | Mechanics | When to prefer | Capital required |
|----------|-----------|---------------|-----------------|
| **Protective put** | Buy put on existing shares | Direct insurance | Premium paid |
| **Put spread** (as hedge) | Buy put + sell lower put | Cheaper insurance, capped protection | Net debit |
| **Collar** | Own shares + buy put + sell call | Funded hedge — CC premium pays for put | Net credit/debit |
| **Index puts** (SPY/QQQ) | Buy OTM puts on broad index | Portfolio-wide protection | Premium paid |

**When to use:**
- Approaching profit target but don't want to sell yet (tax reasons, thesis intact)
- Macro uncertainty — protect gains without exiting
- Collar: when you're willing to cap upside to fund the hedge

**Binary events (event is the risk — hedge costs the most when you need it most):**
Earnings on a large position is precisely when you feel the urge to hedge. But pre-earnings IV makes protective puts expensive — you're paying peak premium for insurance.

- **Collar > protective put pre-earnings.** The sold call offsets the inflated put cost. Pre-earnings IV inflates both sides equally, so the collar's net cost stays reasonable while a naked protective put is overpriced.
- **Index puts for earnings season.** If multiple holdings report in the same week, individual hedges are capital-inefficient. SPY/QQQ puts hedge the portfolio, not the name — cheaper and simpler when the risk is broad.
- **Sizing is the cheapest hedge.** Before spending premium on protection, check: is the position within sizing limits? If a 15% earnings gap would produce a dollar loss within your drawdown tolerance, the position size IS the hedge. Don't pay for insurance you don't need.
