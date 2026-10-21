# Audit of the original ICT bot

Independent 5-lens audit (look-ahead, backtest realism, conservatism, live bugs, data pipeline).
Every finding was attacked by two independent skeptics; only findings upheld by at least half of the verifiers are listed.
Raw findings: 24 | upheld: 19 | refuted: 5

| severity | votes | location | finding | status |
|---|---|---|---|---|
| high | 2/2 | `src/ictbot/risk.py:304` | 25% notional cap always binds, so actual risk per trade is about 0.03-0.1% instead of 0.5% | OPEN - design decision, quantified by the research harness (see RESEARCH_SUMMARY) |
| high | 2/2 | `src/ictbot/execution.py:366` | flatten_all reads positions before waiting for cancels, so it can send a stale market close that opens a reverse position | FIXED (execution.py: wait for cancels, re-read positions) + regression test |
| medium | 2/2 | `config/event_days.yaml:7` | Backtest event-day filter is a no-op for the configured 2025 period (event list only has 2026 dates) | open |
| medium | 2/2 | `src/ictbot/backtest.py:316` | Backtest drawdown kill-switch is permanent: no trades for the rest of the run, including the hold-out | open |
| medium | 1/2 | `src/ictbot/live.py:390` | Live loop's own 15:55 flatten never runs on scheduled starts; the backtest always flattens at 15:55 | open |
| medium | 2/2 | `config/event_days.yaml:6` | Event-day filter is a no-op over the default backtest window, so the backtest trades FOMC/CPI/NFP days that live skips | open |
| medium | 2/2 | `src/ictbot/live.py:228` | Break-even trigger can use the price range from before the fill inside the fill's own 5-minute bar | open |
| medium | 2/2 | `src/ictbot/data.py:302` | Empty or failed per-day fetches are cached permanently | FIXED (empty days not cached) |
| medium | 2/2 | `src/ictbot/data.py:287` | Cache path ignores the data feed, so IEX and SIP bars mix silently | FIXED (cache path includes feed) |
| low | 2/2 | `src/ictbot/reporting.py:92` | MAE/MFE count the entry minute's pre-fill range and the post-exit range | open |
| low | 2/2 | `src/ictbot/state.py:75` | Degraded EntryPlan uses submitted_at as placed_at, so the first bar after placement is never evaluated | open |
| low | 2/2 | `src/ictbot/backtest.py:325` | Backtest never applies the live sparse-data score penalty or the stale-bar/quote guards | open |
| low | 1/2 | `src/ictbot/backtest.py:345` | Backtest fills orders from the decision instant and cancels them instantly; live acts about 30 s later | open |
| low | 2/2 | `src/ictbot/backtest.py:223` | Risk state classifies wins and losses on a different basis in backtest and live | open |
| low | 2/2 | `src/ictbot/backtest.py:297` | Daily equity point is recorded before the end-of-day flatten, so flatten slippage and fees land on the next day | open |
| low | 1/2 | `src/ictbot/strategy.py:391` | min_score 3.0 never rejects; the PD component is constant once PD is required | open |
| low | 2/2 | `src/ictbot/backtest.py:410` | Benchmark is price-only (split-adjusted, no dividends) and comes from IEX minute closes | open |
| low | 2/2 | `src/ictbot/reporting.py:296` | First day's P&L is excluded from strategy return and from the daily return series | open |
| low | 2/2 | `src/ictbot/backtest.py:297` | Last equity point of each day is recorded before flatten costs | open |

## Details

### [high] 25% notional cap always binds, so actual risk per trade is about 0.03-0.1% instead of 0.5%

`src/ictbot/risk.py:304` (lens: conservatism, votes 2/2)

**What:** qty = min(risk_budget/rps, 25% of equity / entry). For the 0.5% risk budget to be the limit instead, the stop would need to be at least 0.5/25 = 2% of price. 5-minute ICT stops are about 0.1-0.4% of price; the measured median stop is 2.5 ATR, about $2 on SPY. So the notional cap decides the size every time. Knock-on effects: vol_scale (line 296), the portfolio half-size rule (risk_fraction 0.5) and the bucket cap of 1.5x risk (line 312) never change the quantity. Measured with the real RiskEngine.approve: setting risk_fraction to 0.5 or 1.0 gives the same qty of 48. Returns, drawdown and the loss-limit kill switches are all about 5-20x smaller than the config suggests, and the risk limits will never fire.

