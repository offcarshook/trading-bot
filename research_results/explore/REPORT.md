# Research report - explore stage

> **Research only - paper trading, no orders placed.** Results are historical
> simulations with modelled costs. They are not predictions and not financial
> advice. A strategy surviving every check can still fail going forward.


- generated: `2026-10-21T16:15:11.339062+00:00` - commit `85895e0d41`
- train **2016-01-01 -> 2021-12-31** | validation **2022-01-01 -> 2023-12-31** | test **2024-01-01 -> 2026-10-20 (LOCKED, not loaded)**
- total parameter trials run: **48** (all counted in the multiple-testing corrections)
- data feed: `sip`; costs: half-spread per ETF + 1.0bp open / 3.0bp stop slippage, margin 7.0%/yr

## Survivors (passed every pre-registered check)

**None.** No strategy passed every check.

## Validation period (out-of-sample for parameter selection)

| strategy | CAGR | avg month (geo) | Sharpe | max DD | worst month | trades |
|---|---|---|---|---|---|---|
| _buy_hold_SPY_ | 1.63% | 0.13% | 0.18 | 24.51% | -9.23% | n/a |
| _buy_hold_QQQ_ | 2.32% | 0.19% | 0.22 | 34.72% | -13.47% | n/a |
| _60_40_SPY_IEF_ | -1.34% | -0.11% | -0.04 | 20.85% | -7.40% | n/a |
| tsmom_multi_asset | -1.66% | -0.14% | -0.23 | 13.45% | -3.56% | 1821 |

## Walk-forward out-of-sample (re-selected every 6 months on the trailing 3 years)

| strategy | CAGR | avg month (geo) | Sharpe | max DD | worst month | trades |
|---|---|---|---|---|---|---|
| _buy_hold_SPY_ | 15.60% | 1.21% | 0.79 | 33.84% | -12.47% | n/a |
| _buy_hold_QQQ_ | 22.48% | 1.70% | 0.92 | 35.00% | -13.47% | n/a |
| _60_40_SPY_IEF_ | 9.63% | 0.77% | 0.79 | 21.17% | -7.40% | n/a |
| tsmom_multi_asset | 2.03% | 0.17% | 0.33 | 16.73% | -4.35% | n/a |

## Robustness checks

| strategy | trials | DSR (train) | PBO | neighbour ratio | null p | 2x-cost val Sharpe | WF choice stability | survives | failed checks |
|---|---|---|---|---|---|---|---|---|---|
| tsmom_multi_asset | 48 | 0.91 | 0.26 | 0.79 | 0.150 | -0.30 | 50% | no | validation_sharpe, validation_cagr, walkforward_oos_sharpe, null_test, cost_stress_2x |

## What it would take to hit 5-8% per month (leverage on walk-forward OOS returns)

| strategy | Kelly leverage | best monthly geo at any leverage | 5%/mo: leverage | 5%/mo: hist max DD | 5%/mo: P(DD>50%) 1y | 8%/mo: leverage | 8%/mo: hist max DD |
|---|---|---|---|---|---|---|---|
| tsmom_multi_asset | 4.86x | 0.17% | unreachable | unreachable | - | unreachable | unreachable |

## Per-strategy detail

### tsmom_multi_asset (trend_following)

_Hypothesis:_ Own-asset trailing return sign predicts next-period return across asset classes (vol-targeted).

- selected on train: `{"lookback": 63, "allow_short": false, "target_vol": 0.1, "rebalance": "W", "confirm_sma": false, "max_gross": 1.0}`
- train: CAGR 6.67%, Sharpe 1.20, max DD 10.12%, trades 1821, time in market 95%, cost drag 0.32%/yr
- share of trials with positive train Sharpe: 100%
- regimes (train+val, ann. return): down_highvol: -4.1%, down_lowvol: 4.6%, up_highvol: 10.1%, up_lowvol: 3.9%, warmup: 7.9%
- by year: 2016: 4.7%, 2017: 10.1%, 2018: 2.4%, 2019: 12.6%, 2020: 3.6%, 2021: 7.0%, 2022: -7.3%, 2023: 4.3%


![walk-forward equity](walkforward_equity.png)
