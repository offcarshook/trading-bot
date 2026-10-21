"""Strategy modules. Each module builds a ``StrategySpec`` and calls ``register``.

Contract (checked by tests/research/test_causality.py):
* weight strategies return ``run_weights(data, W, costs, ...)`` where W is
  indexed by DECISION date and uses only data up to that date's close;
* trade strategies return ``run_trades(trades, dates, costs)`` where each
  trade's decision uses only data strictly before its entry time;
* ``param_grid`` is pre-registered: it is fixed before any real-data run and
  every combination counts as a trial for multiple-testing corrections.
"""