**Failure scenario:** Equity $100k, SPY $600, ATR $0.90, stop 1.5 ATR ($1.35). Sizing by risk gives 370 shares; the notional cap allows 41. Actual risk is $55 (0.055%) instead of $500. QQQ with a 1.0 ATR stop: 48 shares, $53 at risk. Even with a 2.5 ATR stop, risk is only 0.09-0.13%. A year of about 15 trades at +0.3R would return about 0.3%.

**Suggested fix:** Make the notional cap a backstop that only bites at the hard ceiling (e.g. 100-200% of equity with margin, or below 50% via the hard limit). Alternatively, report realized risk % and warn when the cap binds. Size by the risk budget and apply vol scaling only where it actually binds.

### [high] flatten_all reads positions before waiting for cancels, so it can send a stale market close that opens a reverse position

`src/ictbot/execution.py:366` (lens: live_bugs, votes 2/2)

**What:** flatten_all asks the broker to cancel the bracket legs. It then reads positions() once, and for each position waits for that symbol's orders to close before sending a market order for the quantity it read earlier. If a TP or stop leg fills while the cancel is still pending, the position is already closed or smaller by the time the market order goes out. The function also says 'closing anyway' on timeout, while the legs may still be live.

**Failure scenario:** The account is long 10 SPY and the stop leg is triggering right at the end-of-day flatten. The cancel loses the race and the stop fills, so the position is now 0. The loop still holds the old qty=10 and sends a 10-share sell at market. With shorting enabled the account ends up short 10 SPY into the close. That position is unplanned and has no stop, and reconstruct_trades books the extra fill as a 'flatten' exit, which corrupts the P&L.

**Suggested fix:** After _wait_symbol_orders_closed, fetch the position for that symbol again and close only the quantity actually left. Skip the symbol if it is flat. Consider using the broker's close-position endpoint instead.

### [medium] Backtest event-day filter is a no-op for the configured 2025 period (event list only has 2026 dates)

`config/event_days.yaml:7` (lens: lookahead, votes 2/2)

**What:** Outside the look-ahead lens, but it affects research validity. run_backtest skips a day only when `cfg.session.skip_event_days and sess.day in events` (src/ictbot/backtest.py:279), and cli.py:155 loads events from config/event_days.yaml. That file contains only dates from 2026-10-28 onward (lines 7-12). The default backtest window is 2025-01-02..2025-12-31 (config.yaml:161-162). So the backtest trades every 2025 FOMC/CPI/NFP day, while the live bot (live.py:110) skips those days. Nothing warns that the list has no dates inside the backtest range. The README says the backtest uses the same rules as live.

**Failure scenario:** Running `ictbot backtest` with the defaults trades roughly 30 high-impact days in 2025 (8 FOMC decisions plus the CPI and NFP releases, about 12% of sessions) that live trading would never trade. These are the highest-volatility sessions, so they can dominate win rate, expectancy and max drawdown. The reported in-sample and out-of-sample metrics then describe a different strategy from the one deployed.

**Suggested fix:** Add historical event dates covering the backtest range. In cmd_backtest/run_backtest, warn or refuse when skip_event_days is true and the events dict has no dates within [start, end].

### [medium] Backtest drawdown kill-switch is permanent: no trades for the rest of the run, including the hold-out

`src/ictbot/backtest.py:316` (lens: lookahead, votes 2/2)

**What:** Outside the look-ahead lens, but it materially harms research validity. Once drawdown_pct >= max_drawdown_pct, RiskEngine.status returns flatten=True and the loop flattens and `continue`s before any entry logic. drawdown_pct is (sim.peak - equity)/sim.peak (backtest.py:232). sim.peak never resets and equity stays constant while flat, so the condition holds on every remaining bar of every remaining day. The live bot has a manual reset (risk.drawdown_reset_date); the backtest has none.

**Failure scenario:** Demonstrated on synthetic data with max_drawdown_pct=0.15 (scratchpad dd_test.py, seed 3). Drawdown tripped at 2025-03-19 14:30 and there were zero placements over the remaining 17 sessions. With the default 8% limit, a trip during the in-sample 70% leaves the out-of-sample section and all later walk-forward folds with 0 trades. That looks like 'no hold-out evidence' rather than a strategy result, and it is entirely path-dependent.

