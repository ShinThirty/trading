"""Options analytics computations.

Functions for expected move, historical volatility, and strategy P&L analysis.
Operates on option chain dicts (from Tradier) and OHLCV bar data.
"""

from math import exp, log, sqrt
from typing import TypedDict

from trading_clients.bsm import bsm_price, lognormal_cdf
from trading_clients.endpoint import CONTRACT_MULTIPLIER


class EnrichedLeg(TypedDict):
    """Multi-leg strategy input. Built by callers (e.g. trading-mcp) by joining
    user-supplied legs against a Tradier chain so that downstream analyzers can
    rely on a single typed shape across every leg.
    """

    strike: float
    option_type: str  # "call" | "put"
    side: str  # "buy" | "sell"
    quantity: int
    premium: float
    delta: float | None
    iv: float | None
    bid: float | None
    ask: float | None
    spread_pct: float | None
    occ_symbol: str
    expiration: str


def parse_occ(symbol: str) -> tuple[str, str, str, float]:
    """Parse OCC option symbol into (underlying, expiration, option_type, strike).

    Standard format: ROOT + YYMMDD + C/P + 8-digit strike (strike * 1000).
    Example: 'AAPL260417P00250000' → ('AAPL', '2026-04-17', 'put', 250.0)
    """
    root = symbol[:-15]
    d = symbol[-15:-9]
    option_type = "call" if symbol[-9] == "C" else "put"
    strike = int(symbol[-8:]) / 1000
    exp = f"20{d[:2]}-{d[2:4]}-{d[4:6]}"
    return root, exp, option_type, strike


def build_occ(underlying: str, expiration: str, option_type: str, strike: float) -> str:
    """Build OCC option symbol from components.

    Example: ('AAPL', '2026-04-17', 'put', 250.0) → 'AAPL260417P00250000'
    """
    # YYMMDD from YYYY-MM-DD
    date_part = expiration[2:4] + expiration[5:7] + expiration[8:10]
    cp = "C" if option_type.lower().startswith("c") else "P"
    strike_int = round(strike * 1000)
    return f"{underlying}{date_part}{cp}{strike_int:08d}"


def aggregate_greeks(
    positions: list[dict],
    greeks_by_symbol: dict[str, dict],
) -> dict:
    """Aggregate portfolio Greeks from position dicts and a Greeks lookup.

    positions: normalized position dicts (from to_normalized() or Fidelity parser).
      Option entries must have: underlying, option_type, strike, expiration, quantity.
      Equity entries contribute delta = quantity (1 delta per share).
    greeks_by_symbol: OCC symbol → {delta, gamma, theta, vega, mid_iv} from Tradier.

    Returns dict with:
      totals: {delta, gamma, theta, vega}
      by_underlying: {symbol: {delta, gamma, theta, vega, positions: [...]}}
    """
    by_underlying: dict[str, dict] = {}
    totals = {"delta": 0.0, "gamma": 0.0, "theta": 0.0, "vega": 0.0}

    def _get_underlying(sym: str) -> dict:
        if sym not in by_underlying:
            by_underlying[sym] = {
                "delta": 0.0,
                "gamma": 0.0,
                "theta": 0.0,
                "vega": 0.0,
                "positions": [],
            }
        return by_underlying[sym]

    for p in positions:
        if p.get("is_cash"):
            continue

        symbol = p.get("underlying", p["symbol"])
        entry = _get_underlying(symbol)
        positions_list: list = entry["positions"]

        if p.get("is_option"):
            occ = build_occ(
                p["underlying"],
                p["expiration"],
                p["option_type"],
                p["strike"],
            )
            greeks = greeks_by_symbol.get(occ, {})
            qty = p.get("quantity", 0)
            multiplier = qty * CONTRACT_MULTIPLIER

            pos_delta = (greeks.get("delta") or 0) * multiplier
            pos_gamma = (greeks.get("gamma") or 0) * multiplier
            pos_theta = (greeks.get("theta") or 0) * multiplier
            pos_vega = (greeks.get("vega") or 0) * multiplier

            positions_list.append(
                {
                    "occ": occ,
                    "type": p["option_type"],
                    "strike": p["strike"],
                    "expiration": p["expiration"],
                    "quantity": qty,
                    "delta": pos_delta,
                    "gamma": pos_gamma,
                    "theta": pos_theta,
                    "vega": pos_vega,
                    "iv": greeks.get("mid_iv"),
                }
            )
            entry["delta"] = float(entry["delta"]) + pos_delta
            entry["gamma"] = float(entry["gamma"]) + pos_gamma
            entry["theta"] = float(entry["theta"]) + pos_theta
            entry["vega"] = float(entry["vega"]) + pos_vega
            totals["delta"] += pos_delta
            totals["gamma"] += pos_gamma
            totals["theta"] += pos_theta
            totals["vega"] += pos_vega
        else:
            qty = p.get("quantity", 0)
            entry["delta"] = float(entry["delta"]) + qty
            positions_list.append(
                {
                    "type": "equity",
                    "quantity": qty,
                    "delta": qty,
                    "gamma": 0.0,
                    "theta": 0.0,
                    "vega": 0.0,
                }
            )
            totals["delta"] += qty

    return {"totals": totals, "by_underlying": by_underlying}


