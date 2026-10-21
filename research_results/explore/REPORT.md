# Research report - explore stage

> **Research only - paper trading, no orders placed.** Results are historical
> simulations with modelled costs. They are not predictions and not financial
> advice. A strategy surviving every check can still fail going forward.


- generated: `2026-10-21T17:52:22.198390+00:00` - commit `a603f2dcea`
- train **2016-01-01 -> 2021-12-31** | validation **2022-01-01 -> 2023-12-31** | test **2024-01-01 -> 2026-10-20 (LOCKED, not loaded)**
- total parameter trials run: **132** (all counted in the multiple-testing corrections)
- data feed: `sip`; costs: half-spread per ETF + 1.0bp open / 3.0bp stop slippage, margin 7.0%/yr

## Survivors (passed every pre-registered check)

**None.** No strategy passed every check.

## Validation period (out-of-sample for parameter selection)

| strategy | CAGR | avg month (geo) | Sharpe | max DD | worst month | trades |
|---|---|---|---|---|---|---|
| _buy_hold_SPY_ | 1.63% | 0.13% | 0.18 | 24.51% | -9.23% | n/a |
| _buy_hold_QQQ_ | 2.32% | 0.19% | 0.22 | 34.72% | -13.47% | n/a |
| _60_40_SPY_IEF_ | -1.31% | -0.11% | -0.04 | 20.82% | -7.38% | n/a |
| letf_momentum_rotation | -20.58% | -1.89% | -0.37 | 54.37% | -29.92% | 633 |
| broad_etf_momentum | -1.22% | -0.10% | 0.04 | 30.80% | -10.02% | 1101 |

## Walk-forward out-of-sample (re-selected every 6 months on the trailing 3 years)

| strategy | CAGR | avg month (geo) | Sharpe | max DD | worst month | trades |
|---|---|---|---|---|---|---|
| _buy_hold_SPY_ | 15.62% | 1.21% | 0.79 | 33.84% | -12.47% | n/a |
| _buy_hold_QQQ_ | 22.50% | 1.70% | 0.92 | 35.00% | -13.47% | n/a |
| _60_40_SPY_IEF_ | 9.80% | 0.78% | 0.82 | 21.14% | -7.38% | n/a |
| letf_momentum_rotation | -2.58% | -0.22% | 0.33 | 83.33% | -43.19% | n/a |
| broad_etf_momentum | 12.22% | 0.96% | 0.59 | 31.33% | -11.52% | n/a |

## Robustness checks

| strategy | trials | DSR (train) | PBO | neighbour ratio | null p | 2x-cost val Sharpe | WF choice stability | survives | failed checks |
|---|---|---|---|---|---|---|---|---|---|
| letf_momentum_rotation | 108 | 0.93 | 0.76 | 0.94 | 0.300 | -0.39 | 20% | no | validation_sharpe, validation_cagr, walkforward_oos_sharpe, pbo, null_test, cost_stress_2x |
| broad_etf_momentum | 24 | 0.90 | 0.13 | 0.78 | 0.430 | -0.00 | 50% | no | validation_sharpe, validation_cagr, dsr_train, null_test, cost_stress_2x |

## What it would take to hit 5-8% per month (leverage on walk-forward OOS returns)

| strategy | Kelly leverage | best monthly geo at any leverage | 5%/mo: leverage | 5%/mo: hist max DD | 5%/mo: P(DD>50%) 1y | 8%/mo: leverage | 8%/mo: hist max DD |
|---|---|---|---|---|---|---|---|
| letf_momentum_rotation | 0.33x | 0.44% | unreachable | unreachable | - | unreachable | unreachable |
| broad_etf_momentum | 1.26x | 0.98% | unreachable | unreachable | - | unreachable | unreachable |

## Combined portfolio (top walk-forward (NOT survivors))

Members: broad_etf_momentum, letf_momentum_rotation (causal inverse-volatility weights on walk-forward OOS returns).

| strategy | CAGR | avg month (geo) | Sharpe | max DD | worst month | trades |
|---|---|---|---|---|---|---|
| portfolio | 10.58% | 0.84% | 0.47 | 46.51% | -19.30% | n/a |