**Suggested fix:** In the backtest, record the kill-switch trip (date, equity) in the report. Then either reset the peak after it (simulating the manual reset) or continue with the drawdown halt disabled. Report 'with kill-switch' and 'strategy edge' metrics separately, or at least flag the folds that are halted.

### [medium] Live loop's own 15:55 flatten never runs on scheduled starts; the backtest always flattens at 15:55

`src/ictbot/live.py:390` (lens: backtest_realism, votes 1/2)

**What:** The live deadline is `now + max_runtime_minutes`, and `now` is the clock at process start (live.py:362), taken before the bot sleeps until the open. The trade workflow fires at 13:17/14:17 UTC, which is 09:17 ET in both EDT and EST, and the default `max_runtime_minutes` is 340 (config.yaml:40). So on any scheduled start before about 10:15 ET the deadline falls at about 14:57-15:15, before `flatten_at` (15:55). The loop sets `wake = min(wake, flatten_at, deadline)` (live.py:397), then hits `now >= deadline` and breaks (live.py:403-405) without flattening. The end-of-day `flatten_all` at live.py:400-402 is therefore never reached on a normal day. Positions still open in the afternoon go unmanaged from about 15:00, and only the separate flatten workflow can close them. That job's window is 15:30-16:00 (cli.py:101-102, default --max-wait-minutes 25), and it exits without acting if it starts at or after 16:00. The backtest instead always closes every position at the 15:55 1-minute open plus 1 bp (backtest.py:298-303) and can never hold overnight. The README notes that many trades end at neither stop nor target, so this path covers a large share of exits. The live.py docstring (line 9) says the loop flattens at 15:55. The only full-day test sets `max_runtime_minutes=600` (tests/test_backtest_live.py:190), which hides the problem.

**Failure scenario:** I ran a simulation with the repo's FakeBroker and default config. The bot started at 09:20 ET with a filled, stop-protected SPY position. The loop exited at 15:00:00 with 'max runtime reached', no `end_of_day` flatten event was written, and the position was still open. In production, if the GitHub cron for the flatten job (19:41/20:41 UTC) starts more than about 19 minutes late, or is skipped (the README says delays of 5-30+ minutes happen), the position is held overnight and closed at the next open. That gap exposure has no counterpart in backtest results.

**Suggested fix:** Compute the deadline from the session (for example `min(start + max_runtime, flatten_at + margin)`), or start the trade job later or allow a longer runtime, so the in-process 15:55 flatten is reachable. Or treat the flatten workflow as the primary exit and add a test that runs with the default `max_runtime_minutes` and a 09:20 start. Fix the docstring either way.

### [medium] Event-day filter is a no-op over the default backtest window, so the backtest trades FOMC/CPI/NFP days that live skips

`config/event_days.yaml:6` (lens: backtest_realism, votes 2/2)

**What:** Live sets `trading_allowed=False` on any date listed in config/event_days.yaml (live.py:110-111). The backtest uses the same file (cli.py:155 -> backtest.py:279 `sess.day in events`). The file lists only six dates, 2026-10-28 to 2026-12-10. The default backtest window is 2025-01-02 to 2025-12-31 (config.yaml:161-162), so not a single backtest day is filtered. `load_event_days` warns only when the file is missing, not when it doesn't cover the backtest range, so nothing tells you this happened. The backtest sample therefore includes about 30+ high-volatility macro days a year, roughly 12-14% of sessions. These are the days with the biggest opening sweeps and displacement candles, and live never trades them.

**Failure scenario:** I checked with the real config. `load_event_days('config/event_days.yaml')` returns [2026-10-28, 2026-11-06, 2026-11-10, 2026-12-04, 2026-12-09, 2026-12-10], and none of them fall inside 2025-01-02..2025-12-31. So `python -m ictbot backtest` with defaults trades every 2025 FOMC, CPI and NFP session, including those days' opening moves. Live paper trading would sit those days out. Win rate, expectancy and drawdown are measured on a different set of days from the one live trades.

