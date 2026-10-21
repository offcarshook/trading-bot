# Deploy rule for the "grow the account" paper portfolio

Written 2026-10-21, **before** any portfolio simulation of the candidates below
and before any real-data result for the four new strategies (crypto_trend,
crypto_momentum_rotation, letf_momentum_rotation, broad_etf_momentum). PAPER ONLY.

## Candidates

| id | file | idea | gross cap |
|---|---|---|---|
| C0 | `config/daily_portfolio.yaml` | live config: sector rotation x1 + index mean reversion x2 | 1.9 |
| C1 | `config/candidates/c1_degen_stocks.yaml` | TQQQ trend + 3x-ETF mean reversion | 1.9 (broker-capped) |
| C2 | `config/candidates/c2_letf_rotation_meanrev.yaml` | weekly top-2 3x-ETF rotation + 3x-ETF mean reversion | 1.9 (broker-capped) |
| C3 | `config/candidates/c3_everything_balanced.yaml` | 60% 3x-ETF rotation / 40% crypto trend | 1.0 (cash only) |
| C4 | `config/candidates/c4_everything_max.yaml` | all growth sleeves, idle capital flows to what is risk-on | 1.0 (cash only) |

Sleeve parameters are the pre-registered defaults (new strategies) or the
already-frozen a-priori choices (degen strategies, `research/frozen_degen.json`).
Every simulation uses exactly what the bot trades (`daily_portfolio.simulate_portfolio`):
combined targets, gross cap, FINRA/Reg-T margin cap, rebalance band, costs,
margin interest, next-open execution.

## Selection window and rule

* **Selection window S = 2021-01-01 .. 2023-12-31** (or the first date with
  BTC/ETH data, if later): the only pre-2024 window in which every sleeve,
  including crypto, is live. It contains a bull year, a crash year and a
  recovery year for both stocks and crypto.
* **Deploy the candidate with the highest geometric mean monthly return on S**,
  subject to max drawdown on S <= 60% (the degen kill-switch level).
  Tie (within 0.1%/month): higher Sharpe on S.
* The 2019-2023 window and the 2024+ test period are **reported, never used to
  choose**. If the winner loses money over 2024+ it is still deployed and the
  report says so plainly.
* Known bias: the mean-reversion / sector parameters were selected on
  2016-2021 data, which overlaps 2021 in S; this favours C0-C2 slightly.

## Risk settings in degen mode (user asked for maximum risk)

* Kill switch at -60% from peak (liquidate and stop) instead of -30%: a
  catastrophe backstop on a paper account, not a risk limit.
* Broker reality is not optional: Alpaca margin limits (3x ETFs need 75%
  margin; crypto cannot be margined) are enforced in both the simulation and
  the live bot. 50x/100x leverage is impossible at Alpaca and would have been
  wiped out repeatedly in the backtests.
