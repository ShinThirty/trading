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

Net yield **meaningfully above the ~4.5% T-bill floor** on a bounded slice, without converting powder into a static short-vol position. If it can't clear T-bills net of spread and the inevitable tested weeks, it isn't worth the tail exposure — **kill it.**

## Capital cap (hard)

- **Aggregate collateral-at-risk ≤ $250K** — the sum of (strike × 100 × contracts) across all *open* income-sleeve CSPs. Cap hit → no new CSPs until one closes/expires.
- Cross-check the 60% rule (`feedback_60pct_rule`): income-sleeve collateral **+** the growth-first entry-CSP collateral ≤ 60% of the cash account. At the $250K cap plus the entry CSPs this sits far under — verify each review, don't assume.
- The rest of the cash stays **powder / T-bills**. Incremental yield on a slice, never a redeployment of the pile.

## Universe

**Index core (the engine):**
- **QQQ + IWM.** Tight monthly spreads (<3%), diversified, both clear the T-bill floor at 15Δ.
- **DIA is out** — at 15Δ its monthly annualized yield (~3.9%) is *below* the 4.5% floor. Fails the mandate.
- **SPY is out** — selling SPY puts shorts the same vol the structural tail hedge is long (`tail-hedge-playbook.md` / `project_portfolio_hedge`).

**Willing-to-own bucket (opportunistic):**
- Liquid quality single names you'd genuinely own, sold at ~25Δ so assignment→wheel is a *feature*.
- **Spread gate: only sell when the monthly bid/ask spread is < ~15%.** Wide-spread names (e.g. COST ran ~21%) eat the edge — drop them even when the headline yield looks rich. Indices are the clean vehicle; single names are opportunistic.
- **Sector ETFs are permanently out** — XLP/XLU/XLE etc. show rich headline IV but 40–125% option spreads at every tenor; un-harvestable.
- **Gold is capped** — GLD/GDX carry rich IV but the book already holds a large (underwater) gold position; no more gold beta.
- Assigned shares (or shares already held, e.g. V) → **wheel with 30–45 DTE covered calls** (`feedback_cc_duration`).

## Structure

- **DTE:** **monthly, 30–45 DTE.** Open ~45, close at 50% profit **or by 21 DTE**. This is the theta sweet spot — harvest the steep part of decay and exit before gamma turns it into a coin-flip. (Weekly was the trial default; it doesn't scale across four accounts on a full-time schedule and gates the vehicle set down to QQQ/IWM only.)
- **Delta:** **~15Δ** index core (don't want assignment, high win rate) · up to **~25Δ** on willing-to-own names (richer premium, assignment is fine). Split by whether you'd want the shares.
- **Cadence:** roll into the next monthly as legs close. PDT is eliminated (`reference_pdt_rule_eliminated`) so timing is unconstrained.

## Management (where income programs live or die)

- **Close at 50% of max profit.** The single most important rule — never hold for the last pennies against gamma.
- **Manage by 21 DTE** regardless of profit — roll to the next monthly or close.
- **If tested** (short put ITM or delta toward −0.30/−0.40, or loss ≈ 2× the credit): index legs → **roll down-and-out for credit or close** (don't want the shares); willing-to-own legs → **roll or accept assignment**, then wheel with 30–45 DTE CCs.
- **Event guard:** index legs carry no single-name event risk (a 15Δ / 34-DTE index put spanning a macro print is fine). Willing-to-own legs sold *through* a name's earnings are a deliberate willing-to-own bet — only do it on names you'd own on a bad print.

## ⚠ Late-cycle circuit breaker (load-bearing)

The sleeve **auto-throttles as the regime deteriorates** — it is not a static short-vol machine.

- **PAUSE all new income CSPs** if the **bear-regime score rises to Building+ (≥ 4)** OR **HY OAS begins widening** (`get_bear_regime_score` / `get_dix_gex` / `get_market_regime`, surfaced daily in `/briefing` Step 1f).
- Existing positions: manage per the rules above; do not add.
- Resume only when the score falls back to Watchful/Clear and credit stabilizes.

This is the discipline that reconciles selling vol with the keep-powder posture: harvest in calm regimes, stand down exactly when the tail you're short starts to materialize.

## Checkup cadence (regular income-vs-growth separation)

The sleeve is monitored on its own track so income positions never blur into the growth book:

- **Daily — `/briefing` Step 2c (Income Sleeve Monitor).** Tight: isolate the sleeve legs by account, flag legs at ≥50% profit / tested / expiring / newly assigned, and confirm the circuit-breaker gate. Silence if nothing needs action.
- **Biweekly — `/review` §3 item 5 (Income Sleeve ledger).** Full: cap utilization vs $250K, net premium harvested vs the T-bill floor (the mandate metric), per-leg management, composition/concentration, circuit-breaker state.

## Status / live state

This doc holds the **stable rules only**. **Live legs / fills / balances / ledger are pulled from MCP on demand** (`get_portfolio_summary`, `get_snaptrade_positions`) — do not record them here or in memory (`feedback_doc_vs_memory_state`). Memory (`project_harvest_premium_sleeve`) persists only the durable, non-pullable decisions: the account division and the locked structure.
