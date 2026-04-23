# Black-Scholes Option Pricing Model

Two equations: one describes how stock prices move, the other derives what options should cost given that movement.

## Equation 1: Stock Price Distribution

The stock price at expiration follows a lognormal distribution:

```
S_T = S * e^((r - sigma^2/2) * T + sigma * sqrt(T) * Z)
```

- **S** = current stock price
- **r** = risk-free interest rate (annual, continuously compounded)
- **sigma** = volatility (annualized)
- **T** = time to expiration (trading days / 252)
- **Z** ~ N(0,1) = standard normal random variable

The -sigma^2/2 term is a correction ensuring the expected return equals r under risk-neutral pricing. Z ranges from -infinity to +infinity but practically |Z| < 3 covers 99.7% of outcomes.

**Example:** SPY at $708, 22 DTE, IV = 18%:

| Z | S_T | Move |
|---|-----|------|
| +2 | $787 | +11.2% |
| +1 | $747 | +5.4% |
| 0 | $708 | 0% |
| -1 | $671 | -5.2% |
| -2 | $637 | -10.0% |

## Equation 2: Option Pricing

The option price is the expected payoff under the lognormal distribution, discounted to present value:

```
C = e^(-rT) * E[max(S_T - K, 0)]
```

Working out this expectation (splitting the integral at the ITM boundary, completing the square) yields:

**Call:**
```
C = S * N(d1) - K * e^(-rT) * N(d2)
```

**Put:**
```
P = K * e^(-rT) * N(-d2) - S * N(-d1)
```

**Where:**
```
d1 = [ln(S/K) + (r + sigma^2/2) * T] / (sigma * sqrt(T))
d2 = d1 - sigma * sqrt(T)
```

- **N()** = cumulative standard normal distribution (probability that Z <= x)
- **N(d2)** = probability of finishing ITM (risk-neutral)
- **N(d1)** = delta (probability under the "stock measure," slightly higher than N(d2))

### Reading the call formula

- **S * N(d1)** = expected value of receiving the stock, weighted by delta-adjusted ITM probability
- **K * e^(-rT) * N(d2)** = present value of paying the strike, weighted by true ITM probability
- The difference is the option's value today

### Deriving the expectation

The payoff max(S_T - K, 0) is zero when Z <= -d2 (option expires OTM). The integral reduces to:

```
E[max(S_T - K, 0)] = integral from -d2 to infinity of (S_T(z) - K) * n(z) dz
```

Split into two integrals:

1. **Strike integral** (easy): K * integral of n(z) from -d2 to infinity = K * N(d2)
2. **Stock integral** (hard): Substitute S_T, combine exponents with n(z), complete the square in z. The exponent simplifies to -(z - sigma*sqrt(T))^2/2 + rT. Substituting w = z - sigma*sqrt(T) shifts the lower bound from -d2 to -d1, giving S * e^(rT) * N(d1).

Combining and discounting by e^(-rT) produces the Black-Scholes formula.

## Understanding d1

d1 measures how far the stock price is from the strike, normalized by the expected range of movement:

```
d1 ~ ln(S/K) / (sigma * sqrt(T))
```

- **Numerator:** moneyness (how far S is from K in log terms)
- **Denominator:** sigma * sqrt(T) = expected range of price movement to expiration

Same dollar distance from strike produces very different d1 depending on time and volatility:

| Scenario | sigma * sqrt(T) | d1 | Delta |
|----------|-----------------|-----|-------|
| 1 DTE, IV 20% | 0.013 | 0.90 | 0.82 |
| 22 DTE, IV 20% | 0.059 | 0.19 | 0.58 |
| 22 DTE, IV 40% | 0.118 | 0.10 | 0.54 |

Short time / low vol = stock unlikely to reach strike = delta far from 0.50.
Long time / high vol = plenty of room to reach strike = delta near 0.50.

### Behavior at expiration (T -> 0)

As T -> 0, sigma * sqrt(T) -> 0, so d1 diverges:

- S > K: d1 -> +infinity, N(d1) -> 1, delta -> 1 (certain ITM)
- S < K: d1 -> -infinity, N(d1) -> 0, delta -> 0 (certain OTM)
- S = K: d1 = 0, N(d1) = 0.50 (coin flip)

Delta becomes a step function at expiration, which is why 0DTE gamma is extreme.

## The Greeks

All derived as partial derivatives of the Black-Scholes formula.

### Delta = dC/dS = N(d1)

Differentiating the call formula with respect to S requires the product rule (since d1 and d2 depend on S), but the chain rule terms cancel due to the identity S * n(d1) = K * e^(-rT) * n(d2), leaving just N(d1).

**Two meanings:**
1. **Hedge ratio:** if SPY moves $1, a -0.35 delta put changes by ~$0.35
2. **Approximate ITM probability:** ~35% chance of finishing ITM (true probability is N(d2), slightly lower)

For puts: delta = N(d1) - 1 (always between -1 and 0).

### Gamma = dDelta/dS = n(d1) / (S * sigma * sqrt(T))

The rate of change of delta. Highest ATM (where n(d1) peaks, since the bell curve PDF is maximized at d1 = 0) and near expiration (when sigma * sqrt(T) in the denominator shrinks).

**Practical impact:** Large open interest at a strike + high gamma = massive hedging flows. Market makers must constantly rebalance as delta swings, creating the gamma pinning effect that pulls price toward high-OI strikes.

### Other Greeks

- **Theta** = dC/dT: time decay, accelerates near expiration
- **Vega** = dC/d(sigma): sensitivity to IV changes, highest ATM and for longer-dated options
- **Rho** = dC/dr: sensitivity to interest rates, usually small for short-dated options

## Implied Volatility

The only unobservable input in Black-Scholes. Solved numerically by inverting the formula:

```
Given market price, find sigma such that BS(S, K, T, r, sigma) = market price
```

Solved via Newton-Raphson using vega as the derivative:

```
sigma_new = sigma + (market_price - model_price) / vega
```

Converges in 3-4 iterations because price-vs-sigma is smooth and monotonic.

### Volatility Skew

If Black-Scholes were perfect, every strike at the same expiration would have the same IV. They don't:

- OTM puts carry higher IV than ATM options
- OTM calls carry lower IV

This reflects the empirical fact that markets crash faster than they rally (leverage unwinds, loss aversion, forced selling). The left tail is fatter than the normal distribution predicts, and the market prices this in through higher IV on downside strikes.

## Continuous Compounding

Black-Scholes uses e as the compounding base:

```
FV = PV * e^(rT)     (continuous)
vs.
FV = PV * (1 + r/n)^(nT)   (discrete, n times per year)
```

As n -> infinity, (1 + r/n)^(nT) -> e^(rT). This is the definition of e.

Continuous compounding is a modeling choice matching the assumption of continuous trading. It makes the calculus clean: derivatives of e^(rt) are simple, and multiplicative returns become additive in log space.

## Time Convention

T is normalized by 252 trading days, not 365 calendar days. Volatility is estimated from daily returns on trading days, so T must use the same basis. The risk-free rate technically accrues on calendar days, but the rT term is small enough relative to sigma * sqrt(T) that the inconsistency is negligible for short-dated options.

## Where the Model Breaks Down

Black-Scholes assumes normally distributed log returns. Real markets exhibit:

- **Fat tails:** Extreme moves (Z < -3) occur more often than predicted
- **Volatility clustering:** sigma is not constant, it spikes during selloffs
- **Asymmetric moves:** crashes are faster than rallies (reflexive leverage unwinds)

The IV skew, VIX term structure, and gamma-driven price dynamics are all the market's corrections for these model limitations.
