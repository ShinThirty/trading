"""ADR/ADS parity math (pure functions, no I/O).

Fair value of one ADR = ordinary price x ordinary-shares-per-ADR / FX, with FX
quoted as home-currency units per USD. The deposit ratio is set per-program in
the deposit agreement (SKHY: 1 ADS = 1/10 common -> 0.1; TSM: 1 ADS = 5
ordinaries -> 5.0) and can be amended by the issuer later, so callers pass it
explicitly: a wrong or stale ratio yields a plausible-looking but 10-100x wrong
premium, which is the failure this module exists to prevent.
"""

from dataclasses import dataclass

from trading_clients.table_helpers import fmt_number, kv_table


@dataclass(frozen=True)
class AdrParity:
    adr_symbol: str
    ordinary_symbol: str
    adr_price: float
    ordinary_price: float
    ordinary_shares_per_adr: float
    fx_rate: float  # home-currency units per USD
    ordinary_bar_date: str
    fair_value: float
    premium_pct: float

    def to_output(self) -> str:
        label = "premium" if self.premium_pct >= 0 else "discount"
        data = {
            "ADR": f"{self.adr_symbol} @ ${fmt_number(self.adr_price)}",
            "Ordinary": (
                f"{self.ordinary_symbol} @ {fmt_number(self.ordinary_price)} "
                f"(close {self.ordinary_bar_date})"
            ),
            "Ratio": f"{fmt_number(self.ordinary_shares_per_adr, 4)} ordinary shares per ADR",
            "FX (home per USD)": fmt_number(self.fx_rate, 4),
            "Fair Value": f"${fmt_number(self.fair_value)}",
            "Premium": f"{self.premium_pct:+.2f}% ({label} vs FX-adjusted parity)",
        }
        return kv_table(data)


def compute_adr_parity(
    adr_symbol: str,
    ordinary_symbol: str,
    adr_price: float,
    ordinary_price: float,
    ordinary_shares_per_adr: float,
    fx_rate: float,
    ordinary_bar_date: str,
) -> AdrParity:
    """Fair value and premium/discount of a US ADR vs its home-market ordinary.

    fx_rate must be home-currency units per USD (e.g. ~1494 for KRW), matching
    Yahoo's 'USDKRW=X' quote direction.
    """
    if adr_price <= 0 or ordinary_price <= 0:
        raise ValueError("prices must be positive")
    if ordinary_shares_per_adr <= 0:
        raise ValueError("ordinary_shares_per_adr must be positive")
    if fx_rate <= 0:
        raise ValueError("fx_rate must be positive")
    fair_value = ordinary_price * ordinary_shares_per_adr / fx_rate
    premium_pct = (adr_price / fair_value - 1) * 100
    return AdrParity(
        adr_symbol=adr_symbol,
        ordinary_symbol=ordinary_symbol,
        adr_price=adr_price,
        ordinary_price=ordinary_price,
        ordinary_shares_per_adr=ordinary_shares_per_adr,
        fx_rate=fx_rate,
        ordinary_bar_date=ordinary_bar_date,
        fair_value=fair_value,
        premium_pct=premium_pct,
    )
