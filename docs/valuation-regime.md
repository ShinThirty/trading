# Valuation Regime Framework

Two reads of how risk-free rates translate into equity multiples: the **equity risk premium** (cross-section, level) and the **yield curve regime** (time-series, change). Together they tell you whether multiples have room to expand, what kind of yield move is driving the discount-rate path, and which intents/strategies the regime favors.

These are companion reads to `get_market_regime` — that tool covers volatility, breadth, sectors, credit, sentiment, and positioning. Valuation regime is the missing dimension: the *rate at which earnings turn into equity prices*.

## Equity Risk Premium (ERP)

`get_equity_risk_premium` returns the current value, regime tier, and the historical-P/E decomposition (current vs 5y avg, 10y avg, quarter-end). The narrow definition:

```
ERP = forward earnings yield − 10Y Treasury yield
    = (1 / forward_12M_PE) − DGS10
```

Forward P/E comes from FactSet's weekly Earnings Insight PDF (Friday afternoon ET). 10Y comes from FRED `DGS10`. There's usually a 1-day asymmetry between the FactSet snapshot (~Thursday close) and the latest available DGS10 — directionally fine for regime tier reads, not precise to the basis point.

### Tier definitions

| Tier | ERP | What it means | Implication |
|---|---|---|---|
| **Generous** | ≥ +500 bps | Equities cheap vs bonds | Post-GFC 2010-2019 norm. Multiple-expansion room available. Accumulate intent strongest here. |
| **Fair** | +200 to +500 bps | Long-run historical middle | Default framework applies. Returns come from earnings + modest multiple cushion. |
| **Tight** | 0 to +200 bps | Late-cycle valuation regime | Returns come from earnings primarily. Multiples can hold but not expand much. Reduce position sizes on high-multiple names. |
| **Compressed** | -100 to 0 bps | Equities richer than bonds | No room for multiple expansion. Any rate shock compresses mechanically. Favor margin expansion over multiple expansion. Cap accumulate intent at moderate conviction. |
| **Compressed-Negative** | < -100 bps | Dot-com territory | Mechanical compression on any rate or earnings shock. Skip new accumulate. Speculative-growth gate routes to skip. Tail hedges look cheap by ratio. |

### Decomposition: multiples vs rates

The tool also reports implied ERP at the 5y / 10y / quarter-end forward P/E with current DGS10. This lets you read where the compression is coming from:

- If **current P/E >> historical P/E** but implied-ERP-at-5y-avg-P/E is still in the same tier: compression is from rates, not multiples
- If **current P/E ≈ historical P/E** but ERP is compressed: compression is from rates entirely
- If **current P/E >> historical P/E** AND implied-ERP-at-5y-avg-P/E is much better: compression is from multiples (sentiment-driven)

The third case is the most fragile — it unwinds with multiple compression, not rate moves.

### Historical reference points

Use these as sanity-check anchors when reading the current tier label:

| Period | Approximate ERP | Tier | Context |
|---|---|---|---|
| 1995-2000 dot-com peak | -150 to +100 bps | Compressed → Compressed-Negative | Multiple bubble, not credit bubble |
| 2001-2007 mid-cycle | +100 to +250 bps | Tight → Fair | Normal late-cycle range |
| 2008 H2 (Lehman) | -100 to +200 bps | Compressed → Tight | Earnings collapse drove ERP down |
| Mar 2009 trough | +500 to +800 bps | Generous (extreme) | Capitulation pricing |
| 2010-2019 post-GFC | +400 to +600 bps | Fair → Generous | ZIRP-era benchmark |
| 2020-2022 pandemic | +200 to +500 bps | Fair → Generous | Multiples expanded as rates fell |
| 2023-2026 current | -100 to +150 bps | Compressed → Tight | Multiples held while long end rose |

## Yield Curve Regime

`get_yield_curve_state` returns 2Y / 10Y / 30Y levels, 4-week / 12-week changes, 2s10s + 10s30s spreads, and a regime tier. The diagnostic isn't the *level* of yields — it's *which tenor is leading* the move over the 4-week window. That tells you what's actually repricing.

