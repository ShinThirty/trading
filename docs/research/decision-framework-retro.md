# Decision Framework — Case Studies & Retrospective

Companion to [decision-framework.md](decision-framework.md). Contains worked examples, case studies, and the Feb-Apr 2026 retrospective that the framework rules were built from.

---

## Quick Reference: Entry Case Studies

| Stock | Date | Drawdown | IV-HV | Method Used | Optimal Method | Lesson |
|-------|------|----------|-------|------------|----------------|--------|
| ADBE | 4/13 | -44% | -2.6% | Pure CSP $220P | Hybrid (direct-heavy) | Low IV-HV = CSP doesn't overpay you |
| WDAY | 4/13 | -56% | +4.8% | Pure CSP $105P | Hybrid (direct-heavy) | 12.6% OTM too conservative for entry intent |
| NOW | pipeline | -58% | -2.4% | Pending | Hybrid (direct-heavy) | Same pattern as ADBE — IV fairly priced |
| PAYC | pipeline | -56% | +15.9% | Pending | Hybrid (balanced) | Rich IV-HV justifies more CSP weight |
| QCOM | pipeline | -37% | +17.2% | Pending | Pure CSP | Moderate drawdown + rich premium |
| FTNT | pipeline | -28% | +18.6% | Pending | Pure CSP + wait | Shallowest drawdown + active headwind |

---

## Quick Reference: CC Case Studies

| Position | CC Intent | Coverage | Strike Logic | Expiry Logic | Lesson |
|----------|-----------|----------|-------------|-------------|--------|
| CRDO $150C Jan '27 | Thesis exit | 70% (200/286) | Exit at semi cycle plateau | Latest safe exit per thesis | 86 uncovered shares captured today's 12% pump — partial coverage paid off |
| AMZN $250C Dec '26 | Growth w/ income | 90% (800/890) | Rolled $225→$250 for credit | Extended when thesis strengthened | Valid roll — genuine thesis evolution, not drift. Got paid $2.50/ct to roll. |
| AVGO $430C Dec '26 | Thesis exit | 100% (200/200) | Semi cycle exit price | Aligns with neocloud distress phase | Full coverage = committed exit. No second-guessing. |
| VRT $380C Dec '26 | Thesis exit | 80% (100/125) | AI power infrastructure peak | Dec 2026 same as AVGO | 25 uncovered shares for continued participation |
| META $660C Jun '26 | Growth w/ income | 86% (300/347) | ~3.5% OTM, happy-to-sell level | 2-month cycle, post-earnings window | Partial coverage on mega-cap — 47 shares ride free |
| SMH $410C May '26 | Liquidation | 100% (100/100) | Deep ITM ($444 current) | Near-term, one cycle | Getting called is the plan — premium was bonus on top of the exit |
| MOS $29.50C May '26 | Income/wheel | 100% (200/200) | Range-bound commodity play | Monthly rolling cycle | Low conviction, full coverage, wheel candidate |
| GDX $105C May '26 | Income | 88% (400/452) | 6% OTM on commodity position | Monthly cycle | Standard income CC on a non-growth holding |

---

## Chain P&L Worked Example: AMZN CC Chain

**The 50% rule on a rolled position can be misleading.** "50% profit on the current leg" is not the same as "profitable chain."

**AMZN CC chain (8 contracts):**

| Step | Cash Flow | Running Total |
|------|-----------|---------------|
| Sold $220C May | +$6.20/ct | +$6.20 |
| Roll to $225C Jun (net credit) | +$2.18/ct | +$8.38 |
| Roll to $250C Dec (net credit) | +$2.50/ct | +$10.88 |
| **Total chain credits** | | **+$10.88/ct** |
| Buy back $250C Dec at "50% profit" | -$13.00/ct | **-$2.12/ct** |

The current CC shows "50% profit" ($26.05 → $13.00) — but the chain only collected $10.88/ct total. Buying back at $13.00 means the CC chain **lost** $2.12/ct. Webull's P&L on the current leg masks the total chain cost.

**Why a chain loss isn't necessarily bad:** Each roll traded CC profit for share upside room. The AMZN rolls moved the cap from $220 → $250, gaining $30/share of upside on 800 shares ($24,000). The CC chain loss of $1,696 was the price of capturing that appreciation. Net benefit: +$22,304. The rolls were correct — but the CC side lost money.

**Why it matters:** If you only look at the current leg, you think you're taking profit. If you track the chain, you realize you're closing at a loss — which might still be the right move (stopping the bleed), but you should know the true cost.

