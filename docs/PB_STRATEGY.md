# PB Mechanical Model 2.0 — Strategy Spec (PB × ICT/SMC × TJR)

This is the exact logic the engine implements. Each concept maps to a module.

## 1. HTF bias — market structure
`strategy/structure.py`

- **Swing points**: fractal highs/lows (`find_swings`, window `k`).
- **BOS (Break of Structure)**: close beyond the last swing in the *trend* direction → continuation.
- **CHOCH (Change of Character)**: close beyond the protected swing *against* trend → reversal.
- **Premium/Discount**: dealing-range equilibrium. Longs favored in discount, shorts in premium.

## 2. Conditions gate — "read the condition first" (PB)
`strategy/conditions.py`

Necessary before any setup is even considered:
- **Regime** via Kaufman **efficiency ratio**: trending vs ranging vs dead (chop).
- **Volatility** via ATR ratio vs baseline: blocks illiquid (too low) and erratic/news (too high).
- **News blackout**: `NewsCalendar` windows (FOMC/CPI/NFP). Pluggable; wire a real feed later.

If conditions aren't tradeable → **stand aside**, no matter how clean the pattern.

## 3. Liquidity — the raid is the trigger
`strategy/liquidity.py`

- Pools: **BSL** (above highs), **SSL** (below lows), **EQH/EQL** (equal highs/lows = magnet liquidity).
- **Sweep**: wick takes the pool but candle closes back inside → stops taken, trap set. This is the trigger, not a breakout to chase.
- **Next liquidity** in trade direction = logical first target.

## 4. Entry — iFVG inversion + retest
`strategy/fvg.py`

- **FVG**: 3-candle imbalance. Fresh (unfilled) only.
- **iFVG**: a gap price closes through *inverts* (bull→bear support/resistance). The PB entry:
  sweep → displacement inverts the FVG → **retest** of the inverted gap = entry.

## 5. TJR overlays
`strategy/tjr.py`

- **Killzones**: London, NY AM, Silver Bullet (10–11 ET), NY PM. Trade in-window.
- **Power of Three (AMD)**: Accumulation (Asia) → **Manipulation** (judas sweep) → Distribution.
  The manipulation leg sets **daily bias** (swept lows ⇒ bullish day, and vice versa).
- **Market Structure Shift (MSS)**: entry-timeframe displacement break of a recent swing — confirmation.
- **Breaker block**: violated-then-reclaimed order block (supporting confluence).

## 6. SMT — instrument selection
`strategy/smt.py`

ES vs NQ should move together. Divergence (one makes HH/LL, the other fails) reveals the
weaker/stronger instrument. Trade the one SMT favors; if they disagree with the setup, skip.

## 6b. Top-down multi-timeframe (core SMC)
`strategy/htf.py`

Smart-money analysis is top-down. The LTF bar stream is resampled to a higher
timeframe (default 15m) and structure is computed there to get **HTF bias**. Entries
that fight a decided HTF bias are **gated out** (`require_htf_alignment`), and entries
that agree get a heavy confluence bonus.

## 6c. Order blocks & OTE (core SMC entries)
`strategy/order_blocks.py`, `strategy/fib.py`

- **Order block**: the last opposing candle before a displacement that leaves an FVG —
  demand (bull) or supply (bear). Tracked for **mitigation** (price returning to it).
- **OTE (Optimal Trade Entry)**: the 0.62–0.79 fib retracement of the impulse leg —
  the deep-discount/premium pocket smart money re-enters from.

Both add confluence when the entry coincides with them (they often stack with the iFVG).

## 7. Confluence scoring → A+ gate
`strategy/pb_model.py`

| Component | Weight |
|-----------|-------:|
| LTF structure alignment (BOS/CHOCH) | 0.15 |
| **HTF bias alignment (top-down)** | 0.15 |
| Premium/discount of dealing range | 0.08 |
| Liquidity sweep present | 0.15 |
| iFVG inversion + retest | 0.15 |
| **Order block retest** | 0.07 |
| **OTE (0.62–0.79 fib)** | 0.07 |
| Displacement quality | 0.06 |
| TJR MSS | 0.06 |
| TJR killzone | 0.03 |
| TJR PO3 daily bias | 0.03 |

Sum ∈ [0,1]. **≥ 0.75 ⇒ A+ candidate.** The highest-scoring candidate is chosen, and
only after the HTF-alignment + conditions + news gates pass.

## 8. Risk & execution
`risk.py`, `execution/`

- Size = ⌊(equity × risk%) / (stop_pts × point_value)⌋. Floored to stay under the cap.
- Min 1:2 R:R or rejected. Bracket order (entry + stop + target).
- Paper broker simulates fills (stop-before-target pessimism). Tradovate places live OSO brackets.

---

## Promotion checklist (paper → live)

Do **not** skip steps.

1. ✅ Backtest on **real** Databento history (≥ 6 months ES & NQ, 1m). Positive expectancy, sane max DD.
2. ✅ Forward paper-trade on Tradovate **demo** for ≥ 4 weeks. Live results match backtest shape.
3. ✅ Confirm fills/slippage assumptions hold on demo.
4. ✅ Set `PB_RISK_PCT` to the smallest meaningful size; trade **micros** (MES/MNQ) first.
5. ✅ Only then set `PB_MODE=live` with real creds. Watch the first live sessions manually.
6. ✅ Journal every trade. Review weekly. Detach from P&L; iterate on the rules, not the impulses.

> Reminder: backtest edges decay, slippage is real, and futures are leveraged. This system
> is a disciplined assistant, not a money printer. Risk only what you can afford to lose.
