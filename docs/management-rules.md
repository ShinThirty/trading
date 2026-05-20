# Position Management Rules

Exit and management rules by intent. Companion to [decision-framework.md](decision-framework.md) (entry) and [covered-call-overlay.md](covered-call-overlay.md) (CC-specific).

---

## Accumulate / Enter at discount

- **CSP:** Close at 50% profit. If assigned, evaluate covered call overlay (wheel).
- **Direct shares:** No hard stop losses on high-conviction entries. Scale-in T2 triggers at 5-8% drop from T1.
- **If approaching CSP expiry ITM:** Let assignment happen if thesis intact. Only roll if thesis deteriorated.
- **Reassess thesis** if position drops >15% from entry — check fundamentals, not just price.

## Directional leverage

- **Long call:** Set profit target at entry (50-100% return on premium). Take profits, don't diamond-hand.
- **Call backspread:** Let ride if move is developing. Close if stock stalls — time decay on 2 long legs hurts.
- **Both:** Exit immediately if catalyst disappoints. Cut losses inside 14 DTE — theta acceleration destroys value.

## Defined-risk exposure

- **BPS:** Close at 50% of max profit or when short leg reaches 80% profit.
- **Bull call spread:** Let ride toward expiry if directional thesis intact. Close if underlying breaks below support.
- **PMCC:** Manage short call — roll up and out if challenged. LEAPS is the anchor.

## Harvest premium

- **Iron condor/butterfly:** Close at 50% of max profit. Adjust or close tested side if underlying approaches short strike.
- **Calendar:** Close when near-term option decays to target or IV differential narrows.

## Bet on volatility

- **Straddle:** Take profit at 30% return on total premium (stretch: 60%). The move rarely comes when you expect — take what the market gives.
- **Strangle:** Take profit at 40% return on total premium (stretch: 80%). Needs a bigger move than straddle, so let the stretch target run slightly longer.
- **When one leg goes ITM:** Close the losing leg early if it's near worthless (<10% of entry cost) to recoup some capital. Let the winning leg ride toward the profit target.
- **Exit at 21 DTE** if no significant move has occurred — theta is accelerating on both legs.
- **Pre-earnings vol bets:** If the move happens on the earnings gap, close the full position on the first trading day. Don't hold post-earnings hoping for continuation — IV crush will eat the remaining extrinsic value.
- **Never hold through expiry** — close or roll by 14 DTE at the latest.

## Bearish

- **Long puts:** Take profit at 50% return on premium (stretch: 100%). Exit at 21 DTE if thesis hasn't played out.
- **Straddle/strangle:** Take profit at 30-40% return on total premium. Exit at 21 DTE.
- **Bear spreads (L3):** Close at 50-75% of max profit. Don't hold to expiry hoping for max.
- See [bearish-framework.md](bearish-framework.md) for full bearish management rules, thesis checkpoints, and exit triggers.

## Hedge

See [protective-put-collar-playbook.md](protective-put-collar-playbook.md) for the full single-name hedge framework (intent, strike/expiry, collar variations, management). See [tail-hedge-playbook.md](tail-hedge-playbook.md) for portfolio-level structural index puts. Brief reminders:

- **Protective put:** Close when the threat that prompted it has passed. Don't let it expire worthless out of inertia.
- **Collar:** Manage both legs together; rolling the call without the put converts the collar into a directional bet.
- **Index puts (structural):** Only close on a playbook trigger (delta drift, harvest tranches, 30-DTE roll) — never on "nothing is wrong."
- **Re-evaluate every 2 weeks.** If you're holding a hedge for months, either the risk is real (reduce the underlying position) or the risk has passed (close the hedge).
- **Don't hedge a position you should be exiting.** A protective put on a broken thesis is paying insurance on a house you should be selling.

## All strategies

- **Exit signal:** Thesis broken (not price action). Revenue deceleration, margin collapse, competitive disruption, management change.
- **Covered call overlay** once shares are held: see [covered-call-overlay.md](covered-call-overlay.md).

---

## Thesis Checkpoint: When a Position Drops >15%

Don't watch the ticker and feel pain. Run this checklist:

1. **Is the end customer still spending?** Check the demand environment upstream of your company. If the buyers of your company's products are still deploying capital, the thesis is intact.
2. **Is this company-specific or sector-wide?** Company-specific drawdowns need more scrutiny. Sector-wide drawdowns are *often* noise — but not always. A sector-wide drawdown can also be the beginning of a cycle turn. If the drawdown aligns with your exit thesis signals, it's not noise — it's the signal.
3. **Has the competitive moat actually narrowed?** Check for concrete evidence: lost customers, cancelled contracts, actual product displacement. A narrative shift in financial media is not the same as lost revenue.
4. **Is the thesis timeline still valid?** A 2-month drawdown inside an 18-month thesis is noise, not signal.
5. **Would I buy this at today's price if I had no position?** Strip away anchoring to your entry.

If all five pass → hold or add. If any fail → exit regardless of price.

---

## Selling Into Strength vs Selling Into Recovery

**The diagnostic test:** "Am I selling because I've won, or because I've survived?"

| | Selling into strength | Selling into recovery |
|---|---|---|
| Position P&L | Green or solidly profitable | Still red or barely recovered |
| Motivation | "I've hit my target" | "I can finally get out" |
| Emotion | Confidence, maybe mild FOMO | Relief, exhaustion |
| Usually right? | Yes — disciplined profit-taking | Usually wrong — you paid the emotional cost of the drawdown but captured none of the recovery |

**The rule:** If you survived the worst of a drawdown, a partial bounce should confirm the thesis, not trigger an exit. The crash is the tax. The recovery is the refund. Don't walk away before the refund arrives.
