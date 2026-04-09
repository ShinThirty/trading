"""Parse Webull positions into typed ShortOptionLeg objects."""

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class ShortOptionLeg:
    symbol: str  # underlying, e.g. "AAPL"
    strike: float
    expiration: str  # "YYYY-MM-DD"
    option_type: str  # "CALL" or "PUT"
    quantity: int  # negative for short
    strategy: str  # "COVERED_STOCK", "SINGLE", etc.
    account_id: str = ""  # Webull account ID
    account_label: str = ""  # e.g. "Roth IRA", "Individual Cash"

    @property
    def dedup_key(self) -> str:
        return (
            f"{self.account_id}:{self.symbol}-{self.strike:.2f}"
            f"-{self.expiration}-{self.option_type}"
        )

    @property
    def dte(self) -> int:
        exp = date.fromisoformat(self.expiration)
        return (exp - date.today()).days

    @property
    def direction(self) -> str:
        """Which direction triggers an alert: 'rising' for calls, 'falling' for puts."""
        return "rising" if self.option_type == "CALL" else "falling"


def extract_short_legs(
    positions: list[dict], account_id: str = "", account_label: str = ""
) -> list[ShortOptionLeg]:
    """Extract short option legs from Webull position data.

    Identifies:
    - Covered calls: COVERED_STOCK strategy with a short CALL leg
    - CSPs: SINGLE strategy with a short PUT leg
    - Future: spreads, straddles, etc.
    """
    legs: list[ShortOptionLeg] = []
    for pos in positions:
        option_legs = pos.get("legs", [])
        if not option_legs:
            continue

        symbol = pos.get("symbol", "")
        strategy = pos.get("option_strategy", "")
        qty = pos.get("quantity", "0")

        pos_qty = int(float(qty))

        for leg in option_legs:
            if leg.get("instrument_type") != "OPTION":
                continue

            option_type = leg.get("option_type", "")
            strike = leg.get("option_exercise_price")
            expiration = leg.get("option_expire_date", "")

            if not option_type or strike is None or not expiration:
                continue

            # Determine if the option leg is short:
            # - COVERED_STOCK: the CALL leg is always short (sold), qty is positive
            # - SINGLE with negative qty: naked/cash-secured short option
            # - Future: spreads will need per-leg side detection
            if strategy == "COVERED_STOCK" and option_type == "CALL":
                short_qty = -abs(pos_qty)
            elif pos_qty < 0:
                short_qty = pos_qty
            else:
                continue

            legs.append(
                ShortOptionLeg(
                    symbol=symbol,
                    strike=float(strike),
                    expiration=expiration,
                    option_type=option_type,
                    quantity=short_qty,
                    strategy=strategy,
                    account_id=account_id,
                    account_label=account_label,
                )
            )

    return legs
