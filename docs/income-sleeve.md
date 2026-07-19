# Income Sleeve (Harvest-Premium CSP)

A bounded, walled-off **income** book that sells cash-secured puts (and wheels assigned shares) to earn yield above the T-bill floor on the cash that isn't doing growth work. It is deliberately **separate from the growth-first CSP book** — there, CSPs are an *entry mechanism* (25–30Δ, want to own; see `feedback_csp_philosophy`). Here they are *income* (don't need to own). The two live on separate ledgers **and separate accounts** so the mental division stays clean.

The design solves one problem: **sell vol for income without violating the late-cycle "keep powder / don't get caught" posture.** Four constraints make it defensible — an account boundary, a hard capital cap, a willing-to-own bias so assignment is a feature, and a regime circuit breaker that stands the sleeve down as risk builds.

## The division (organizing principle)

The sleeve is defined by an **account boundary**, not a dollar carve-out — a clearer mental model. Theta runs in every account **except** the two main Webull accounts, which stay the growth / position-building book.

| Book | Accounts | Role |
|------|----------|------|
| **Growth (position-building)** | Webull Individual Cash, Webull Individual Margin | Long-term positions, growth-first entry CSPs, the structural tail hedge. Reviewed in `/briefing` Step 2 + `/review` Section 2. |
| **Income sleeve (this doc)** | Webull Roth IRA · Fidelity BrokerageLink · Fidelity BrokerageLink Roth · Fidelity HSA | Harvest-premium CSPs + wheels. All tax-advantaged. Reviewed in `/briefing` Step 2c + `/review` §3 item 5. |
| **Excluded from both** | Tradier, TastyTrade (taxable, ~$2K each) · Confluent 401k core (VINIX, not option-enabled) | Too small for an index CSP and tax-inefficient for churn — leave in SGOV / core funds. |

**Why account-scoped:** the income accounts are almost all **tax-advantaged** (Roth ×2, HSA, pre-tax BrokerageLink). High-churn premium is short-term ordinary income — housing it in Roth/HSA/401k makes the churn tax-free or deferred. That, plus the clean "which account = which book" mental split, is the whole point.

## Mandate

