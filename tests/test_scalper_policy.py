"""GatePolicy — the default-deny live-execution gate.

Pins the three rejection axes (instrument root, verdict mode, running version) and
the roll-proof symbol resolution. The gate is the only path a proposal takes to real
money, so these are the tests that keep an un-promoted setup out of a live account.
"""

from trading_scalper.policy import DENY_ALL, GateDecision, GatePolicy
from trading_scalper.version import __version__

V = __version__


def _policy(*pairs: tuple[str, str], version: str = V) -> GatePolicy:
    return GatePolicy(version=version, approved=frozenset(pairs))


def test_approved_pair_at_matching_version_passes() -> None:
    decision = _policy(("/MES", "fade")).evaluate("/MES", "fade", V)
    assert isinstance(decision, GateDecision)
    assert decision.approved
    assert "live-approved" in decision.reason


def test_unapproved_root_is_denied() -> None:
    # /MES fade approved does not authorize /MNQ — each instrument earns live alone
    decision = _policy(("/MES", "fade")).evaluate("/MNQ", "fade", V)
    assert not decision.approved
    assert "allow-list" in decision.reason


def test_unapproved_mode_on_an_approved_root_is_denied() -> None:
    # /MES fade approved does not authorize /MES break — each mode is its own cohort
    decision = _policy(("/MES", "fade")).evaluate("/MES", "break", V)
    assert not decision.approved


def test_version_drift_voids_an_otherwise_approved_pair() -> None:
    # the pair IS on the list, but the running code is not the version it was proven at
    decision = _policy(("/MES", "fade"), version="9.9.9").evaluate("/MES", "fade", V)
    assert not decision.approved
    assert "drift" in decision.reason


def test_deny_all_rejects_everything() -> None:
    assert not DENY_ALL.evaluate("/MES", "fade", V).approved
    assert not DENY_ALL.evaluate("/MNQ", "break", V).approved


def test_evaluate_symbol_is_roll_proof() -> None:
    # a dated front-month contract approves under its root's allow-list entry, so a
    # quarterly roll (a new streamer symbol, same instrument) never de-authorizes it
    decision = _policy(("/MES", "retest")).evaluate_symbol("/MESU26:XCME", "retest", V)
    assert decision.approved


def test_evaluate_symbol_unknown_falls_back_to_raw_and_is_denied() -> None:
    # a pre-futures options symbol resolves to itself (not /MES) and stays out of live
    decision = _policy(("/MES", "fade")).evaluate_symbol("QQQ260101C00500000", "fade", V)
    assert not decision.approved