**Suggested fix:** Add historical event dates for every backtest period, or have run_backtest/cmd_backtest warn or refuse when skip_event_days is true and the event file has no dates in [start, end]. Report the number of event days skipped in the backtest summary.

### [medium] Break-even trigger can use the price range from before the fill inside the fill's own 5-minute bar

`src/ictbot/live.py:228` (lens: live_bugs, votes 2/2)

**What:** The fill time is rounded down to the minute, not to the bar. Any 5-minute bar whose start time is at or after that minute is included. When a fill lands exactly on a bar boundary minute, for example 10:00:40, that whole bar counts, including its high or low from before the fill. A long limit entry fills on a dip, so the bar's high from before the dip can already meet trigger_r*R.

**Failure scenario:** A long limit fills at 10:00:40 at 100.00 with the stop at 99.00. The 10:00-10:05 bar opened at 101.10, then dropped to fill the order and stayed near 100. fav = 1.10 >= 1R, so the stop moves to break-even even though price never rose 1R after the entry. Live results then diverge from the backtester's rules.

**Suggested fix:** Only use bars that start strictly after the fill, or compute the favorable move from 1-minute bars after filled_at.

### [medium] Empty or failed per-day fetches are cached permanently

`src/ictbot/data.py:302` (lens: data_pipeline, votes 2/2)

**What:** CachedMinuteBars.load writes `part.to_csv(p)` for every day in the chunk even when `part` is empty. A day is refetched only when its file is missing (line 291), so an empty file counts as cached forever. On read, line 308 skips empty frames without logging anything.

**Failure scenario:** Alpaca returns no rows for QQQ for a 5-day chunk, for example after a transient IEX gap, a bad response that still passed retry, or a symbol missing from that response. Header-only .csv.gz files are written for all 5 days. Every later backtest treats those days as having no bars: no trades and flat equity. That adds zero-return days to the Sharpe and Sortino series and drops the days from the results. Nothing warns about it, and only deleting the cache by hand fixes it.

**Suggested fix:** Do not write empty frames for a session day, or write a sentinel with fetch metadata and retry it. Validate coverage against the session's expected RTH minutes before caching, and log a warning when a cached day is empty.

### [medium] Cache path ignores the data feed, so IEX and SIP bars mix silently

`src/ictbot/data.py:287` (lens: data_pipeline, votes 2/2)

**What:** The cache path is `<cache_dir>/<symbol>/<day>.csv.gz` with no feed or adjustment in the key. cmd_backtest (cli.py:154) uses `cfg.data.cache_dir` whatever `cfg.data.feed` is. The research path avoids this only because it uses a separate `minute_sip` directory (cli.py:298); research/data.py puts the feed in its tag and manifest, but this cache does not.

**Failure scenario:** A user runs the backtest with feed: iex, then switches config to feed: sip to get realistic consolidated data and reruns. Every day already cached is served from the IEX files and only new days come from SIP. The second report claims SIP results but is built from IEX data, or from a mix of the two.

**Suggested fix:** Put the feed and adjustment in the cache path (for example `<cache_dir>/<feed>_split/<symbol>/...`), or write a manifest and check it on load.

### [low] MAE/MFE count the entry minute's pre-fill range and the post-exit range

`src/ictbot/reporting.py:92` (lens: lookahead, votes 2/2)

**What:** mae_mfe uses the full high/low of every 1m bar with floor(entry_time) <= index <= exit_time. That includes: (a) the part of the entry minute before the limit filled; for a resting long limit the minute opens above the entry, so its high always adds favorable excursion that never happened after the fill; (b) the exit minute after the exit; (c) for backtest flatten exits, stamped at flatten_at and filled at that bar's OPEN (backtest.py:301-302), and risk-halt exits, stamped at asof and filled at the previous minute's close (backtest.py:318), a whole 1m bar that is entirely after the exit. The backtest (backtest.py:351) and the live journal (live.py:441, broker timestamps) both use it. The values feed avg_mae_r/avg_mfe_r in summary.md and metrics.json. Decisions are unaffected.

