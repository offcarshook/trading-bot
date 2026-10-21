# Research report - explore stage

> **Research only - paper trading, no orders placed.** Results are historical
> simulations with modelled costs. They are not predictions and not financial
> advice. A strategy surviving every check can still fail going forward.


- generated: `2026-10-21T16:55:28.750114+00:00` - commit `9c273c6a84`
- train **2016-01-01 -> 2021-12-31** | validation **2022-01-01 -> 2023-12-31** | test **2024-01-01 -> 2026-10-20 (LOCKED, not loaded)**
- total parameter trials run: **54** (all counted in the multiple-testing corrections)
- data feed: `sip`; costs: half-spread per ETF + 1.0bp open / 3.0bp stop slippage, margin 7.0%/yr

## Survivors (passed every pre-registered check)

**None.** No strategy passed every check.

## Validation period (out-of-sample for parameter selection)

| strategy | CAGR | avg month (geo) | Sharpe | max DD | worst month | trades |
|---|---|---|---|---|---|---|
| _buy_hold_SPY_ | 1.63% | 0.13% | 0.18 | 24.51% | -9.23% | n/a |
| _buy_hold_QQQ_ | 2.32% | 0.19% | 0.22 | 34.72% | -13.47% | n/a |
| _60_40_SPY_IEF_ | -1.31% | -0.11% | -0.04 | 20.82% | -7.38% | n/a |
| degen_meanrev_letf | 2.42% | 0.20% | 0.26 | 13.79% | -7.44% | 676 |
| degen_trend_letf | 15.20% | 1.18% | 0.56 | 39.57% | -20.47% | 13 |
| degen_combo | 12.06% | 0.95% | 0.48 | 52.29% | -31.85% | 1169 |

## Walk-forward out-of-sample (re-selected every 6 months on the trailing 3 years)

| strategy | CAGR | avg month (geo) | Sharpe | max DD | worst month | trades |
|---|---|---|---|---|---|---|
| _buy_hold_SPY_ | 15.60% | 1.21% | 0.79 | 33.84% | -12.47% | n/a |
| _buy_hold_QQQ_ | 22.48% | 1.70% | 0.92 | 35.00% | -13.47% | n/a |
| _60_40_SPY_IEF_ | 9.79% | 0.78% | 0.82 | 21.14% | -7.38% | n/a |
| degen_meanrev_letf | 32.57% | 2.37% | 1.30 | 28.61% | -14.09% | n/a |
| degen_trend_letf | 56.55% | 3.80% | 1.13 | 48.14% | -24.09% | n/a |
| degen_combo | 99.58% | 5.92% | 1.35 | 52.29% | -33.43% | n/a |

## Robustness checks

| strategy | trials | DSR (train) | PBO | neighbour ratio | null p | 2x-cost val Sharpe | WF choice stability | survives | failed checks |
|---|---|---|---|---|---|---|---|---|---|
| degen_meanrev_letf | 24 | 1.00 | 0.40 | 0.89 | 0.000 | 0.20 | 40% | no | validation_sharpe |
| degen_trend_letf | 18 | 0.99 | 0.60 | 0.86 | 0.020 | 0.56 | 100% | no | pbo, enough_trades |
| degen_combo | 12 | 0.99 | 0.11 | 0.86 | 0.010 | 0.41 | 90% | no | validation_sharpe |

## What it would take to hit 5-8% per month (leverage on walk-forward OOS returns)

| strategy | Kelly leverage | best monthly geo at any leverage | 5%/mo: leverage | 5%/mo: hist max DD | 5%/mo: P(DD>50%) 1y | 8%/mo: leverage | 8%/mo: hist max DD |
|---|---|---|---|---|---|---|---|
| degen_meanrev_letf | 5.14x | 6.28% | 2.75x | 62.99% | 17.60% | unreachable | unreachable |
| degen_trend_letf | 1.98x | 4.77% | unreachable | unreachable | - | unreachable | unreachable |
| degen_combo | 1.79x | 7.65% | 1.00x | 52.73% | 25.20% | unreachable | unreachable |

## Combined portfolio (top walk-forward (NOT survivors))

Members: degen_combo, degen_meanrev_letf, degen_trend_letf (causal inverse-volatility weights on walk-forward OOS returns).

| strategy | CAGR | avg month (geo) | Sharpe | max DD | worst month | trades |
|---|---|---|---|---|---|---|
| portfolio | 45.09% | 3.14% | 1.29 | 34.44% | -17.10% | n/a |

Adds value vs best single member (degen_combo, WF Sharpe 1.35): **no**

## Data quality