def roll_analysis(
    current: dict,
    new: dict,
    stock_price: float,
    current_exp: str,
    target_exp: str,
    current_strike: float,
    actual_strike: float,
    option_type: str = "call",
    chain_credits: float | None = None,
) -> dict:
    """Compute roll metrics for a short option position.

    current/new: option quote dicts with bid, ask, and optional greeks.
    option_type: 'call' or 'put' — needed for debit budget analysis.
    chain_credits: total accumulated chain credits (from get_cc_chain_pnl).
    Returns dict with: close_cost, open_premium, net, net_total,
    cur_dte, new_dte, roll_type, greek changes, and debit budget fields.
    """
    from datetime import date

    cur_bid = float(current.get("bid") or 0)
    cur_ask = float(current.get("ask") or 0)
    new_bid = float(new.get("bid") or 0)
    new_ask = float(new.get("ask") or 0)
    cur_greeks = current.get("greeks") or {}
    new_greeks = new.get("greeks") or {}

    close_cost = cur_ask
    open_premium = new_bid
    net = open_premium - close_cost

    today = date.today()
    cur_dte = max((date.fromisoformat(current_exp) - today).days, 0)
    new_dte = max((date.fromisoformat(target_exp) - today).days, 0)

    if abs(actual_strike - current_strike) < 0.01:
        roll_type = "Horizontal (same strike)"
    elif actual_strike > current_strike:
        roll_type = "Diagonal (roll up)"
    else:
        roll_type = "Diagonal (roll down)"

    if option_type == "call":
        assignment_cost = max(stock_price - current_strike, 0.0)
    else:
        assignment_cost = max(current_strike - stock_price, 0.0)

    result: dict = {
        "stock_price": stock_price,
        "roll_type": roll_type,
        "close_cost": close_cost,
        "open_premium": open_premium,
        "net": net,
        "cur_bid": cur_bid,
        "cur_ask": cur_ask,
        "new_bid": new_bid,
        "new_ask": new_ask,
        "cur_dte": cur_dte,
        "new_dte": new_dte,
        "assignment_cost": assignment_cost,
    }

    if net < 0:
        debit = abs(net)
        debit_budget = chain_credits * 0.5 if chain_credits is not None else None
        result["debit"] = debit
        result["debit_budget"] = debit_budget
        result["chain_credits"] = chain_credits
        result["gate1_pass"] = (
            chain_credits is not None
            and chain_credits > 0
            and debit_budget is not None
            and debit <= debit_budget
        )
        result["gate2_pass"] = assignment_cost > 0 and debit < assignment_cost

    for key in ("delta", "theta", "mid_iv"):
        cur_val = cur_greeks.get(key)
        new_val = new_greeks.get(key)
        if cur_val is not None and new_val is not None:
            result[f"cur_{key}"] = cur_val
            result[f"new_{key}"] = new_val

    return result


def historical_volatility(closes: list[float], period: int = 20) -> float | None:
    """Annualized historical volatility from daily closing prices.

    Computes standard deviation of daily log returns, annualized by √252.
    Returns None if insufficient data.
    """
    if len(closes) < period + 1:
        return None
    recent = closes[-(period + 1) :]
    log_returns = [log(recent[i] / recent[i - 1]) for i in range(1, len(recent))]
    mean = sum(log_returns) / len(log_returns)
    variance = sum((r - mean) ** 2 for r in log_returns) / len(log_returns)
    return sqrt(variance) * sqrt(252)


def find_atm_options(chain: list[dict], stock_price: float) -> tuple[dict | None, dict | None]:
    """Find the ATM call and put closest to the current stock price."""
    calls = [o for o in chain if o.get("option_type") == "call"]
    puts = [o for o in chain if o.get("option_type") == "put"]
    atm_call = min(calls, key=lambda o: abs(o["strike"] - stock_price)) if calls else None
    atm_put = min(puts, key=lambda o: abs(o["strike"] - stock_price)) if puts else None
    return atm_call, atm_put


def mid_price(option: dict) -> float:
    """Compute mid price from bid/ask."""
    bid = option.get("bid")
    ask = option.get("ask")
    if bid is not None and ask is not None and ask > 0:
        return (bid + ask) / 2
    return option.get("last") or 0


def bid_ask_spread_pct(option: dict) -> float | None:
    """Return bid-ask spread as a percentage of the ask price, or None if unavailable."""
    bid = option.get("bid")
    ask = option.get("ask")
    if bid is not None and ask is not None and ask > 0:
        return (ask - bid) / ask * 100
    return None


