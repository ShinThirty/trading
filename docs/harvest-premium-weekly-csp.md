# Harvest-Premium Weekly CSP Sleeve

**Created 2026-07-17 (investigation/trial phase).** A bounded, walled-off income sleeve that sells weekly low-delta cash-secured puts to earn incremental yield above the T-bill floor on a slice of the cash pile. This is **distinct from the growth-first CSP book** — there, CSPs are an *entry mechanism* (25–30Δ, want to own; see `feedback_csp_philosophy`). Here they are *income* (10–16Δ, don't need to own). Keep the two on separate mental ledgers.

The design exists to solve one problem: **how to sell vol for income without violating the late-cycle "keep powder / don't get caught" posture.** The answer is three constraints — a hard capital cap, a willing-to-own bias so assignment is a feature, and a regime circuit breaker that stands the sleeve down as risk builds.

## Mandate

Net yield **meaningfully above the ~4.5% T-bill floor** on a bounded carve-out, without converting the powder into a static short-vol position. If it can't clear T-bills net of spread and the inevitable tested weeks, it isn't worth the tail exposure — kill it.

## Capital cap (hard)

- **Aggregate collateral-at-risk ≤ $250K** — the sum of (strike × 100 × contracts) across all *open* harvest CSPs. Cap hit → no new CSPs until one closes/expires.
- Cross-check the 60% rule: harvest collateral **+** the growth-first entry-CSP collateral must stay ≤ 60% of the cash account (`feedback_60pct_rule`). At the $250K cap plus ~$109K entry CSPs, total ≈ 26% of cash — ample headroom.
- The remaining cash stays **powder / T-bills**. This sleeve is incremental yield on a slice, never a redeployment of the pile.

## Universe (blend)

- **Core engine:** QQQ + IWM. Tight spreads (2–4%), diversified, consistent harvest. **SPY is excluded** — selling SPY puts shorts the same underlying vol the structural tail hedge is long (`project_portfolio_hedge`).
- **Opportunistic:** willing-to-own quality + GLD/GDX (extends the existing gold wheel). On these, assignment is a *feature* — you own quality/gold at a discount, then wheel with CCs.
- **Spread gate:** only sell a single-name weekly when its bid/ask spread is **< ~15%** *and* it's a name you'd own. Single-name weeklies routinely run 20–47% spread (PGR 23%, COST 31%, V 47% observed 2026-07-17) — that eats the edge. Indices are the clean vehicle; single names are opportunistic only.
- **Capital efficiency note:** QQQ's high strike (~$66K/contract) is lumpy — lead the sleeve with IWM/GLD for diversification per dollar, add QQQ as the sleeve scales.

## Structure

- **Delta:** 10–16Δ (default ~14Δ). Low delta = harvest, not entry.
- **DTE:** weekly, 5–9 DTE. Fastest theta, highest gamma — management discipline (below) is mandatory.
- **Cadence:** sell for the next Friday; PDT is eliminated (`reference_pdt_rule_eliminated`) so timing is unconstrained.

## Management (where harvest programs live or die)

- **Close at 50–70% of max profit.** Never hold a weekly to expiry for the last pennies — that's pure gamma risk for negligible premium. This is the single most important rule.
- **If tested** (delta rising toward −0.30/−0.40): index legs → **roll down-and-out or close** (don't want the shares); willing-to-own legs → **roll or accept assignment**, then wheel with 30–45 DTE CCs.
- **Event guard:** skip or size-down any weekly that spans a known binary — single-name earnings, or an index weekly spanning a major macro print (FOMC / CPI / PCE / GDP / NFP).

## ⚠ Late-cycle circuit breaker (load-bearing)

The sleeve **auto-throttles as the regime deteriorates** — it is not a static short-vol machine.

- **PAUSE all new harvest CSPs** if the **bear-regime score rises to Building+ (≥ 4)** OR **HY OAS begins widening** (`get_bear_regime_score` / `get_dix_gex` / `get_market_regime`, surfaced daily in `/briefing` 1f).
- Existing positions: manage per the rules above; do not add.
- Resume only when the score falls back to Watchful/Clear and credit stabilizes.

This is the discipline that reconciles selling vol with the keep-powder posture: harvest in calm regimes, stand down exactly when the tail you're short starts to materialize. Without it, this sleeve is just picking up pennies in front of the late-cycle steamroller.

## Trial protocol (investigate before scaling)

Per `feedback_shadow_then_live` — prove positive expectancy on a small sample before sizing up.

- **Start at ~$50–75K collateral**, not the full $250K.
- **Run 8–12 weeks** on a **separate ledger** (premium collected − losses/assignment MTM − spread costs).
- **Success metric:** net annualized yield beats the T-bill floor by a *meaningful* margin **AND** no single tested week wipes more than ~6–8 weeks of accumulated premium.
- **Scale toward the $250K cap only after** the trial proves positive net expectancy through at least one tested week. If a single bad week erases the quarter's premium, the risk/reward isn't there — stop.

## Execution / accounts

- Index legs (QQQ/IWM) are Webull-executable (preview/place via MCP). Suggested home: a single Webull account to keep the sleeve's ledger clean and separate from the growth-first entry CSPs.
- GLD/GDX legs fit the existing wheel accounts (Webull Roth / Fidelity HSA) or the same sleeve account.
- Always preview before placing (`feedback_preview_prices`); limit orders only on wide-spread names.

## Status

**Investigation/trial phase as of 2026-07-17.** First trial legs identified (IWM 285P + GLD 355P, 7/24 weekly, ~$64K). No live position yet. Do not scale past the trial size until the 8–12 week ledger clears the success metric.