Adds value vs best single member (broad_etf_momentum, WF Sharpe 0.59): **no**

## Data quality

64 series loaded. Flagged (big jumps / gaps / zero volume): ARKK {'first': '2016-01-04', 'last': '2026-10-20', 'days': 2707, 'missing_sessions_after_first': 8, 'max_abs_daily_return': 0.1628078817733989, 'days_abs_return_over_15pct': ['2020-03-16', '2025-04-09'], 'zero_volume_days': 0}, CURE {'first': '2016-01-04', 'last': '2026-10-20', 'days': 2715, 'missing_sessions_after_first': 0, 'max_abs_daily_return': 0.29693140794223827, 'days_abs_return_over_15pct': ['2020-03-04', '2020-03-09', '2020-03-12', '2020-03-13', '2020-03-16', '2020-03-17', '2020-03-23', '2020-03-24', '2020-03-26', '2020-04-06'], 'zero_volume_days': 0}, DPST {'first': '2016-01-04', 'last': '2026-10-20', 'days': 2647, 'missing_sessions_after_first': 68, 'max_abs_daily_return': 0.4592458988233272, 'days_abs_return_over_15pct': ['2016-06-27', '2016-11-09', '2017-03-21', '2018-12-04', '2020-03-05', '2020-03-09', '2020-03-10', '2020-03-11', '2020-03-12', '2020-03-13'], 'zero_volume_days': 0}, DRN {'first': '2016-01-04', 'last': '2026-10-20', 'days': 2715, 'missing_sessions_after_first': 0, 'max_abs_daily_return': 0.3944362017804154, 'days_abs_return_over_15pct': ['2020-02-27', '2020-03-09', '2020-03-11', '2020-03-12', '2020-03-13', '2020-03-16', '2020-03-18', '2020-03-23', '2020-03-24', '2020-03-25'], 'zero_volume_days': 0}, ERX {'first': '2016-01-04', 'last': '2026-10-20', 'days': 2715, 'missing_sessions_after_first': 0, 'max_abs_daily_return': 0.5991253644314869, 'days_abs_return_over_15pct': ['2016-11-30', '2018-12-26', '2020-02-27', '2020-03-06', '2020-03-09', '2020-03-11', '2020-03-12', '2020-03-13', '2020-03-16', '2020-03-18'], 'zero_volume_days': 0}, EWZ {'first': '2016-01-04', 'last': '2026-10-20', 'days': 2715, 'missing_sessions_after_first': 0, 'max_abs_daily_return': 0.22813487881981032, 'days_abs_return_over_15pct': ['2017-05-18', '2020-03-12', '2020-03-13', '2020-03-16', '2020-03-18'], 'zero_volume_days': 0}, FAS {'first': '2016-01-04', 'last': '2026-10-20', 'days': 2715, 'missing_sessions_after_first': 0, 'max_abs_daily_return': 0.38961038961038963, 'days_abs_return_over_15pct': ['2020-03-09', '2020-03-10', '2020-03-11', '2020-03-12', '2020-03-13', '2020-03-16', '2020-03-18', '2020-03-24', '2020-03-26', '2020-04-01'], 'zero_volume_days': 0}, FXI {'first': '2016-01-04', 'last': '2026-10-20', 'days': 2715, 'missing_sessions_after_first': 0, 'max_abs_daily_return': 0.21151490404246642, 'days_abs_return_over_15pct': ['2022-03-16'], 'zero_volume_days': 0}, GDX {'first': '2016-01-04', 'last': '2026-10-20', 'days': 2715, 'missing_sessions_after_first': 0, 'max_abs_daily_return': 0.18030690537084404, 'days_abs_return_over_15pct': ['2020-03-16', '2020-03-17', '2020-03-18'], 'zero_volume_days': 0}, ITB {'first': '2016-01-04', 'last': '2026-10-20', 'days': 2715, 'missing_sessions_after_first': 0, 'max_abs_daily_return': 0.20111214087117701, 'days_abs_return_over_15pct': ['2020-03-16', '2020-03-24'], 'zero_volume_days': 0}, KWEB {'first': '2016-01-04', 'last': '2026-10-20', 'days': 2715, 'missing_sessions_after_first': 0, 'max_abs_daily_return': 0.39778449144008077, 'days_abs_return_over_15pct': ['2022-03-16'], 'zero_volume_days': 0}, LABU {'first': '2016-01-04', 'last': '2026-10-20', 'days': 2715, 'missing_sessions_after_first': 0, 'max_abs_daily_return': 0.33374655936797437, 'days_abs_return_over_15pct': ['2016-01-11', '2016-01-13', '2016-02-08', '2016-03-08', '2016-03-15', '2016-03-23', '2016-04-06', '2016-11-09', '2018-01-22', '2018-10-16'], 'zero_volume_days': 0}, MIDU {'first': '2016-01-04', 'last': '2026-10-20', 'days': 2715, 'missing_sessions_after_first': 0, 'max_abs_daily_return': 0.4354033662217064, 'days_abs_return_over_15pct': ['2020-03-09', '2020-03-11', '2020-03-12', '2020-03-13', '2020-03-16', '2020-03-17', '2020-03-18', '2020-03-24', '2020-03-26', '2020-04-01'], 'zero_volume_days': 0}, NUGT {'first': '2016-01-04', 'last': '2026-10-20', 'days': 2715, 'missing_sessions_after_first': 0, 'max_abs_daily_return': 0.5581395348837208, 'days_abs_return_over_15pct': ['2016-02-03', '2016-02-04', '2016-02-05', '2016-02-11', '2016-02-16', '2016-02-18', '2016-03-16', '2016-03-23', '2016-03-29', '2016-04-11'], 'zero_volume_days': 0}, QLD {'first': '2016-01-04', 'last': '2026-10-20', 'days': 2715, 'missing_sessions_after_first': 0, 'max_abs_daily_return': 0.24327485380116964, 'days_abs_return_over_15pct': ['2020-03-12', '2020-03-13', '2020-03-16', '2020-03-24', '2025-04-09'], 'zero_volume_days': 0}, RETL {'first': '2016-01-04', 'last': '2026-10-20', 'days': 2715, 'missing_sessions_after_first': 0, 'max_abs_daily_return': 0.3637873754152824, 'days_abs_return_over_15pct': ['2018-12-26', '2020-03-09', '2020-03-11', '2020-03-12', '2020-03-13', '2020-03-16', '2020-03-18', '2020-03-20', '2020-03-24', '2020-04-01'], 'zero_volume_days': 0}, SLV {'first': '2016-01-04', 'last': '2026-10-20', 'days': 2715, 'missing_sessions_after_first': 0, 'max_abs_daily_return': 0.2863769762378112, 'days_abs_return_over_15pct': ['2026-01-30', '2026-02-05'], 'zero_volume_days': 0}, SMH {'first': '2016-01-04', 'last': '2026-10-20', 'days': 2715, 'missing_sessions_after_first': 0, 'max_abs_daily_return': 0.17196209587513933, 'days_abs_return_over_15pct': ['2020-03-16', '2025-04-09'], 'zero_volume_days': 0}, SOXL {'first': '2016-01-04', 'last': '2026-10-20', 'days': 2715, 'missing_sessions_after_first': 0, 'max_abs_daily_return': 0.5598342676090666, 'days_abs_return_over_15pct': ['2016-06-24', '2018-10-24', '2018-12-26', '2019-01-03', '2019-01-24', '2020-03-04', '2020-03-09', '2020-03-10', '2020-03-11', '2020-03-12'], 'zero_volume_days': 0}, SPXL {'first': '2016-01-04', 'last': '2026-10-20', 'days': 2715, 'missing_sessions_after_first': 0, 'max_abs_daily_return': 0.34311926605504595, 'days_abs_return_over_15pct': ['2020-03-09', '2020-03-10', '2020-03-12', '2020-03-13', '2020-03-16', '2020-03-17', '2020-03-18', '2020-03-24', '2020-03-26', '2020-04-06'], 'zero_volume_days': 0}, SSO {'first': '2016-01-04', 'last': '2026-10-20', 'days': 2715, 'missing_sessions_after_first': 0, 'max_abs_daily_return': 0.23401139137510163, 'days_abs_return_over_15pct': ['2020-03-09', '2020-03-12', '2020-03-13', '2020-03-16', '2020-03-24', '2025-04-09'], 'zero_volume_days': 0}, TAN {'first': '2016-01-04', 'last': '2026-10-20', 'days': 2715, 'missing_sessions_after_first': 0, 'max_abs_daily_return': 0.16886930983847281, 'days_abs_return_over_15pct': ['2020-03-16'], 'zero_volume_days': 0}, TECL {'first': '2016-01-04', 'last': '2026-10-20', 'days': 2715, 'missing_sessions_after_first': 0, 'max_abs_daily_return': 0.3955759839126687, 'days_abs_return_over_15pct': ['2018-12-26', '2020-02-27', '2020-03-02', '2020-03-09', '2020-03-10', '2020-03-12', '2020-03-13', '2020-03-16', '2020-03-24', '2020-03-26'], 'zero_volume_days': 0}, TMF {'first': '2016-01-04', 'last': '2026-10-20', 'days': 2715, 'missing_sessions_after_first': 0, 'max_abs_daily_return': 0.20867023497703352, 'days_abs_return_over_15pct': ['2020-03-06', '2020-03-10', '2020-03-16', '2020-03-17', '2020-03-18', '2020-03-20'], 'zero_volume_days': 0}, TNA {'first': '2016-01-04', 'last': '2026-10-20', 'days': 2715, 'missing_sessions_after_first': 0, 'max_abs_daily_return': 0.3752252252252253, 'days_abs_return_over_15pct': ['2020-03-09', '2020-03-11', '2020-03-12', '2020-03-13', '2020-03-16', '2020-03-18', '2020-03-24', '2020-03-26', '2020-04-01', '2020-04-06'], 'zero_volume_days': 0}, TQQQ {'first': '2016-01-04', 'last': '2026-10-20', 'days': 2715, 'missing_sessions_after_first': 0, 'max_abs_daily_return': 0.3525441329179646, 'days_abs_return_over_15pct': ['2018-12-26', '2020-02-27', '2020-03-09', '2020-03-10', '2020-03-12', '2020-03-13', '2020-03-16', '2020-03-17', '2020-03-24', '2020-03-26'], 'zero_volume_days': 0}, UDOW {'first': '2016-01-04', 'last': '2026-10-20', 'days': 2715, 'missing_sessions_after_first': 0, 'max_abs_daily_return': 0.3567131327953045, 'days_abs_return_over_15pct': ['2020-03-09', '2020-03-11', '2020-03-12', '2020-03-13', '2020-03-16', '2020-03-18', '2020-03-24', '2020-03-26', '2020-04-06', '2020-06-11'], 'zero_volume_days': 0}, UPRO {'first': '2016-01-04', 'last': '2026-10-20', 'days': 2715, 'missing_sessions_after_first': 0, 'max_abs_daily_return': 0.3502304147465438, 'days_abs_return_over_15pct': ['2020-03-09', '2020-03-10', '2020-03-12', '2020-03-13', '2020-03-16', '2020-03-17', '2020-03-18', '2020-03-24', '2020-03-26', '2020-04-06'], 'zero_volume_days': 0}, USO {'first': '2016-01-04', 'last': '2026-10-20', 'days': 2715, 'missing_sessions_after_first': 0, 'max_abs_daily_return': 0.25458715596330284, 'days_abs_return_over_15pct': ['2020-03-09', '2020-03-18', '2020-04-02', '2020-04-03', '2020-04-21', '2020-04-27'], 'zero_volume_days': 0}, VNQ {'first': '2016-01-04', 'last': '2026-10-20', 'days': 2715, 'missing_sessions_after_first': 0, 'max_abs_daily_return': 0.1765559496936473, 'days_abs_return_over_15pct': ['2020-03-16'], 'zero_volume_days': 0}, XLE {'first': '2016-01-04', 'last': '2026-10-20', 'days': 2715, 'missing_sessions_after_first': 0, 'max_abs_daily_return': 0.20160791589363025, 'days_abs_return_over_15pct': ['2020-03-09', '2020-03-24'], 'zero_volume_days': 0}, XLF {'first': '2016-01-04', 'last': '2026-10-20', 'days': 2715, 'missing_sessions_after_first': 0, 'max_abs_daily_return': 0.17902813299232734, 'days_abs_return_over_15pct': ['2016-09-19'], 'zero_volume_days': 0}, XME {'first': '2016-01-04', 'last': '2026-10-20', 'days': 2715, 'missing_sessions_after_first': 0, 'max_abs_daily_return': 0.15149625935162092, 'days_abs_return_over_15pct': ['2020-03-18'], 'zero_volume_days': 0}, YINN {'first': '2016-01-04', 'last': '2026-10-20', 'days': 2715, 'missing_sessions_after_first': 0, 'max_abs_daily_return': 0.6379525593008739, 'days_abs_return_over_15pct': ['2016-06-24', '2018-02-07', '2020-03-12', '2020-03-13', '2020-03-16', '2020-03-18', '2020-03-24', '2020-03-27', '2020-07-06', '2021-07-26'], 'zero_volume_days': 0}