def expected_move(chain: list[dict], stock_price: float) -> dict[str, float | None]:
    """Compute expected move from ATM straddle price.

    Returns dict with: straddle_price, expected_move, expected_move_pct,
    atm_iv, atm_call_strike, atm_put_strike.
    """
    atm_call, atm_put = find_atm_options(chain, stock_price)
    if not atm_call or not atm_put:
        return {
            "straddle_price": None,
            "expected_move": None,
            "expected_move_pct": None,
            "atm_iv": None,
            "atm_call_strike": None,
            "atm_put_strike": None,
        }

    call_mid = mid_price(atm_call)
    put_mid = mid_price(atm_put)
    straddle = call_mid + put_mid

    call_greeks = atm_call.get("greeks") or {}
    put_greeks = atm_put.get("greeks") or {}
    call_iv = call_greeks.get("mid_iv")
    put_iv = put_greeks.get("mid_iv")
    atm_iv = None
    if call_iv and put_iv:
        atm_iv = (call_iv + put_iv) / 2
    elif call_iv:
        atm_iv = call_iv
    elif put_iv:
        atm_iv = put_iv

    return {
        "straddle_price": straddle,
        "expected_move": straddle,
        "expected_move_pct": (straddle / stock_price * 100) if stock_price else None,
        "atm_iv": atm_iv,
        "atm_call_strike": atm_call["strike"],
        "atm_put_strike": atm_put["strike"],
    }


_POSITIONING_BIN_KEYS = [
    "call_volume",
    "put_volume",
    "call_oi",
    "put_oi",
    "otm_call_vol",
    "atm_call_vol",
    "itm_call_vol",
    "otm_put_vol",
    "atm_put_vol",
    "itm_put_vol",
    "otm_call_oi",
    "atm_call_oi",
    "itm_call_oi",
    "otm_put_oi",
    "atm_put_oi",
    "itm_put_oi",
]


def options_positioning(
    chain: list[dict],
    stock_price: float,
    atm_band_pct: float = 2.0,
) -> dict[str, float | int | None]:
    """Aggregate single-name put/call positioning metrics from an option chain.

    Sums volume and open interest across calls and puts and bins each contract by
    moneyness relative to the underlying spot:
      - OTM: puts with strike < spot*(1-band); calls with strike > spot*(1+band)
      - ATM: strikes within ±band% of spot
      - ITM: puts with strike > spot*(1+band); calls with strike < spot*(1-band)

    When chain entries include 'greeks' with a 'delta' value, also computes
    delta-weighted skew: (Σ call_OI·call_delta − Σ put_OI·|put_delta|) / total_OI.
    Range -1 to +1. Captures both count and moneyness — 5Δ wing OI contributes
    far less than ATM OI, so a 0.9 OI P/C with all OI at the wings reads as
    balanced (delta_skew ~0) rather than tilted.

    Returns a dict with: call_volume, put_volume, call_oi, put_oi, volume_pc_ratio,
    oi_pc_ratio, six volume bins (otm/atm/itm × call/put), six OI bins, band_low,
    band_high, delta_skew, call_delta_oi, put_delta_oi. Ratios and skew are None
    when the underlying counts are zero or greeks are absent.
    """
    band = atm_band_pct / 100
    band_low = stock_price * (1 - band)
    band_high = stock_price * (1 + band)

    b: dict[str, int] = {k: 0 for k in _POSITIONING_BIN_KEYS}
    call_delta_oi = 0.0
    put_delta_oi = 0.0
    has_greeks = False

    for o in chain:
        ot = o.get("option_type")
        if ot not in ("call", "put"):
            continue
        strike = o.get("strike")
        if strike is None:
            continue
        vol = int(o.get("volume") or 0)
        oi = int(o.get("open_interest") or 0)

        if ot == "call":
            b["call_volume"] += vol
            b["call_oi"] += oi
            if strike < band_low:
                b["itm_call_vol"] += vol
                b["itm_call_oi"] += oi
            elif strike > band_high:
                b["otm_call_vol"] += vol
                b["otm_call_oi"] += oi
            else:
                b["atm_call_vol"] += vol
                b["atm_call_oi"] += oi
        else:
            b["put_volume"] += vol
            b["put_oi"] += oi
            if strike > band_high:
                b["itm_put_vol"] += vol
                b["itm_put_oi"] += oi
            elif strike < band_low:
                b["otm_put_vol"] += vol
                b["otm_put_oi"] += oi
            else:
                b["atm_put_vol"] += vol
                b["atm_put_oi"] += oi

        if oi > 0:
            greeks = o.get("greeks") or {}
            delta = greeks.get("delta")
            if delta is not None:
                has_greeks = True
                if ot == "call":
                    call_delta_oi += oi * float(delta)
                else:
                    put_delta_oi += oi * abs(float(delta))

    vol_pc: float | None = b["put_volume"] / b["call_volume"] if b["call_volume"] > 0 else None
    oi_pc: float | None = b["put_oi"] / b["call_oi"] if b["call_oi"] > 0 else None

    total_oi = b["call_oi"] + b["put_oi"]
    delta_skew: float | None
    if has_greeks and total_oi > 0:
        delta_skew = (call_delta_oi - put_delta_oi) / total_oi
    else:
        delta_skew = None

    out: dict[str, float | int | None] = dict(b)
    out["volume_pc_ratio"] = vol_pc
    out["oi_pc_ratio"] = oi_pc
    out["band_low"] = band_low
    out["band_high"] = band_high
    out["delta_skew"] = delta_skew
    out["call_delta_oi"] = call_delta_oi if has_greeks else None
    out["put_delta_oi"] = put_delta_oi if has_greeks else None
    return out