**Failure scenario:** Demonstrated (scratchpad mae_test.py). Long limit at 100.00 with stop 99.50. The 10:00 bar O100.30 H100.35 L99.95 fills at 100.00 while price is falling, and the 10:01 bar stops the trade out. Reported MFE is 0.7R although price never traded above the entry after the fill. In the flatten case the position is closed at the 15:55 open (99.99), and that 15:55 bar (H101.5/L98.0, all after the exit) produces MAE/MFE of 4.0R/3.0R instead of 0.2R/0.7R. Tuning targets, stops or break-even on these diagnostics is biased by post-exit data.

**Suggested fix:** Bound the window to the time in the trade. Exclude bars that start at or after the exit for exits stamped at a bar start (flatten, risk_halt). For stop and target exits, cap the exit-minute extremes at the exit price. For the entry minute, only count the adverse side, bounded by the fill price, or skip that minute. Alternatively, have the Simulator track running MAE/MFE as it processes minutes.

### [low] Degraded EntryPlan uses submitted_at as placed_at, so the first bar after placement is never evaluated

`src/ictbot/state.py:75` (lens: lookahead, votes 2/2)

**What:** EntryPlan.placed_at is defined as the START of the signal 5m bar (strategy.py:431). The cached live path and the backtest both set it that way, so `today5.index > placed_at` (live.py:193, backtest.py:311) starts at the first bar after placement. When the plan cache is missing, _plan_from_order instead sets placed_at to the broker's submitted_at, which is about the signal bar's end plus 30 s. `today5.index > submitted_at` then drops the first post-placement bar. That bar is never checked for target_hit_before_fill, fvg_invalidated or beyond_sweep_extreme, and expiry comes one bar late. state/ is uploaded as an artifact in trade.yml but never restored, so any same-day rerun of the trade job takes this path.

**Failure scenario:** Demonstrated (scratchpad placed_at_test.py). Signal bar 10:10, order submitted 10:15:31, then a restart without the cache. Cached plan: bars counted are [10:15, 10:20]. Degraded plan: only [10:20]. At 10:20:30 `after` is empty and the check is skipped. If the 10:15 bar hit the target before filling, the order is not cancelled and can fill later on a retrace. Expiry moves from the 10:40 bar to the 10:45 bar.

**Suggested fix:** In _plan_from_order, set placed_at = floor_to_bar(submitted_at, session.open) - 5 minutes, the start of the bar that completed before submission. Better, encode the signal-bar time in the client_order_id and rebuild placed_at from it.

### [low] Backtest never applies the live sparse-data score penalty or the stale-bar/quote guards

`src/ictbot/backtest.py:325` (lens: backtest_realism, votes 2/2)

**What:** Live calls `find_setups(fr, cfg, data_sparse=sparse)`, where `sparse = coverage < sparse_warn_ratio` (live.py:300-301). That subtracts `sparse_data_penalty` (1.0) from the score, against `min_score` 3.0. The backtest calls `find_setups(frames[s], cfg)` (backtest.py:325), so `data_sparse` is always False. The backtest's MarketCheck also hard-codes `newest_bar_age_s=0.0` and a synthetic one-tick quote built from the bar close (backtest.py:339-341). As a result, `stale_or_missing_bars`, `stale_quote`, `missing_quote` and the spread rejections can never fire in the backtest. The README (line 304) says the bot 'penalizes the score' on sparse data, and the backtest docstring says it uses the same functions as live.

**Failure scenario:** Take a day where IEX 1-minute coverage for a symbol is below 80% (common for thin symbols such as QQQM, which is the BotConfig default, and possible for others in quiet periods). A setup scoring 3.5 is rejected live (3.5 - 1.0 < 3.0) but taken in the backtest. Likewise, if the newest IEX bar is more than 420 s old at decision time, live rejects the trade and the backtest takes it.

**Suggested fix:** In run_backtest, compute `assess_quality` on `m_today[s]` up to `asof` (as live.py:179 does). Pass `data_sparse` to `find_setups`, and use the real `newest_bar_age_s` in MarketCheck.

### [low] Backtest fills orders from the decision instant and cancels them instantly; live acts about 30 s later

`src/ictbot/backtest.py:345` (lens: backtest_realism, votes 1/2)

