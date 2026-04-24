# Tax Loss Recovery Playbook

Playbook for capturing the annual tax loss selling → January recovery cycle. The most predictable recurring pattern in equity markets: investors sell YTD losers in November-December to harvest tax losses, creating artificial selling pressure that reverses in January when the pressure lifts.

**Edge:** The selling is tax-motivated, not fundamental. The catalyst has a known expiration date (year-end). When a high-conviction name is down 25%+ YTD with intact fundamentals, the December weakness is an entry opportunity with a built-in timeline.

**Frequency:** Once per year. Setup develops in November, entry window is December, payoff is January.

---

## When This Playbook Applies

**Gate 1: Calendar** — November through mid-December. Tax loss selling peaks in the last 4-6 weeks of the year. Earlier selling (October) is usually fundamental, not tax-driven.

**Gate 2: Candidate identification** — screen pipeline names for:
- YTD drawdown >20%
- Conviction intact (Steps 1-4 already completed, no thesis-breaking developments)
- Elevated selling volume in November-December vs trailing 3-month average
- No fundamental catalyst explaining the recent leg down (earnings miss, guidance cut, etc.)

**Gate 3: Confirm tax-driven selling** — distinguish from fundamental selling:

| Signal | Tax-Driven | Fundamental |
|--------|-----------|-------------|
| Selling volume | Elevated in Nov-Dec specifically, normal before | Elevated for months, tied to earnings or news |
| News | No new negative catalysts | Earnings miss, guidance cut, sector headwind |
| Analyst estimates | Stable or rising | Declining |
| Conviction score | Unchanged from prior analysis | Deteriorated (new Negative factors) |
| Insider activity | No unusual selling | Insider selling accelerating |

If 3+ signals point to tax-driven, proceed. If fundamental selling, skip — the January bounce won't come for a broken thesis.

---

## Entry Timing

Tax loss selling follows a predictable calendar:

| Period | What's Happening | Action |
|--------|-----------------|--------|
| **Early November** | Selling begins, gradual | Screen and identify candidates. Re-run `get_entry_signals` to confirm conviction. |
| **Late November** | Selling accelerates (post-Thanksgiving) | Begin positioning on highest-conviction names |
| **Early-Mid December** | Peak selling pressure | Primary entry window — maximum discount, IV often elevated |
| **Late December** | Selling exhausts, early bargain hunters enter | Last entry window. Volume drops, names stabilize. |
| **January** | Selling pressure fully lifts, recovery begins | Hold positions, manage per targets below |

---

## Entry Strategy Matrix

The entry method depends on drawdown depth and IV environment:

| Drawdown YTD | Conviction | IV Rank <30% | IV Rank 30-50% | IV Rank >50% |
|-------------|------------|-------------|---------------|-------------|
| **>30%** | Highest | **Long calls** — cheap vol + known catalyst | **Hybrid** — direct buy + CSP | **CSP-heavy hybrid** — sell the rich premium |
| **>30%** | High | **Direct buy** (tranches) | **Hybrid** — direct buy + CSP | **CSP** |
| **20-30%** | Highest | **Direct buy** (tranches) | **CSP** | **CSP** (best premium math) |
| **20-30%** | High | **Small direct buy** (starter) | **CSP** | **CSP** |

### Long Call Parameters (>30% drawdown, IV Rank <30%)

This is the directional leverage variant. The "catalyst" is the calendar — selling pressure lifts at year-end.

| Parameter | Target | Rationale |
|-----------|--------|-----------|
| Delta | 0.40-0.50 | Balanced leverage and probability |
| Expiry | Late January to mid-February | Spans the recovery window with buffer |
| Entry | Early-mid December | During peak selling, before recovery |

The known timeline is what makes directional leverage appropriate here — you're not guessing when the catalyst fires. Tax selling ends on December 31. Period.

### CSP Parameters

Standard framework rules from [strategy-catalog.md](strategy-catalog.md), with selloff-adjusted strikes:

