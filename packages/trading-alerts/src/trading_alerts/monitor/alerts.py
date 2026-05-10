"""PagerDuty-inspired alert state machine.

State transitions:
    new → warning       = notify
    new → critical      = notify
    warning → critical  = escalate (immediate, ignores cooldown)
    same level          = suppress if within 30 min cooldown, re-notify if expired
    any → resolved      = silent (rearms for future breach)
    muted_until > now   = suppress (orthogonal to level, preserves original state)
"""

from dataclasses import dataclass

from trading_alerts.state import AlertRecord

COOLDOWN_SECONDS = 1800  # 30 minutes


@dataclass(frozen=True)
class AlertDecision:
    action: str  # notify, escalate, suppress, resolve, none
    level: str | None  # current alert level (warning/critical/None)

    @property
    def should_notify(self) -> bool:
        return self.action in ("notify", "escalate")


def decide(
    current_level: str | None,
    previous: AlertRecord | None,
    now: float,
) -> AlertDecision:
    """Decide what action to take based on current evaluation and previous state.

    Args:
        current_level: Result from thresholds.evaluate() — "warning", "critical", or None.
        previous: Previous alert record from DynamoDB, or None if first time.
        now: Current Unix timestamp.
    """
    # Muted — suppress regardless of level (mute is orthogonal to state)
    if previous and previous.muted_until and now < previous.muted_until:
        return AlertDecision(action="suppress", level=current_level)

    # No alert triggered — check if we need to resolve a previous alert
    if current_level is None:
        if previous and previous.level in ("warning", "critical"):
            return AlertDecision(action="resolve", level=None)
        return AlertDecision(action="none", level=None)

    # New alert (no previous state or previously resolved)
    if previous is None or previous.level == "resolved":
        return AlertDecision(action="notify", level=current_level)

    # Escalation: warning → critical (immediate, ignores cooldown)
    if previous.level == "warning" and current_level == "critical":
        return AlertDecision(action="escalate", level=current_level)

    # Same level or de-escalation: check cooldown
    if now < previous.cooldown_until:
        return AlertDecision(action="suppress", level=current_level)

    # Cooldown expired — re-notify
    return AlertDecision(action="notify", level=current_level)
