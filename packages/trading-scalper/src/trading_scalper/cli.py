"""Composition root: wire the subsystems into one runnable paper session.

The daemon detects a setup off the live underlying tape, **prompts** the human,
and on every prompt **auto-executes the same option bracket** in an in-memory
``PaperBroker`` (entry + OCO stop-loss / take-profit), **persisting** fills + a
P&L summary so the detector's track record is reviewable.

Paper-only by construction — there is no live-order path. The safety story is
simply that no real capital is ever at risk, so the daemon opening positions
(which the old assist-only guard forbade) is now its whole job.

    feed (Tradier WS) ──underlying tape──▶ SetupDetector ──▶ notify(human)
                       │                                  └─▶ propose ─▶ PaperBroker.place_bracket
                       └──option tape──▶ PaperBroker (fills entry + OCO children)
                                              │ order events
                                              ▼
                                         PaperPersister (fills JSONL + summary JSON)
"""

import argparse
import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import httpx
from trading_clients.config import load_config
from trading_clients.tradier_stream_client import TradierStreamClient

from trading_scalper.detector import SetupDetector, watch_setups
from trading_scalper.domain import TradeProposal
from trading_scalper.feed import TradierFeed, drive_paper_fills
from trading_scalper.notify import Notifier
from trading_scalper.paper import PaperBroker
from trading_scalper.persist import PaperPersister, default_fills_path, default_summary_path
from trading_scalper.plan import PlanStore, SessionPlan, default_plan_path
from trading_scalper.ports import MarketDataFeed


@dataclass(slots=True)
class ScalpSession:
    """The wired-up bundle: feed, paper broker, detector, notifier, persister."""

    feed: MarketDataFeed
    broker: PaperBroker
    detector: SetupDetector
    notifier: Notifier
    persister: PaperPersister


def make_executor(broker: PaperBroker, notifier: Notifier) -> Callable[[TradeProposal], None]:
    """Build the proposal → paper-bracket executor; a missing price is a soft warn."""

    def execute(p: TradeProposal) -> None:
        try:
            broker.place_bracket(
                p.contract, p.quantity, stop_pct=p.stop_pct, target_pct=p.target_pct
            )
        except ValueError:
            notifier.notify(f"(paper) skipped {p.contract}: no price on the tape yet")

    return execute


def collect_symbols(plan: SessionPlan | None, underlyings: list[str]) -> list[str]:
    """Underlyings + every level's option contract (deduped, order-preserved)."""
    out = list(underlyings)
    if plan is not None:
        for lvl in plan.levels:
            if lvl.contract and lvl.contract not in out:
                out.append(lvl.contract)
    return out


def build_session(
    feed: MarketDataFeed,
    broker: PaperBroker,
    plan_source: Callable[[], SessionPlan | None],
    *,
    notifier: Notifier | None = None,
    date: str,
    fills_path: Path | None = None,
    summary_path: Path | None = None,
    interval: float = 30.0,
) -> ScalpSession:
    """Wire detector → proposal → paper bracket → persisted ledger onto the tape.

    Stop/target/qty are read from the plan at fire time (in the detector), so this
    composition is plan-driven; the CLI ``--stop-pct``/``--target-pct``/``--contracts``
    only feed the offline ``--demo-setup`` path.
    """
    notifier = notifier or Notifier()
    detector = SetupDetector(plan_source, notifier.notify, make_executor(broker, notifier))
    persister = PaperPersister(
        broker,
        date=date,
        fills_path=fills_path or default_fills_path(date),
        summary_path=summary_path or default_summary_path(date),
        interval=interval,
    )
    drive_paper_fills(feed, broker)  # option + underlying prints fill the engine
    watch_setups(feed, detector)  # underlying tape → detector
    return ScalpSession(
        feed=feed, broker=broker, detector=detector, notifier=notifier, persister=persister
    )


def _parse_demo_setup(spec: str) -> tuple[str, int, float]:
    """Parse ``CONTRACT[:QTY[:PRICE]]`` for the offline --demo-setup affordance."""
    parts = spec.split(":")
    if not parts[0]:
        raise SystemExit(f"--demo-setup needs a contract, got {spec!r}")
    try:
        qty = int(parts[1]) if len(parts) > 1 and parts[1] else 1
        price = float(parts[2]) if len(parts) > 2 and parts[2] else 2.00
    except ValueError as exc:
        raise SystemExit(f"--demo-setup expects CONTRACT[:QTY[:PRICE]], got {spec!r}") from exc
    return parts[0], qty, price