def aggregate_positioning(
    per_exp: list[dict[str, float | int | None]],
    stock_price: float,
    atm_band_pct: float = 2.0,
) -> dict[str, float | int | None]:
    """Sum bin counts across per-expiration positioning dicts and recompute ratios.

    Used by callers that fetched chains across multiple expirations and want a
    single roll-up (with the per-expiration views still available separately).
    """
    band = atm_band_pct / 100
    agg: dict[str, int] = {k: 0 for k in _POSITIONING_BIN_KEYS}
    call_delta_oi = 0.0
    put_delta_oi = 0.0
    has_greeks = False

    for p in per_exp:
        for k in _POSITIONING_BIN_KEYS:
            v = p.get(k)
            if v is not None:
                agg[k] += int(v)
        if p.get("delta_skew") is not None:
            has_greeks = True
            call_delta_oi += float(p.get("call_delta_oi") or 0)
            put_delta_oi += float(p.get("put_delta_oi") or 0)

    out: dict[str, float | int | None] = dict(agg)
    out["band_low"] = stock_price * (1 - band)
    out["band_high"] = stock_price * (1 + band)
    out["volume_pc_ratio"] = (
        agg["put_volume"] / agg["call_volume"] if agg["call_volume"] > 0 else None
    )
    out["oi_pc_ratio"] = agg["put_oi"] / agg["call_oi"] if agg["call_oi"] > 0 else None

    total_oi = agg["call_oi"] + agg["put_oi"]
    if has_greeks and total_oi > 0:
        out["delta_skew"] = (call_delta_oi - put_delta_oi) / total_oi
        out["call_delta_oi"] = call_delta_oi
        out["put_delta_oi"] = put_delta_oi
    else:
        out["delta_skew"] = None
        out["call_delta_oi"] = None
        out["put_delta_oi"] = None
    return out


def classify_positioning(p: dict[str, float | int | None]) -> str:
    """5-tier regime classifier for a positioning dict from `options_positioning`.

    Primary signal is delta-weighted skew (range -1 to +1) — captures both contract
    count and moneyness, which a raw OI P/C ratio misses. Falls back to OI P/C when
    greeks are unavailable.

    Tiers:
      Concentrated Bull   delta_skew > 0.25 (or oi_pc < 0.5)
      Tilted Bull         delta_skew > 0.10 (or oi_pc < 0.85)
      Balanced            otherwise
      Tilted Bear         delta_skew < -0.10 (or oi_pc > 1.15)
      Concentrated Bear   delta_skew < -0.25 (or oi_pc > 2.0)
    """
    delta_skew = p.get("delta_skew")
    if delta_skew is not None:
        ds = float(delta_skew)
        if ds > 0.25:
            return "Concentrated Bull"
        if ds > 0.10:
            return "Tilted Bull"
        if ds < -0.25:
            return "Concentrated Bear"
        if ds < -0.10:
            return "Tilted Bear"
        return "Balanced"

    oi_pc = p.get("oi_pc_ratio")
    if oi_pc is None:
        return "Insufficient activity"
    oi = float(oi_pc)
    if oi < 0.5:
        return "Concentrated Bull"
    if oi < 0.85:
        return "Tilted Bull"
    if oi > 2.0:
        return "Concentrated Bear"
    if oi > 1.15:
        return "Tilted Bear"
    return "Balanced"


# ---------------------------------------------------------------------------
# Strategy detection
# ---------------------------------------------------------------------------


