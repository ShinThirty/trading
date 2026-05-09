---
description: Evaluate the structural tail-risk hedge program (Universa-style)
---

Manage the structural tail-risk hedge program per [tail-hedge-playbook.md](../../docs/tail-hedge-playbook.md). This skill evaluates whether one of the playbook's three triggers has fired and surfaces the resulting action. **It does not open, close, or resize the hedge based on cleared signals.**

The structural program is **deep OTM (20-25%) SPY puts at 90-120 DTE, rolled on discipline, never closed because nothing is wrong**. If you're considering correction-zone protection (5-15% OTM) instead, don't — see playbook Mistake 2. Either trim positions, hold cash, or use single-name puts at the position level.

## Step 1: Inventory the structural hedge

Call in parallel:
- `get_account_positions` for cash account `5GJ21MGS53M5FU0T8TQN6PEGQA`
- `decision_list` filtered by `source=hedge` for entry context
- `get_portfolio_summary` for live put P&L %

For each open SPY/QQQ put:

| Strike depth from spot | Classification | Action |
|---|---|---|
| ≥20% OTM | Structural sweet spot | Evaluate per Step 3 |
| 15-20% OTM | Edge of tail | Evaluate per Step 3; consider rolling deeper at next maintenance window |
| <15% OTM | **Outside structural definition** | Flag as legacy correction-zone position; recommend rolling to 25% OTM at next maintenance window |

If no structural hedge exists, jump to Step 5 (Recommendation) — the question is whether to commit to running the program, which is governed by playbook's [When to deploy](../../docs/tail-hedge-playbook.md#when-to-deploy), not by signals.

## Step 2: Pull trigger inputs

Call in parallel:
- `get_quote SPY,VIX,VIX3M`
- `get_tradier_history VIX` (60+ days, to read recent spike high)
- `get_tradier_history SPY` (60+ days, to read drawdown from recent high)
- `get_quote` on each put contract with `greeks=True` — read current delta
- `get_market_regime` — verdict + dimensional labels (incl Sentiment/Positioning/Policy extremes) for informational context only

Compute:

| Input | Source | Used by |
|---|---|---|
| Put delta | `get_quote greeks=True` | Trigger 1 |
| VIX retracement from spike high | VIX history | Trigger 1 |
| Put P&L % | `get_portfolio_summary` | Trigger 1 + 2 |
| SPY drawdown from recent high | SPY history | Trigger 2 context |
| Current VIX level | `get_quote VIX` | Trigger 2 context |
| DTE remaining | put expiry | Trigger 3 |

Regime/signal context from `get_market_regime` is **informational only** at this step. It does NOT drive hedge actions. It feeds downstream decisions (position sizing, pipeline timing, accumulation cadence) — not hedge open/close.

## Step 3: Evaluate the three triggers

Apply in priority order. First match wins. If none fire, **hold the hedge** — that's the answer.

### Trigger 1: Maintenance roll (delta drift)

Fires when **both**:
- Put delta in **-0.20 to -0.40** range (was -0.05 at entry; signals ~10-15% SPY drop has moved the put out of tail zone), AND
- One of:
  - VIX retraced ≥50% from recent spike high
  - Known catalyst that drove the move has resolved
  - Put P&L is in 100-300% range and stalling

Do NOT roll if:
- Delta still tighter than -0.15 (move hasn't materialized — give it room)
- VIX still climbing or holding above 30 (move not done)
- SPY making new lows daily (Trigger 2 may be coming — let it develop)
- P&L only 50-100% (premature — let convexity work)

### Trigger 2: Harvest tranches (real crash in progress)

Fires when the move is large AND fast — typically VIX above 50, SPY down 20%+ from recent high, puts deep ITM. Execute mechanically; do NOT try to top-tick. Read live P&L % from `get_portfolio_summary`.

| P&L threshold | Action |
|---|---|
| **+400% (5x)** | Close 50% of contracts |
| **+900% (10x)** | Close another 25% of original |
| **+1900% (20x)+** | Close remaining (let small residue ride only if crash is grinding lower with fresh leg setups) |

### Trigger 3: Routine 30-DTE roll (calendar)

Fires when DTE ≤ 30 regardless of any other condition. Sell expiring + buy fresh at the new 25% OTM strike from current SPY.

### Universal close+redeploy workflow (any trigger)

Sell the tranche (full for T1/T3, partial for T2) → `calculate_hedge` with current SPY + `crisis_multiplier=1.25` → buy new contracts at 25% OTM from *current* SPY → record `decision_close` (old) + `decision_add` action `WRITE_NEW` source `hedge` (new).

**No trigger fired → hold.** Cleared signals, premium decay, drawdown anxiety — none are valid close reasons. Decay is the design (3-7 consecutive losing years expected).

## Step 4: Cost tracking

Run `get_order_history` for the cash account, filter for SPY/QQQ put trades.

| Metric | Target | Action if breached |
|---|---|---|
| Annual drag % | 0.5-1.5% | Above 2%: check strike depth — likely correction-zone in disguise, OR entering at high IV (skip strikes with IV Rank >50% per playbook execution checklist) |
| Hedges closed YTD | tracking only | — |
| Total hedge P&L YTD | tracking only | Negative is the modal outcome — see playbook performance expectations |

**Do NOT** apply "3+ rolls without payoff = reduce exposure" logic. The playbook explicitly expects 3-7 consecutive losing years. That's the program working as designed, not a failure mode.

## Step 5: Recommendation

### If a structural hedge exists

**Action: [HOLD / MAINTENANCE ROLL / HARVEST TRANCHE / 30-DTE ROLL]**

| Field | Value |
|---|---|
| Position | (N contracts at K strike, exp date) |
| Strike depth | X% OTM (sweet spot / edge of tail / legacy) |
| Current put delta | -X.XX |
| DTE remaining | X |
| Put P&L % | X% |
| VIX current vs recent high | X.X / Y.Y (Z% retracement) |
| SPY drawdown from recent high | -X.X% |
| Trigger fired | None / Trigger 1 / Trigger 2 [percent] / Trigger 3 |
| Annual drag YTD | X% (vs 0.5-1.5% target) |

**Rationale:** One sentence — anchored on trigger criteria, NOT on signals or feel.

If action is anything other than HOLD: run through `preview_order` first, then place. Record via `decision_close` + `decision_add` (source `hedge`).

### If no structural hedge exists

This is a one-time program-commitment question, not a signal-driven entry. Surface the [When to deploy](../../docs/tail-hedge-playbook.md#when-to-deploy) inputs:

- Net delta from `get_portfolio_greeks`
- Equity exposure % from `get_portfolio_summary`
- Trailing beta from `calculate_hedge`
- Cash buffer

Then defer to the playbook for the commit/skip decision. If committing: run `calculate_hedge` with the parameters from the [Sizing](../../docs/tail-hedge-playbook.md#sizing) section, follow the [Execution checklist](../../docs/tail-hedge-playbook.md#execution-checklist), and record via `decision_add` (source `hedge`).

## What this skill does NOT do

- Open hedges based on signals (regime, vol, divergences) — those drive sizing/pipeline, not hedge actions
- Recommend correction-zone (5-15% OTM) puts at the portfolio level — use trimming or cash
- Close on cleared signals or premium decay — only the three triggers
- Time entry on IV (the only IV note: skip individual strikes at IV Rank >50%)

For single-stock catalyst hedges, use long puts per [strategy-catalog.md](../../docs/strategy-catalog.md) — not this skill.