**Match the index with less drawdown** — the honest goal for a capped short-vol book. A CSP sleeve *cannot* beat the S&P on absolute return (upside is capped at the premium); over a full cycle it delivers index-like return with materially lower drawdown — better risk-adjusted, not higher. Success = **SPY-like return with a smaller peak-to-trough**, judged over a full cycle (bull windows lag on return *by design* — don't kill it for that).

The **~4.5% cash floor** is the absolute minimum, not the target: if the sleeve can't clear cash net of the inevitable tested weeks, kill it. And if it merely *matches* SPY's return while taking *similar* drawdown, the sleeve adds nothing — convert that capital (especially the tax-free Roth/HSA space, whose best use is long-term equity compounding) to equity instead. Judge it with `get_income_sleeve_ledger`, which prints the window's sleeve return + realized drawdown next to SPY buy-and-hold.

## Capital cap (hard)

- **Aggregate collateral-at-risk ≤ $250K** — the sum of (strike × 100 × contracts) across all *open* income-sleeve CSPs. Cap hit → no new CSPs until one closes/expires.
- Cross-check the 60% rule (`feedback_60pct_rule`): income-sleeve collateral **+** the growth-first entry-CSP collateral ≤ 60% of the cash account. At the $250K cap plus the entry CSPs this sits far under — verify each review, don't assume.
- The rest of the cash stays **powder / T-bills**. Incremental yield on a slice, never a redeployment of the pile.

## Universe — your choice, gated

**You pick the instrument.** The sleeve no longer prescribes a fixed list — any underlying you choose is admitted if it clears the gates below. The gates are what protect the mandate (match the index with less drawdown); the specific ticker is yours. QQQ + IWM remain the natural *default* core (tight <3% monthly spreads, diversified, both clear the floor at 15Δ) — a starting point, not a fence.

**The gates — a candidate must clear all that apply:**

1. **Liquidity gate** — monthly bid/ask spread **< ~15%** at your target strike. Wide-spread names eat the edge before theta pays (COST ran ~21%; **sector ETFs — XLP/XLU/XLE etc. — run 40–125% at every tenor and are effectively un-harvestable**). Tighter is better; the index ETFs sit <3%.
2. **Yield-floor gate** — the 15Δ monthly annualized premium must clear the **~4.5% cash floor**, else you're taking assignment risk for less than SGOV pays (this is why DIA, ~3.9% at 15Δ, fails as a *core* engine).
3. **Hedge-conflict gate** — **no SPY puts.** Selling SPY vol shorts the same tail the structural hedge is long (`tail-hedge-playbook.md` / `project_portfolio_hedge`). QQQ / IWM / single names don't conflict.
4. **Willing-to-own gate** — anything sold above ~15Δ (the 25Δ bucket) must be a name **you'd genuinely own on assignment**, because at 25Δ assignment is the base case, not the tail. Index ETFs auto-pass; single names need the judgment.
5. **Concentration gate** — respect existing book exposure. **Gold is capped** (GLD/GDX carry rich IV but the book already holds a large, underwater gold position — no more gold beta). A name already large in the growth book counts against the cluster cap (`project_circular_financing_buckets`).

**Overriding a gate** is allowed *only* as a conscious willing-to-own decision on gate 4 — e.g. a slightly-wide single name you truly want. Gates 1–3 and 5 are hard: a below-floor yield, a hedge conflict, or an over-concentrated add defeats the sleeve's purpose regardless of how much you like the ticker.

**Mandate guardrail:** free choice widens the drawdown profile — the more collateral concentrates in single names, the more the sleeve drifts from index-like behavior toward idiosyncratic risk. Keep the *core* diversified (indices or a spread of names) and use single-name free choice as the opportunistic layer. `get_income_sleeve_ledger`'s drawdown-vs-SPY check is the backstop that flags when your choices have drifted off-mandate.

**Pre-trade check (run before every new leg):** name the instrument; the flow pulls `get_iv_metrics` (liquidity rating + IV rank) and `get_option_chain` (spread at your delta), computes the 15Δ annualized yield vs the floor, and confirms the gates before previewing the order. Clears → preview → your approval → place.

Assigned shares (or shares already held, e.g. V) → **wheel with 30–45 DTE covered calls** (`feedback_cc_duration`).

## Structure

- **DTE:** **monthly, 30–45 DTE.** Open ~45, close at 50% profit **or by 21 DTE**. This is the theta sweet spot — harvest the steep part of decay and exit before gamma turns it into a coin-flip. (Weekly was the trial default; it doesn't scale across four accounts on a full-time schedule and gates the vehicle set down to QQQ/IWM only.)
- **Delta = intent, not instrument.** **~15Δ** for assignment-averse legs (high win rate, don't want the shares) — available on **the index *or* an individual name**; up to **~25Δ** for willing-to-own legs (richer premium, assignment is fine) — single names you'd genuinely own. The delta reflects whether you want the shares, not whether the underlying is an ETF. Only the ~25Δ willing-to-own legs trip gate 4.
- **Cadence:** roll into the next monthly as legs close. PDT is eliminated (`reference_pdt_rule_eliminated`) so timing is unconstrained.

## Management (where income programs live or die)

- **Close at 50% of max profit.** The single most important rule — never hold for the last pennies against gamma.
- **Manage by 21 DTE** regardless of profit — roll to the next monthly or close.
- **If tested** (short put ITM or delta toward −0.30/−0.40, or loss ≈ 2× the credit): **assignment-averse legs (~15Δ, index *or* single name)** → **roll down-and-out for credit or close** (don't want the shares); **willing-to-own legs (~25Δ)** → **roll or accept assignment**, then wheel with 30–45 DTE CCs. The stop branches on intent, not instrument.
- **Event guard:** the index carries no single-name event risk (a 15Δ / 34-DTE index put spanning a macro print is fine). A **single name — even at 15Δ — can gap through the stop on an earnings/headline print** before you can roll, so only span a name's earnings on a leg you'd accept assignment on (which makes it a willing-to-own bet regardless of the delta you opened at). Otherwise keep single-name legs clear of their earnings.

## ⚠ Late-cycle circuit breaker (load-bearing)

The sleeve **auto-throttles as the regime deteriorates** — it is not a static short-vol machine.

- **PAUSE all new income CSPs** if the **bear-regime score rises to Building+ (≥ 4)** OR **HY OAS begins widening** (`get_bear_regime_score` / `get_dix_gex` / `get_market_regime`, surfaced daily in `/briefing` Step 1f).
- Existing positions: manage per the rules above; do not add.
- Resume only when the score falls back to Watchful/Clear and credit stabilizes.

This is the discipline that reconciles selling vol with the keep-powder posture: harvest in calm regimes, stand down exactly when the tail you're short starts to materialize.

## Checkup cadence (regular income-vs-growth separation)

The sleeve is monitored on its own track so income positions never blur into the growth book:

- **Daily — `/briefing` Step 2c (Income Sleeve Monitor).** Tight: isolate the sleeve legs by account, flag legs at ≥50% profit / tested / expiring / newly assigned, and confirm the circuit-breaker gate. Silence if nothing needs action.
- **Biweekly — `/review` §3 item 5 (Income Sleeve ledger).** Full, via **`get_income_sleeve_ledger`** (transaction-ledger, contribution-immune): sleeve return + realized drawdown vs SPY buy-and-hold (the mandate metric), net premium vs the ~4.5% cash floor, cap utilization vs $250K, per-leg management, composition/concentration, circuit-breaker state.

## Status / live state

This doc holds the **stable rules only**. **Live legs / fills / balances / ledger are pulled from MCP on demand** (`get_portfolio_summary`, `get_snaptrade_positions`) — do not record them here or in memory (`feedback_doc_vs_memory_state`). Memory (`project_harvest_premium_sleeve`) persists only the durable, non-pullable decisions: the account division and the locked structure.