## Per-strategy detail

### letf_momentum_rotation (leveraged_momentum)

_Hypothesis:_ Holding the top-N (1-3) of 20 daily-reset 2x/3x leveraged ETFs by trailing 1/3/6-month (optionally last-week-skipped or volatility-adjusted) momentum, at most one fund per underlying index, equal weight with requested gross = margin capped to the FINRA leveraged-ETF maintenance limit (3x book <= ~1.29x), rebalanced on the first session of each week and moved to cash/IEF/TMF when SPY is below its 200-day SMA, earns a positive after-cost Sharpe that a random re-timing of the same holdings does not. SURVIVORSHIP CAVEAT: only leveraged ETFs that still exist today are in the universe (many closed after crashes; NUGT/ERX cut leverage in 2020), so the backtest is biased UPWARD.

- selected on train: `{"score": "blend_skip1w", "top_n": 3, "regime": "IEF", "margin": 1.0, "rebalance": "W", "band": 0.02}`
- train: CAGR 37.39%, Sharpe 0.89, max DD 46.07%, trades 633, time in market 87%, cost drag 1.17%/yr
- share of trials with positive train Sharpe: 100%
- regimes (train+val, ann. return): down_highvol: 15.6%, down_lowvol: 51.0%, up_highvol: 50.6%, up_lowvol: 26.1%, warmup: 0.0%
- by year: 2016: 40.2%, 2017: 35.6%, 2018: -5.6%, 2019: 27.8%, 2020: 65.3%, 2021: 76.7%, 2022: -26.5%, 2023: -13.9%

