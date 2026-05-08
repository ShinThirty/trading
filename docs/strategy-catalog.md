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

**LEAPS vs shares:** Use LEAPS when capital-constrained, multiple names competing for capital, or 100 shares >$15K notional and you want exposure to several names. Time horizon must be 6-12+ months.

**Auto-trigger:** When Accumulate intent is selected and 100 shares would cost >$15K, proactively run a side-by-side LEAPS-vs-shares comparison (capital, delta per dollar, break-even, monthly theta, max loss) before presenting the recommendation.

**Binary events:** Both outcomes serve highest conviction (beat accelerates thesis, miss gives cheaper entry) — the matrix modifiers handle timing. One addition: **LEAPS through earnings** carry vega risk even at 80+ delta. Verify break-even can absorb the expected move's worth of IV crush.

---

## Intent: Enter at Discount (high conviction)

**Strategies:**

| Strategy | Mechanics | When to prefer | Capital required |
|----------|-----------|---------------|-----------------|
| **CSP** | Sell OTM put, collect premium | Default entry-at-discount method | Full strike notional (cash account) |
| **Wide BPS as entry** | Sell put + buy lower put ($30-40 wide) | CSP with a floor — want assignment but cap worst-case | Spread width |
| **Put ratio spread** (sell 2 puts, buy 1 lower put) | Extra premium, partially defined risk | Aggressive discount, willing to own 200 shares | ~1.5x collateral |

**CSP-as-entry intent check:** The CSP here is a limit order that pays you to wait — you *want* assignment. If you find yourself picking far-OTM strikes to maximize probability of expiring worthless, you've drifted into income mode. Reclassify to Harvest Premium and use the Wheel or iron condor instead. The diagnostic question: **do you want to own the shares at this strike?** If yes, this is the right section. If no, you're selling volatility, not entering a position.

**Wide BPS as entry:** $30-40 wide spreads behave like a CSP between strikes (short assigns, long expires worthless); the long only matters if the stock blows through both strikes, capping max loss. Narrower spreads shift toward defined-risk (see Defined-Risk section).

**CSP strike selection by drawdown:**

| Drawdown | Strike target | Rationale |
|----------|--------------|-----------|
| >50% | **ATM to 5% OTM** | You want assignment. Deep discount already built in. |
| 30-50% | **5-10% OTM** | Balanced — assignment gives additional discount |
| <30% | **10-15% OTM** | Demand a real pullback before owning |

Conservative OTM strikes (>12%) on deeply drawdown stocks defeat the entry purpose — you likely expire worthless and just ran an income trade.

**Expiry rule:** Always sell THROUGH the nearest earnings date. Earnings IV is a feature — you either keep inflated premium or get assigned at an even better price. Never pick a pre-earnings expiry that wastes the IV.

**For event-specific CSP setups** (depressed quality name into a known catalyst, harvesting IV crush as the primary alpha source rather than entry-at-discount), see [csp-earnings-playbook.md](csp-earnings-playbook.md). It covers the optimal 30-50 DTE sweet spot, the 2W tape disqualifier (Front-Run Catalyst applied to event CSPs), entry timing in the vol-expansion window, and the management rule of holding through the event rather than closing pre-event for "safety."

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

**Binary events:** "Sell through earnings" already captures this. Re-check the thesis (margins, guidance, revenue) after every report the CSP spans. If thesis survived, working as designed. If thesis broke, buy back immediately — don't let a broken CSP assign you.

---

## Intent: Directional Leverage (high conviction, time-specific)

The key difference from Accumulate/Enter at Discount: you have **timing conviction**, not just directional conviction. You believe a specific catalyst will move the stock within weeks, and you want leveraged exposure to that move without committing to long-term ownership.

**Strategies:**

