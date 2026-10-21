"""Quantitative research harness (PAPER research only - never places orders).

Layout:
  base.py        ResearchData container, StrategyResult, Strategy protocol, registry
  universe.py    instrument universe + per-symbol cost assumptions
  data.py        Alpaca historical download (SIP, split+dividend adjusted), cache, RTH daily build
  costs.py       transaction-cost + financing model
  engine.py      next-open weight engine and intraday trade engine (causal, cost-aware)
  metrics.py     performance statistics
  validation.py  splits, walk-forward, sensitivity, DSR, PBO (CSCV), bootstrap, null tests, regimes, leverage
  runner.py      staged research pipeline (explore -> validate -> test, test period locked)
  report.py      markdown/JSON/plot reporting
  strategies/    one module per strategy family
"""