**What:** In the backtest an order approved at bar close `asof` is placed at once (backtest.py:345). The next loop iteration simulates the 1-minute bar starting at `asof` (backtest.py:289-293), so the whole minute counts toward a fill. Live wakes `poll_offset_seconds` (30 s, config.yaml:18) after the boundary (live.py:396), then fetches data and quotes before submitting. So at least the first ~30 s of that minute are unavailable to it. In the other direction, the backtest deletes a pending order the moment `pending_entry_action` fires at `asof` (backtest.py:312-313), before minute `asof` is simulated. Live cancels about 30 s later and can fill in that window. README item 4 mentions live's late cancellation, but the backtest doesn't model it.

**Failure scenario:** A long FVG limit is approved at 10:15:00. Price trades through the limit at 10:15:10 and recovers by 10:15:25. The backtest records a fill, often a good one. Live submits at about 10:15:32 and never fills. Or: at 10:20:00 the bar shows `target_hit_before_fill`. The backtest cancels immediately, while live's order is still working until about 10:20:30. If price retraces to the entry in that window, live gets a fill on a setup whose target pool is already spent, and the backtest never sees that trade.

**Suggested fix:** Make fill and cancel take effect at `asof + poll_offset_seconds`. For example, skip a fill on the first minute after placement, or require it to happen in the second half of that minute, and keep pending orders live through the first minute after a cancel decision.

### [low] Risk state classifies wins and losses on a different basis in backtest and live

`src/ictbot/backtest.py:223` (lens: backtest_realism, votes 2/2)

**What:** The backtest counts a trade as a loss for `consecutive_losses` and the 30-minute `cooldown_after_loss` when `t.pnl - t.fees < 0` (backtest.py:223, 227). That P&L includes 2 bp stop slippage (backtest.py:64-65) and SEC/TAF fees. Live uses `t.pnl < 0` on gross broker fills with fees=0 (state.py:253, 257, 152). Separately, the backtest drawdown peak is the intraday mark-to-market maximum, updated every 5 minutes (backtest.py:296, 232), while live takes the peak from prior daily closing equity plus current equity (state.py:245-247). The backtest also never honours `drawdown_reset_date`.

**Failure scenario:** Set `break_even.enabled: true` (offset $0.01). A SPY long at $600.00 has its stop moved to $600.01 and is later stopped. The backtest exits at 600.01 x (1 - 0.0002) = $599.89, a loss of about $0.11/share before fees. That counts as a loss, starts a 30-minute cooldown and extends the loss streak. Live paper fills near $600.01 and counts a small win with no cooldown. So the backtest blocks entries that live would take. Separately, a day whose unrealized equity peaks intraday sets a higher drawdown baseline in the backtest than live ever records, so the 8% kill switch trips earlier. Once tripped, it stops all trading for the rest of the run, hold-out included.

**Suggested fix:** Classify wins and losses the same way in both. Either use gross P&L in Simulator.risk_state, or add fees to live. Build the backtest drawdown peak from end-of-day equity, honour drawdown_reset_date, and report when a halt fires.

### [low] Daily equity point is recorded before the end-of-day flatten, so flatten slippage and fees land on the next day

`src/ictbot/backtest.py:297` (lens: backtest_realism, votes 2/2)

**What:** On the last bucket, `sim.equity_points.append((asof, eq))` runs before the flatten (backtest.py:297 vs 298-303). `eq` is valued at the 15:54 close. The 15:55-open flatten price, the 1 bp market slippage, and the `_finalize` fees for every trade closed by the flatten are only reflected in the first equity point of the next day. `report_backtest` takes each day's last point (backtest.py:413), so daily returns, Sharpe and drawdown carry that cost on the wrong day. The final day's flatten never appears in the equity series or `strategy_return_pct` at all. Summary max drawdown uses daily closes, while the in-sample/out-of-sample sections use the 5-minute series (backtest.py:384 vs 413-416), so the two drawdown figures can disagree.

**Failure scenario:** A 40-share SPY position is flattened at 15:55. The roughly $2-3 of slippage and fees, plus the 15:54-close to 15:55-open move, appear as P&L at 09:35 the next trading day. On the last backtest day they are dropped from the equity-based metrics, but they remain in trade-based net_pnl, so the two disagree. The size is small per day but systematic.

**Suggested fix:** Append an equity point after the flatten and after the end-of-day safety loop (for example at sess.close), so each day's last point reflects all realized P&L and fees.

