# Graph Report - Stock-Automationa  (2026-10-13)

## Corpus Check
- 71 files · ~41,394 words
- Verdict: corpus is large enough that graph structure adds value.
- Unclassified: 3 file(s) not represented in the graph (top: (none) 2, .example 1)

## Summary
- 778 nodes · 2155 edges · 29 communities (24 shown, 5 thin omitted)
- Extraction: 85% EXTRACTED · 15% INFERRED · 0% AMBIGUOUS · INFERRED: 322 edges (avg confidence: 0.92)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `c8b42b25`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- backtest.py
- Trade
- Bar
- TradovateClient
- walkforward.py
- PaperBroker
- models.py
- PBModel
- report.py
- CLAUDE.md — PB Trader project instructions
- mem.py
- test_strategy.py
- pb_model.py
- order_blocks.py
- Direction
- run_live
- FVG
- PB Mechanical Model 2.0 — Strategy Spec (PB × ICT/SMC × TJR)
- news.py
- ._evaluate
- fib.py
- tjr.py
- PB Trader — ES/NQ Day-Trading Automation
- NOW — Stock-Automationa current truth
- AGENTS.md
- GROK.md
- pb-trader

## God Nodes (most connected - your core abstractions)
1. `Bar` - 130 edges
2. `Direction` - 72 edges
3. `Trade` - 52 edges
4. `Side` - 50 edges
5. `run_backtest()` - 40 edges
6. `TradeMemory` - 39 edges
7. `PBModel` - 32 edges
8. `PaperBroker` - 28 edges
9. `TradingBrain` - 25 edges
10. `Setup` - 25 edges

## Surprising Connections (you probably didn't know these)
- `Cadence + daily circuit breaker (`governor.py`)` --references--> `SessionGovernor`  [INFERRED]
  CLAUDE.md → pb_trader/governor.py
- `1. HTF bias — market structure` --references--> `find_swings()`  [INFERRED]
  docs/PB_STRATEGY.md → pb_trader/strategy/structure.py
- `Learning self-audit — review the learning, find weak spots (`review.py`)` --references--> `_hypo_r()`  [INFERRED]
  docs/agents/CLAUDE-reference.md → pb_trader/backtest.py
- `Non-negotiable rules (enforced in code)` --references--> `validate_setup()`  [INFERRED]
  CLAUDE.md → pb_trader/risk.py
- `2. Conditions gate — "read the condition first" (PB)` --references--> `NewsCalendar`  [INFERRED]
  docs/PB_STRATEGY.md → pb_trader/strategy/conditions.py

## Import Cycles
- None detected.

## Communities (29 total, 5 thin omitted)

### Community 0 - "backtest.py"
Cohesion: 0.05
Nodes (36): BacktestResult, load_series(), main(), _print_report(), run_backtest(), _write_equity_csv(), Decision, TradingBrain (+28 more)

### Community 1 - "Trade"
Cohesion: 0.08
Nodes (30): CLAUDE.md — reference sections (moved verbatim), Intelligence layer (the "brain"), Learning self-audit — review the learning, find weak spots (`review.py`), Loss journal — learning from mistakes (`lessons.py`), Running on real Databento data (ES/NQ), Scenario projection — prepared for multiple paths (`strategy/scenarios.py`), SMT monitor — automatic ES⇄NQ divergence (`smt_monitor.py`), Testing across many randomized markets (`montecarlo.py`) (+22 more)

### Community 2 - "Bar"
Cohesion: 0.06
Nodes (12): AdversarialSource, DataSource, CSVSource, DatabentoSource, _resample_secs(), NeutralSource, SyntheticSource, Bar (+4 more)

### Community 3 - "TradovateClient"
Cohesion: 0.06
Nodes (16): check_databento(), check_tradovate(), _fail(), main(), _ok(), TradovateSource, on_frame(), make_handler() (+8 more)

### Community 4 - "walkforward.py"
Cohesion: 0.08
Nodes (35): ascii_equity(), breakdown(), compute_metrics(), confluence_bucket(), format_report(), Metrics, GoalStatus, render() (+27 more)

### Community 5 - "PaperBroker"
Cohesion: 0.08
Nodes (14): Broker, get_broker(), PaperBroker, _price_key(), parse_fill_pairs(), TradovateBroker, Order, OrderType (+6 more)

### Community 6 - "models.py"
Cohesion: 0.09
Nodes (11): StructureEvent, SwingPoint, fresh_fvgs(), _bucket(), htf_bias(), htf_fvgs(), resample(), build_pools() (+3 more)

### Community 7 - "PBModel"
Cohesion: 0.07
Nodes (12): Multi-timeframe conjunction (`mtf.py`), 2. Conditions gate — "read the condition first" (PB), MultiTimeframeModel, NewsCalendar, PBModel, _session_of(), session_name(), SessionTracker (+4 more)

### Community 8 - "report.py"
Cohesion: 0.09
Nodes (21): get_source(), LiquidityPool, build_report(), main(), _warm(), current(), main(), render() (+13 more)

### Community 9 - "CLAUDE.md — PB Trader project instructions"
Cohesion: 0.06
Nodes (26): Cadence + daily circuit breaker (`governor.py`), CLAUDE.md — PB Trader project instructions, Each model belongs on its own timeframe (the brain remembers this), Intelligence layer (the "brain"), Learning self-audit — review the learning, find weak spots (`review.py`), Loss journal — learning from mistakes (`lessons.py`), Memory protocol (auto, every task — do not wait to be asked), Mission: capital growth plan (+18 more)

