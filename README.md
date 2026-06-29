# PB Trader — ES/NQ Day-Trading Automation

Mechanical automation of **PB Trading Theory (Mechanical Model 2.0)** fused with ICT/SMC,
for **ES** (S&P 500 futures) and **NQ** (Nasdaq futures).

> **Read this first.** This is trading software. It can lose money. The default mode is
> **backtest + paper** — it places **no real orders** until you explicitly configure live
> credentials *and* set `PB_MODE=live`. Prove the edge on history and paper before risking a
> single real dollar. Past backtest performance does not guarantee future results. Nothing here
> is financial advice.

---

## What this does

```
Market data ──► Strategy engine ──► Risk manager ──► Execution
(Databento /    (PB Mechanical      (0.5%/trade      (Paper sim  /
 Tradovate /     Model 2.0:          hard cap,         Tradovate)
 synthetic)      FVG/iFVG, BOS/      position sizing)
                 CHOCH, liquidity
                 sweeps, SMT)
```

The PB Mechanical Model 2.0 pipeline (see `docs/PB_STRATEGY.md`):

1. **HTF bias** — market structure (BOS/CHOCH) + premium/discount + PD arrays.
2. **Liquidity sweep** — raid of BSL/SSL/EQH/EQL/session highs & lows.
3. **LTF confirmation** — iFVG inversion + displacement back through the gap.
4. **Entry** — retest of the inverted FVG; stop past the sweep; targets at next liquidity (≥1:2R).
5. **SMT** — ES-vs-NQ divergence picks the superior instrument (or stand aside).

Only **A+ setups (≥70% confluence)** are emitted. Otherwise: stand aside.

---

## Quick start (offline, no accounts needed)

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e .
# Run a backtest on built-in synthetic data — proves the full pipeline runs:
python -m pb_trader.backtest --symbols ES NQ --bars 5000
# ...with an equity-curve CSV + full analytics (profit factor, Sharpe, breakdowns):
python -m pb_trader.backtest --bars 8000 --equity-csv journal/equity.csv
# Tune parameters with train/test robustness (finds settings that hold out-of-sample):
python -m pb_trader.optimize --bars 12000 --metric expectancy_r
# Run the paper-trading loop on synthetic data:
python -m pb_trader.live --mode paper
```

You should see trades, an equity curve summary, win rate, expectancy, and max drawdown.

---

## Connecting real data & broker (when you're ready)

1. Copy the env template and fill in *your* keys:
   ```bash
   cp .env.example .env
   ```
2. **Databento** (data): create an account at databento.com, generate an API key, put it in
   `DATABENTO_API_KEY`. ES/NQ live on the CME Globex (`GLBX.MDP3`) dataset.
3. **Tradovate** (execution): create a Tradovate account (start with the **demo/sim** environment),
   request API access, and fill `TRADOVATE_*` vars. Keep `TRADOVATE_ENV=demo` until you have
   paper-tested.
4. **Verify the wiring** (authenticates + does a tiny real call, prints PASS/FAIL):
   ```bash
   pip install -e ".[databento,tradovate]"
   python -m pb_trader.connect all
   ```
5. Backtest on real history:
   ```bash
   python -m pb_trader.backtest --source databento --symbols ES NQ --start 2026-01-01 --end 2026-06-26
   ```
5. Paper-trade live data through Tradovate's **demo** environment:
   ```bash
   python -m pb_trader.live --mode paper --source tradovate
   ```
6. Going live is a deliberate, separate step — see `docs/PB_STRATEGY.md` → "Promotion checklist".

---

## Project layout

| Path | Purpose |
|------|---------|
| `pb_trader/models.py` | Core dataclasses (Bar, FVG, Setup, Order, Trade…) |
| `pb_trader/config.py` | Settings loaded from env |
| `pb_trader/data/` | Data sources: synthetic, Databento, Tradovate, CSV |
| `pb_trader/strategy/` | PB model: structure, FVG/iFVG, liquidity, SMT, orchestrator |
| `pb_trader/risk.py` | Position sizing + risk caps |
| `pb_trader/execution/` | Brokers: paper sim + Tradovate adapter |
| `pb_trader/backtest.py` | Event-driven backtester + CLI |
| `pb_trader/analytics.py` | Metrics (profit factor, Sharpe, DD), breakdowns, ASCII equity curve |
| `pb_trader/optimize.py` | Parameter tuning harness with train/test robustness |
| `pb_trader/live.py` | Paper/live trading loop + CLI |
| `pb_trader/journal.py` | Trade journal (JSONL) |
| `tests/` | Unit tests for the strategy primitives |

## Safety rails baked in

- Hard **0.5% risk per trade** cap (configurable, but capped).
- **One A+ setup per session** default throttle.
- Live trading is **off by default** and requires `PB_MODE=live` + non-empty Tradovate creds.
- Every signal and fill is written to the journal for review.
