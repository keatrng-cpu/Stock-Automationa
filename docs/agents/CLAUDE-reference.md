# CLAUDE.md — reference sections (moved verbatim)

_Moved out of `CLAUDE.md` by Forge Atlas Wave 1 (M2 canon trim) so agents load the rules first and open detail on demand. Content unchanged. Rules, gates and floors stayed in `CLAUDE.md`._

## Intelligence layer (the "brain")

The model is *perception*; `brain.py` is *judgment*. On every A+ candidate the brain fuses:
- **News** (`news.py`): blackout high-impact windows, caution around medium.
- **Adaptive** (`adaptive.py`): cut size + raise the A+ bar after losing streaks/drawdown.
- **Memory** (`memory.py`): **aware of every concept** — it learns how each SMC/ICT/PB
  concept (mechanical, sponsored, sig-sweep, HTF-FVG nest, CISD, BPR, rejection…) performs
  AND how it performs in the current **regime + volatility** (`concept-in-regime`,
  `regime×volatility` buckets), so it knows what works and *when*. Nudges size by that
  edge; vetoes setup types that keep losing.
- **Recency-weighted (EWMA)** memory: every bucket decays prior weight by `recency_decay`
  (~34-trade half-life) on each new sample, so recent results dominate and stale edges
  fade — the brain adapts to the market it's in *now*, not months ago. (Non-stationarity.)
- **Live market-condition gate**: the brain reads the current `regime×volatility` and, via
  `memory.condition_edge`, gets pickier (raises the bar — defensive only) when that exact
  environment has been hostile lately. Volatility is a first-class learned dimension.
It learns from every closed trade (persisted to `journal/memory.jsonl` in live). All
adjustments are explainable — no black box. It never gets reckless (defensive-only).

## Scenario projection — prepared for multiple paths (`strategy/scenarios.py`)

Elite traders map the **decision tree**, not a single prediction. `project_scenarios()`
turns live context (price, significant liquidity, stacked top-down bias, regime/volatility)
into a ranked set of if/then branches — **primary continuation + alternate reversal +
range rotation** — each with a trigger, an invalidation, a draw-on-liquidity target, and a
probability (from bias conviction + regime). The engine pre-plans every branch and trades
only the one that confirms. `PBModel.project_scenarios()` pulls live state; the session
report renders the map ("if price sweeps PDH and fails → short to PDL"). Pure/deterministic
— every level named comes from real levels, never fabricated.

## Learning self-audit — review the learning, find weak spots (`review.py`)

`python -m pb_trader.review` runs the engine, then audits its OWN learning and names where
it's weak — the honest introspection a great trader does nightly:
1. **Collinearity**: SMC/ICT concepts that always co-fire carry identical stats, so the brain
   can't separate them. `memory._shrunk` now **collapses identical-stat buckets to one vote**
   (a real fix — a blob of 8 co-firing concepts no longer outvotes an independent `sym:ES`
   8-to-1); the audit still flags the residual (can't credit a concept until it's seen apart).
2. **Sample health**: how many buckets are actually TRUSTED (n ≥ shrink_k) vs undersampled noise.
3. **Blind spots**: regimes / volatility / sessions / TFs with zero experience.
4. **Trusted edges**: the best/worst edges the brain can stand behind.
5. **Veto calibration** (counterfactual, no look-ahead): of the setups the brain SKIPPED, how
   many WOULD have won? `run_backtest(track_skips=True)` + `_hypo_r` grade each veto —
   SMT/cadence vetoes that skip losers are GOOD; a veto that skips net winners is over-filtering.
   This is how the system measures whether its own filters actually add value.

## Loss journal — learning from mistakes (`lessons.py`)

Every losing trade is journalized. On a loss the brain introspects via
`memory.worst_feature()` to name the most likely **culprit** (the worst-edge concept/regime/
session present), writes a structured post-mortem to `journal/lessons.jsonl`, and — because
memory now weighs losses more (`loss_emphasis`, default 1.5) — the same mistake is absorbed
faster. Readable, not a black box; surfaced in the report and weekly ledger.

## Testing across many randomized markets (`montecarlo.py`)

One profitable seed is curve-fitting; the honest signal is the **distribution** across many
independent markets. `python -m pb_trader.montecarlo --seeds 30 --source neutral --weeks 4`
runs N seeds and reports median/mean return, % profitable, median expectancy, worst drawdown,
and a GO/NO-GO verdict. `--carry` carries one brain across all markets (continual learning);
`--mtf` adds the conjunction gate. Read the MEDIAN, never the best seed.

## SMT monitor — automatic ES⇄NQ divergence (`smt_monitor.py`)

`python -m pb_trader.smt_monitor` scans ES vs NQ bar-by-bar and emits a deduplicated timeline
of SMT divergences (one event per divergence, not per bar), each naming the instrument to
favor (strong→longs, weak→shorts) and the live read. Same logic the backtester uses for
instrument selection, surfaced as a continuous monitor.

## Tooling

- **Session reports**: `python -m pb_trader.report --session morning|afternoon` runs the
  full PB Elite protocol (context → HTF bias → SMT → key levels → A+ setup → risk → goal).
- **Validation**: `python -m pb_trader.validate` runs backtest + optimizer + walk-forward
  and prints a GO/NO-GO verdict driven by out-of-sample results.
- **Monte-Carlo**: `python -m pb_trader.montecarlo --seeds N` — distribution across many
  randomized markets (median/% profitable/worst DD), not one lucky seed.
- **SMT monitor**: `python -m pb_trader.smt_monitor` — automatic ES⇄NQ divergence timeline.
- **Learning audit**: `python -m pb_trader.review` — reviews what the brain learned and names
  weak spots (collinearity, undersampling, blind spots, veto calibration).
- **Multi-timeframe**: add `--mtf` to backtest/weekly/montecarlo for full-ladder conjunction.
- **Goal tracking**: `pb_trader/goals.py` tracks the $1k→$10k→$50k→$100k journey.

## Running on real Databento data (ES/NQ)

The engine reads live/historical CME data via `data/databento_source.py`. Databento only
publishes native `ohlcv-1s/1m/1h/1d`, so the source fetches the finest native schema and
**resamples** up to any ladder timeframe (1m→15m, 1s→30s) — so every `--timeframe` works.

Setup (once, on a machine with the key):
1. `pip install 'pb-trader[databento]'`  (installs the `databento>=0.34` extra)
2. In `.env`: `DATABENTO_API_KEY=db-...`  (dataset defaults to `GLBX.MDP3`)
3. Verify: `python -m pb_trader.connect databento`

Then point any tool at real data with `--source databento --start <ISO> --end <ISO>`:
- Backtest: `python -m pb_trader.backtest --source databento --start 2025-05-01 --end 2025-06-01 --timeframe 1m`
- Weekly ledger: `python -m pb_trader.weekly --source databento --start 2025-05-01 --end 2025-06-01`
- Learning audit: `python -m pb_trader.review --source databento --start 2025-05-01 --end 2025-06-01`
- Paper loop: `python -m pb_trader.live --mode paper --source databento`

Dates are ISO (`YYYY-MM-DD`); if omitted the source defaults to the last ~10 days. This is
the single highest-leverage move — it takes the brain's learning off synthetic noise.

