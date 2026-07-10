# Scalper Automation — Local Paper Entry-Detector

A standalone session-scoped app that **detects an intraday SPY/QQQ scalp setup,
prompts you to enter, and paper-trades the same option bracket** — so the
detector accumulates a reviewable track record before it is ever trusted with
real capital.

This is the executable counterpart to the [`/scalp`](../.claude/commands/scalp.md)
skill: the skill *draws the map* (pre-session levels, lean, day-type, and the
option contract per level); this app *watches the map* during the session, points
your eyes at a level the instant price tags it, and forward-tests the trade on
paper.

> Learning to read the map by eye — tape, VWAP, volume profile, gamma walls, L2 —
> is its own skill: see [chart-reading-curriculum.md](chart-reading-curriculum.md).

## Why this exists (and the pivot that shaped it)

The original design was an **assist-only stop-enforcer**: it watched for a manual
opening fill and auto-attached a broker-resting stop (`AutoStop`), the "killer
feature." That feature is **redundant** — Webull desktop natively brackets an
*option* order (a "1st-Trigger Stop": entry + an OCO stop-loss −20% / take-profit
+20%, resting at the broker). The broker already does the load-bearing exit job,
and better (it adds a take-profit leg + OCO the daemon never had).

So the daemon's value moved to the **entry**. Per memory `project-qqq-scalping`
the *reads* were fine; the net loss came from **no stops, chasing, and revenge
adds**. With the broker now owning the mechanical exit (place the native bracket
when you enter), what's left worth building is the thing that points your eyes at
a blessed level at the right moment — and a paper loop that measures whether those
prompts actually make money. See memory `project-scalper-pivot`.

## The three goals

