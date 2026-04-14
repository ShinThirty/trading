# Cycle Health Check: Leading Indicators for AI Capex Turn

By the time a hyperscaler CEO says "capex moderation" on an earnings call, AVGO and VRT are already down 20% in after-hours. You cannot wait for the official announcement. The covered calls provide a floor, but detecting the turn early lets you tighten strikes, pull expiries closer, and accelerate the exit before the gap-down.

**Run this check monthly (around the 10th-15th). If 2+ signals flash yellow, execute the defensive playbook below.**

## Signal 1: Cloud Compute Spot Market (canary in the coal mine)

Hyperscalers buy GPUs to rent them out. If rental demand softens, buying stops.

- **GPU rental lead times**: If securing a large GPU cluster from AWS/Azure drops from months to days/weeks, supply has caught up to demand.
- **Spot pricing for compute**: Track hourly rates for GPU instances (AWS P5, Azure ND H100) on spot/secondary markets (Lambda Labs, CoreWeave, AWS Spot). Aggressively dropping spot prices = excess un-rented capacity. Why buy more hardware if current hardware sits idle?

## Signal 2: Upstream Supply Chain & ODMs

The companies that actually build the servers and chips report earlier and more frequently than their hyperscaler customers.

- **TSMC monthly revenue**: Reported monthly. Watch for unseasonal plateaus or declines. More importantly, watch CoWoS (Chip-on-Wafer-on-Substrate) advanced packaging capacity — if TSMC pauses its own capex for expanding CoWoS, the cycle is topping.
- **Taiwanese ODM monthly sales**: Quanta, Wistron, Wiwynn report sales around the 10th of every month. A sudden, unseasonal plateau in monthly revenue growth = hyperscalers quietly tapped the brakes on deliveries.
- **SMCI revenue trajectory**: Already volatile, but a sustained downturn here leads the broader semi space.

## Signal 3: Memory Pricing (HBM)

High-Bandwidth Memory is attached to every AI accelerator. Memory is notoriously cyclical and sensitive to demand shocks.

- **HBM spot pricing**: If spot prices for HBM start softening, GPU production is slowing.
- **Memory maker guidance**: SK Hynix, Micron, Samsung. If any guide down forward memory capex, it's a massive leading indicator.
- **MU is in the portfolio** — its earnings calls and guidance are a direct read on HBM demand.

## Signal 4: Networking & Power (edge fraying)

Semi cycles rarely turn all at once — the edges fray first, then the core.

- **Optical transceivers & networking**: Companies making optical components (Coherent, Lumentum) and networking chips (MRVL). If they guide down, GPUs are next. CRDO connectivity is a direct read here.
- **Data center power equipment**: Eaton, Schneider Electric, Legrand. If backlog for data center thermal management and power delivery stops growing, new data center construction is slowing. VRT is the canary for this subsector.

## Signal 5: Software ROI Check (the fundamental ceiling)

The $690B+ in AI infra capex must eventually be justified by software revenue. If enterprise AI adoption stalls, hyperscaler CFOs will pull the plug.

- **Watch Phase 3 AI software adoption**: Microsoft Copilot adoption numbers, ServiceNow AI agents, Salesforce Agentforce, Adobe Firefly revenue contribution.
- **The test**: If multiple quarters pass and enterprises refuse to pay for AI tools because productivity gains aren't materializing, the infrastructure investment thesis collapses from the demand side.

## Defensive Playbook (when 2+ signals flash yellow)

| Action | Detail |
|--------|--------|
| **Tighten CC strikes** | Roll existing CCs to closer-to-ATM strikes — accept less upside to lock in more downside protection |
| **Pull CC expiries closer** | Roll from Dec '26/Jan '27 to shorter-dated expiries — accelerate the exit |
| **Stop rolling CSPs** | On any Phase 1 names, let existing CSPs expire. Don't write new ones. |
| **Accelerate LEAPS exits** | NVDA Jan '27 LEAPS — if signals fire before earnings catalyst (5/27), close for whatever profit exists rather than holding into a gap-down |
| **Rotate into Phase 3** | Begin CSP pipeline on software/application winners (ADBE, CRM, FTNT) at fear-compressed valuations |
| **Portfolio hedges** | Activate QQQ bear put spreads (Category A from L3 plan) |
