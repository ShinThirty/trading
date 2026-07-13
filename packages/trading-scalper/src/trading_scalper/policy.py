"""GatePolicy — the default-deny gate that decides which fires may touch real money.

The scalper is paper-only today; every proposal fills in the in-memory
``PaperBroker``. When a live ``BrokerExecution`` finally exists (see ``ports.py``),
we do **not** want the detector to hand it *every* setup — only the specific
``(instrument-root, verdict-mode)`` combinations a human has promoted after they
cleared the scorecard's go-live gate (``scorecard.py``), and only while the code
running is the exact version those combinations were proven at.

This module is that decision, and only the decision — a pure function over
``(root, mode, version)``, no I/O, no broker, no notifier. The composition root
(``cli.py`` :func:`make_gated_executor`) is what *acts* on it: it runs the paper
broker on **every** proposal (so the track record never pauses, even for a mode that
has gone live — keeping paper-vs-live slippage comparable) and, **additionally**,
the live broker only when :meth:`GatePolicy.evaluate` approves. Keeping the two apart
means the transport stays dumb and the whole enforcement is one small, unit-testable
place — you cannot route a trade to real money without passing through here.

Three rejection axes, all default-deny — a proposal is live-eligible only if it
clears **all** of them:

1. **Instrument** — ``root_of(symbol)`` must be on the allow-list. ``/MES`` approved
   never authorizes ``/MNQ``; each instrument earns live on its own record, so you
   never need both promoted before either can go live.
2. **Mode** — the verdict mode must be approved *for that root*. ``/MES fade`` approved
   never authorizes ``/MES break``; each mode is a separate scorecard cohort, promoted
   alone.
3. **Version** — the running detector ``__version__`` must equal the version the pair
   was approved at. A promotion is evidence about one exact behavior; bump the version
   (a fresh cohort, by construction resetting the sample) and the old approval is void
   until the new cohort re-clears the gate. This is the fail-safe that stops a
   mid-promotion code change from silently trading live on unproven logic.

The allow-list is populated from the git-tag manifest that pins a passing cohort
(the ``scalper-vX.Y.Z`` promotion) — that loader is **not built here**; :data:`DENY_ALL`
is the safe default the CLI wires until it exists, so production is paper-only *by
construction*, not by omission.
"""

from dataclasses import dataclass, field

from trading_scalper.instruments import root_of


@dataclass(frozen=True, slots=True)
class GateDecision:
    """The gate's verdict on one proposal: whether it may route to the live broker.

    ``approved`` is the only load-bearing bit; ``reason`` is human-readable audit text
    (which axis rejected it, or why it passed) for the notifier / logs.
    """

    approved: bool
    reason: str


@dataclass(frozen=True, slots=True)
class GatePolicy:
    """A default-deny allow-list of ``(root, mode)`` pairs approved at one ``version``.

    Deliberately tiny and immutable: a promotion decision is just a set of pairs plus
    the version they were proven at. Construct it from the git-tag manifest; the CLI's
    default is :data:`DENY_ALL` (an empty set), which rejects everything regardless of
    version — production stays paper-only until a real manifest is wired.
    """

    version: str
    approved: frozenset[tuple[str, str]] = field(default_factory=frozenset)

    def evaluate(self, root: str, mode: str, current_version: str) -> GateDecision:
        """Approve iff ``(root, mode)`` is on the list AND we're running its version.

        Membership is checked before version so the common denial (an un-promoted pair)
        reads cleanly as "not on the allow-list"; a pair that *is* promoted but is
        running drifted code is the more interesting catch, and says so.
        """
        if (root, mode) not in self.approved:
            return GateDecision(False, f"{root} {mode} not on the live allow-list")
        if current_version != self.version:
            return GateDecision(
                False,
                f"{root} {mode} approved at {self.version} but running {current_version}"
                " (version drift — re-clear the gate)",
            )
        return GateDecision(True, f"{root} {mode} live-approved at {self.version}")

    def evaluate_symbol(self, symbol: str, mode: str, current_version: str) -> GateDecision:
        """:meth:`evaluate` keyed by a (possibly dated) streamer symbol — resolves the root.

        ``/MESU26:XCME`` approves under an ``/MES`` allow-list entry, so a quarterly roll
        never de-authorizes a promoted instrument (roll-proof, the same cohort grain the
        scorecard uses via ``root_of``).
        """
        return self.evaluate(root_of(symbol), mode, current_version)


DENY_ALL = GatePolicy(version="", approved=frozenset())
"""The production default: an empty allow-list rejects every proposal on the instrument
axis. The scalper stays paper-only until a real promotion manifest replaces this."""
