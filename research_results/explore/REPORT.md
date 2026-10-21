# Research report - explore stage

> **Research only - paper trading, no orders placed.** Results are historical
> simulations with modelled costs. They are not predictions and not financial
> advice. A strategy surviving every check can still fail going forward.


- generated: `2026-10-21T16:27:06.050372+00:00` - commit `1f9e549e94`
- train **2016-01-01 -> 2021-12-31** | validation **2022-01-01 -> 2023-12-31** | test **2024-01-01 -> 2026-10-20 (LOCKED, not loaded)**
- total parameter trials run: **228** (all counted in the multiple-testing corrections)
- data feed: `sip`; costs: half-spread per ETF + 1.0bp open / 3.0bp stop slippage, margin 7.0%/yr

## Survivors (passed every pre-registered check)

**None.** No strategy passed every check.

## Validation period (out-of-sample for parameter selection)

| strategy | CAGR | avg month (geo) | Sharpe | max DD | worst month | trades |
|---|---|---|---|---|---|---|
| _buy_hold_SPY_ | 1.63% | 0.13% | 0.18 | 24.51% | -9.23% | n/a |
| _buy_hold_QQQ_ | 2.32% | 0.19% | 0.22 | 34.72% | -13.47% | n/a |
| _60_40_SPY_IEF_ | -1.31% | -0.11% | -0.04 | 20.82% | -7.38% | n/a |
| leveraged_trend | 8.91% | 0.71% | 0.45 | 35.73% | -13.64% | 27 |
| meanrev_regime | 1.24% | 0.10% | 0.32 | 4.58% | -2.44% | 670 |
| regime_allocation | -1.16% | -0.10% | -0.10 | 13.65% | -4.43% | 303 |
| xsmom_sector_rotation | 5.85% | 0.47% | 0.61 | 11.06% | -4.32% | 374 |

## Walk-forward out-of-sample (re-selected every 6 months on the trailing 3 years)

| strategy | CAGR | avg month (geo) | Sharpe | max DD | worst month | trades |
|---|---|---|---|---|---|---|
| _buy_hold_SPY_ | 15.60% | 1.21% | 0.79 | 33.84% | -12.47% | n/a |
| _buy_hold_QQQ_ | 22.48% | 1.70% | 0.92 | 35.00% | -13.47% | n/a |
| _60_40_SPY_IEF_ | 9.79% | 0.78% | 0.82 | 21.14% | -7.38% | n/a |
| leveraged_trend | 36.12% | 2.60% | 0.97 | 50.82% | -31.90% | n/a |
| meanrev_regime | 8.53% | 0.68% | 1.52 | 4.58% | -2.44% | n/a |
| regime_allocation | 9.31% | 0.74% | 0.85 | 21.26% | -6.42% | n/a |
| xsmom_sector_rotation | 10.36% | 0.82% | 0.73 | 22.11% | -11.30% | n/a |

## Robustness checks

| strategy | trials | DSR (train) | PBO | neighbour ratio | null p | 2x-cost val Sharpe | WF choice stability | survives | failed checks |
|---|---|---|---|---|---|---|---|---|---|
| leveraged_trend | 72 | 0.99 | 0.41 | 0.90 | 0.020 | 0.45 | 30% | no | validation_sharpe, enough_trades |
| meanrev_regime | 48 | 0.94 | 0.02 | 0.80 | 0.000 | 0.23 | 80% | no | validation_sharpe |
| regime_allocation | 36 | 1.00 | 0.84 | 0.93 | 0.160 | -0.15 | 40% | no | validation_sharpe, validation_cagr, pbo, null_test, cost_stress_2x |
| xsmom_sector_rotation | 72 | 0.89 | 0.06 | 0.89 | 0.110 | 0.58 | 30% | no | dsr_train, null_test |

## What it would take to hit 5-8% per month (leverage on walk-forward OOS returns)

| strategy | Kelly leverage | best monthly geo at any leverage | 5%/mo: leverage | 5%/mo: hist max DD | 5%/mo: P(DD>50%) 1y | 8%/mo: leverage | 8%/mo: hist max DD |
|---|---|---|---|---|---|---|---|
| leveraged_trend | 2.03x | 3.23% | unreachable | unreachable | - | unreachable | unreachable |
| meanrev_regime | 24.08x | 7.28% | 10.00x | 41.93% | 3.60% | unreachable | unreachable |
| regime_allocation | 2.03x | 0.80% | unreachable | unreachable | - | unreachable | unreachable |
| xsmom_sector_rotation | 1.76x | 0.88% | unreachable | unreachable | - | unreachable | unreachable |

