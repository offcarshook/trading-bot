# Research report - explore stage

> **Research only - paper trading, no orders placed.** Results are historical
> simulations with modelled costs. They are not predictions and not financial
> advice. A strategy surviving every check can still fail going forward.


- generated: `2026-10-21T17:45:12.657012+00:00` - commit `9ee48b4ae0`
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
| degen_meanrev_letf | 2.57% | 0.21% | 0.23 | 20.50% | -11.06% | 751 |
| degen_trend_letf | 15.23% | 1.18% | 0.56 | 39.57% | -20.47% | 13 |
| degen_combo | 10.22% | 0.81% | 0.44 | 40.03% | -29.63% | 1009 |

## Walk-forward out-of-sample (re-selected every 6 months on the trailing 3 years)

| strategy | CAGR | avg month (geo) | Sharpe | max DD | worst month | trades |
|---|---|---|---|---|---|---|
| _buy_hold_SPY_ | 15.62% | 1.21% | 0.79 | 33.84% | -12.47% | n/a |
| _buy_hold_QQQ_ | 22.50% | 1.70% | 0.92 | 35.00% | -13.47% | n/a |
| _60_40_SPY_IEF_ | 9.80% | 0.78% | 0.82 | 21.14% | -7.38% | n/a |
| degen_meanrev_letf | 33.03% | 2.40% | 1.31 | 25.31% | -13.37% | n/a |
| degen_trend_letf | 56.61% | 3.80% | 1.13 | 48.14% | -24.09% | n/a |
| degen_combo | 55.79% | 3.75% | 1.07 | 48.14% | -29.63% | n/a |

## Robustness checks

| strategy | trials | DSR (train) | PBO | neighbour ratio | null p | 2x-cost val Sharpe | WF choice stability | survives | failed checks |
|---|---|---|---|---|---|---|---|---|---|
| degen_meanrev_letf | 24 | 1.00 | 0.38 | 0.91 | 0.000 | 0.17 | 40% | no | validation_sharpe |
| degen_trend_letf | 18 | 0.99 | 0.67 | 0.86 | 0.020 | 0.56 | 100% | no | pbo, enough_trades |
| degen_combo | 12 | 0.99 | 0.21 | 0.86 | 0.030 | 0.38 | 50% | no | validation_sharpe |

## What it would take to hit 5-8% per month (leverage on walk-forward OOS returns)

| strategy | Kelly leverage | best monthly geo at any leverage | 5%/mo: leverage | 5%/mo: hist max DD | 5%/mo: P(DD>50%) 1y | 8%/mo: leverage | 8%/mo: hist max DD |
|---|---|---|---|---|---|---|---|
| degen_meanrev_letf | 5.18x | 6.39% | 2.75x | 57.84% | 20.00% | unreachable | unreachable |
| degen_trend_letf | 1.98x | 4.77% | unreachable | unreachable | - | unreachable | unreachable |
| degen_combo | 1.69x | 4.23% | unreachable | unreachable | - | unreachable | unreachable |

## Combined portfolio (top walk-forward (NOT survivors))

Members: degen_meanrev_letf, degen_trend_letf, degen_combo (causal inverse-volatility weights on walk-forward OOS returns).

| strategy | CAGR | avg month (geo) | Sharpe | max DD | worst month | trades |
|---|---|---|---|---|---|---|
| portfolio | 39.54% | 2.81% | 1.23 | 30.05% | -16.51% | n/a |

Adds value vs best single member (degen_meanrev_letf, WF Sharpe 1.31): **no**

## Data quality