| Strategy | Mechanics | When to prefer | Capital required |
|----------|-----------|---------------|-----------------|
| **Long call** | Buy OTM or ATM call | Clean directional bet, defined cost | Premium paid |
| **Bull call spread** (debit) | Buy call + sell higher call | Reduce cost and vega exposure on a catalyst bet | Net debit |
| **Call backspread** (buy 2 calls, sell 1 lower call) | Convex upside — small debit/credit, profits from explosive move up | Expect outsized move, want asymmetric payoff | Small net debit or credit |

**When to use:** Timed catalyst (earnings, product launch, FDA), capital-constrained, recovery snap on hammered name, or L2-only leveraged bullish need.

**Key parameters:**
- Long call: 40-60 delta (ATM for delta, OTM for leverage)
- Call backspread: low IV + violent-move thesis; sold call partially funds 2 longs
- **Expiry:** 2-4 weeks past expected catalyst — room to play out without excessive theta

**Critical distinction from LEAPS:** LEAPS (9-15 month, 80+ delta) replicate ownership and belong under Accumulate. Near-term long calls (2-8 week, 40-60 delta) are directional bets and belong here.

**Binary events (the event IS your catalyst):** IV crush is the trap — you can be right on direction and lose money.
- **Entry:** 5-10 trading days before the event, not day-of. IV building but pre-peak.
- **IV crush math:** Run `get_expected_move`. Your thesis must imply a move LARGER than expected for a long call to profit through earnings. If equal or smaller, this is a Vol Bet (sell vol) or skip.
- **Post-event alternative:** Wait until morning after to trade the *reaction* — IV crushed, you have information, converts binary bet to momentum trade.

**Management:** Set profit target at entry (50-100% on premium). Theta accelerates inside 14 DTE — cut losses if thesis hasn't played out. If catalyst disappoints, exit immediately.

---

## Intent: Defined-Risk Exposure (moderate conviction)

**Strategies:**

| Strategy | Mechanics | When to prefer | Capital required |
|----------|-----------|---------------|-----------------|
| **Bull put spread** (credit) | Sell put + buy lower put | Bullish thesis, cap downside | Spread width |
| **Bull call spread** (debit) | Buy call + sell higher call | Bullish directional bet, defined cost | Net debit |

**Bull call spread vs BPS:** Bull call spread when you want defined cost upfront and would rather not own 100 shares. For BPS used as entry mechanism (wide spreads, want assignment), see Wide BPS under Enter at Discount.

**Credit-to-width ratio (all credit spreads):** Collect ≥**30% of strike width** in net credit. On a $10-wide BPS, minimum is $3.00 — below that means risking $7 to make $3. If short, widen, move closer to ATM, or wait for higher IV.

**Key parameter:** Spreads enable 5-10 positions vs 2-3 CSPs — capital efficiency is the main reason to choose this intent over CSP at moderate conviction.

**Binary events (event is a threat — close before or open after):** Moderate conviction + binary risk + capped upside is inconsistent. You chose defined-risk because you're not convinced — don't gamble that on a coin flip.
- **BPS through earnings:** Gap down can blow through both strikes for max loss. Close before, or pick expiry pre-event.
- **Bull call spread through earnings:** IV crush hits, short call partially offsets vega. Not worth holding through unless already profitable.
- **Post-earnings is the sweet spot:** IV crushed, event risk removed, cleaner directional read. Defined-risk shines on information, not hope.

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

**When to use:** IV Rank >50%, stock in defined range, no directional thesis, or post-earnings IV crush play.

**Per-strategy notes:**
- Iron condor: wider wings = less premium, higher probability
- Iron butterfly: max profit only if stock pins at center — rare but lucrative
- Butterfly: cheapest neutral strategy, best for pin-at-a-price thesis
- Calendar: profits from theta differential + IV mean reversion
- Wheel: income intent, not ownership. CC leg caps upside *by design* — if you expect significant appreciation, use CSP→hold with selective CC overlay under Enter at Discount instead. See [covered-call-overlay.md](covered-call-overlay.md).
- Avoid all of these on stocks you'd be happy to own — use CSP/direct instead.