def detect_strategy(legs: list[EnrichedLeg], equity_position: dict | None = None) -> str:
    """Detect option strategy name from leg structure and equity position."""
    n = len(legs)

    # Multi-expiration strategies: route to dedicated detection
    expirations = {lg.get("expiration") for lg in legs if lg.get("expiration")}
    if len(expirations) > 1:
        from trading_clients.options_multi_exp import detect_multi_exp_strategy

        return detect_multi_exp_strategy(legs)

    # Equity-aware strategies (checked first)
    if equity_position is not None:
        short_calls = [lg for lg in legs if lg["side"] == "sell" and lg["option_type"] == "call"]
        long_puts = [lg for lg in legs if lg["side"] == "buy" and lg["option_type"] == "put"]
        if short_calls and long_puts and n == 2:
            return "Collar"
        if short_calls and n == 1:
            return "Covered Call"
        if long_puts and n == 1:
            return "Protective Put"

    # Single-leg
    if n == 1:
        side = legs[0]["side"]
        otype = legs[0]["option_type"]
        if side == "sell" and otype == "put":
            return "Cash-Secured Put"
        if side == "sell" and otype == "call":
            return "Short Call"
        if side == "buy" and otype == "call":
            return "Long Call"
        if side == "buy" and otype == "put":
            return "Long Put"

    # Two-leg strategies
    if n == 2:
        types = {lg["option_type"] for lg in legs}
        sides = {lg["side"] for lg in legs}
        qtys = [lg.get("quantity", 1) for lg in legs]

        # Ratio spread / backspread: same type, different quantities
        if len(types) == 1 and len(sides) == 2 and qtys[0] != qtys[1]:
            short_qty = sum(lg.get("quantity", 1) for lg in legs if lg["side"] == "sell")
            long_qty = sum(lg.get("quantity", 1) for lg in legs if lg["side"] == "buy")
            if short_qty > long_qty:
                return "Ratio Spread"
            return "Backspread"

        # Vertical spreads: same type, different sides, equal quantities
        if len(types) == 1 and len(sides) == 2:
            short = [lg for lg in legs if lg["side"] == "sell"][0]
            long = [lg for lg in legs if lg["side"] == "buy"][0]
            if types == {"put"}:
                if short["strike"] > long["strike"]:
                    return "Bull Put Spread"
                return "Bear Put Spread"
            if types == {"call"}:
                if short["strike"] > long["strike"]:
                    return "Bull Call Spread"
                return "Bear Call Spread"

        # Straddle / strangle: different types, same side
        if types == {"call", "put"} and len(sides) == 1:
            strikes = {lg["strike"] for lg in legs}
            if len(strikes) == 1:
                return "Straddle" if sides == {"buy"} else "Short Straddle"
            return "Strangle" if sides == {"buy"} else "Short Strangle"

    # Three-leg: butterfly
    if n == 3:
        types = {lg["option_type"] for lg in legs}
        if len(types) == 1:
            sorted_legs = sorted(legs, key=lambda lg: lg["strike"])
            sides = [lg["side"] for lg in sorted_legs]
            low_qty = sorted_legs[0].get("quantity", 1)
            mid_qty = sorted_legs[1].get("quantity", 1)
            high_qty = sorted_legs[2].get("quantity", 1)
            if mid_qty == low_qty + high_qty:
                if sides == ["buy", "sell", "buy"]:
                    return "Butterfly"
                if sides == ["sell", "buy", "sell"]:
                    return "Short Butterfly"

    # Four-leg strategies
    if n == 4:
        types = [lg["option_type"] for lg in legs]
        call_count = types.count("call")
        put_count = types.count("put")
        short_count = sum(1 for lg in legs if lg["side"] == "sell")

        if call_count == 2 and put_count == 2 and short_count == 2:
            # Iron condor vs iron butterfly: 3 unique strikes = iron butterfly
            strikes = {lg["strike"] for lg in legs}
            if len(strikes) == 3:
                return "Iron Butterfly"
            return "Iron Condor"

        # Condor: all same type, 4 different strikes, sell inner 2
        if len({lg["option_type"] for lg in legs}) == 1:
            sorted_legs = sorted(legs, key=lambda lg: lg["strike"])
            sides = [lg["side"] for lg in sorted_legs]
            if sides == ["buy", "sell", "sell", "buy"]:
                return "Condor"

    return f"{n}-Leg Strategy"


# ---------------------------------------------------------------------------
# Shared P&L evaluation engine
# ---------------------------------------------------------------------------


def _compute_net_premium(legs: list[EnrichedLeg]) -> float:
    """Compute net premium from legs. Positive = credit, negative = debit."""
    net = 0.0
    for leg in legs:
        qty = leg.get("quantity", 1)
        premium = leg["premium"]
        if leg["side"] == "sell":
            net += premium * qty
        else:
            net -= premium * qty
    return net