def _print_banner(
    plan: SessionPlan | None, path: object, symbols: list[str], date: str, sandbox: bool
) -> None:
    print("=" * 64)
    print("trading-scalper — PAPER entry-detector (no live orders)")
    print(f"date: {date}   underlyings: {' '.join(symbols)}")
    if plan is not None:
        print(f"plan: {path}")
        print(
            f"  regime={plan.regime}  lean={plan.lean}  qty={plan.contracts}  "
            f"bracket={plan.default_stop_pct:.0%} stop / {plan.target_pct:.0%} target"
        )
        for lvl in plan.levels:
            tag = f"→ buy {lvl.contract}" if lvl.contract else "(alert-only, no contract)"
            print(f"  {lvl.side:<10} {lvl.price:g}  {tag}")
        if plan.notes:
            print(f"  notes: {plan.notes}")
    else:
        print(f"plan: NONE ({path}) — detector silent until /scalp prep writes today's plan")
    if sandbox:
        print("WARNING: [tradier] sandbox=true — streaming is PRODUCTION-ONLY; it will 401.")
    print("=" * 64)


def _run_demo(broker: PaperBroker, session: ScalpSession, notifier: Notifier, args) -> None:
    """Offline (no-network) demo: inject a setup, fill the bracket, persist a summary."""
    contract, qty, price = _parse_demo_setup(args.demo_setup)
    print("=" * 64)
    print("trading-scalper — DEMO (offline, no network)")
    broker.trade(contract, price)  # seed a tape price for the option
    notifier.notify(
        f"(demo) {contract} setup — buy {qty}, "
        f"stop {args.stop_pct:.0%} / target {args.target_pct:.0%}"
    )
    make_executor(broker, notifier)(
        TradeProposal(contract, qty, args.stop_pct, args.target_pct, reason="(demo setup)")
    )
    stop_px = round(price * (1 - args.stop_pct), 2)
    target_px = round(price * (1 + args.target_pct), 2)
    print(f"  entry filled @ {price:g}; bracket resting (stop {stop_px:g} / target {target_px:g})")
    broker.trade(contract, target_px + 0.01)  # cross the target → win; OCO cancels the stop
    print(f"  target hit; position flat; realized ${broker.realized_pnl():.0f}")
    session.persister.write_summary()
    print(f"  fills   → {session.persister.fills_path}")
    print(f"  summary → {session.persister.summary_path}")
    print("=" * 64)


async def _run(args: argparse.Namespace) -> None:
    cfg = load_config()
    if cfg.tradier is None:
        raise SystemExit(
            "No [tradier] section in ~/.tradingrc — streaming needs a production Tradier token."
        )

    primary = args.symbols[0]
    plan_path = default_plan_path(primary, args.date)
    plan_store = PlanStore(plan_path)
    plan = plan_store.current()

    notifier = Notifier(bell=not args.no_bell)
    broker = PaperBroker()
    stream = TradierStreamClient(cfg.tradier.api_token)
    feed = TradierFeed(stream)
    session = build_session(feed, broker, plan_store.current, notifier=notifier, date=args.date)

    if args.demo_setup:
        _run_demo(broker, session, notifier, args)
        await stream.close()
        return

    _print_banner(plan, plan_path, args.symbols, args.date, cfg.tradier.sandbox)
    symbols = collect_symbols(plan, args.symbols)
    print(f"streaming: {' '.join(symbols)}")
    await feed.subscribe(symbols)
    try:
        await asyncio.gather(feed.run(), session.persister.run())
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
    except httpx.HTTPStatusError as exc:
        raise SystemExit(_tradier_http_msg(exc)) from exc
    finally:
        await stream.close()
        session.persister.write_summary()
        print("\nscalp session closed.")


def _tradier_http_msg(exc: httpx.HTTPStatusError) -> str:
    return (
        f"Tradier session-create failed: HTTP {exc.response.status_code}. "
        "401/403 means the token isn't authorized for production streaming."
    )


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Paper entry-detector for intraday SPY/QQQ options scalps."
    )
    ap.add_argument(
        "--symbols", nargs="+", default=["QQQ"], help="underlying tape symbols (first drives plan)"
    )
    ap.add_argument("--date", default=date.today().isoformat(), help="plan date YYYY-MM-DD")
    ap.add_argument("--stop-pct", type=float, default=0.20, help="demo-setup stop %% of premium")
    ap.add_argument("--target-pct", type=float, default=0.20, help="demo-setup target %% premium")
    ap.add_argument("--contracts", type=int, default=1, help="demo-setup quantity")
    ap.add_argument("--no-bell", action="store_true", help="silence the terminal bell")
    ap.add_argument(
        "--demo-setup",
        metavar="CONTRACT[:QTY[:PRICE]]",
        help="offline: inject a setup, fill the bracket, write a summary, exit",
    )
    args = ap.parse_args()
    try:
        asyncio.run(_run(args))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