64 series loaded. Flagged (big jumps / gaps / zero volume): ARKK {'first': '2016-01-04', 'last': '2026-10-20', 'days': 2707, 'missing_sessions_after_first': 8, 'max_abs_daily_return': 0.1628078817733989, 'days_abs_return_over_15pct': ['2020-03-16', '2025-04-09'], 'zero_volume_days': 0}, CURE {'first': '2016-01-04', 'last': '2026-10-20', 'days': 2715, 'missing_sessions_after_first': 0, 'max_abs_daily_return': 0.29693140794223827, 'days_abs_return_over_15pct': ['2020-03-04', '2020-03-09', '2020-03-12', '2020-03-13', '2020-03-16', '2020-03-17', '2020-03-23', '2020-03-24', '2020-03-26', '2020-04-06'], 'zero_volume_days': 0}, DPST {'first': '2016-01-04', 'last': '2026-10-20', 'days': 2647, 'missing_sessions_after_first': 68, 'max_abs_daily_return': 0.4592458988233272, 'days_abs_return_over_15pct': ['2016-06-27', '2016-11-09', '2017-03-21', '2018-12-04', '2020-03-05', '2020-03-09', '2020-03-10', '2020-03-11', '2020-03-12', '2020-03-13'], 'zero_volume_days': 0}, DRN {'first': '2016-01-04', 'last': '2026-10-20', 'days': 2715, 'missing_sessions_after_first': 0, 'max_abs_daily_return': 0.3944362017804154, 'days_abs_return_over_15pct': ['2020-02-27', '2020-03-09', '2020-03-11', '2020-03-12', '2020-03-13', '2020-03-16', '2020-03-18', '2020-03-23', '2020-03-24', '2020-03-25'], 'zero_volume_days': 0}, ERX {'first': '2016-01-04', 'last': '2026-10-20', 'days': 2715, 'missing_sessions_after_first': 0, 'max_abs_daily_return': 0.5991253644314869, 'days_abs_return_over_15pct': ['2016-11-30', '2018-12-26', '2020-02-27', '2020-03-06', '2020-03-09', '2020-03-11', '2020-03-12', '2020-03-13', '2020-03-16', '2020-03-18'], 'zero_volume_days': 0}, EWZ {'first': '2016-01-04', 'last': '2026-10-20', 'days': 2715, 'missing_sessions_after_first': 0, 'max_abs_daily_return': 0.22813487881981032, 'days_abs_return_over_15pct': ['2017-05-18', '2020-03-12', '2020-03-13', '2020-03-16', '2020-03-18'], 'zero_volume_days': 0}, FAS {'first': '2016-01-04', 'last': '2026-10-20', 'days': 2715, 'missing_sessions_after_first': 0, 'max_abs_daily_return': 0.38961038961038963, 'days_abs_return_over_15pct': ['2020-03-09', '2020-03-10', '2020-03-11', '2020-03-12', '2020-03-13', '2020-03-16', '2020-03-18', '2020-03-24', '2020-03-26', '2020-04-01'], 'zero_volume_days': 0}, FXI {'first': '2016-01-04', 'last': '2026-10-20', 'days': 2715, 'missing_sessions_after_first': 0, 'max_abs_daily_return': 0.21151490404246642, 'days_abs_return_over_15pct': ['2022-03-16'], 'zero_volume_days': 0}, GDX {'first': '2016-01-04', 'last': '2026-10-20', 'days': 2715, 'missing_sessions_after_first': 0, 'max_abs_daily_return': 0.18030690537084404, 'days_abs_return_over_15pct': ['2020-03-16', '2020-03-17', '2020-03-18'], 'zero_volume_days': 0}, ITB {'first': '2016-01-04', 'last': '2026-10-20', 'days': 2715, 'missing_sessions_after_first': 0, 'max_abs_daily_return': 0.20111214087117701, 'days_abs_return_over_15pct': ['2020-03-16', '2020-03-24'], 'zero_volume_days': 0}, KWEB {'first': '2016-01-04', 'last': '2026-10-20', 'days': 2715, 'missing_sessions_after_first': 0, 'max_abs_daily_return': 0.39778449144008077, 'days_abs_return_over_15pct': ['2022-03-16'], 'zero_volume_days': 0}, LABU {'first': '2016-01-04', 'last': '2026-10-20', 'days': 2715, 'missing_sessions_after_first': 0, 'max_abs_daily_return': 0.33374655936797437, 'days_abs_return_over_15pct': ['2016-01-11', '2016-01-13', '2016-02-08', '2016-03-08', '2016-03-15', '2016-03-23', '2016-04-06', '2016-11-09', '2018-01-22', '2018-10-16'], 'zero_volume_days': 0}, MIDU {'first': '2016-01-04', 'last': '2026-10-20', 'days': 2715, 'missing_sessions_after_first': 0, 'max_abs_daily_return': 0.4354033662217064, 'days_abs_return_over_15pct': ['2020-03-09', '2020-03-11', '2020-03-12', '2020-03-13', '2020-03-16', '2020-03-17', '2020-03-18', '2020-03-24', '2020-03-26', '2020-04-01'], 'zero_volume_days': 0}, NUGT {'first': '2016-01-04', 'last': '2026-10-20', 'days': 2715, 'missing_sessions_after_first': 0, 'max_abs_daily_return': 0.5581395348837208, 'days_abs_return_over_15pct': ['2016-02-03', '2016-02-04', '2016-02-05', '2016-02-11', '2016-02-16', '2016-02-18', '2016-03-16', '2016-03-23', '2016-03-29', '2016-04-11'], 'zero_volume_days': 0}, QLD {'first': '2016-01-04', 'last': '2026-10-20', 'days': 2715, 'missing_sessions_after_first': 0, 'max_abs_daily_return': 0.24327485380116964, 'days_abs_return_over_15pct': ['2020-03-12', '2020-03-13', '2020-03-16', '2020-03-24', '2025-04-09'], 'zero_volume_days': 0}, RETL {'first': '2016-01-04', 'last': '2026-10-20', 'days': 2715, 'missing_sessions_after_first': 0, 'max_abs_daily_return': 0.3637873754152824, 'days_abs_return_over_15pct': ['2018-12-26', '2020-03-09', '2020-03-11', '2020-03-12', '2020-03-13', '2020-03-16', '2020-03-18', '2020-03-20', '2020-03-24', '2020-04-01'], 'zero_volume_days': 0}, SLV {'first': '2016-01-04', 'last': '2026-10-20', 'days': 2715, 'missing_sessions_after_first': 0, 'max_abs_daily_return': 0.2863769762378112, 'days_abs_return_over_15pct': ['2026-01-30', '2026-02-05'], 'zero_volume_days': 0}, SMH {'first': '2016-01-04', 'last': '2026-10-20', 'days': 2715, 'missing_sessions_after_first': 0, 'max_abs_daily_return': 0.17196209587513933, 'days_abs_return_over_15pct': ['2020-03-16', '2025-04-09'], 'zero_volume_days': 0}, SOXL {'first': '2016-01-04', 'last': '2026-10-20', 'days': 2715, 'missing_sessions_after_first': 0, 'max_abs_daily_return': 0.5598342676090666, 'days_abs_return_over_15pct': ['2016-06-24', '2018-10-24', '2018-12-26', '2019-01-03', '2019-01-24', '2020-03-04', '2020-03-09', '2020-03-10', '2020-03-11', '2020-03-12'], 'zero_volume_days': 0}, SPXL {'first': '2016-01-04', 'last': '2026-10-20', 'days': 2715, 'missing_sessions_after_first': 0, 'max_abs_daily_return': 0.34311926605504595, 'days_abs_return_over_15pct': ['2020-03-09', '2020-03-10', '2020-03-12', '2020-03-13', '2020-03-16', '2020-03-17', '2020-03-18', '2020-03-24', '2020-03-26', '2020-04-06'], 'zero_volume_days': 0}, SSO {'first': '2016-01-04', 'last': '2026-10-20', 'days': 2715, 'missing_sessions_after_first': 0, 'max_abs_daily_return': 0.23401139137510163, 'days_abs_return_over_15pct': ['2020-03-09', '2020-03-12', '2020-03-13', '2020-03-16', '2020-03-24', '2025-04-09'], 'zero_volume_days': 0}, TAN {'first': '2016-01-04', 'last': '2026-10-20', 'days': 2715, 'missing_sessions_after_first': 0, 'max_abs_daily_return': 0.16886930983847281, 'days_abs_return_over_15pct': ['2020-03-16'], 'zero_volume_days': 0}, TECL {'first': '2016-01-04', 'last': '2026-10-20', 'days': 2715, 'missing_sessions_after_first': 0, 'max_abs_daily_return': 0.3955759839126687, 'days_abs_return_over_15pct': ['2018-12-26', '2020-02-27', '2020-03-02', '2020-03-09', '2020-03-10', '2020-03-12', '2020-03-13', '2020-03-16', '2020-03-24', '2020-03-26'], 'zero_volume_days': 0}, TMF {'first': '2016-01-04', 'last': '2026-10-20', 'days': 2715, 'missing_sessions_after_first': 0, 'max_abs_daily_return': 0.20867023497703352, 'days_abs_return_over_15pct': ['2020-03-06', '2020-03-10', '2020-03-16', '2020-03-17', '2020-03-18', '2020-03-20'], 'zero_volume_days': 0}, TNA {'first': '2016-01-04', 'last': '2026-10-20', 'days': 2715, 'missing_sessions_after_first': 0, 'max_abs_daily_return': 0.3752252252252253, 'days_abs_return_over_15pct': ['2020-03-09', '2020-03-11', '2020-03-12', '2020-03-13', '2020-03-16', '2020-03-18', '2020-03-24', '2020-03-26', '2020-04-01', '2020-04-06'], 'zero_volume_days': 0}, TQQQ {'first': '2016-01-04', 'last': '2026-10-20', 'days': 2715, 'missing_sessions_after_first': 0, 'max_abs_daily_return': 0.3525441329179646, 'days_abs_return_over_15pct': ['2018-12-26', '2020-02-27', '2020-03-09', '2020-03-10', '2020-03-12', '2020-03-13', '2020-03-16', '2020-03-17', '2020-03-24', '2020-03-26'], 'zero_volume_days': 0}, UDOW {'first': '2016-01-04', 'last': '2026-10-20', 'days': 2715, 'missing_sessions_after_first': 0, 'max_abs_daily_return': 0.3567131327953045, 'days_abs_return_over_15pct': ['2020-03-09', '2020-03-11', '2020-03-12', '2020-03-13', '2020-03-16', '2020-03-18', '2020-03-24', '2020-03-26', '2020-04-06', '2020-06-11'], 'zero_volume_days': 0}, UPRO {'first': '2016-01-04', 'last': '2026-10-20', 'days': 2715, 'missing_sessions_after_first': 0, 'max_abs_daily_return': 0.3502304147465438, 'days_abs_return_over_15pct': ['2020-03-09', '2020-03-10', '2020-03-12', '2020-03-13', '2020-03-16', '2020-03-17', '2020-03-18', '2020-03-24', '2020-03-26', '2020-04-06'], 'zero_volume_days': 0}, USO {'first': '2016-01-04', 'last': '2026-10-20', 'days': 2715, 'missing_sessions_after_first': 0, 'max_abs_daily_return': 0.25458715596330284, 'days_abs_return_over_15pct': ['2020-03-09', '2020-03-18', '2020-04-02', '2020-04-03', '2020-04-21', '2020-04-27'], 'zero_volume_days': 0}, VNQ {'first': '2016-01-04', 'last': '2026-10-20', 'days': 2715, 'missing_sessions_after_first': 0, 'max_abs_daily_return': 0.1765559496936473, 'days_abs_return_over_15pct': ['2020-03-16'], 'zero_volume_days': 0}, XLE {'first': '2016-01-04', 'last': '2026-10-20', 'days': 2715, 'missing_sessions_after_first': 0, 'max_abs_daily_return': 0.20160791589363025, 'days_abs_return_over_15pct': ['2020-03-09', '2020-03-24'], 'zero_volume_days': 0}, XLF {'first': '2016-01-04', 'last': '2026-10-20', 'days': 2715, 'missing_sessions_after_first': 0, 'max_abs_daily_return': 0.17902813299232734, 'days_abs_return_over_15pct': ['2016-09-19'], 'zero_volume_days': 0}, XME {'first': '2016-01-04', 'last': '2026-10-20', 'days': 2715, 'missing_sessions_after_first': 0, 'max_abs_daily_return': 0.15149625935162092, 'days_abs_return_over_15pct': ['2020-03-18'], 'zero_volume_days': 0}, YINN {'first': '2016-01-04', 'last': '2026-10-20', 'days': 2715, 'missing_sessions_after_first': 0, 'max_abs_daily_return': 0.6379525593008739, 'days_abs_return_over_15pct': ['2016-06-24', '2018-02-07', '2020-03-12', '2020-03-13', '2020-03-16', '2020-03-18', '2020-03-24', '2020-03-27', '2020-07-06', '2021-07-26'], 'zero_volume_days': 0}