def _evaluate_pnl(
    legs: list[EnrichedLeg],
    net_premium: float,
    price_low: float,
    price_high: float,
    equity_position: dict | None = None,
    steps: int = 1000,
) -> dict:
    """Evaluate P&L at price points across a range.

    Returns dict with: max_profit, max_loss, breakevens, risk_reward_ratio.
    """
    step_size = (price_high - price_low) / steps
    pnl_points: list[tuple[float, float]] = []

    eq_shares = equity_position["shares"] if equity_position else 0
    eq_cost = equity_position["cost_basis"] if equity_position else 0.0

    for i in range(steps + 1):
        price = price_low + i * step_size
        pnl = net_premium
        for leg in legs:
            qty = leg.get("quantity", 1)
            strike = leg["strike"]
            if leg["option_type"] == "call":
                intrinsic = max(price - strike, 0)
            else:
                intrinsic = max(strike - price, 0)
            if leg["side"] == "sell":
                pnl -= intrinsic * qty
            else:
                pnl += intrinsic * qty
        contract_pnl = pnl * 100
        if equity_position:
            contract_pnl += (price - eq_cost) * eq_shares
        pnl_points.append((price, contract_pnl))

    max_profit = max(p[1] for p in pnl_points)
    max_loss = min(p[1] for p in pnl_points)

    # Breakeven points (where P&L crosses zero)
    breakevens: list[float] = []
    for i in range(len(pnl_points) - 1):
        p1, pnl1 = pnl_points[i]
        p2, pnl2 = pnl_points[i + 1]
        if (pnl1 <= 0 <= pnl2) or (pnl2 <= 0 <= pnl1):
            if pnl2 != pnl1:
                be = p1 + (0 - pnl1) * (p2 - p1) / (pnl2 - pnl1)
                breakevens.append(round(be, 2))

    risk_reward = None
    if max_loss < 0 and max_profit > 0:
        risk_reward = abs(max_profit / max_loss)

    return {
        "max_profit": max_profit,
        "max_loss": max_loss,
        "breakevens": breakevens,
        "risk_reward_ratio": risk_reward,
    }


def _estimate_probability_of_profit(legs: list[EnrichedLeg]) -> float | None:
    """Approximate probability of profit from delta."""
    short_legs = [lg for lg in legs if lg["side"] == "sell"]

    if len(legs) == 1:
        leg = legs[0]
        delta = leg.get("delta")
        if delta is None:
            return None
        if leg["side"] == "sell":
            return 1 - abs(delta)
        return abs(delta)

    if short_legs and all(lg.get("delta") is not None for lg in short_legs):
        probs = []
        for leg in short_legs:
            delta = leg["delta"]
            if delta is None:
                return None
            probs.append(1 - abs(delta))
        return sum(probs) / len(probs)

    return None


# ---------------------------------------------------------------------------
# Per-strategy analysis functions
# ---------------------------------------------------------------------------


def _build_result(
    strategy_type: str,
    legs: list[EnrichedLeg],
    net_premium: float,
    pnl: dict,
    **extras: float | None,
) -> dict:
    """Build the standard result dict returned by strategy_analysis()."""
    result = {
        "strategy_type": strategy_type,
        "net_premium": net_premium,
        "net_premium_total": net_premium * 100,
        "max_profit": pnl["max_profit"],
        "max_loss": pnl["max_loss"],
        "breakevens": pnl["breakevens"],
        "risk_reward_ratio": pnl["risk_reward_ratio"],
        "probability_of_profit": _estimate_probability_of_profit(legs),
    }
    for k, v in extras.items():
        if v is not None:
            result[k] = v
    return result


def _analyze_equity_strategy(
    strategy_type: str,
    legs: list[EnrichedLeg],
    stock_price: float,
    equity_position: dict,
) -> dict:
    """Analyze strategies with an equity position (Covered Call, Protective Put, Collar)."""
    net_premium = _compute_net_premium(legs)
    strikes = [lg["strike"] for lg in legs]

    has_short_call = any(lg["side"] == "sell" and lg["option_type"] == "call" for lg in legs)
    has_long_put = any(lg["side"] == "buy" and lg["option_type"] == "put" for lg in legs)

    # Downside: stock can go to zero unless protected by a long put
    price_low = 0.0 if not has_long_put else max(0, min(strikes) - stock_price * 0.1)

    # Upside: capped if short call present, otherwise extends
    if has_short_call:
        price_high = max(strikes) + stock_price * 0.5
    else:
        price_high = stock_price * 2

    pnl = _evaluate_pnl(legs, net_premium, price_low, price_high, equity_position)

    # Covered call extras
    extras: dict[str, float | None] = {}
    if strategy_type == "Covered Call":
        cost_basis = equity_position["cost_basis"]
        if cost_basis > 0:
            short_call = [
                lg for lg in legs if lg["side"] == "sell" and lg["option_type"] == "call"
            ][0]
            strike = short_call["strike"]
            premium = short_call["premium"]  # per-share, not scaled by qty
            extras["if_called_return"] = (strike - cost_basis + premium) / cost_basis
            extras["static_return"] = premium / cost_basis

    return _build_result(strategy_type, legs, net_premium, pnl, **extras)


def _analyze_defined_risk(
    strategy_type: str,
    legs: list[EnrichedLeg],
    stock_price: float,
) -> dict:
    """Analyze defined-risk strategies (verticals, iron condors, butterflies, condors)."""
    net_premium = _compute_net_premium(legs)
    strikes = [lg["strike"] for lg in legs]
    margin = max(max(strikes) - min(strikes), stock_price * 0.1)
    price_low = max(0, min(strikes) - margin)
    price_high = max(strikes) + margin

    pnl = _evaluate_pnl(legs, net_premium, price_low, price_high)
    return _build_result(strategy_type, legs, net_premium, pnl)