## Combined portfolio (top walk-forward (NOT survivors))

Members: meanrev_regime, leveraged_trend, regime_allocation (causal inverse-volatility weights on walk-forward OOS returns).

| strategy | CAGR | avg month (geo) | Sharpe | max DD | worst month | trades |
|---|---|---|---|---|---|---|
| portfolio | 11.98% | 0.95% | 1.51 | 6.45% | -3.94% | n/a |

Adds value vs best single member (meanrev_regime, WF Sharpe 1.52): **no**

## Data quality

33 series loaded. Flagged (big jumps / gaps / zero volume): QLD {'first': '2016-01-04', 'last': '2026-10-20', 'days': 2715, 'missing_sessions_after_first': 0, 'max_abs_daily_return': 0.24327485380116964, 'days_abs_return_over_15pct': ['2020-03-12', '2020-03-13', '2020-03-16', '2020-03-24', '2025-04-09'], 'zero_volume_days': 0}, SLV {'first': '2016-01-04', 'last': '2026-10-20', 'days': 2715, 'missing_sessions_after_first': 0, 'max_abs_daily_return': 0.2863769762378112, 'days_abs_return_over_15pct': ['2026-01-30', '2026-02-05'], 'zero_volume_days': 0}, SSO {'first': '2016-01-04', 'last': '2026-10-20', 'days': 2715, 'missing_sessions_after_first': 0, 'max_abs_daily_return': 0.23401139137510163, 'days_abs_return_over_15pct': ['2020-03-09', '2020-03-12', '2020-03-13', '2020-03-16', '2020-03-24', '2025-04-09'], 'zero_volume_days': 0}, TQQQ {'first': '2016-01-04', 'last': '2026-10-20', 'days': 2715, 'missing_sessions_after_first': 0, 'max_abs_daily_return': 0.3525441329179646, 'days_abs_return_over_15pct': ['2018-12-26', '2020-02-27', '2020-03-09', '2020-03-10', '2020-03-12', '2020-03-13', '2020-03-16', '2020-03-17', '2020-03-24', '2020-03-26'], 'zero_volume_days': 0}, UPRO {'first': '2016-01-04', 'last': '2026-10-20', 'days': 2715, 'missing_sessions_after_first': 0, 'max_abs_daily_return': 0.3502304147465438, 'days_abs_return_over_15pct': ['2020-03-09', '2020-03-10', '2020-03-12', '2020-03-13', '2020-03-16', '2020-03-17', '2020-03-18', '2020-03-24', '2020-03-26', '2020-04-06'], 'zero_volume_days': 0}, USO {'first': '2016-01-04', 'last': '2026-10-20', 'days': 2715, 'missing_sessions_after_first': 0, 'max_abs_daily_return': 0.25458715596330284, 'days_abs_return_over_15pct': ['2020-03-09', '2020-03-18', '2020-04-02', '2020-04-03', '2020-04-21', '2020-04-27'], 'zero_volume_days': 0}, VNQ {'first': '2016-01-04', 'last': '2026-10-20', 'days': 2715, 'missing_sessions_after_first': 0, 'max_abs_daily_return': 0.1765559496936473, 'days_abs_return_over_15pct': ['2020-03-16'], 'zero_volume_days': 0}, XLE {'first': '2016-01-04', 'last': '2026-10-20', 'days': 2715, 'missing_sessions_after_first': 0, 'max_abs_daily_return': 0.20160791589363025, 'days_abs_return_over_15pct': ['2020-03-09', '2020-03-24'], 'zero_volume_days': 0}, XLF {'first': '2016-01-04', 'last': '2026-10-20', 'days': 2715, 'missing_sessions_after_first': 0, 'max_abs_daily_return': 0.17902813299232734, 'days_abs_return_over_15pct': ['2016-09-19'], 'zero_volume_days': 0}

## Per-strategy detail

### leveraged_trend (leveraged_trend)

