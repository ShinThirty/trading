# Pre-Profit Speculative-Growth Framework

Decision framework for the **Speculative Growth** conviction tier — pre-profit IPO candidates where unit economics may compound, but profitability is not yet proven.

Derived from a 16-name historical study (`docs/research/pre-profit-growth-study.md`). Replaces the manual override previously captured in `feedback_pre_profit_speculation.md`.

---

## When this framework applies

Use this framework when evaluating a **pre-profit IPO candidate** that doesn't fit cleanly into the standard intent tiers in `decision-framework.md`. Typical profile: high revenue growth, GAAP losses, "story stock" pitch, narrative-driven valuation.

**Pre-check (must pass to be in scope):**

| Check | Required | Rationale |
|-------|----------|-----------|
| Trailing 12-month revenue ≥ $100M | Yes | Below this, the company is venture-stage (RIVN was pre-revenue at IPO with $10.5B raised). Wait for revenue evidence. |
| Operating income ≤ 0 (i.e., not yet GAAP-profitable) | Yes | If already GAAP-profitable, route to Accumulate or Defined-risk-exposure tier — this framework doesn't apply (ANET case). |
| At least one full audited fiscal year disclosed | Yes | Pets.com had 7 months of operating history at S-1; no way to evaluate. |

If any pre-check fails → **out-of-scope** for this framework.

---

## Core principle: bias toward rejection

The asymmetry of errors favors rejection:

- **False positive** (admit a future SNAP/PTON/AFRM-style ambiguous name): permanent capital impairment at speculative-growth-tier sizing
- **False negative** (reject a future NVDA/TWLO/ROKU-style winner): foregone upside, but the name doesn't disappear — re-evaluate at next 10-K when structural risk dissipates

**Borderline cases default to reject.** Don't let "but it might work out" override clear gate failures. If you're not sure, that uncertainty itself is a reject signal.

---

## Snapshot discipline

- Use the **most recent disclosed full fiscal year** as the observation point
- Do NOT cherry-pick a favorable historical year (PTON's S-1 had FY2018 OCF +$50M and FY2019 OCF -$109M; the deterioration was the warning)
- A sharp deterioration in the most recent year (OCF flipping negative, op margin worsening >5pp, GM worsening >5pp) is itself a critical warning — overrides apparent strength in prior years
- For the IPO-era business, evaluate as it is — do **not** credit hypothetical future pivots that aren't visible in disclosures (NVDA's $3T came from CUDA + AI pivots not in 1999 S-1)

---

## Capital structure prerequisite (one of two paths must pass)

The business must pass EITHER the software path OR the negative-working-capital path.

### Software path (DDOG, MDB pattern)

| Check | Required |
|-------|----------|
| Gross margin ≥ 70% | Yes |
| Capex / revenue ≤ 10% | Yes |
| Consolidated OCF margin positive OR clearly improving toward positive | Yes |

### Negative-working-capital path (AMZN pattern)

| Check | Required |
|-------|----------|
| Gross margin ≥ 15% | Yes |
| Capex / revenue ≤ 10% | Yes |
| Consolidated OCF margin positive (or break-even) at observation point | Yes |
| Repeat customer rate (or NRR equivalent) ≥ 40% disclosed | Yes |

**Always evaluate consolidated economics, not segment economics.** PTON's subscription segment alone looked SaaS-grade (67% GM, 0.65% monthly churn) — but the consolidated business with hardware capacity build was capex-heavy and OCF-negative. Subscription metrics in isolation can mislead.

If neither path passes → **REJECT.** Asset-heavy businesses (hardware, CPG, biotech, manufacturing) typically fail both — they should be evaluated under different frameworks, not forced through this one.

---

## Hard requirements (all must pass)