### Community 10 - "mem.py"
Cohesion: 0.15
Nodes (19): 2026-10-13 — auto-memory protocol adopted, DECISIONS — Stock-Automationa (append-only), build(), changed(), context(), gbin(), graph(), install_hook() (+11 more)

### Community 11 - "test_strategy.py"
Cohesion: 0.11
Nodes (20): _hypo_r(), efficiency_ratio(), detect_fvgs(), update_fvg_states(), order_blocks_from_fvgs(), project_scenarios(), detect_mss(), _bar() (+12 more)

### Community 12 - "pb_model.py"
Cohesion: 0.13
Nodes (12): LiquidityVoid, assess_conditions(), atr(), MarketConditions, next_liquidity(), detect_voids(), nearest_unfilled_void(), new_vacuum() (+4 more)

### Community 13 - "order_blocks.py"
Cohesion: 0.11
Nodes (12): BreakerBlock, OrderBlock, find_breakers(), flip_broken_blocks(), fresh_blocks(), order_block_at_formation(), retesting_block(), retesting_breaker() (+4 more)

### Community 14 - "Direction"
Cohesion: 0.12
Nodes (10): Direction, in_htf_fvg(), _bias_vote(), Scenario, _split_levels(), detect_rejection_block(), DailyPO3, test_htf_fvg_nesting() (+2 more)

### Community 15 - "run_live"
Cohesion: 0.17
Nodes (7): SessionGovernor, Lesson, LossJournal, run_live(), test_governor_cadence_is_a_ceiling_not_a_forcer(), test_governor_daily_circuit_breaker_halts_entries(), test_governor_medium_tier_allowed_within_floor()

### Community 16 - "FVG"
Cohesion: 0.16
Nodes (7): FVG, active_ifvgs(), new_fvg(), consequent_encroachment(), detect_bpr(), in_bpr(), test_consequent_encroachment_and_bpr()

### Community 17 - "PB Mechanical Model 2.0 — Strategy Spec (PB × ICT/SMC × TJR)"
Cohesion: 0.12
Nodes (15): 10. Measuring the enhancements (A/B), 1. HTF bias — market structure, 3. Liquidity — the raid is the trigger, 4. Entry — iFVG inversion + retest, 5. TJR overlays, 6. SMT — instrument selection, 6b. Top-down multi-timeframe (core SMC), 6c. Order blocks & OTE (core SMC entries) (+7 more)

### Community 18 - "news.py"
Cohesion: 0.29
Nodes (4): EconomicCalendar, NewsEvent, NewsReaction, test_news_reaction_blackout_and_caution()

### Community 19 - "._evaluate"
Cohesion: 0.23
Nodes (6): current_macro(), in_macro(), detect_cisd(), premium_discount(), test_ict_macro_windows(), test_sweep_is_mandatory_for_a_plus()

### Community 20 - "fib.py"
Cohesion: 0.32
Nodes (4): dealing_range(), in_ote(), ote_check(), test_ote_zone()

### Community 21 - "tjr.py"
Cohesion: 0.36
Nodes (4): current_killzone(), detect_breaker(), in_killzone(), test_killzone()

### Community 22 - "PB Trader — ES/NQ Day-Trading Automation"
Cohesion: 0.29
Nodes (6): Connecting real data & broker (when you're ready), PB Trader — ES/NQ Day-Trading Automation, Project layout, Quick start (offline, no accounts needed), Safety rails baked in, What this does

### Community 23 - "NOW — Stock-Automationa current truth"
Cohesion: 0.40
Nodes (4): Goal, In flight, Known facts / constraints, NOW — Stock-Automationa current truth

## Knowledge Gaps
- **1 isolated node(s):** `pb-trader`
  These have ≤1 connection - possible missing edges or undocumented components. (Counts symbols only; 275 node(s) total have ≤1 connection when file, concept and rationale nodes are included.)
- **5 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `Bar` connect `Bar` to `TradovateClient`, `PaperBroker`, `models.py`, `PBModel`, `report.py`, `test_strategy.py`, `pb_model.py`, `order_blocks.py`, `Direction`, `FVG`, `._evaluate`, `fib.py`, `tjr.py`?**
  _High betweenness centrality (0.204) - this node is a cross-community bridge._
- **Are the 49 inferred relationships involving `Bar` (e.g. with `AdversarialSource` and `DataSource`) actually correct?**
  _`Bar` has 49 INFERRED edges - model-reasoned connections that need verification._
- **What connects `pb-trader` to the rest of the system?**
  _1 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `backtest.py` be split into smaller, more focused modules?**
  _Cohesion score 0.050686641697877656 - nodes in this community are weakly interconnected._
- **Why does `CLAUDE.md — PB Trader project instructions` connect `CLAUDE.md — PB Trader project instructions` to `PBModel`?**
  _High betweenness centrality (0.055) - this node is a cross-community bridge._
- **Are the 50 inferred relationships involving `Direction` (e.g. with `build_report()` and `detect_fvgs()`) actually correct?**
  _`Direction` has 50 INFERRED edges - model-reasoned connections that need verification._
- **Should `Trade` be split into smaller, more focused modules?**
  _Cohesion score 0.07514124293785311 - nodes in this community are weakly interconnected._