---

## Roll Examples

**AMZN $225C Jun → $250C Dec (Apr 2026):** Rolled for $2.50/ct credit ($2,000 total on 8 contracts). Gained $25 of upside room and 6 months of additional time. Valid roll — thesis strengthened, credit received, new expiry aligned with Phase 1c exit.

**META $660C Jun → $720C Dec (planned Apr 2026):** $22/ct credit ($6,600 total on 3 contracts). Gains $60 of upside room before April 29 earnings. Rolled because earnings conviction is high and the June CC caps the expected beat. Dec expiry aligns with thesis timeline.

---

## Retrospective: Feb-Apr 2026

This framework was written in April 2026 after two months of learning by doing. The trades below — made before this framework existed — are the raw material it was built from.

### The Three Defining Trades

**ALAB — The $14K lesson that wrote Step 5**

| Date | Event | Price |
|------|-------|-------|
| Feb 2026 | Bought ~251 shares, no research, no CC, no scale-in | $182 |
| Mar 30 | Bottom — max drawdown -45% | $100 |
| Apr 9 | Sold into recovery — emotional exit | $125 |
| Apr 13 | Stock without you | $167 (+29% from sell) |

What went wrong: Entry violated every rule in this framework — no intent determination (Step 1), no signal reading (Step 2), full-size single-tranche entry (violates Step 4), no CC for emotional armor. Two months of slow-bleed drawdown created an intolerable dollar loss. The bounce to $129 felt like an escape window, not a confirmation signal.

What the framework would have done differently: Step 4 sizing (>35x P/E = reduced size). Scale-in with T2 reserved. CC written within 2 weeks of entry. Thesis checkpoint at -15% would have confirmed all five questions passed → hold or add.

**CRDO — The hold that proved the framework**

| Date | Event | Price |
|------|-------|-------|
| Mar 2-24 | Scaled in: 100 @ $103, 50 @ $103.50, 36 @ $99.70 | ~$102 avg |
| Mar 17 | GTC: "optical replaces copper" narrative | $104 → crash |
| Mar 30 | Bottom — max drawdown -30% from high | $88 |
| Apr 2 | Wrote $110C May CC (emotional armor) | $101 |
| Apr 13 | Recovery + DustPhotonics acquisition | $134 |

What went right: Scale-in across 3 tranches over 3 weeks. CC written during drawdown cushioned the pain. Thesis checkpoint passed — customers still buying, sector-wide drawdown, competitive moat intact. Partial coverage (200/286) let 86 uncovered shares capture the full recovery.

**LITE — The exit that showed how to sell**

| Date | Event | Price |
|------|-------|-------|
| Mar 4 | Bought 8 shares | $650 |
| Mar 10 | Sold 4 — first trim into strength | $692 |
| Mar 24-25 | Sold 4 — second trim higher | $780-790 |
| Apr 8 | Sold final 4 — last tranche at near-highs | $910 |

What went right: Sold in 4 tranches over a month, each at a higher price than the last. Every sell was "selling into strength" — motivated by hitting a target, not by relief. Average exit ~$768 vs $650 entry = +18%. Contrast with ALAB: LITE exits were confident; ALAB exit was exhausted.

### Patterns Across All Feb-Apr Trades

| Pattern | Trades that showed it | Framework rule it became |
|---------|----------------------|--------------------------|
| Single-tranche entries hurt | ALAB ($182 all-in), SNDK (10 @ $582), AVGO (20 @ $309) | Step 4: Always reserve cash for T2 |
| Scale-in entries work | CRDO (3 tranches), META (trimmed high, added low), PLTR (trimmed $155, rebought $130-141) | Step 4: Scale-in is default |
| Too many names too fast | 18 names bought in 10 days (Mar 3-13) | Step 4: Limit to 5-7 names/month |
| CCs prevent emotional exits | CRDO held through -30% with CC; ALAB sold at -29% without CC | CC Step 3: CCs as emotional armor |
| Selling into strength works | LITE (+18%), XLE (+6.5%), COHR (+6%), ARM (+16%) | Step 5: Selling into strength vs recovery |
| Selling into recovery fails | ALAB (sold $125, stock went to $167) | Step 5: The crash is the tax, the recovery is the refund |
| Thesis exits beat price exits | ALAB thesis was intact at exit — pure emotional sell | Step 5: Thesis checkpoint at -15% |
| ETFs are fine when you lack "which" | GLD, GDX, XLE — macro thesis without company-specific conviction | Which/When/How: ETFs for macro, stocks for conviction |