1. **Prompt** — detect when the underlying tags one of the morning's blessed
   levels (filtered by the plan's `lean`, annotated with tape direction) and fire
   a desk alert: *enter here.*
2. **Auto-execute on paper** — on every prompt, place the *same* option bracket
   (entry + child stop-loss + take-profit, OCO) in an in-memory `PaperBroker`.
3. **Persist for review** — periodically write the paper ledger (fills + realized
   P&L) to disk so a session's detector performance is reviewable afterward, plus a
   per-fire **B4 velocity/absorption telemetry** log (recorded, not gated) so the
   run can later learn which setup conditions separate winners from losers.

## Safety model: paper-only

There is **no live-order path**. The old load-bearing invariant
(`RiskReducingOnly` — the daemon may submit only risk-reducing orders) is
deliberately gone: the daemon now *opens* positions, which that invariant
forbade. The new safety story is simpler and absolute — **it is all paper, zero
real capital at risk.** Going live (autonomous entry) is a future tier that must
be earned by a long paper track record; it is out of scope here.

## Two ports, not one

Data source and execution are **independent**. Tradier is the *data feed*; the
`PaperBroker` is the *executor*. (Webull is not involved in this design — the
human places the real bracket by hand on Webull desktop.)

```python
class MarketDataFeed(Protocol):          # where prices come from
    async def subscribe(self, symbols: list[str]) -> None: ...
    def on_quote(self, cb): ...          # top-of-book bid/ask + sizes
    def on_trade(self, cb): ...          # last prints
    def on_timesale(self, cb): ...       # the tape

class BrokerExecution(Protocol):         # orders out + order events in
    def place(self, order: Order) -> OrderId: ...
    def cancel(self, id: OrderId) -> None: ...
    def positions(self) -> list[Position]: ...
    def net_position(self, symbol: str) -> int: ...
    def realized_pnl(self) -> float: ...
    def on_order_event(self, cb): ...                 # fills / status changes
```

`PaperBroker` additionally exposes `place_bracket(symbol, qty, *, stop_pct,
target_pct)` — the in-memory analog of Webull's native OCO bracket: it opens at
market and rests a stop-loss + take-profit pair, where a fill on one cancels the
other.

### Data-feed reality (read before over-promising the detector)

None of the cheap streaming feeds replicate the **Nasdaq TotalView L2 ladder**
the user reads by eye on Webull Premium:

- **Tradier** stream = top-of-book quote + trade prints + timesale. **No depth
  ladder, no greeks.** Two-step handshake: `POST /v1/markets/events/session` for a
  `sessionid`, then `wss://ws.tradier.com/v1/markets/events`. **Streaming is
  production-only** — the sandbox serves 15-min-delayed data and cannot stream, so
  the feed needs a **production** Tradier token in `~/.tradingrc`.
- **Tastytrade** DXLink adds **streaming greeks + IV** on the option (the one real
  upgrade over Tradier) but still no retail depth ladder. A future data task.
- **Webull** TotalView L2 is an **app** entitlement, not cleanly via OpenAPI.

So the detector runs on **top-of-book + tape** — a degraded view of what you
already see. It is therefore an **alerter that points the eyes at a pre-mapped
level**, not (yet) an autonomous trigger. The human's eyes + the Webull L2 do the
real confirmation. See memory `project-scalper-pivot` for the full feed analysis.

## Architecture

```
MarketDataFeed (Tradier WS)
   │  underlying tape (QQQ/SPY)          option tape (the contracts)
   ▼                                          │
SetupDetector ── price tags a blessed level   │
   │  filtered by lean, tape-annotated         │
   ├──▶ Notifier (console + bell)  ── "enter QQQ 721P here"   (points the eyes)
   ├──▶ FireRecord ──▶ SignalLog ── per-fire B4 velocity/absorption telemetry JSONL
   └──▶ TradeProposal ──▶ PaperBroker.place_bracket ◀─────────┘
                              │  fills entry + rests OCO stop/target off the option tape
                              │  order events
                              ▼
                         PaperPersister ── fills JSONL + periodic P&L summary JSON
```

Each setup is a short paper round-trip: `propose → entry fill → {stop | target}
fill → flat`, with the losing OCO leg auto-cancelled. The detector fires **once
per tag** (hysteresis re-arms only after price leaves the band), so a hovering
price yields one prompt + one paper bracket, not a spam stream.

## Components

1. **`TradierFeed` / `MarketDataFeed`** — streaming session + WS subscribe for the
   underlyings *and* the plan's option contracts; emits quote/trade/timesale.
   `drive_paper_fills` fans every print into the `PaperBroker` matching engine, so
   option prints fill the bracket and underlying prints feed the detector.
2. **`SetupDetector` + `Notifier`** — fires only a *confirmed* setup, gated on
   three things already on the wire: **geometry** keyed to the level's `mode`
   (`fade` = touch-and-reject within the band, the +GEX trade; `break` =
   cross-the-wall-with-follow-through, the −GEX trade), **lean** (on the trade
   *direction* — a call/long needs `long-only`/`both`, a put/short
   `short-only`/`both`), and **tape** (the print aggressor must agree with the
   option's call/put). On a confirmed fire it `notify`s the human (console line +
   bell) and, if the level names a `contract` whose quoted spread is tradeable,
   emits a `TradeProposal`; a confirmed-but-wide spread still alerts but is not
   paper-filled (honest fills). There is no bare-touch heads-up. Underlying
   top-of-book size imbalance is a soft annotation, never a gate.
   A **break** level additionally **arms** only after the detector has *witnessed*
   price on the pre-break side (below a resistance breakout, above a support
   breakdown): a break is a one-time edge event, but the geometry gate alone reads
   "price is currently across the level" — true for the whole extended move — so a
   cold start (or re-arm) with price already past the level stays silent until
   price comes back and crosses again. The **wake guard** backs this up: a long gap
   between print timestamps (`gap_s`, default 90s) means the stream was
   suspended/disconnected (laptop sleep), so all arming + fired state is dropped —
   every break level must re-witness its setup side before it can fire. Together
   these stop a daemon that slept through the actual cross from waking up and firing
   at the extended top (the 2026-06-15 paper-run loss mode). Fade levels need no
   arming — they re-test their level all session and self-correct.
3. **`PaperBroker.place_bracket`** — opens the proposed contract at market and
   rests an OCO stop-loss (`entry*(1-stop_pct)`) / take-profit (`entry*(1+target_pct)`)
   pair, mirroring the native Webull bracket. Position + realized P&L are computed
   by the `Ledger` cost-basis primitive (the single place the math lives).
4. **`PaperPersister`** — subscribes to the broker's order events; appends each
   fill to `~/.trading/scalp/paper/{date}.jsonl` and rewrites a
   `{date}-summary.json` (realized P&L + open positions) on a timer and once on
   shutdown.
5. **`SignalLog`** — the detector's `record` sink; appends one row per *confirmed
   fire* to `~/.trading/scalp/paper/{date}-signals.jsonl` carrying the **B4
   velocity/absorption telemetry** (trailing-window underlying velocity in $/s,
   cumulative confirming vs contrary tape size, top-of-book imbalance) next to the
   setup identity. **Recorded, never a gate** — separate from the fills log on
   purpose, so an alert-only or spread-suppressed fire (no paper fill) is still
   captured. The paper run mines these against the realized win/loss to learn which
   metrics actually separate winners from losers *before* any of them is allowed to
   veto a setup.

## The `/scalp` handoff — the session plan (daily file)

The detector needs the morning's **blessed levels** in structured form, each
naming the option to trade if it tags. A plan is valid for one day, so it's a
dated, hand-editable flat file:

`~/.trading/scalp/{date}-{symbol}.yaml`

```yaml
date: 2026-06-12
symbol: QQQ
regime: fragile-pin          # pin | fragile-pin | breakout-trend  (GEX sign)
lean: both                   # long-only | short-only | both | no-trade
contracts: 1                 # quantity per setup
default_stop_pct: 0.20       # child stop-loss = entry * (1 - pct)
target_pct: 0.20             # child take-profit = entry * (1 + pct)
zero_gamma: 721.00           # the gamma flip — tripwire, alerts on a cross (no trade)
levels:                      # the gamma walls + the option to buy if it triggers
  # +GEX → fade: put wall (support) → CALL, call wall (resistance) → PUT
  - {price: 719.40, side: support,    stop: 718.90, mode: fade, contract: "QQQ260612C00720000"}
  - {price: 723.10, side: resistance, stop: 723.70, mode: fade, contract: "QQQ260612P00723000"}
notes: "Fragile pin: fade the walls to the zero-gamma flip; a break of it = trend, stop fading"
```

- `levels` are *underlying* prices (ideally the GEX **walls** from
  `get_gamma_profile`) that drive the detector. Each `mode` picks the trigger
  geometry — `fade` (touch-and-reject) or `break` (cross-and-follow-through) — and
  the `contract` is the *option* to buy when it triggers. The call/put mapping is
  mode-dependent: in `fade` a support → call and a resistance → put; in `break`
  this **inverts** (a resistance breakout → call, a support breakdown → put). You
  pick the strike in `/scalp prep`. `level.stop` is **alert-text only** — the
  bracket's stop/target are a percent of the *option* premium.
- `zero_gamma` is the **gamma-flip tripwire** (one price, not a level). The
  detector watches the underlying cross it in *either* direction and fires a
  *non-trading* "the regime may be inverting — re-run `/scalp prep`" alert; it
  proposes no trade. It is the cheap mitigation for the top residual risk — a
  stale regime label (yesterday's OI) feeding each level's `mode`, so the bot
  fades a level that's actually breaking. The detector **never recomputes GEX**
  (the stream has no OI/greeks); the flip stays the static prep-time number, so a
  cross means *reassess*, not an automatic fade↔break switch. Omit it (or set
  null) to disable the tripwire.
- The daemon loads today's file on launch and **hot-reloads on change** (re-run
  `/scalp prep` and edited levels/lean are picked up). **Caveat:** the Tradier
  subscribe list is fixed at startup, so adding a *new* contract mid-session needs
  a restart.
- **Missing file = graceful degrade:** no plan → the detector is silent (no
  prompts, no paper trades). A level with no `contract` → alert-only.
- `/scalp prep` **writes this file** — it reads the regime + gamma walls from
  `get_gamma_profile`, sets each level's `mode` from the GEX sign, resolves a
  liquid 0-1DTE option per wall off the chain (mode-correct call/put), and emits
  the YAML; the file stays hand-editable to nudge an edge before the open.

This is the seam: **skill draws the map → `~/.trading/scalp/*.yaml` → daemon
watches the map and paper-trades it.**

## Runtime & lifecycle

**Not a daemon — a session-scoped foreground app.** Start it from a terminal
(`uv run --package trading-scalper trading-scalper`); it streams the tape, prompts
+ paper-trades through the session, and you Ctrl-C at the close. **POSIX-first
(Linux + macOS).**

- **Single asyncio loop.** One feed connection, one paper broker, one persister
  task (`asyncio.gather(feed.run(), persister.run())`). The persister flushes a
  final summary on shutdown.
- **Feed resilience.** WS auto-reconnect with exponential backoff + re-subscribe
  on drop.
- **Clock.** Session windows are ET-anchored via `zoneinfo`, independent of the
  machine's local timezone.
- **Offline demo.** `--demo-setup CONTRACT[:QTY[:PRICE]]` injects one setup,
  fills the bracket, writes a summary, and exits — no network, for smoke-testing
  the loop.

## Monorepo placement

Package `packages/trading-scalper/`, depends on `trading-clients[streaming]` +
`pyyaml`. The one streaming transport (`tradier_stream_client.py`) and the
provider-neutral `market_stream.py` value types live in `trading-clients`.

```
trading-clients (httpx[http2]; + websockets via [streaming] extra)
  ├── trading-mcp        (+ fastmcp + yfinance)
  ├── trading-alerts     (+ boto3 + pynacl)
  └── trading-scalper    (+ pyyaml)
```

## Versioning & the go-live scorecard

Going live is **earned per verdict mode**, on the numbers — not on a feeling that
"the bot looks ready." Two pieces make that objective.

**Version cohorts (`version.py`).** The detector carries a `major.minor.patch`
version. A **minor** bump means the change alters what/when/how it trades (arming
rules, verdict logic, calibration constants, gates, bracket placement); a **patch**
bump is observer-only (telemetry, logging, persistence). `SignalLog` stamps the
version on every fire row, so each session's logs self-describe which bot produced
them. The **cohort** is `major.minor`: grading pools only trades from the same
behavior cohort, because a change to the trading logic makes earlier trades evidence
about a bot that no longer exists. Bump in the same commit as the behavior change so
the stamp can't drift from the code. Sessions that predate versioning (before
`0.3.1`, shipped 2026-07-10) are mapped to a cohort by date in `scorecard._RETRO_COHORTS`.

