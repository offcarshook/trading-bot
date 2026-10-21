# Research summary - can any strategy reach 5-8% per month?

> Paper research only. These are historical simulations with modelled costs.
> They are not predictions and not financial advice.

## Verdict (short)

**The evidence does not support the 5-8% per month target.**

- No strategy passed every pre-registered survival check (11 strategies, 476 parameter trials).
- On the locked 2024-2026 test period, **no frozen candidate reaches 5% per month at any leverage up to 20x.**
  Volatility drag and financing costs dominate first.
- Only one route reached 5% per month at all: mean reversion levered **10x** in the 2019-2023 walk-forward.
  - Historical max drawdown at that leverage: **42%**.
  - Bootstrap probability of a >30% drawdown within a year: 53%.
  - It needs about 10x gross exposure overnight. Alpaca's Reg-T limit is about 2x overnight, so it **cannot be executed** at this broker.
  - On the test period even that route topped out around **2.9% per month**.
- On the test period, nothing beat **buy-and-hold QQQ** on return. Only the leveraged trend edged past SPY: 21.7% vs 20.2% CAGR, with about 1.6x the drawdown and a lower Sharpe (0.75 vs 1.30). Several strategies beat both clearly on drawdown.

## Method

| item | setting |
|---|---|
| Data | Alpaca **SIP** (consolidated), split and dividend adjusted. RTH daily bars are built from 30-minute bars; intraday strategies use 5-minute bars. Coverage is 2016-01-04 to 2026-10-20, 33 series, and data-quality checks are in the report. |
| Splits | Train 2016-2021, validation 2022-2023, test 2024-01-01 to 2026-10-20. The test period was **locked**: it was cut from the data during exploration and **opened exactly once** (`test_access_log.json`, access #1). |
| Selection | Parameters were picked on **train Sharpe only**. The grids were pre-registered and every trial counts toward the multiple-testing corrections. |
| Costs | Per-ETF half-spread, plus 1 bp slippage at the open and 3 bp on stops, the SEC fee, 7%/yr margin interest on borrowed exposure, and short borrow costs. Every strategy was also re-run at **2x costs**. |
| Execution | Daily decisions are made at the close and **filled at the next open**, including the overnight gap. Intraday entries use only completed bars, and the stop wins whenever a bar hits both stop and target. |
| Look-ahead guard | A generic test runs every strategy on truncated data and on full data, and past decisions must be identical. Each module was also reviewed by a separate agent looking for look-ahead. |
| Survival checks | Validation Sharpe ≥ 0.5 and CAGR > 0; walk-forward OOS Sharpe ≥ 0.5; Deflated Sharpe ≥ 0.90; PBO ≤ 0.5; null-test p ≤ 0.10; 2x-cost Sharpe ≥ 0; parameter-neighbourhood ratio ≥ 0.5; ≥ 30 trades. |

## Walk-forward out-of-sample, 2019-2023 (parameters re-selected every 6 months on the trailing 3 years)

| strategy | avg month (geo) | CAGR | Sharpe | max DD | worst month | outcome |
|---|---|---|---|---|---|---|
| *buy & hold QQQ* | 1.70% | 22.5% | 0.92 | 35.0% | -13.5% | benchmark |
| *buy & hold SPY* | 1.21% | 15.6% | 0.79 | 33.8% | -12.5% | benchmark |
| leveraged_trend (QLD / IEF, SMA150) | **2.60%** | 36.1% | 0.97 | **50.8%** | **-31.9%** | near-miss |
| xsmom_sector_rotation | 0.82% | 10.4% | 0.73 | 22.1% | -11.3% | near-miss |
| regime_allocation | 0.74% | 9.3% | 0.85 | 21.3% | -6.4% | near-miss |
| meanrev_regime | 0.68% | 8.5% | **1.52** | **4.6%** | -2.4% | near-miss |
| xsmom_asset_rotation | 0.71% | 8.9% | 0.72 | 22.7% | -6.7% | failed |
| overnight_drift | 0.20% | 2.5% | 0.27 | 21.1% | -12.7% | failed |
| tsmom_multi_asset | 0.18% | 2.2% | 0.35 | 16.7% | -4.5% | failed |
| leveraged_trend_regime | 0.24% | 2.9% | 0.24 | 43.5% | -13.7% | failed |
| intraday_drift_control | -0.02% | -0.3% | 0.08 | 35.3% | -12.5% | failed |
| vol_breakout_daily | -0.67% | -7.8% | -1.12 | 36.5% | -19.3% | failed |
| orb_intraday | -1.88% | -20.4% | -1.13 | 69.3% | -27.3% | failed (cost drag ~33%/yr) |
| **original ICT bot** (train + validation, default config) | ~0% | ~0% | | | | **25 trades in 8 years** |

The full robustness table is in `explore_full_run_39633867929.md`.

## Locked test period, 2024-01-01 to 2026-10-20 (one look, frozen train-selected parameters)

| strategy | avg month (geo) | CAGR | Sharpe | max DD | worst month | 2x-cost Sharpe | best monthly at any leverage |
|---|---|---|---|---|---|---|---|
| *buy & hold SPY* | 1.52% | 20.2% | 1.30 | 18.7% | -5.6% | | |
| *buy & hold QQQ* | 1.71% | 22.9% | 1.10 | 22.7% | -7.6% | | |
| *60/40 SPY/IEF* | 0.97% | 12.5% | 1.30 | 10.6% | -3.9% | | |
| leveraged_trend | 1.62% | 21.7% | 0.75 | 30.7% | -13.5% | 0.74 | 1.78% |
| xsmom_sector_rotation | 1.01% | 13.1% | 1.12 | 8.8% | -5.3% | 1.08 | 1.66% |
| regime_allocation | 0.57% | 7.1% | 0.96 | 6.9% | -4.1% | 0.93 | 0.57% |
| meanrev_regime | 0.36% | 4.4% | 1.06 | **3.2%** | -1.4% | 0.94 | 2.93% |

None of these four passed every check; they were frozen only as the best near-misses (see `frozen.json`).
Picking near-misses after seeing validation results is itself a mild selection bias.

## What the research found

1. **The original ICT bot barely trades.** It made 25 trades in about 2,000 sessions. Its expectancy was -0.18R on train.
   The audit also found that the 25% notional cap always binds, so real risk per trade is about **0.03-0.1%** rather than 0.5%.
   Those two facts, not "too little leverage", explain most of the tiny returns.
2. **High returns came only from leverage, and leverage came with very large drawdowns.**
   The leveraged-ETF trend roughly tied buy-and-hold on the test period. It lost 51% at its worst in 2019-2023, and its worst month was -32%.
3. **The best risk-adjusted ideas are low-return.**
   Mean reversion had a Sharpe of 1.5 walk-forward and 1.06 on test, with drawdowns of 3-5%.
   It is only invested about 30% of the time, so it returns about 4-8% per year.
4. **Intraday breakout strategies (ORB, volatility breakout) lose money after costs on SPY/QQQ/IWM.**
5. **Combining the best near-misses** (inverse-vol mix) gave a walk-forward Sharpe of 1.51 with a 6.5% max drawdown. That did not beat the best single member.

## Caveats

- The test period is only 2.8 years and mostly a bull market. Every strategy here is long-biased.
- The universe is a hand-picked set of popular, long-lived ETFs, so there is mild survivorship and selection bias.
- RTH "close" is the last trade before the 16:00 auction. The live bot uses IEX data and research used SIP.
- Costs are modelled, not measured. Paper fills are kinder than live fills.
- Thresholds in the survival criteria are judgment calls. They were fixed before any real-data run and were not changed afterwards.

## Reproduce

```bash
python -m ictbot research explore            # train + validation only (test locked)
python -m ictbot research ict-baseline
python -m ictbot research test --reason "..."  # evaluates research/frozen.json, logged
```

Or use the GitHub workflow **research**, whose results are pushed to the `research-results` branch.