def _analyze_undefined_risk(
    strategy_type: str,
    legs: list[EnrichedLeg],
    stock_price: float,
) -> dict:
    """Analyze undefined-risk strategies (CSP, naked call, short straddle/strangle, ratio)."""
    net_premium = _compute_net_premium(legs)

    has_short_put = any(lg["side"] == "sell" and lg["option_type"] == "put" for lg in legs)
    has_short_call = any(lg["side"] == "sell" and lg["option_type"] == "call" for lg in legs)
    strikes = [lg["strike"] for lg in legs]

    price_low = 0.0 if has_short_put else max(0, min(strikes) - stock_price * 0.1)
    price_high = max(strikes) + stock_price if has_short_call else max(strikes) + stock_price * 0.1

    pnl = _evaluate_pnl(legs, net_premium, price_low, price_high)
    return _build_result(strategy_type, legs, net_premium, pnl)


def _analyze_long_only(
    strategy_type: str,
    legs: list[EnrichedLeg],
    stock_price: float,
) -> dict:
    """Analyze long-only strategies (long call/put, straddle/strangle, backspread)."""
    net_premium = _compute_net_premium(legs)

    has_long_put = any(lg["side"] == "buy" and lg["option_type"] == "put" for lg in legs)
    has_long_call = any(lg["side"] == "buy" and lg["option_type"] == "call" for lg in legs)
    strikes = [lg["strike"] for lg in legs]

    price_low = 0.0 if has_long_put else max(0, min(strikes) - stock_price * 0.1)
    price_high = max(strikes) + stock_price if has_long_call else max(strikes) + stock_price * 0.1

    pnl = _evaluate_pnl(legs, net_premium, price_low, price_high)
    return _build_result(strategy_type, legs, net_premium, pnl)


# ---------------------------------------------------------------------------
# Strategy classifications
# ---------------------------------------------------------------------------
# Sets of strategy-type strings grouped by various characteristics. Used
# internally by strategy_analysis() for routing and externally (e.g. by
# trading-mcp's analyze_option_strategy) for metric calculations.

# --- Risk profile: routes strategy_analysis() to the correct analyzer ---
EQUITY_STRATEGIES = {"Covered Call", "Protective Put", "Collar"}
DEFINED_RISK_STRATEGIES = {
    "Bull Put Spread",
    "Bear Put Spread",
    "Bull Call Spread",
    "Bear Call Spread",
    "Iron Condor",
    "Iron Butterfly",
    "Butterfly",
    "Short Butterfly",
    "Condor",
}
UNDEFINED_RISK_STRATEGIES = {
    "Cash-Secured Put",
    "Short Call",
    "Short Straddle",
    "Short Strangle",
    "Ratio Spread",
}
LONG_ONLY_STRATEGIES = {
    "Long Call",
    "Long Put",
    "Straddle",
    "Strangle",
    "Backspread",
}

# --- Premium direction: used by lognormal expected-value calculations ---
CREDIT_SPREAD_STRATEGIES = {
    "Bull Put Spread",
    "Bear Call Spread",
    "Iron Condor",
    "Iron Butterfly",
}
DEBIT_STRATEGIES = {
    "Long Call",
    "Long Put",
    "Bull Call Spread",
    "Bear Put Spread",
}
EV_STRATEGIES = CREDIT_SPREAD_STRATEGIES | DEBIT_STRATEGIES | {"Cash-Secured Put"}

# --- Profit zone shape: used by lognormal PoP calculations ---
PROFIT_ABOVE_BREAKEVEN = {
    "Cash-Secured Put",
    "Bull Put Spread",
    "Bull Call Spread",
    "Long Call",
}
PROFIT_BELOW_BREAKEVEN = {
    "Bear Call Spread",
    "Bear Put Spread",
    "Long Put",
    "Short Call",
}
PROFIT_BETWEEN_BREAKEVENS = {
    "Iron Condor",
    "Iron Butterfly",
    "Butterfly",
    "Short Straddle",
    "Short Strangle",
}
PROFIT_OUTSIDE_BREAKEVENS = {
    "Straddle",
    "Strangle",
    "Short Butterfly",
}


# ---------------------------------------------------------------------------
# Lognormal EV / PoP — risk-neutral expectations under terminal price model
# ---------------------------------------------------------------------------