### [low] min_score 3.0 never rejects; the PD component is constant once PD is required

`src/ictbot/strategy.py:391` (lens: conservatism, votes 1/2)

**What:** Because PD is required, every surviving setup gets the +1 PD bonus, and displacement adds at least 0.6. The lowest possible score is therefore 2.6, and almost any other bonus clears 3.0. Measured: none of the 36 setups that passed every hard filter scored below 3 (the lowest was 4.26). htf_aligned (+2) was awarded to only 7%, because both_agree leaves the bias neutral most of the time. The scoring threshold does no filtering. Its only effect is ranking.

**Failure scenario:** Removing the min_score filter leaves the setup count unchanged: 13 vs 13 and 23 vs 23 setups.

**Suggested fix:** Either make min_score meaningful or treat the score as ranking only. Award the PD bonus only when PD is not required.

### [low] Benchmark is price-only (split-adjusted, no dividends) and comes from IEX minute closes

`src/ictbot/backtest.py:410` (lens: data_pipeline, votes 2/2)

**What:** The benchmark comes from daily_from_minutes over minute bars fetched with Adjustment.SPLIT (data.py:222). It therefore leaves out SPY dividends, about 1.2-1.5% a year, and uses the last IEX print before 16:00 instead of the official close. The `daily_closes` helper (Adjustment.ALL) exists but is not used. The chart is labelled 'buy & hold SPY'.

**Failure scenario:** Over a 3-year backtest, the benchmark_return_pct for buy-and-hold is understated by about 4 percentage points. The strategy's excess return over buy-and-hold is overstated by the same amount.

**Suggested fix:** Build the benchmark from total-return (Adjustment.ALL) daily SIP closes, for example via daily_closes on a SIP client, and label it as total return.

### [low] First day's P&L is excluded from strategy return and from the daily return series

`src/ictbot/reporting.py:296` (lens: data_pipeline, votes 2/2)

**What:** report_backtest passes daily_eq, which is the last equity of each day stamped at 16:00. write_summary then computes strategy_return_pct as equity.iloc[-1]/equity.iloc[0]-1, and the Sharpe input is daily.pct_change(). Both use the end of day 1 as the base, not cfg.backtest.initial_equity, so day 1's return disappears. In-sample and walk-forward folds have the same base problem.

**Failure scenario:** The strategy makes +1.5% on the first day of the backtest. strategy_return_pct and Sharpe never include it. Max drawdown also ignores any intraday loss on day 1 relative to starting capital. In short folds this can noticeably change the reported return.

**Suggested fix:** Prepend initial_equity, stamped at the first session open, to the daily equity series before computing returns and drawdown.

### [low] Last equity point of each day is recorded before flatten costs

`src/ictbot/backtest.py:297` (lens: data_pipeline, votes 2/2)

**What:** At the bucket that crosses flatten_at, the code appends the equity point (line 297) and then calls sim.flatten with slippage and fees (lines 298-303). The daily 'last' equity used for the Sharpe input and for drawdown is therefore mark-to-market before exit costs. Those costs show up in the next day's first point, which shifts returns between days. On the final day they never appear in the equity series, although they are in net_pnl.

**Failure scenario:** A position flattened at 15:55 pays 1bp of slippage plus commission. That day's return is overstated by the cost and the next day's is understated. The final day's costs are missing from strategy_return_pct, so it does not match net_pnl.

**Suggested fix:** Append an equity point after the flatten and the end-of-session safety flatten, so the daily close equity reflects realized costs.

## Refuted by verifiers

- 2R minimum to the NEAREST intact pool rejects about 75% of otherwise complete setups (`src/ictbot/strategy.py:347`, votes 0/2)
- Premium/discount on the leg rejects about 67% of candidates; the FVG midpoint usually sits in the wrong half, contrary to the README (`src/ictbot/strategy.py:371`, votes 0/2)
- The rule that the first close past the level must be a displacement candle discards about 60% of structure breaks (`src/ictbot/ict_detectors.py:250`, votes 0/2)
- Held stop legs of unfilled entry brackets count as protection for an existing position (`src/ictbot/state.py:197`, votes 0/2)
- Backtest runs on IEX-only bars by default, distorting signals, fills and volume filters (`config.yaml:14`, votes 0/2)