### Tier definitions

| Regime | Pattern | What's repricing | Strategy implication |
|---|---|---|---|
| **Bear Steepener** | Yields rising, long end leads | Term premium / inflation / supply | Hostile to long-duration equities and bond proxies. Discount rate rises faster than Fed cuts can offset. Favor short-duration cash flows (commodities, energy, banks). Multiple compression mechanical. |
| **Bear Flattener** | Yields rising, short end leads | Fed-path repricing (hawkish) | Less hostile than bear steepener — long end stable means duration multiples less mechanically punished. Still tightens financial conditions. Defensive on rate-sensitive names. |
| **Bull Steepener** | Yields falling, short end leads | Fed cuts being priced | Constructive for equities. Multiple-expansion room opens. Watch for un-inversion trap if cuts confirm recession. |
| **Bull Flattener** | Yields falling, long end leads | Duration bid / recession trade | Mixed signal — bonds rallying because growth is slowing. Defensive equity positioning despite falling discount rate. |
| **Quiet** | All 4w moves <10 bps | No meaningful repricing | Default framework applies. Trade the stock signal. |
| **Mixed** | Tenor moves disagree | No coherent regime | Don't read macro into the curve this week. |

### Shape vs direction

The regime label describes the *direction of change* (steepening or flattening over 4w), not the absolute curve shape. A bear flattener can still leave the curve well-steeped overall — what matters is whether the 4w move is making it steeper or flatter, and which tenor is doing the work.

For absolute-shape tracking (un-inversion trap detection), `get_market_regime` already covers T10Y2Y vs Fed funds direction. Use `get_yield_curve_state` for the velocity + leading-tenor diagnostic.

## How valuation regime feeds decisions

### Step 1 (Conviction & Intent)

ERP tier conditions the conviction tier without overriding it:

| ERP tier | Conviction adjustment |
|---|---|
| Generous | No adjustment — accumulate intent works full size |
| Fair | No adjustment |
| Tight | Reduce concentration on high-multiple names; favor margin-expansion stories |
| Compressed | Cap accumulate at moderate; prefer enter-at-discount (CSP) over direct buy |
| Compressed-Negative | Skip new accumulate; speculative-growth gate skips even strong unit economics |

### Step 2 (Read the Signals)

Run alongside `get_market_regime`:

- `get_equity_risk_premium` — valuation regime tier
- `get_yield_curve_state` — what's driving the discount-rate move

Both surface where in the macro cycle returns will come from (earnings vs multiples).

### Step 3 (Strategy Selection)

Curve regime shifts default strategy weights:

| Curve | Accumulate | Directional leverage | Harvest premium |
|---|---|---|---|
| Bear Steepener | Skew toward CSP (rate shock = better entry) | Avoid long calls on duration names | Sell index call spreads (multiple compression) |
| Bear Flattener | Direct buy still fine on margin-expansion names | OK but size down | Default |
| Bull Steepener | Best window — multiples have room | Long calls work | Tighter strikes (vol may compress) |
| Bull Flattener | Defensive — earnings will be the problem | Skip — growth slowing | Range strategies |
| Quiet / Mixed | Default | Default | Default |

## When to check

- **Biweekly review** — both tools as part of the macro section
- **After any 50+ bps move in DGS10 over a week** — curve regime may have shifted
- **After FactSet Friday PDF** — ERP may have shifted on earnings revisions
- **Before opening any LEAPS or PMCC-like long-duration position** — multiple-compression risk is mechanical at compressed-negative ERP

## Companion reads

- [decision-framework.md](decision-framework.md) — Step 1/2/3 integration
- [market-regime.md](market-regime.md) — verdict + dimensional reads
- [bearish-framework.md](bearish-framework.md) — compressed ERP routes more names to bearish setups
- [tail-hedge-playbook.md](tail-hedge-playbook.md) — structural hedge economics shift at compressed-negative ERP