35 series loaded. Flagged (big jumps / gaps / zero volume): QLD {'first': '2016-01-04', 'last': '2026-10-20', 'days': 2715, 'missing_sessions_after_first': 0, 'max_abs_daily_return': 0.24327485380116964, 'days_abs_return_over_15pct': ['2020-03-12', '2020-03-13', '2020-03-16', '2020-03-24', '2025-04-09'], 'zero_volume_days': 0}, SLV {'first': '2016-01-04', 'last': '2026-10-20', 'days': 2715, 'missing_sessions_after_first': 0, 'max_abs_daily_return': 0.2863769762378112, 'days_abs_return_over_15pct': ['2026-01-30', '2026-02-05'], 'zero_volume_days': 0}, SSO {'first': '2016-01-04', 'last': '2026-10-20', 'days': 2715, 'missing_sessions_after_first': 0, 'max_abs_daily_return': 0.23401139137510163, 'days_abs_return_over_15pct': ['2020-03-09', '2020-03-12', '2020-03-13', '2020-03-16', '2020-03-24', '2025-04-09'], 'zero_volume_days': 0}, TNA {'first': '2016-01-04', 'last': '2026-10-20', 'days': 2715, 'missing_sessions_after_first': 0, 'max_abs_daily_return': 0.3752252252252253, 'days_abs_return_over_15pct': ['2020-03-09', '2020-03-11', '2020-03-12', '2020-03-13', '2020-03-16', '2020-03-18', '2020-03-24', '2020-03-26', '2020-04-01', '2020-04-06'], 'zero_volume_days': 0}, TQQQ {'first': '2016-01-04', 'last': '2026-10-20', 'days': 2715, 'missing_sessions_after_first': 0, 'max_abs_daily_return': 0.3525441329179646, 'days_abs_return_over_15pct': ['2018-12-26', '2020-02-27', '2020-03-09', '2020-03-10', '2020-03-12', '2020-03-13', '2020-03-16', '2020-03-17', '2020-03-24', '2020-03-26'], 'zero_volume_days': 0}, UDOW {'first': '2016-01-04', 'last': '2026-10-20', 'days': 2715, 'missing_sessions_after_first': 0, 'max_abs_daily_return': 0.3567131327953045, 'days_abs_return_over_15pct': ['2020-03-09', '2020-03-11', '2020-03-12', '2020-03-13', '2020-03-16', '2020-03-18', '2020-03-24', '2020-03-26', '2020-04-06', '2020-06-11'], 'zero_volume_days': 0}, UPRO {'first': '2016-01-04', 'last': '2026-10-20', 'days': 2715, 'missing_sessions_after_first': 0, 'max_abs_daily_return': 0.3502304147465438, 'days_abs_return_over_15pct': ['2020-03-09', '2020-03-10', '2020-03-12', '2020-03-13', '2020-03-16', '2020-03-17', '2020-03-18', '2020-03-24', '2020-03-26', '2020-04-06'], 'zero_volume_days': 0}, USO {'first': '2016-01-04', 'last': '2026-10-20', 'days': 2715, 'missing_sessions_after_first': 0, 'max_abs_daily_return': 0.25458715596330284, 'days_abs_return_over_15pct': ['2020-03-09', '2020-03-18', '2020-04-02', '2020-04-03', '2020-04-21', '2020-04-27'], 'zero_volume_days': 0}, VNQ {'first': '2016-01-04', 'last': '2026-10-20', 'days': 2715, 'missing_sessions_after_first': 0, 'max_abs_daily_return': 0.1765559496936473, 'days_abs_return_over_15pct': ['2020-03-16'], 'zero_volume_days': 0}, XLE {'first': '2016-01-04', 'last': '2026-10-20', 'days': 2715, 'missing_sessions_after_first': 0, 'max_abs_daily_return': 0.20160791589363025, 'days_abs_return_over_15pct': ['2020-03-09', '2020-03-24'], 'zero_volume_days': 0}, XLF {'first': '2016-01-04', 'last': '2026-10-20', 'days': 2715, 'missing_sessions_after_first': 0, 'max_abs_daily_return': 0.17902813299232734, 'days_abs_return_over_15pct': ['2016-09-19'], 'zero_volume_days': 0}

## Per-strategy detail

### degen_meanrev_letf (degen_leverage)

_Hypothesis:_ The mean-reversion edge on index ETFs survives being expressed through 3x leveraged ETFs with up to ~2x margin (~6x underlying).

- selected on train: `{"margin": 1.0, "alloc": "equal_slots", "threshold": "strict", "vol_filter": true}`
- train: CAGR 26.14%, Sharpe 1.71, max DD 11.71%, trades 676, time in market 25%, cost drag 0.76%/yr
- share of trials with positive train Sharpe: 100%
- regimes (train+val, ann. return): down_highvol: 12.7%, down_lowvol: 51.9%, up_highvol: 33.5%, up_lowvol: 14.8%, warmup: 0.0%
- by year: 2016: 0.0%, 2017: 21.4%, 2018: 4.4%, 2019: 26.6%, 2020: 58.6%, 2021: 58.2%, 2022: 2.8%, 2023: 2.0%

### degen_trend_letf (degen_leverage)

_Hypothesis:_ Holding a 3x index ETF with up to ~2x margin only while the underlying trends up compounds faster than unlevered trend following.

- selected on train: `{"lev": "TQQQ", "sma": 150, "margin": 1.0}`
- train: CAGR 59.64%, Sharpe 1.20, max DD 48.14%, trades 13, time in market 82%, cost drag 0.03%/yr
- share of trials with positive train Sharpe: 100%
- regimes (train+val, ann. return): down_highvol: 33.9%, down_lowvol: 3.7%, up_highvol: 66.7%, up_lowvol: 55.3%, warmup: 0.0%
- by year: 2016: 3.3%, 2017: 118.4%, 2018: 3.5%, 2019: 65.5%, 2020: 133.5%, 2021: 83.0%, 2022: -33.2%, 2023: 98.2%

### degen_combo (degen_leverage)

_Hypothesis:_ Using idle time between mean-reversion trades for a margined TQQQ trend position raises growth over either sleeve alone.

- selected on train: `{"trend_margin": 1.0, "sma": 150, "threshold": "strict", "vol_filter": true}`
- train: CAGR 85.46%, Sharpe 1.29, max DD 53.76%, trades 1169, time in market 83%, cost drag 5.59%/yr
- share of trials with positive train Sharpe: 100%
- regimes (train+val, ann. return): down_highvol: 64.1%, down_lowvol: 183.3%, up_highvol: 99.6%, up_lowvol: 58.4%, warmup: 0.0%
- by year: 2016: 3.3%, 2017: 156.7%, 2018: -30.0%, 2019: 113.2%, 2020: 408.6%, 2021: 101.4%, 2022: -17.4%, 2023: 51.7%


![walk-forward equity](walkforward_equity.png)