**Binary events (never hold through):** Every strategy here is short gamma; earnings is a gamma event. That combination is how max losses happen.
- **Iron condor / butterfly:** Expected move often exceeds short strike width. Close 1-2 days before earnings, no exceptions.
- **Calendar / double diagonal:** Earnings IV crush collapses the back-month option you own faster than expected (term structure inverts). Close before.
- **Wheel:** Close or roll the CSP before earnings (don't get assigned a low-conviction name on a gap down). Accept CC assignment risk — it's part of the cycle.
- **Post-earnings is the prime window** for opening every strategy in this section.

---

## Intent: Bet on Volatility (direction-agnostic)

**Strategies:**

| Strategy | Mechanics | When to prefer | Capital required |
|----------|-----------|---------------|-----------------|
| **Long straddle** | Buy ATM call + ATM put | Expect big move, direction unknown | Net debit (expensive) |
| **Long strangle** | Buy OTM call + OTM put | Cheaper straddle, needs bigger move | Net debit |
| **Reverse calendar** | Buy near-term + sell far-term same strike | Expect near-term IV spike | Net debit |

**When to use:** Pre-earnings on names you expect to move *more* than expected, IV Rank <30%, or major catalyst imminent (FDA, legal, M&A).

**Key decision factor:** Compare `get_expected_move` to your estimate. If you think move > implied, buy vol. If less, sell vol (Harvest Premium).

**Binary events (the event IS the trade):** Tactical timing matters more here than any other intent.
- **Entry:** 5-10 trading days before the event — IV building but pre-peak.
- **Exit:** Morning after. The overnight gap IS your move; IV crushes immediately, theta resumes. Take what the gap gives you.
- **Reverse calendar exception:** Enter 3-5 days out — closer to event = steeper term structure distortion to exploit.

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

**When to use:** Explicit bearish thesis or portfolio beta hedge (index puts).

**Key parameters:**
- Post-earnings gap-down: buy puts AFTER the gap to avoid IV crush
- Crash conviction: put backspread — pay little or nothing, profit big on blowup
- Bear call spreads: 30% credit-to-width minimum (same as BPS)

**Binary events (event confirms or denies thesis):** Earnings is a confirmation event for bearish trades, not the trade itself.
- **Debit (long put, bear put spread):** Don't buy pre-earnings — peak IV + IV crush eats gains even if stock drops. Buy puts AFTER the gap.
- **Credit (bear call spread):** Opposite — holding through is favorable. Gap down or flat = short call decays. Gap up = long call caps loss. Best bearish structure to hold through earnings.
- **Put backspread:** Pre-earnings is a good entry — net long options want IV expansion, and gamma event can produce the violent move the structure needs. Only if thesis is blowup, not slow bleed.

---

## Intent: Hedge (existing positions)

**Strategies:**

| Strategy | Mechanics | When to prefer | Capital required |
|----------|-----------|---------------|-----------------|
| **Protective put** | Buy put on existing shares | Direct insurance | Premium paid |
| **Put spread** (as hedge) | Buy put + sell lower put | Cheaper insurance, capped protection | Net debit |
| **Collar** | Own shares + buy put + sell call | Funded hedge — CC premium pays for put | Net credit/debit |
| **Index puts** (SPY/QQQ) | Buy OTM puts on broad index | Portfolio-wide protection | Premium paid |

**When to use:** Approaching profit target but not ready to sell (tax, thesis intact), macro uncertainty, or willing to cap upside (collar) to fund the hedge.

**Binary events (hedge costs most when you need it most):** Pre-earnings IV makes protective puts expensive.
- **Collar > protective put pre-earnings:** Sold call offsets inflated put cost; pre-earnings IV inflates both sides equally.
- **Index puts for earnings season:** If multiple holdings report the same week, individual hedges are capital-inefficient. SPY/QQQ hedges the portfolio.
- **Sizing is the cheapest hedge:** If a 15% earnings gap stays within drawdown tolerance, position size IS the hedge. Don't pay for insurance you don't need.