_Hypothesis:_ Holding a real daily-reset leveraged ETF only while its underlying closes above SMA(n) (else a defensive asset) beats buy-and-hold of the leveraged ETF on risk-adjusted return and drawdown.

- selected on train: `{"lev": "QLD", "sma": 150, "filter": "band2", "defensive": "IEF"}`
- train: CAGR 43.28%, Sharpe 1.25, max DD 34.39%, trades 27, time in market 100%, cost drag 0.07%/yr
- share of trials with positive train Sharpe: 100%
- regimes (train+val, ann. return): down_highvol: 22.1%, down_lowvol: 0.0%, up_highvol: 43.9%, up_lowvol: 37.8%, warmup: 10.7%
- by year: 2016: 9.3%, 2017: 70.4%, 2018: 10.2%, 2019: 43.8%, 2020: 89.3%, 2021: 54.6%, 2022: -32.0%, 2023: 74.2%

### meanrev_regime (mean_reversion)

_Hypothesis:_ For SPY/QQQ/IWM/DIA trading above their 200-day SMA, buying the next open after a short-term oversold close (RSI(2), IBS or consecutive down closes) and selling on the bounce earns a positive after-cost return per unit of exposure (Sharpe > 0) out of sample.

- selected on train: `{"signal": "ibs", "threshold": "strict", "exit_rule": "rsi2", "max_hold": 5, "vol_filter": true, "allow_short": false, "gross": 1.0, "band": 0.02}`
- train: CAGR 8.29%, Sharpe 1.70, max DD 4.19%, trades 670, time in market 25%, cost drag 0.41%/yr
- share of trials with positive train Sharpe: 100%
- regimes (train+val, ann. return): down_highvol: 4.3%, down_lowvol: 17.8%, up_highvol: 11.1%, up_lowvol: 5.1%, warmup: 0.0%
- by year: 2016: 0.0%, 2017: 6.8%, 2018: 1.6%, 2019: 8.8%, 2020: 16.9%, 2021: 16.9%, 2022: 0.9%, 2023: 1.6%

### regime_allocation (regime_allocation)

_Hypothesis:_ Allocating SPY/QQQ/TLT/IEF/GLD/SHY by a causal regime (SPY vs SMA, SPY vol vs 1y median, bond trend) yields a higher Sharpe and smaller max drawdown than a static 60/40 SPY/IEF mix.

- selected on train: `{"trend_sma": 100, "bond_sma": 50, "vol_filter": true, "alloc_map": "defensive", "min_hold": 5, "band": 0.05}`
- train: CAGR 8.42%, Sharpe 1.37, max DD 6.70%, trades 303, time in market 82%, cost drag 0.19%/yr
- share of trials with positive train Sharpe: 100%
- regimes (train+val, ann. return): down_highvol: 1.0%, down_lowvol: 2.2%, up_highvol: 5.5%, up_lowvol: 8.9%, warmup: 0.0%
- by year: 2016: 0.0%, 2017: 10.4%, 2018: 0.1%, 2019: 9.2%, 2020: 17.4%, 2021: 14.6%, 2022: -13.1%, 2023: 12.4%

### xsmom_sector_rotation (cross_sectional_momentum)

_Hypothesis:_ Holding the top-N of the 9 SPDR sector ETFs by trailing return (equal weight, rebalanced weekly/monthly, optional SHY switch for sectors that fail to beat SHY and for the whole book when SPY is below its 200-day SMA) earns a positive after-cost Sharpe that a random re-timing of the same holdings does not, because industry momentum persists at the sector level.

- selected on train: `{"lookback": "blend_1_3_6_12", "top_n": 4, "rebalance": "W", "abs_filter": false, "market_filter": true, "band": 0.01}`
- train: CAGR 13.07%, Sharpe 1.01, max DD 14.03%, trades 374, time in market 83%, cost drag 0.31%/yr
- share of trials with positive train Sharpe: 100%
- regimes (train+val, ann. return): down_highvol: 6.5%, down_lowvol: 2.0%, up_highvol: 19.1%, up_lowvol: 10.9%, warmup: 0.0%
- by year: 2016: 0.0%, 2017: 18.7%, 2018: 0.7%, 2019: 12.3%, 2020: 20.4%, 2021: 29.2%, 2022: 0.9%, 2023: 11.0%


![walk-forward equity](walkforward_equity.png)
