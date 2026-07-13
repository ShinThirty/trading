"""Composition root: wire the subsystems into one runnable paper session.

The daemon detects a setup off the live futures tape, **prompts** the human, and on
every prompt **auto-executes the same bracket** in an in-memory ``PaperBroker`` (a
direction-aware entry + OCO stop-loss / take-profit at absolute prices),
**persisting** fills + a P&L summary so the detector's track record is reviewable.

Paper-only by construction — there is no live-order path. The safety story is
simply that no real capital is ever at risk, so the daemon opening positions
(which the old assist-only guard forbade) is now its whole job.

    feed (DXLink WS) ──futures tape──▶ SetupDetector ──▶ notify(human)
                     │                                 ├─▶ propose ─▶ PaperBroker.place_bracket
                     │                                 └─▶ record  ─▶ SignalLog (B4 telemetry)
                     └──────tape──────▶ PaperBroker (fills entry + OCO children)
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
from trading_clients.dxlink_stream_client import DxLinkStreamClient
from trading_clients.tastytrade_client import TastyTradeClient

from trading_scalper.basis import BasisRecorder, default_basis_path
from trading_scalper.contract import ContractError, ResolvedContract, resolve_contract
from trading_scalper.detector import SetupDetector, watch_setups
from trading_scalper.domain import OrderId, Side, TradeProposal
from trading_scalper.feed import DxLinkFeed, drive_paper_fills
from trading_scalper.instruments import Geometry, profile_for
from trading_scalper.notify import Notifier
from trading_scalper.paper import PaperBroker, round_to_tick
from trading_scalper.persist import (
    PaperPersister,
    SignalLog,
    default_fills_path,
    default_signals_path,
    default_summary_path,
)
from trading_scalper.plan import PlanStore, SessionPlan, default_plan_path
from trading_scalper.policy import DENY_ALL, GatePolicy
from trading_scalper.ports import MarketDataFeed
from trading_scalper.shadow import ShadowRecorder, default_shadow_path, default_tape_path
from trading_scalper.version import __version__


@dataclass(slots=True)
class ScalpSession:
    """The wired-up bundle: feed, paper broker, detector, notifier, persister, signal log."""

    feed: MarketDataFeed
    broker: PaperBroker
    detector: SetupDetector
    notifier: Notifier
    persister: PaperPersister
    signals: SignalLog
    shadow: ShadowRecorder
    basis: BasisRecorder | None  # cash-index↔future carry-basis shadow; None when no reference


def make_executor(
    broker: PaperBroker, notifier: Notifier
) -> Callable[[TradeProposal], OrderId | None]:
    """Build the proposal → paper-bracket executor; a missing price is a soft warn.

    Returns the bracket's ``entry_id`` so the detector can stamp it on the fire's
    ``FireRecord`` (the join key to the bracket's fills); ``None`` when no fill
    happened (no price on the tape yet)."""

    def execute(p: TradeProposal) -> OrderId | None:
        try:
            entry_id, _stop_id, _target_id = broker.place_bracket(
                p.symbol,
                p.direction,
                p.quantity,
                stop_price=p.stop_price,
                target_price=p.target_price,
            )
            return entry_id
        except ValueError:
            notifier.notify(f"(paper) skipped {p.symbol}: no price on the tape yet")
            return None

    return execute


def make_gated_executor(
    paper_exec: Callable[[TradeProposal], OrderId | None],
    notifier: Notifier,
    *,
    policy: GatePolicy = DENY_ALL,
    live_exec: Callable[[TradeProposal], OrderId | None] | None = None,
) -> Callable[[TradeProposal], OrderId | None]:
    """Wrap the paper executor with the live gate — a **fan-out**, never an either/or.

    Every proposal fills in paper, unconditionally: the track record never pauses, even
    for a ``(root, mode)`` that has gone live, so paper-vs-live slippage stays
    comparable and the scorecard keeps grading the same continuous series. A proposal
    the ``policy`` approves for its ``(root, mode)`` at the running ``__version__``
    **additionally** routes to ``live_exec`` when one is wired — real money and paper
    from the same fire. Until a live broker exists (``live_exec is None``) an approved
    fire only annotates ("would route live"), so the gate can be dry-run on live paper
    tape as a shadow before a cent is at risk ([[feedback_shadow_then_live]]).

    Returns the **paper** bracket id — the join key the scorecard already grades on — so
    the paper track record is unaffected by the gate. A live fill keeps its own id in its
    own (future) ledger; segregating the two fill streams is part of the live-broker
    increment, not this seam.
    """

    def execute(p: TradeProposal) -> OrderId | None:
        entry_id = paper_exec(p)  # paper always — the continuous, gradeable track record
        decision = policy.evaluate_symbol(p.symbol, p.mode, __version__)
        if decision.approved:
            if live_exec is not None:
                live_exec(p)  # real fill, in parallel; paper id above stays the join key
            else:
                notifier.notify(f"(gate) LIVE-eligible: {p.symbol} [{p.mode}] — {decision.reason}")
        return entry_id

    return execute


def collect_symbols(plan: SessionPlan | None, underlyings: list[str]) -> list[str]:
    """The subscribe list: the watched/traded symbols, plus the plan's symbol if distinct.

    For futures the watched tape and the traded instrument are one symbol, so this
    just dedupes and guarantees the plan's symbol is subscribed even if ``--symbols``
    didn't name it."""
    out = list(underlyings)
    if plan is not None and plan.symbol and plan.symbol not in out:
        out.append(plan.symbol)
    return out


def build_session(
    feed: MarketDataFeed,
    broker: PaperBroker,
    plan_source: Callable[[], SessionPlan | None],
    *,
    notifier: Notifier | None = None,
    geometry: Geometry = Geometry(),
    policy: GatePolicy = DENY_ALL,
    live_exec: Callable[[TradeProposal], OrderId | None] | None = None,
    date: str,
    underlyings: list[str] | None = None,
    fills_path: Path | None = None,
    summary_path: Path | None = None,
    signals_path: Path | None = None,
    tape_path: Path | None = None,
    shadow_path: Path | None = None,
    reference_symbol: str | None = None,
    basis_path: Path | None = None,
    interval: float = 30.0,
) -> ScalpSession:
    """Wire detector → proposal → paper bracket → persisted ledger onto the tape.

    Stop/target/qty are read from the plan at fire time (in the detector), so this
    composition is plan-driven; the CLI ``--stop-points``/``--target-points``/``--contracts``
    only feed the offline ``--demo-setup`` path. The detector's ``record`` sink lands
    the B4 telemetry in a per-fire ``SignalLog`` alongside the fills/summary.

    ``geometry`` is the traded root's price-distance band-set — our calibration, from
    ``instruments.py`` — so the detector's bands match the symbol's price magnitude. Its
    counterparts ``point_value``/``tick`` are *not* ours: they ride in on the resolved
    contract and are threaded into the ``PaperBroker`` by ``_run``. The default is the
    S&P set, for tests/demo that don't wire a specific instrument.

    ``policy`` + ``live_exec`` are the live gate (``policy.py``): the paper broker fills
    every fire, and an approved ``(root, mode)`` at this ``__version__`` *additionally*
    routes to ``live_exec``. Defaults (``DENY_ALL`` + ``None``) keep the session paper-only
    and the gate transparent; the live-broker increment wires a real executor + a manifest
    policy here.

    A ``ShadowRecorder`` is also wired onto the tape — pure telemetry, gating nothing
    (see ``shadow.py``). It tracks the ``underlyings`` only. When ``reference_symbol`` is
    given (e.g. ``SPX``), a ``BasisRecorder`` records the live future↔reference carry
    basis — also shadow, gating nothing (see ``basis.py``); the future leg is the first
    ``underlyings`` symbol.
    """
    notifier = notifier or Notifier()
    signals = SignalLog(signals_path or default_signals_path(date))
    detector = SetupDetector(
        plan_source,
        notifier.notify,
        # the live gate wraps the paper executor: paper fills every fire; an approved
        # (root, mode) at this __version__ *additionally* routes to live_exec. Default
        # DENY_ALL + live_exec=None → paper-only, the gate transparent (see policy.py).
        make_gated_executor(
            make_executor(broker, notifier), notifier, policy=policy, live_exec=live_exec
        ),
        geometry=geometry,  # the traded instrument's price-distance bands (see instruments.py)
        record=signals.record,
    )
    persister = PaperPersister(
        broker,
        date=date,
        fills_path=fills_path or default_fills_path(date),
        summary_path=summary_path or default_summary_path(date),
        interval=interval,
    )
    shadow = ShadowRecorder(
        underlyings or [],
        tape_path=tape_path or default_tape_path(date),
        shadow_path=shadow_path or default_shadow_path(date),
        interval=interval,
    )
    basis: BasisRecorder | None = None
    if reference_symbol and underlyings:
        basis = BasisRecorder(
            underlyings[0],
            reference_symbol,
            basis_path=basis_path or default_basis_path(date),
            interval=interval,
        )
    drive_paper_fills(feed, broker)  # tape prints fill the engine
    watch_setups(feed, detector)  # tape → detector
    shadow.attach(feed)  # tape → shadow volume telemetry (reads nothing back)
    if basis is not None:
        basis.attach(feed)  # future + reference quotes → basis telemetry (reads nothing back)
    return ScalpSession(
        feed=feed,
        broker=broker,
        detector=detector,
        notifier=notifier,
        persister=persister,
        signals=signals,
        shadow=shadow,
        basis=basis,
    )


def _plan_key(symbol: str) -> str:
    """Filesystem-safe plan-file key from a futures symbol.

    ``/MESU25:XCME`` → ``MESU25``; ``/MES`` → ``MES``. Both the daemon and
    ``/scalp prep`` must derive the plan path the same way.
    """
    return symbol.lstrip("/").split(":")[0]


# --demo-setup runs with no network, so it has no exchange to ask for economics. These are
# stand-ins — realistic /MES numbers so the printed P&L reads sensibly — and they are
# deliberately *not* a lookup table: a real session gets its $/pt and tick from the venue
# (contract.py), and nothing here can leak into one.
_DEMO_POINT_VALUE = 5.0
_DEMO_TICK = 0.25


def _parse_demo_setup(spec: str) -> tuple[str, int, float]:
    """Parse ``SYMBOL[:QTY[:PRICE]]`` for the offline --demo-setup affordance.

    Use the plain root (e.g. ``/MES``) here — the ``:XCME`` streamer suffix collides
    with the ``:`` field delimiter, and the demo symbol is just a paper-broker key.
    """
    parts = spec.split(":")
    if not parts[0]:
        raise SystemExit(f"--demo-setup needs a symbol, got {spec!r}")
    try:
        qty = int(parts[1]) if len(parts) > 1 and parts[1] else 1
        price = float(parts[2]) if len(parts) > 2 and parts[2] else 6300.00
    except ValueError as exc:
        raise SystemExit(f"--demo-setup expects SYMBOL[:QTY[:PRICE]], got {spec!r}") from exc
    return parts[0], qty, price


def _print_banner(
    plan: SessionPlan | None,
    path: object,
    symbols: list[str],
    date: str,
    contract: ResolvedContract,
) -> None:
    print("=" * 64)
    print("trading-scalper — PAPER entry-detector (no live orders)")
    print(
        f"date: {date}   symbol: {' '.join(symbols)}   "
        f"(${contract.point_value:g}/pt, {contract.tick:g} tick — exchange-verified)"
    )
    if plan is not None:
        print(f"plan: {path}")
        print(
            f"  regime={plan.regime}  lean={plan.lean}  qty={plan.contracts}  "
            f"bracket={plan.default_stop_points:g}pt stop / {plan.default_target_points:g}pt target"
        )
        for lvl in plan.levels:
            tag = f"→ {lvl.direction} {plan.symbol}" if lvl.direction else "(alert-only, no trade)"
            stop_txt = f"  stop {lvl.stop:g}" if lvl.stop is not None else ""
            print(f"  {lvl.side:<10} {lvl.price:g} [{lvl.mode}]  {tag}{stop_txt}")
        if plan.zero_gamma is not None:
            print(f"  zero-gamma flip {plan.zero_gamma:g}  (tripwire — alerts on cross, no trade)")
        if plan.notes:
            print(f"  notes: {plan.notes}")
    else:
        print(f"plan: NONE ({path}) — detector silent until /scalp prep writes today's plan")
    print("=" * 64)


def _run_demo(broker: PaperBroker, session: ScalpSession, notifier: Notifier, args) -> None:
    """Offline (no-network) demo: inject a long setup, fill the bracket, persist a summary."""
    symbol, qty, price = _parse_demo_setup(args.demo_setup)
    print("=" * 64)
    print("trading-scalper — DEMO (offline, no network)")
    print(f"  economics: ${_DEMO_POINT_VALUE:g}/pt, {_DEMO_TICK:g} tick — DEMO, not the exchange's")
    broker.trade(symbol, price)  # seed a tape price
    stop_price = round_to_tick(price - args.stop_points, _DEMO_TICK)
    target_price = round_to_tick(price + args.target_points, _DEMO_TICK)
    notifier.notify(
        f"(demo) {symbol} long {qty} — stop {args.stop_points:g}pt ({stop_price:g}) / "
        f"target {args.target_points:g}pt ({target_price:g})"
    )
    make_executor(broker, notifier)(
        TradeProposal(symbol, Side.BUY, qty, stop_price, target_price, reason="(demo setup)")
    )
    print(
        f"  entry filled @ {price:g}; bracket resting "
        f"(stop {stop_price:g} / target {target_price:g})"
    )
    broker.trade(symbol, target_price + _DEMO_TICK)  # cross the target → win; OCO cancels the stop
    print(f"  target hit; position flat; realized ${broker.realized_pnl():.0f}")
    session.persister.write_summary()
    print(f"  fills   → {session.persister.fills_path}")
    print(f"  summary → {session.persister.summary_path}")
    print("=" * 64)


async def _run_basis(tasty: TastyTradeClient, future_symbol: str, reference_symbol: str) -> None:
    """`--basis`: print the current future↔reference carry basis and exit (prep helper).

    `/scalp` prep adds this basis to each cash-index gamma wall to get its futures
    level. Reads only — never writes the shadow artifact. Meaningful during RTH only
    (the cash index must be live); off-hours the future has drifted against a stale
    cash index.
    """
    feed = DxLinkFeed(DxLinkStreamClient(tasty.get_quote_token))
    rec = BasisRecorder(future_symbol, reference_symbol, basis_path=Path("/dev/null"))
    rec.attach(feed)
    await feed.subscribe([future_symbol, reference_symbol])
    task = asyncio.create_task(feed.run())
    try:
        for _ in range(40):  # poll up to ~20 s for both legs to print
            await asyncio.sleep(0.5)
            if rec.snapshot_row() is not None:
                break
    finally:
        task.cancel()
    row = rec.snapshot_row()
    if row is None:
        print(f"no basis yet — {future_symbol}/{reference_symbol} haven't both printed (try RTH)")
        return
    print(
        f"{future_symbol} {row['future_price']:g}  −  {reference_symbol} "
        f"{row['reference_level']:g}  =  basis {row['basis']:+.2f}"
    )
    print(
        f"→ add basis to each {reference_symbol} wall for its {future_symbol} level "
        f"(RTH only — {reference_symbol} must be live)"
    )


async def _demo_token() -> tuple[str, str]:
    """A throwaway token provider for the offline demo — never actually invoked."""
    return ("demo", "wss://demo")


async def _run(args: argparse.Namespace) -> None:
    cfg = load_config()
    notifier = Notifier(bell=not args.no_bell)

    if args.demo_setup:
        # offline self-test: no feed, no network, no exchange to ask — so it runs on the
        # labeled _DEMO_* economics above. Exercises the bracket plumbing, not a session.
        primary = args.symbols[0]
        plan_path = default_plan_path(_plan_key(primary), args.date)
        plan_store = PlanStore(plan_path, on_error=notifier.notify)
        broker = PaperBroker(multiplier=_DEMO_POINT_VALUE, tick=_DEMO_TICK)
        session = build_session(
            DxLinkFeed(DxLinkStreamClient(_demo_token)),  # throwaway: satisfies build_session
            broker,
            plan_store.current,
            notifier=notifier,
            geometry=profile_for(primary).geometry,
            date=args.date,
            underlyings=args.symbols,
        )
        _run_demo(broker, session, notifier, args)
        return

    if cfg.tastytrade is None:
        raise SystemExit(
            "No [tastytrade] section in ~/.tradingrc — the futures feed streams via "
            "Tastytrade DXLink (needs OAuth client_secret + refresh_token)."
        )
    tasty = TastyTradeClient(cfg.tastytrade)

    # Ask the exchange which contract is live, and what it's worth, before anything keys off
    # the symbol: a bare root (/MES) becomes its active-month contract, a dated symbol gets
    # checked against the live set, and $/pt + tick come back with it. No fallback — an
    # unanswerable lookup ends the session (contract.py).
    try:
        contract = await resolve_contract(tasty, args.symbols[0])
    except ContractError as exc:
        await tasty.close()
        raise SystemExit(f"contract: {exc}") from exc
    for warning in contract.warnings:
        notifier.notify(f"contract: {warning}")
    primary = contract.symbol
    symbols_arg = [primary, *args.symbols[1:]]

    if args.basis:
        try:
            await _run_basis(tasty, primary, args.reference or contract.reference)
        finally:
            await tasty.close()
        return

    plan_path = default_plan_path(_plan_key(primary), args.date)
    plan_store = PlanStore(plan_path, on_error=notifier.notify)  # bad hot-edit -> warn, keep last
    plan = plan_store.current()
    broker = PaperBroker(multiplier=contract.point_value, tick=contract.tick)
    stream = DxLinkStreamClient(tasty.get_quote_token)
    feed = DxLinkFeed(stream)
    # default: the traded instrument's cash index (SPX for /MES, NDX for /MNQ); "" disables
    reference = contract.reference if args.reference is None else (args.reference or None)
    session = build_session(
        feed,
        broker,
        plan_store.current,
        notifier=notifier,
        geometry=contract.geometry,
        date=args.date,
        underlyings=symbols_arg,
        reference_symbol=reference,
    )

    _print_banner(plan, plan_path, symbols_arg, args.date, contract)
    symbols = collect_symbols(plan, symbols_arg)
    if reference and reference not in symbols:
        symbols.append(reference)  # stream the cash-index reference for the carry-basis shadow
    print(f"streaming: {' '.join(symbols)}")
    await feed.subscribe(symbols)
    tasks = [feed.run(), session.persister.run(), session.shadow.run()]
    if session.basis is not None:
        tasks.append(session.basis.run())
    try:
        await asyncio.gather(*tasks)
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
    except httpx.HTTPStatusError as exc:
        raise SystemExit(_dxlink_http_msg(exc)) from exc
    finally:
        await stream.close()
        await tasty.close()
        session.persister.write_summary()
        session.shadow.flush_tape()  # mirror the persister: don't lose the tail on a hard exit
        session.shadow.write_snapshots()
        if session.basis is not None:
            session.basis.write_snapshot()
        print(
            f"\nscalp session closed — {session.signals.n_fires} fires logged → "
            f"{session.signals.path}"
        )
        print(f"shadow telemetry → {session.shadow.tape_path} + {session.shadow.shadow_path}")
        if session.basis is not None:
            print(f"basis telemetry  → {session.basis.basis_path}")


def _dxlink_http_msg(exc: httpx.HTTPStatusError) -> str:
    return (
        f"Tastytrade quote-token fetch failed: HTTP {exc.response.status_code}. "
        "401/403 means the OAuth refresh token is invalid/expired, or the account "
        "isn't a funded customer (DXLink futures streaming needs a real tastytrade customer)."
    )


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Paper entry-detector for intraday index-futures (/MES) scalps."
    )
    ap.add_argument(
        "--symbols",
        nargs="+",
        default=["/MES"],
        help="futures tape symbols (first drives the plan + instrument economics)",
    )
    ap.add_argument(
        "--reference",
        default=None,
        help="cash-index reference for the carry-basis shadow "
        "(default: the instrument's — SPX for /MES, NDX for /MNQ; empty string to disable)",
    )
    ap.add_argument("--date", default=date.today().isoformat(), help="plan date YYYY-MM-DD")
    ap.add_argument(
        "--stop-points", type=float, default=6.0, help="(--demo-setup only) stop distance in points"
    )
    ap.add_argument(
        "--target-points",
        type=float,
        default=8.0,
        help="(--demo-setup only) target distance in points",
    )
    ap.add_argument(
        "--contracts",
        type=int,
        default=1,
        help="(--demo-setup only) quantity; live qty is plan-set",
    )
    ap.add_argument("--no-bell", action="store_true", help="silence the terminal bell")
    ap.add_argument(
        "--basis",
        action="store_true",
        help="print the current front-month↔cash-index carry basis and exit (prep helper)",
    )
    ap.add_argument(
        "--demo-setup",
        metavar="SYMBOL[:QTY[:PRICE]]",
        help="offline: inject a setup, fill the bracket, write a summary, exit",
    )
    args = ap.parse_args()
    try:
        asyncio.run(_run(args))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
