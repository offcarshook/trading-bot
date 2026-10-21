# ictbot: an ICT-concept intraday paper-trading bot for SPY / QQQM

> **This is an educational experiment, not financial advice.**
> It trades an Alpaca **paper** (simulated) account only and refuses to start on a live account.
> Nothing here claims or implies that the strategy is profitable. The default parameters were picked
> as plausible starting points. They were **not** optimized or validated on market data. Paper results
> overstate what live trading would achieve. Do not put real money behind this code.

ictbot turns a handful of popular "Inner Circle Trader" (ICT) chart ideas (liquidity sweeps, market
structure shifts, fair value gaps) into strict, testable rules. It trades them intraday on SPY and
QQQM through Alpaca's paper API and runs free on GitHub Actions. It logs every decision, including
the trades it skipped and why, so you can study how the rules behave.

---

## Contents

1. [How it works (one picture)](#1-how-it-works)
2. [Setup for beginners](#2-setup-step-by-step)
3. [Reading the reports](#3-reading-the-reports)
4. [Controls: dry run, pause, kill-switch](#4-controls)
5. [The rules, defined mechanically](#5-the-ict-rules-defined-mechanically)
6. [Risk management](#6-risk-management)
7. [Backtesting (optional)](#7-backtesting-optional)
8. [Project layout](#8-project-layout)
9. [Verified Alpaca facts this design relies on](#9-verified-alpaca-facts)
10. [Known limitations](#10-known-limitations)
11. [Honest self-review: where this can fail or be misread](#11-honest-self-review)

---

## 1. How it works

```
 GitHub Actions cron (2 UTC times, DST-safe)
        |
        v
 ictbot run ── start gate (NY time 08:30-11:00?) ──no──> exit
        |
        ├─ Alpaca calendar: holiday? early close? event day?  -> no new entries
        ├─ reconcile from BROKER: cancel stale orders, flatten overnight/naked positions
        ├─ load ~45 days of 1-min bars (IEX feed)  ->  5m / 1h / daily RTH bars
        |
        └─ every 5 min, ~30 s after the bar closes (only COMPLETED bars):
              risk state from broker (P&L, drawdown, trades, losses)
              manage working orders (expiry / invalidation / break-even)
              find setups:  pools -> sweep -> MSS + displacement -> FVG -> filters -> score
              portfolio:    SPY+QQQM = one risk bucket, pick best / split
              risk engine:  sizing, caps, guards  ->  ApprovedOrder (or rejection)
              execution:    server-side BRACKET (limit entry + stop + target), idempotent id
        |
        └─ 15:55 ET flatten (plus an independent "safety flatten" workflow)
           -> journal.md, signals.csv, trades.csv, events.jsonl, summary + equity plot
```

The bot only ever acts on **completed** 5-minute candles. Those are built from 1-minute bars and
anchored to the session open from Alpaca's calendar. Every detector takes an `end` index and never
reads past it, so there is no look-ahead. Live trading and the backtest call the **same** functions.

---

## 2. Setup, step by step

You need a free Alpaca account, a GitHub account, and about 15 minutes.

### 2.1 Create Alpaca **paper** API keys

1. Sign up at <https://alpaca.markets> and log in to the dashboard.
2. Make sure you are on the **Paper** account. The account switcher is at the top left; paper accounts are labelled "Paper".
3. Find **API Keys** on the paper dashboard home page and click **Generate New Keys** (or "Regenerate").
4. Copy the **Key ID**, which should start with `PK`, and the **Secret Key**. The secret is shown **only once**.
   - If your key ID starts with `AK`, it is a **live** key. The bot will refuse to run with it, on purpose.
5. Never paste keys into code, config files, issues or chat. They only go into GitHub Secrets (next step).

### 2.2 Put the code in your own GitHub repository

```bash
git clone <this repo> ict-paper-bot && cd ict-paper-bot
# or: create an empty repo on GitHub, then
git remote add origin git@github.com:<you>/ict-paper-bot.git
git push -u origin main
```

**Public or private?** Public repos get unlimited free Actions minutes, but their logs and artifacts
are visible to anyone. Those contain your paper P&L, though never your keys. Private repos get
2,000 free minutes per month. On a normal day the bot runs about 1.5-2.5 h because it exits early
once the 09:30-11:00 window is over and it is flat. That can exceed 2,000 minutes in a 21-day month,
so check *Settings → Billing* if you go private.

### 2.3 Add GitHub Secrets

In your repo go to **Settings → Secrets and variables → Actions → New repository secret**:

| Secret | Required | Value |
|---|---|---|
| `APCA_API_KEY_ID` | yes | your paper Key ID (`PK...`) |
| `APCA_API_SECRET_KEY` | yes | your paper Secret Key |
| `TELEGRAM_BOT_TOKEN` | optional | from [@BotFather](https://t.me/BotFather) |
| `TELEGRAM_CHAT_ID` | optional | your chat id (message the bot, then open `https://api.telegram.org/bot<TOKEN>/getUpdates`) |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `ALERT_EMAIL_TO` | optional | e-mail alerts over STARTTLS |

Alerts (fills, halts, errors) turn on automatically when their secrets exist.

Optional **variable** (same page, *Variables* tab): `ICTBOT_TRADING_ENABLED` = `false` pauses all new
entries without touching code.

### 2.4 Enable and test the workflows

1. Open the **Actions** tab and click *"I understand my workflows, go ahead and enable them"*.
2. The **tests** workflow runs on every push. It should be green.
3. Run **trade (paper)** manually with *Run workflow*. The defaults are `dry_run = true` and
   `ignore_start_window = true`. Dry run computes and logs signals but **sends no orders**.
   Outside market hours it will simply report that the market is closed.
4. When you are happy, let the schedule take over. It runs on weekdays at 13:17 and 14:17 UTC
   (one of the two lands at about 09:17 New York time all year round), and **safety flatten** runs
   at 19:41 and 20:41 UTC.

### 2.5 Optional: run locally

```bash
python3.11 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt && pip install -e . --no-deps
export APCA_API_KEY_ID=PK...  APCA_API_SECRET_KEY=...      # paper keys only
python -m ictbot check                    # verifies paper endpoint, calendar, data, assets
python -m ictbot run --dry-run --ignore-start-window
python -m pytest -q                       # 102 tests, no network needed
```

---

## 3. Reading the reports

Every workflow run uploads an **artifact**: open the run, then *Artifacts* at the bottom of the page.
Inside, `reports/<date>/` holds:

| File | What it tells you |
|---|---|
| `journal.md` | The day in one page: equity, P&L, drawdown, HTF bias, SPY/QQQM 5-minute correlation, a table of **every signal decision and its reason**, trades, day metrics. |
| `signals.csv` | One row per evaluated setup, **including skipped/rejected ones**, with stage, reason, entry/stop/target, reward:risk, score and detector details (pool, sweep extreme, FVG bounds, score components). |
| `trades.csv` | Round trips rebuilt from broker orders: entry/exit, qty, P&L, R-multiple, MAE/MFE (in R). |
| `events.jsonl` | Machine-readable timeline: start, entries, fills, cancels (with reason), halts, flattens. |
| `reports/summary/summary.md` | **Cumulative** stats over `reporting.summary_lookback_days`: win rate, average R, expectancy, profit factor, Sharpe, Sortino, max drawdown, MAE/MFE, per-setup table and `equity_curve.png` vs buy-and-hold SPY. |
| `logs/*.jsonl` | Structured logs with secrets redacted. |

How to read the numbers without fooling yourself:

- **R-multiple** = P&L ÷ initial risk. −1R is a normal full stop. Expectancy in R is the most portable metric.
- **Sample size matters more than anything.** At most 2 trades a day means roughly 40 a month at best.
  A 60 % win rate over 20 trades is statistically indistinguishable from a coin flip.
  Sharpe and Sortino from a few weeks of daily returns are close to meaningless.
- The skipped-signal table often teaches more than the trades. It shows which filter does the work.

---

## 4. Controls

| You want to… | Do this |
|---|---|
| See signals without trading | Run the workflow manually with `dry_run`, or set `mode.dry_run: true` in `config.yaml` |
| Pause new entries | Repo variable `ICTBOT_TRADING_ENABLED=false` |
| Close everything now | Run **safety flatten** with `force = true` |
| Reset the max-drawdown kill-switch | Find out *why* it fired first. Then `python -m ictbot reset-killswitch`, which sets `risk.drawdown_reset_date` to today; commit and push. |
| Use QQQ instead of QQQM | `symbols: [SPY, QQQ]`. QQQ is already in the correlated bucket. |
| Stop running entirely | Disable the workflows in the Actions tab |

**Why the kill-switch needs a config change.** GitHub runners are wiped after every job, so the bot
keeps no local memory. Drawdown is recomputed from Alpaca's portfolio history every time it starts.
Once it is ≥ 8 % from the peak, it stays ≥ 8 %, because no new trades happen to change it. The switch
therefore holds by itself until you move the peak's start date.

---

## 5. The ICT rules, defined mechanically

Every threshold lives in `config.yaml`. ATR is a 14-period Wilder ATR on 5-minute bars.

| Concept | Mechanical definition (code: `ict_detectors.py`, `strategy.py`) |
|---|---|
| **Swing high/low** | Fractal with `N=2` bars each side: strictly beyond the left bars and at or beyond the right bars. It is only *known* N bars later (`confirmed_index`), so no look-ahead. |
| **Liquidity pools** | Buy-side above / sell-side below: previous-day H/L, previous-week H/L, pre-market H/L (levels only, never traded), opening range (first 15 min) H/L, confirmed 5m swings (last ~2 sessions), and **equal highs/lows** (≥2 swings within 0.1 × ATR). |
| **Sweep** | A bar trades beyond an intact pool by ≥ max(0.05 × ATR, $0.02) and a bar **closes back inside within k=2 bars**, counting the breach bar. Records the sweep extreme. A breach without that close is a breakout and consumes the pool. |
| **Displacement** | Body ≥ 1.2 × ATR and total wicks ≤ 35 % of range. |
| **MSS** | After a buy-side sweep, the **first** close below the last swing low formed before the sweep must be a bearish displacement candle (mirror for longs), within 12 bars. A break without displacement, or a trade beyond the sweep extreme first, means no MSS. |
| **FVG** | Bullish `low[i] > high[i-2]`, bearish `high[i] < low[i-2]`, size ≥ 0.1 × ATR, inside the displacement leg. Tracks touched / midpoint (consequent encroachment) / filled / invalidated. |
| **Order block** (optional) | Last opposing candle before the displacement. Adds score if it overlaps the FVG; can be made required. |
| **Premium/discount** | Dealing range = sweep extreme ↔ displacement-leg extreme. Longs only at/below equilibrium, shorts at/above. Required by default. |
| **HTF bias** | Daily and 1-hour structure (last two swing highs and lows rising = bullish, falling = bearish), combined with `both_agree`. Counter-bias trades only after sweeping an HTF pool (prev day/week, pre-market). |
| **Time filter** | Entries only in kill zones (default NY open 09:30-11:00; Silver Bullet 10:00-11:00 optional and adds score), never in the last 30 min, not on early-close or listed event days (`config/event_days.yaml`, which you maintain). |
| **Entry** | Limit at the FVG midpoint (or edge). Cancelled after 6 bars, on a close through the FVG, on a trade beyond the sweep extreme, or if the target is hit first. |
| **Stop / target** | Stop = sweep extreme ± 0.1 × ATR. Target = nearest intact opposing pool. **Skipped if reward:risk < 2.** Server-side bracket. |
| **Score** | Sum of weighted components (HTF alignment, HTF pool, equal levels, OB, premium/discount, Silver Bullet, displacement strength, extra R, sparse-data penalty). Trades below `min_score` are skipped, and the best score wins when several setups appear. |

---

## 6. Risk management

The risk engine (`risk.py`) is the only code that can create an `ApprovedOrder`, the only object
execution will submit. Config values above the **hard ceilings** in `risk.py` (e.g. 2 % per trade,
20 % drawdown) make the bot refuse to start.

| Rule | Default |
|---|---|
| Risk per trade (sized from stop distance, whole shares) | 0.5 % of equity, scaled **down** (never up) when ATR % is high |
| Max notional per position / total | 25 % / 50 % of equity |
| SPY + QQQM correlated bucket | aggregate open risk ≤ 1.5 × one trade's risk; a 2nd same-direction trade gets half size; opposite directions blocked |
| Daily / weekly loss limit | 2 % / 4 %: stop entries and flatten |
| Max drawdown kill-switch | 8 % from peak: flatten, no trading until manually reset |
| Trades per day / consecutive losses / cooldown | 2 / 3 / 30 min after a loss |
| Pre-trade guards | quote present and < 60 s old, spread ≤ 5 bps and ≤ 0.25 × ATR, bar volume ≥ 1,000 (IEX), relative volume ≥ 0.3, newest bar < 7 min old, shortable + easy-to-borrow for shorts |
| No averaging down / pyramiding | one position or working entry per symbol |
| Every order has a stop | invariant checked at approval and again at submission; a position found without a stop is flattened |
| Idempotency | deterministic `client_order_id = ictb-YYMMDD-SYMBOL-<setup hash>-<leg>`; checked before every submit, so restarts cannot double-place |
| Reconciliation | positions, orders, trades, P&L, losses and drawdown are **rebuilt from Alpaca** every cycle |

---

## 7. Backtesting (optional)

```bash
python -m ictbot backtest --start 2025-01-02 --end 2025-12-31
```

The GitHub workflow **backtest (optional)** is manual only. Set `backtest.enabled: false` to turn it off.

- It uses the **same** frame builder, detectors, strategy, portfolio selector and risk engine as live trading.
- Decisions are made at 5m closes. Fills are simulated on the following **1-minute** bars and
  never on the signal bar.
- The fill model is conservative. A limit only fills if price trades **through** it. A stop beats a
  target inside the same bar. The fill bar can stop you out but cannot take profit.
- Costs: stop/market slippage in bps, SEC fee and FINRA TAF on sells, optional commission.
  **Check the current regulatory rates.** The defaults are placeholders.
- **Held-out period:** the last 30 % of days is reported separately. Change parameters using
  in-sample results only, and look at the hold-out once. Every extra look leaks information.
- **Walk-forward:** `backtest.walk_forward.enabled: true` reports metrics per sequential fold with
  fixed parameters, to show stability over time. There is no automatic parameter search. Bolting a
  grid search onto 2-trade-a-day data is a fast way to overfit.

---

## 8. Project layout

```
config.yaml                every threshold (validated, unknown keys rejected)
config/event_days.yaml     high-impact days to skip (maintain it yourself)
src/ictbot/
  config.py                typed frozen dataclasses + loader
  safety.py                paper-only guard (URL, key prefix, account number)
  timeutils.py             America/New_York, DST-safe session helpers
  data.py                  Alpaca IEX data, 1m→5m/1h/daily aggregation, data quality
  indicators.py            causal ATR, EMA, relative volume, rolling correlation
  ict_detectors.py         PURE detectors: swings, pools, sweeps, displacement, MSS, FVG, OB, PD, bias
  strategy.py              single source of truth for signals + pending-order rules
  risk.py                  hard-coded risk engine + ApprovedOrder issuance
  portfolio.py             correlated buckets, setup selection, correlation report
  execution.py             Alpaca broker adapter, bracket orders, flatten
  state.py                 broker reconciliation, trade reconstruction, risk state
  reporting.py             CSV/JSONL logs, metrics, journal, equity plot
  alerts.py                Telegram / e-mail
  live.py                  the trading loop
  backtest.py              optional simulator + hold-out + walk-forward
  cli.py                   check | run | flatten | report | backtest | reset-killswitch
tests/                     102 tests with synthetic candles, a fake broker and a simulated full trading day
.github/workflows/         trade, safety flatten, tests, backtest
```

---

## 9. Verified Alpaca facts

Checked on 2026-10-21 against Alpaca's docs and the **alpaca-py 0.44.0** source, which is pinned in
`requirements.txt`. Re-verify before upgrading.

- **Bracket orders:** `time_in_force` must be `day` or `gtc`; extended hours are not supported; the
  take-profit and stop-loss legs only activate **after the entry is completely filled**; cancelling
  one leg cancels the group; stop/limit legs can be PATCHed; the stop must be ≥ $0.01 from the base
  price (the entry limit). [Orders at Alpaca](https://docs.alpaca.markets/us/docs/orders-at-alpaca)
- **Fractional shares:** only market, limit, stop and stop-limit **DAY** orders, and **never short**.
  Brackets are not listed as supported, so the bot uses **whole shares only**.
  [Fractional trading](https://docs.alpaca.markets/docs/fractional-trading)
- **Shorting:** check `shortable` / `easy_to_borrow` on `/v2/assets/{symbol}`; hard-to-borrow names
  need a locate. The bot only shorts ETB symbols and needs `shorting_enabled` on the account.
  [Margin and short selling](https://docs.alpaca.markets/us/docs/margin-and-short-selling)
- **Free data:** the Basic plan has real-time **IEX only**; SIP history is allowed only for data older
  than 15 minutes; 200 historical calls/min.
  [Market data](https://docs.alpaca.markets/us/docs/about-market-data-api)
- **Calendar:** alpaca-py returns calendar `open`/`close` as **naive New York times**, which the bot
  localizes. Early closes show up as `close < 16:00`.
- **Pattern-day-trader rule:** FINRA's amendment to Rule 4210 removed the $25k PDT requirement
  (effective 2026-06-04, with up to 18 months for brokers to implement). alpaca-py 0.44 notes that
  Alpaca removed `pdt_check` / `dtbp_check` from responses on 2026-07-06. The bot still refuses new
  entries if an account is flagged PDT under $25k, as a harmless legacy guard. Intraday margin rules
  are broker-specific and may change.
- Paper key IDs start with `PK` and live ones with `AK`; paper account numbers start with `PA`.
  These are Alpaca conventions the safety guard relies on. If Alpaca changes them, the bot refuses
  to start rather than guessing.

---

## 10. Known limitations

1. **IEX-only data.** IEX prints about 2-3 % of US volume. Highs and lows, and therefore sweeps,
   swings and FVGs, can differ from the consolidated chart you see on TradingView. QQQM is especially
   thin on IEX, so 1-minute bars go missing and 5-minute candles become ragged. The bot warns about
   sparse data and penalizes the score, but **switching to QQQ is strongly recommended**.
2. **Paper fills are not real fills.** Alpaca simulates fills from quotes, with no queue position,
   no market impact and optimistic limit fills. Live results would be worse.
3. **GitHub cron is best-effort.** Runs can start 5-30+ minutes late or be skipped. In public
   repositories, scheduled workflows are disabled after 60 days without repository activity. Jobs are capped at 6 hours,
   which is why end-of-day flattening is a separate workflow. If that workflow starts after the
   close, leftover positions are closed at the next open, not before.
4. **5-minute polling.** Stops and targets are server-side and react instantly. Cancellation rules
   (expiry, invalidation) can act up to about 5 minutes late, and an entry can fill in that gap.
5. **Partial fills.** Bracket legs wait for a *complete* entry fill, so a partially filled entry is
   unprotected until the next cycle. The bot then cancels the remainder and flattens the partial.
6. **GTC brackets** (default) keep the stop alive if the bot dies, but an unfilled GTC entry could
   survive into the next day. The morning reconcile cancels stale orders and flattens overnight
   positions. Use `bracket_time_in_force: day` if you prefer entries that can never outlive the day,
   at the cost of exits that also expire at the close.
7. **Dedicated account assumed.** Flattening closes *every* position and cancels *every* order in the account.
8. **The event calendar is manual**, and FOMC days are skipped entirely, not just around 14:00.
9. **The risk-engine "token" is a convention, not a security boundary.** Python cannot stop code
   that deliberately imports private names. It stops accidents, not malice.
10. **Daily P&L uses Alpaca's `last_equity`.** Resetting or funding the paper account shows up as P&L.
11. **No borrow fees, dividends or corporate actions** are modelled in the backtest. Regulatory fee
    rates in `config.yaml` are placeholders.
12. **Rule changes** (PDT / intraday margin, Alpaca API) can silently change behaviour. Pin the SDK
    and re-run `ictbot check` after any upgrade.

---

## 11. Honest self-review

Where the strategy itself can fail, and where its output is easy to misread:

- **Mechanizing a discretionary method changes it.** ICT practitioners judge context such as
  narrative, draw on liquidity and the quality of "obvious" levels. These rules approximate that
  with fixed thresholds. Many mechanical "sweeps" on 5-minute SPY are ordinary noise around a
  level, not engineered liquidity runs. The rules test *this* definition, not ICT in general.
- **Unvalidated defaults.** Every number in `config.yaml` is a reasonable-sounding guess. None was
  fitted, and there is no evidence of an edge. A backtest that looks good after you tweak 20
  parameters is most likely curve-fitting. There are many degrees of freedom: pools, buffers,
  displacement size, scoring weights, windows.
- **Tiny samples.** At most 2 trades a day gives a few hundred trades a year, *if* setups appear.
  Expect long stretches with no trades, especially with premium/discount, HTF bias and 2R all
  required. Confidence intervals on win rate, profit factor and Sharpe stay wide for months.
- **2R targets at the next pool may be unrealistic intraday.** With a 15:55 flatten, many trades end
  at neither stop nor target, and the R distribution has a fat middle.
- **SPY and QQQM are nearly one asset** (5-minute correlation often > 0.9). Two symbols are not
  diversification. The bucket cap exists because the risk is effectively doubled.
- **The bias filter is crude and lagging.** Two-swing structure on daily and hourly bars flips late
  and is neutral much of the time.
- **Premium/discount on the displacement leg is partly self-fulfilling.** A midpoint entry inside a
  deep leg is often in the "right" half by construction. It filters less than its name suggests.
- **Complexity is not edge.** The confluence score orders setups but does not make them better.
  Scores have no calibrated probability behind them.
- **Paper ≠ live.** IEX data, simulated fills and zero market impact all flatter paper results.
  Even a strategy that works on paper may fail live.
- **What the reports cannot tell you:** whether any profit came from skill or luck, whether results
  carry over to another period, or whether ICT concepts work at all. Only a large out-of-sample
  record could begin to answer that, and even then without certainty.

**Reminder: this is not financial advice.** It is a learning tool for exploring how discretionary
trading ideas behave once written down as strict rules. Use paper money only.
