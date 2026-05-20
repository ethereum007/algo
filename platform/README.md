# Algo AI Platform

Local web platform built around your fork, `ethereum007/algo`.

## Run

```powershell
cd C:\Users\kiran\Documents\Twitter\algo-ai-platform
python server.py 8765
```

Open `http://127.0.0.1:8765`.

## What It Does

- Generates strategy projects through your fork's `scaffold_strategy.py`.
- Applies your brief and risk controls into `config.py`, `strategy.py`, and `README.md`.
- Runs the upstream `validate_strategy.py` linter.
- Lets you browse generated files and the skill reference library.
- Fetches public delayed Indian market quotes and 1-minute intraday candles through the Market Data tab.
- Creates zip downloads for generated strategy projects.

## Notes

When this folder lives inside the fork, the server uses the parent repo as the skill source. If copied outside the fork, it falls back to `C:\Users\kiran\Documents\Twitter\ethereum007-algo` and then `algo_ai_skill`.

Market Data currently uses Yahoo Finance chart data for research and UI validation. It maps common Indian symbols automatically, for example `NIFTY` to `^NSEI`, `BANKNIFTY` to `^NSEBANK`, and equities like `RELIANCE` to `RELIANCE.NS`. It does not scrape NSE.

This is a research and development platform. It produces paper/live shells, not a ready-to-trade system. Before any real order placement, connect broker data, instrument lookup, tick-size and DPR checks, margin checks, WebSocket order updates, and paper-trade validation.