| Drawdown | Strike Target | Rationale |
|----------|--------------|-----------|
| >30% | ATM to 5% OTM | You want assignment at these prices |
| 20-30% | 5-10% OTM | Balanced — assignment gives additional discount |

Expiry: January monthly (3rd Friday). Spans the selling period and captures the bounce. If assigned, you own shares at a discount heading into the recovery.

### Direct Buy Parameters

Scale-in tranches per [strategy-catalog.md](strategy-catalog.md):
- T1 in early December (starter position)
- T2 in mid-late December if price drops further or thesis confirmed
- Reserve: always keep T2 capital available — selling can deepen before it lifts

---

## Screening Workflow

```
November (weekly):
1. Review pipeline for YTD losers >20%
2. get_entry_signals <TICKER>         — re-confirm conviction, check for new Negative factors
3. get_company_news <TICKER>          — any fundamental catalyst for the decline?
4. get_iv_metrics <TICKER>            — IV environment for strategy selection

December (entry):
5. get_option_expirations <TICKER>    — find January expiry
6. get_option_chain <TICKER> <expiry> — strike selection
7. For long calls: target 0.40-0.50 delta, Jan/Feb expiry
8. For CSPs: target per drawdown table above, January expiry
```

---

## Sizing

| Rule | Limit |
|------|-------|
| Max single position (long calls) | 3% of portfolio (premium at risk) |
| Max single position (CSP/direct) | Standard framework sizing (per conviction tier) |
| Max total tax-loss deployment | 20% of portfolio across all candidates |
| Max candidates | 3-5 names (focus beats diversification here) |

The 20% cap exists because you're concentrating entries in a narrow time window. If January disappoints, you don't want a quarter of your portfolio in names that didn't bounce.

---

## Management

### Long Calls

| Rule | Trigger |
|------|---------|
| Take profit | 50% return on premium (stretch: 100%) |
| Time window | Most of the bounce happens in the first 2-3 weeks of January |
| Time stop | If no recovery by late January, close. The thesis was tax-driven bounce — if it hasn't happened, it won't. |
| Roll | Don't roll. This is a defined-window trade. If it doesn't work, take the loss. |

### CSPs

| Rule | Trigger |
|------|---------|
| Expires worthless | Keep premium, reassess for next cycle |
| Assigned | Hold shares — you had high conviction at these prices. Manage per standard framework. |
| Take profit early | Buy back at 50% profit if reached before expiry |

### Direct Buy

Standard [management-rules.md](management-rules.md) applies. The tax-loss entry is a timing mechanism, not a different holding strategy.

---

## What Can Go Wrong

| Risk | Mitigation |
|------|-----------|
| **January selloff** — broad market drops in January, overwhelming the bounce effect | Sizing cap (20%). The tax-loss bounce is a tailwind, not a guarantee. |
| **Fundamental deterioration masked as tax selling** — the stock is down for real reasons | Gate 3 screening. Re-run `get_entry_signals` in December, not just once in November. |
| **Crowded trade** — everyone knows about January effect, front-running erodes the edge | Enter in December during active selling, not in late December when bargain hunters arrive. The pain of buying during selling is the edge. |
| **Low-liquidity names** — small/mid caps may have wide spreads in December (low volume) | Check liquidity rating via `get_iv_metrics`. Liq 3-4 → direct buy only, skip options. |
| **Tax law changes** — wash sale rules, holding period changes, or capital gains rate changes could alter behavior | Monitor in November. If tax policy shifts are pending, the pattern may weaken or invert. |

---

## Historical Context

The January effect is one of the most studied market anomalies. It has weakened over decades as more participants trade it, but the underlying mechanic (forced selling with a deadline) persists because tax incentives don't change. The edge is smaller than it was in the 1980s, but it's real — especially on names with genuine fundamental support that are being sold purely for tax reasons.

The best opportunities come in years with high market dispersion — when some names are up big (creating tax gains to offset) while others are down big (creating the candidates). Years where everything moves together produce fewer candidates.