## Per-strategy detail

### degen_meanrev_letf (degen_leverage)

_Hypothesis:_ The mean-reversion edge on index ETFs survives being expressed through 3x leveraged ETFs with up to ~2x margin (~6x underlying).

- selected on train: `{"margin": 1.5, "alloc": "equal_slots", "threshold": "strict", "vol_filter": true}`
- train: CAGR 39.25%, Sharpe 1.73, max DD 17.54%, trades 751, time in market 25%, cost drag 1.23%/yr
- share of trials with positive train Sharpe: 100%
- regimes (train+val, ann. return): down_highvol: 19.2%, down_lowvol: 73.2%, up_highvol: 48.2%, up_lowvol: 21.2%, warmup: 0.0%
- by year: 2016: 0.0%, 2017: 29.9%, 2018: 4.9%, 2019: 41.8%, 2020: 97.5%, 2021: 90.4%, 2022: 4.0%, 2023: 1.1%

### degen_trend_letf (degen_leverage)

_Hypothesis:_ Holding a 3x index ETF with up to ~2x margin only while the underlying trends up compounds faster than unlevered trend following.

- selected on train: `{"lev": "TQQQ", "sma": 150, "margin": 1.0}`
- train: CAGR 59.71%, Sharpe 1.20, max DD 48.14%, trades 13, time in market 82%, cost drag 0.03%/yr
- share of trials with positive train Sharpe: 100%
- regimes (train+val, ann. return): down_highvol: 33.9%, down_lowvol: 3.7%, up_highvol: 66.7%, up_lowvol: 55.3%, warmup: 0.0%
- by year: 2016: 3.3%, 2017: 118.4%, 2018: 3.5%, 2019: 65.5%, 2020: 133.5%, 2021: 83.0%, 2022: -33.2%, 2023: 98.2%

### degen_combo (degen_leverage)

_Hypothesis:_ Using idle time between mean-reversion trades for a margined TQQQ trend position raises growth over either sleeve alone.

- selected on train: `{"trend_margin": 1.0, "sma": 150, "threshold": "strict", "vol_filter": true}`
- train: CAGR 55.08%, Sharpe 1.11, max DD 48.25%, trades 1009, time in market 83%, cost drag 3.31%/yr
- share of trials with positive train Sharpe: 100%
- regimes (train+val, ann. return): down_highvol: 50.9%, down_lowvol: 98.8%, up_highvol: 59.6%, up_lowvol: 45.9%, warmup: 0.0%
- by year: 2016: 3.3%, 2017: 115.4%, 2018: -30.4%, 2019: 88.6%, 2020: 187.1%, 2021: 65.0%, 2022: -24.0%, 2023: 59.6%


![walk-forward equity](walkforward_equity.png)
