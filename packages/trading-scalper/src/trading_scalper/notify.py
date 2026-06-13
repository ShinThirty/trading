"""Notifier — v1 is a console line + a terminal bell.

You're at the screen during a session, so the alert just needs to say *look now*:
a timestamped line, optionally prefixed with the BEL character (``\\a``) so the
terminal dings. Desk-only and portable — no platform-specific notification API
(phone-push via the trading-alerts Discord bot is a deferred upgrade).

``Notifier.notify`` is the single injected callback both ``SetupDetector`` and
``DisciplineEngine`` emit through.
"""

from collections.abc import Callable
from datetime import datetime


def _default_clock() -> str:
    return datetime.now().strftime("%H:%M:%S")


class Notifier:
    def __init__(
        self,
        *,
        bell: bool = True,
        write: Callable[[str], None] | None = None,
        clock: Callable[[], str] = _default_clock,
    ) -> None:
        self._bell = bell
        self._write = write or (lambda line: print(line, flush=True))
        self._clock = clock

    def notify(self, message: str) -> None:
        line = f"[{self._clock()}] {message}"
        if self._bell:
            line = "\a" + line
        self._write(line)