### broad_etf_momentum (cross_sectional_momentum)

_Hypothesis:_ Holding the top-N (3/5) of 39 unlevered ETFs (core asset classes, SPDR sectors and the extended thematic/country list) by blended 1/3/6(/12)-month return, each slot kept only if it beats SHY's return over the same window (else parked in SHY out of unborrowed equity only), with requested risky gross = margin capped to Reg-T buying power (<= ~1.94x), rebalanced on the first session of each week or month, earns a positive after-cost Sharpe that a random re-timing does not. SURVIVORSHIP CAVEAT: the extended list was picked with hindsight of which ETFs are popular and still trade today, so the backtest is biased UPWARD.

- selected on train: `{"score": "blend_1_3_6", "top_n": 5, "margin": 1.0, "rebalance": "W", "band": 0.01}`
- train: CAGR 13.34%, Sharpe 0.77, max DD 26.51%, trades 1101, time in market 83%, cost drag 0.76%/yr
- share of trials with positive train Sharpe: 100%
- regimes (train+val, ann. return): down_highvol: 0.4%, down_lowvol: 41.2%, up_highvol: 29.1%, up_lowvol: 4.9%, warmup: 0.0%
- by year: 2016: 0.0%, 2017: 28.7%, 2018: -9.8%, 2019: 10.6%, 2020: 59.9%, 2021: 3.1%, 2022: -22.8%, 2023: 26.4%


![walk-forward equity](walkforward_equity.png)
