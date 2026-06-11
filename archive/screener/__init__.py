"""
Pre-market screener.

Ranks each strategy's universe on EOD data and writes the top-N candidates per
strategy to config/daily_watchlist.json, which live/runner.py reads at startup.

Modules:
  universe.py          — named universes + strategy→universe map
  ranking_features.py  — pure (numpy) ranking math: per-symbol metrics + score formula
  catalyst_detector.py — optional event catalysts (earnings / bulk deals / FII flow)
  daily_screener.py    — orchestration: load EOD candles → rank → write watchlist

Entry point: scripts/run_screener.py  (run pre-market, ~9:00 IST)
"""