**The scorecard (`scorecard.py`, `trading-scalper-scorecard`).** Reconstructs closed
trades by joining the fills log to `{date}-signals.jsonl` on `bracket_id` (a closed
trade = a bracket with a SELL exit; P&L = the exit's `realized_delta`), buckets them
by `(cohort, mode)`, and reports n, sessions, win rate, expectancy, expectancy's
one-sided 95% lower bound, profit factor, max drawdown, and **session concentration**
(the best single session's share of gross wins — the guard against a "one good day
carries the mode" edge). A pooled all-history line shows as a floor ("has this ever
worked"), never as the promotion basis. `--chart` writes a per-mode cumulative-P&L
curve with dashed cohort-boundary markers (a slope kink at a ship is the improvement
verdict — readable where a daily win-rate bar is just noise).

**The go-live gate** is evaluated on the **current cohort only**: `n ≥ 50` across
`≥ 10` sessions, profit factor `≥ 1.5`, expectancy lower bound `> 0`, concentration
`< 40%`. When a mode passes, the promotion is a git tag on that commit
(`scalper-vX.Y.Z`); the future live runner deploys from the tag while paper keeps
running the workspace head, and the version stamp keeps the two track records
attributable. Nothing has passed yet (as of `0.3`, `break`'s edge is one 0.2-cohort
session, `fade` is net-negative, `retest`/`reversal` are single-digit n).

**Caching.** Past sessions are immutable, so the scorecard caches each pre-*today*
session's extracted trades in `~/.trading/scalp/paper/scorecard-cache.json` (keyed by
date; today's still-appending session is always re-parsed). The cache stores the raw
version stamp, not the resolved cohort — so re-tuning the retro map or the gate never
invalidates it. It rides the scalp prefix in `env_sync` for free (whole-directory
sweep) and its dateless name keeps the retention archiver from ever gzipping it.

## Roadmap (deferred)

- **Tastytrade greeks feed** — add a DXLink streaming client for live
  delta/gamma/theta/vega + IV on the option (the one real data upgrade over
  Tradier). Slots in as a new neutral value type alongside `Quote`/`Trade`/`TimeSale`.
- **Phone-push notifier** — reuse the `trading-alerts` Discord bot to land prompts
  on your phone. v1 is desk-only console + bell.
- **Autonomous entry (live)** — only after a verdict mode passes the go-live gate
  above. This re-introduces a live broker that *opens* (a different shape from
  the old exit-only one) and a real risk-budget; the Webull gRPC order-push then
  becomes useful (the daemon sees its own fills). Out of scope until the scorecard
  earns it. See memory `project-scalper-pivot` / `project-scalper-grpc-events`.

---

*v1. Paper-only entry-detector. Pivoted from the assist-only stop-enforcer
2026-06-12 once Webull's native option bracket made `AutoStop` redundant. Safety
property: no real capital is ever at risk.*