def lognormal_ev(
    enriched_legs: list[EnrichedLeg],
    strategy_type: str,
    stock_price: float,
    max_loss: float,
    dte: int,
    risk_free_rate: float,
) -> tuple[float, float] | None:
    """Risk-neutral expected P&L and EV / capital-at-risk for a credit or
    debit strategy.

    Integrates each leg's payoff over the lognormal terminal distribution using
    its own implied vol, then nets against the upfront credit/debit. Returns
    (expected_pnl_dollars, ev_pct) or None if the strategy doesn't qualify or
    inputs are missing.

    Capital at risk:
      - Cash-Secured Put: strike * 100 * qty per short put leg (collateral)
      - Defined-risk strategies (credit spreads, debit spreads, long options):
        abs(max_loss)
    """
    if strategy_type not in EV_STRATEGIES or dte <= 0:
        return None
    if not all(el.get("iv") for el in enriched_legs):
        return None

    if strategy_type == "Cash-Secured Put":
        capital_at_risk = sum(
            el["strike"] * el["quantity"] * CONTRACT_MULTIPLIER
            for el in enriched_legs
            if el["side"] == "sell" and el["option_type"] == "put"
        )
    elif max_loss < 0:
        capital_at_risk = abs(max_loss)
    else:
        return None

    if not capital_at_risk or capital_at_risk <= 0:
        return None

    tte = dte / 365
    forward_factor = exp(risk_free_rate * tte)
    net_premium = sum(
        (1 if el["side"] == "sell" else -1) * el["premium"] * el["quantity"] for el in enriched_legs
    )
    expected_pnl = net_premium * CONTRACT_MULTIPLIER
    for el in enriched_legs:
        iv = el["iv"]
        if iv is None:
            return None
        # Risk-neutral expected payoff at expiration = bsm_price * exp(rT)
        payoff = (
            bsm_price(
                stock_price=stock_price,
                strike=el["strike"],
                tte=tte,
                iv=iv,
                option_type=el["option_type"],
                r=risk_free_rate,
            )
            * forward_factor
        )
        side_sign = -1 if el["side"] == "sell" else 1
        expected_pnl += side_sign * payoff * el["quantity"] * CONTRACT_MULTIPLIER

    ev_pct = expected_pnl / capital_at_risk * 100
    return expected_pnl, ev_pct


def lognormal_pop(
    strategy_type: str,
    breakevens: list[float],
    enriched_legs: list[EnrichedLeg],
    stock_price: float,
    dte: int,
    risk_free_rate: float,
) -> float | None:
    """Probability of finishing in the strategy's profit zone using lognormal CDF.

    Uses the average IV across legs as the underlying terminal-vol proxy, then
    computes P(S_T in profit_zone) by integrating the risk-neutral lognormal
    distribution. More accurate than the delta-based approximation for
    multi-leg strategies (especially iron condors/butterflies and long
    options where delta conflates ITM with above-breakeven). Returns None if
    the strategy isn't classifiable, breakevens are missing, or IVs are
    unavailable.
    """
    if not breakevens or dte <= 0:
        return None
    ivs = [el.get("iv") for el in enriched_legs if el.get("iv")]
    if not ivs:
        return None
    iv = sum(ivs) / len(ivs)
    if iv <= 0:
        return None

    tte = dte / 365

    def cdf(price: float) -> float:
        return lognormal_cdf(price, stock_price, tte, iv, risk_free_rate)

    if strategy_type in PROFIT_ABOVE_BREAKEVEN and len(breakevens) >= 1:
        return 1.0 - cdf(breakevens[0])
    if strategy_type in PROFIT_BELOW_BREAKEVEN and len(breakevens) >= 1:
        return cdf(breakevens[0])
    if strategy_type in PROFIT_BETWEEN_BREAKEVENS and len(breakevens) >= 2:
        return cdf(breakevens[1]) - cdf(breakevens[0])
    if strategy_type in PROFIT_OUTSIDE_BREAKEVENS and len(breakevens) >= 2:
        return cdf(breakevens[0]) + (1.0 - cdf(breakevens[1]))
    return None


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def strategy_analysis(
    legs: list[EnrichedLeg],
    stock_price: float,
    equity_position: dict | None = None,
) -> dict:
    """Analyze a multi-leg option strategy.

    Each leg dict should have:
      - strike: float
      - option_type: 'call' or 'put'
      - side: 'buy' or 'sell'
      - premium: float (mid price per share)
      - delta: float (optional, for probability estimation)
      - quantity: int (number of contracts, default 1)

    equity_position: optional dict with 'shares' (int) and 'cost_basis' (float)
    for strategies involving stock (covered call, protective put, collar).

    Returns dict with: net_premium, max_profit, max_loss, breakevens,
    risk_reward_ratio, probability_of_profit, strategy_type,
    plus strategy-specific extras (e.g. if_called_return, static_return).
    """
    if not legs:
        return {}

    strategy_type = detect_strategy(legs, equity_position)

    if strategy_type in EQUITY_STRATEGIES and equity_position:
        return _analyze_equity_strategy(strategy_type, legs, stock_price, equity_position)
    if strategy_type in DEFINED_RISK_STRATEGIES:
        return _analyze_defined_risk(strategy_type, legs, stock_price)
    if strategy_type in UNDEFINED_RISK_STRATEGIES:
        return _analyze_undefined_risk(strategy_type, legs, stock_price)
    if strategy_type in LONG_ONLY_STRATEGIES:
        return _analyze_long_only(strategy_type, legs, stock_price)

    # Fallback for unrecognized strategies
    return _analyze_undefined_risk(strategy_type, legs, stock_price)