| Requirement | Threshold | Rationale |
|-------------|-----------|-----------|
| Customer/distributor concentration | No counterparty >10% of revenue | Look-through to whoever physically pays. BYND failed at 66% from 3 distributors; AFRM at 30% (Peloton). |
| Customer concentration trajectory | Stable or decreasing | If single-customer % is *increasing* (AFRM Peloton 20%→28%→30%), flag as more dangerous than static 10%+. |
| Operating history | ≥3 years before public disclosure | Pets.com had 7 months. Allow 2+ years only if hyper-acceleration evidence (AMZN's 18x sequential growth). |
| Pre-IPO capital raised / TTM revenue | ≤5x | Pets.com 167x, RIVN infinite. Winners cluster 0.2-2.7x. |
| Off-balance-sheet commitments | Future minimum lease + inventory + capex commitments / TTM revenue ≤3x | WeWork had $47.2B leases / $3B revenue = 16x. |
| No asset-liability duration mismatch | Revenue duration must match liability duration | WeWork had 15-year leases vs month-to-month memberships — built-in fragility. |
| For software cases | NRR / Net Revenue Expansion ≥120% disclosed for 4+ consecutive quarters | DDOG 146%+, MDB 120%+ for 10+ quarters. |
| For NWC cases | Repeat customer rate ≥40% AND increasing or stable | AMZN >40% growing to 73%; Pets.com "no material" repeat business. |

---

## Soft signals (need 3+ of 5)

| Signal | Bullish if... | Notes |
|--------|---------------|-------|
| Cash flow inflection | CFO+ at S-1 OR clear path to CFO+ within 24 months | NFLX CFO+ at IPO was the canonical strong signal |
| S&M efficiency | $ revenue growth / $ S&M spend ≥0.5x | DDOG 1.85x, MDB 0.67x acceptable when NRR strong |
| Multi-product expansion | No single product >50% of revenue OR clear roadmap articulated | DDOG infra→APM→logs→security; BYND was 70% Beyond Burger |
| Founder still at company | CEO or CTO, **and no super-voting structure, and no disclosed self-dealing** | WeWork failed both governance tests; SHOP/SNAP have multi-class but no abuse → neutral, not positive |
| Operating margin trajectory | Improving for 3+ consecutive years (not a one-year breakout) | BYND nearly hit breakeven FY2019 then collapsed — single-year "breakeven" is misleading peak |

---

## Disqualifying signals (any one = automatic reject)

| Signal | Example |
|--------|---------|
| Non-GAAP metric invented to exclude basic operating costs | WeWork's "Community-Adjusted EBITDA" excluded G&A, S&M |
| Disclosed self-dealing transactions between founder/insiders and the company | Adam Neumann sold "We" trademark to himself for $5.9M |
| Sharp deterioration in most recent disclosed year on key metrics | OCF flipping negative (PTON FY2018→FY2019), op margin worsening >5pp, GM worsening >5pp |
| Self-disclosed "expect losses for 4+ years, increasing" or equivalent honest statement of structural unprofitability | Pets.com S-1 |

---

## Verdict logic

Apply in order:

1. **Pre-check.** If any fails → out-of-scope (use different framework).
2. **Disqualifying signals.** Any one → reject.
3. **Capital structure prereq.** Neither path passes → reject.
4. **Hard requirements.** Any one fails → reject.
5. **Soft signals.** Fewer than 3 of 5 pass → reject.
6. **All gates pass cleanly** → **Pass** (clear admission to speculative-growth tier).
7. **Some gates require judgment** (e.g., hybrid economics where literal capex fails but OCF positive proves productive spend) → **Borderline pass** with smaller initial size and explicit re-evaluation trigger.

---

## Borderline patterns to watch

### Hybrid economics (AMZN, NFLX, SHOP pattern)

**Profile:** Recurring/sticky revenue + capital-intensive infrastructure (e-commerce + warehouses, subscription + rental inventory, SaaS + payments). Literal capex gate fails; OCF positive or near-positive; subscription segment clean SaaS but blended below 70% GM.

**Practical rule:** Default to literal-rejection per bias-to-rejection. Flag for re-evaluation at next 10-K. These names typically inflect to clear-pass within 1-2 years post-IPO. Cost of waiting (foregone first-year returns) is bounded.

### "Acceptable false negative" cluster (NVDA, TWLO, ROKU pattern)

**Profile:** Founder-CEO with super-voting structure + customer concentration failing literal gate + OCF borderline at IPO + multi-product platform articulated + capital-efficient build.

**Practical rule:** Framework correctly rejects per concentration/governance gates. Recognize this cluster: when 3+ of these signals are present, expect rejection AND expect the name might be a re-entry candidate after 1-2 years of structural risk dissipation (concentration normalizes, OCF stably positive, governance softens).

### Sentiment-driven peak rallies (SNAP, AFRM pattern)

**Profile:** Real revenue growth + plausible bull narrative + sentiment-driven 3-5x rally post-IPO + multi-year disappointment.

**Lesson:** Real revenue growth ≠ compounding unit economics. The framework rejects these correctly even when the post-IPO rally looks tempting. **The framework is NOT a "buy at any price" signal** — it evaluates IPO-era unit economics, not entry timing on already-public names.

---

## Sizing and strategy guidance

For names that **pass or borderline-pass** the framework:

| Element | Rule |
|---------|------|
| Position size cap | 3-5% of portfolio (smaller than Accumulate's 15% cap) |
| Initial deployment | Single tranche; no scale-in until first post-IPO 10-K validates |
| Strategy | Direct buy preferred (CSP collateral inefficient when stock is volatile) |
| Long calls | Only if IV Rank <40 (most pre-profit IPOs have rich IV) |
| Leverage / spreads | None until business proves out (multiple consecutive years of CFO+) |
| Borderline-pass reduction | Use lower end of cap (3% instead of 5%) and require explicit re-evaluation note |

**Sizing rationale:** Pre-profit hyper-growth has higher uncertainty than profitable accumulate-tier names. The cap reflects that even a passing thesis can still drawdown 50-70% in a multiple-compression cycle (TWLO, ROKU). Size for the drawdown.

---

## Re-evaluation cadence

For names admitted at borderline-pass OR rejected on a single specific gate (concentration, OCF inflection):

- **Trigger:** Annual 10-K release, or material disclosure (major customer loss, restructuring, acquisition)
- **Pass/fail check:** Re-run all hard requirements + cap-structure prereq with newest data
- **Action:** Upgrade to clear-pass if all gates now clean; maintain borderline if still mixed; close position if any disqualifying signal appears

**Names rejected on single gate** (NVDA-cluster pattern) are explicit re-entry candidates. Track these; don't permanently dismiss.

---

## Examples (cohort summary)

| Name | Verdict | Reasoning |
|------|---------|-----------|
| DDOG | Clear pass | Software path: 76% GM, 5% capex, OCF+ |
| MDB | Clear pass | Software path: 74% GM, 2% capex, NRR 120%+ for 10+ quarters |
| AMZN | Borderline pass | NWC path: 22% GM, 8% capex, OCF+ via negative working capital, repeat customers >40% |
| NFLX | Borderline pass | NWC path with rental-inventory caveat; OCF+ FY2001, churn ~7%/mo |
| SHOP | Borderline pass | NWC path; subscription segment SaaS-pure, capex 19% from infrastructure build |
| Pets.com | Reject | Negative GM (-198%), 7-month operating history, "expect losses 4+ years increasing" disclosed |
| BYND | Reject | 20% GM (1 year only), 25% capex, 66% concentration from 3 distributors |
| PTON | Reject | OCF turned negative most recent year (deterioration), capex hardware-funnel-to-subscription model |
| WeWork | Reject | Multiple gate failures + $47.2B lease commitments + Community-Adjusted EBITDA + self-dealing |
| RIVN | Reject | Pre-revenue at IPO; fails revenue threshold |
| SNAP | Reject | Negative GM (cloud infra costs), OCF -151%, capex 16%, capital efficiency 6.4x |
| AFRM | Reject | OCF -14%, Peloton 30% concentration AND concentrating |
| NVDA, TWLO, ROKU | Acceptable false negatives | All rejected on customer concentration + OCF; long-term winners but framework discipline preserved |
| ANET | Out of scope | Already GAAP-profitable at IPO — use Accumulate or Defined-risk tier instead |

---

## See also

- [`docs/research/pre-profit-growth-study.md`](research/pre-profit-growth-study.md) — full 16-name research study with 30 framework observations
- [`docs/decision-framework.md`](decision-framework.md) — parent framework; this doc handles the speculative-growth tier
- `~/.claude/projects/-Users-shinthirty-Workspaces-trading/memory/feedback_speculative_growth_bias.md` — bias-to-rejection principle
- `~/.claude/projects/-Users-shinthirty-Workspaces-trading/memory/feedback_pivot_optionality.md` — evaluate IPO-era business, not pivot optionality
