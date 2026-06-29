"""Unit tests for the PB strategy primitives."""
from datetime import datetime, timedelta

from pb_trader.models import Bar, Direction, Setup, Side
from pb_trader.risk import position_size, validate_setup
from pb_trader.strategy.conditions import assess_conditions, efficiency_ratio
from pb_trader.strategy.fvg import detect_fvgs, update_fvg_states
from pb_trader.strategy.structure import find_swings
from pb_trader.strategy.tjr import DailyPO3, current_killzone, detect_mss


def _bar(i, o, h, l, c, sym="ES"):
    return Bar(datetime(2026, 6, 26, 9, 30) + timedelta(minutes=i), o, h, l, c, 100, sym)


def test_bullish_fvg_detected():
    bars = [_bar(0, 100, 101, 99, 100),
            _bar(1, 100, 105, 100, 104),     # displacement up
            _bar(2, 104, 106, 102, 105)]     # low 102 > bar0 high 101 -> bull FVG
    fvgs = detect_fvgs(bars)
    assert any(f.direction is Direction.BULL for f in fvgs)
    f = [f for f in fvgs if f.direction is Direction.BULL][0]
    assert f.bottom == 101 and f.top == 102


def test_fvg_inversion():
    bars = [_bar(0, 100, 101, 99, 100),
            _bar(1, 100, 105, 100, 104),
            _bar(2, 104, 106, 102, 105)]
    fvgs = detect_fvgs(bars)
    f = [f for f in fvgs if f.direction is Direction.BULL][0]
    # Price closes below the gap -> inverts to bearish iFVG.
    update_fvg_states([f], _bar(3, 102, 102, 95, 96))
    assert f.inverted and f.direction is Direction.BEAR


def test_swings_found():
    bars = [_bar(i, 100 + (i % 5), 102 + (i % 5), 98 + (i % 5), 100 + (i % 5))
            for i in range(20)]
    swings = find_swings(bars, k=2)
    assert any(s.kind == "high" for s in swings)
    assert any(s.kind == "low" for s in swings)


def test_efficiency_ratio_trend_vs_chop():
    trend = [_bar(i, 100 + i, 100 + i + 1, 99 + i, 100 + i) for i in range(30)]
    chop = [_bar(i, 100 + (i % 2), 101, 99, 100 + (i % 2)) for i in range(30)]
    assert efficiency_ratio(trend, 20) > efficiency_ratio(chop, 20)


def test_conditions_gate_blocks_chop():
    chop = [_bar(i, 100 + (i % 2) * 0.1, 100.2, 99.8, 100 + (i % 2) * 0.1)
            for i in range(60)]
    cond = assess_conditions(chop)
    assert cond.regime in ("dead", "ranging")


def test_killzone():
    assert current_killzone(datetime(2026, 6, 26, 9, 0)) == "NY AM"
    assert current_killzone(datetime(2026, 6, 26, 12, 15)) is None


def test_mss_detects_displacement_break():
    bars = [_bar(i, 100, 100.5, 99.5, 100) for i in range(20)]
    bars.append(_bar(20, 100, 108, 100, 107))   # big displacement up through swing highs
    assert detect_mss(bars, k=2) is Direction.BULL


def test_po3_bias_from_sweep():
    po3 = DailyPO3()
    # Asia accumulation (hour < 2).
    for i in range(5):
        b = Bar(datetime(2026, 6, 26, 0, i), 100, 101, 99, 100, 10, "ES")
        po3.update(b)
    # Manipulation: London hour sweeps Asia low then closes back up -> bullish bias.
    po3.update(Bar(datetime(2026, 6, 26, 3, 0), 100, 100.5, 98, 100.2, 10, "ES"))
    assert po3.bias is Direction.BULL


def test_position_sizing_respects_risk():
    s = Setup("ES", Side.LONG, entry=5000, stop=4990, targets=[5020],
              ts=datetime(2026, 6, 26, 9, 30), confluence=0.8)
    sized = position_size(s, equity=10_000, risk_pct=0.005)  # $50 budget
    # 10 pts * $50 = $500 risk/contract > $50 budget -> 0 full ES contracts.
    assert sized.qty == 0
    micro = position_size(s, equity=100_000, risk_pct=0.005, use_micros=True)
    assert micro.symbol == "MES" and micro.qty >= 1


def test_htf_resample_aggregates():
    from pb_trader.strategy.htf import resample
    # 30 one-minute bars -> resample to 15m should yield 2 candles.
    bars = [_bar(i, 100 + i, 101 + i, 99 + i, 100 + i) for i in range(30)]
    htf = resample(bars, 15)
    assert len(htf) == 2
    # First HTF candle's high is the max of its 15 constituents.
    assert htf[0].high == max(b.high for b in bars[:15])
    assert htf[0].open == bars[0].open and htf[0].close == bars[14].close


def test_order_block_from_bullish_fvg():
    from pb_trader.strategy.fvg import detect_fvgs
    from pb_trader.strategy.order_blocks import order_blocks_from_fvgs
    from pb_trader.models import Direction
    bars = [_bar(0, 100, 100.5, 98, 99),     # down candle -> demand OB origin
            _bar(1, 99, 105, 99, 104),        # displacement up
            _bar(2, 104, 106, 102, 105)]      # leaves bullish FVG
    fvgs = detect_fvgs(bars)
    obs = order_blocks_from_fvgs(bars, fvgs)
    assert any(o.direction is Direction.BULL for o in obs)


def test_ote_zone():
    from pb_trader.strategy.fib import in_ote
    from pb_trader.models import Side
    # Leg 100 -> 110. Long OTE zone = 110-7.9 .. 110-6.2 = [102.1, 103.8].
    assert in_ote(103.0, 100, 110, Side.LONG)
    assert not in_ote(108.0, 100, 110, Side.LONG)


def test_costs_reduce_pnl():
    from pb_trader.execution.paper import PaperBroker
    from pb_trader.models import Order, OrderType

    # Zero-cost broker vs realistic-cost broker on the same winning trade.
    free = PaperBroker(100_000, slippage_ticks=0)
    costed = PaperBroker(100_000, slippage_ticks=1)
    order = Order("ES", Side.LONG, 1, OrderType.MARKET, price=5000, stop=4990,
                  targets=[5020])
    t0 = datetime(2026, 6, 26, 9, 30)
    for b in (free, costed):
        b.submit_at(order, 5000, t0)
    exit_bar = Bar(datetime(2026, 6, 26, 10, 0), 5020, 5021, 5019, 5020, 100, "ES")
    ft = free.on_bar(exit_bar)[0]
    ct = costed.on_bar(exit_bar)[0]
    assert ct.commission > 0 and ct.slippage_cost > 0
    assert ct.pnl < ft.pnl                 # costs eat into profit
    assert costed.total_commission == 4.0  # ES round-turn


def test_analytics_metrics():
    from pb_trader.analytics import compute_metrics
    from pb_trader.models import Trade
    t0 = datetime(2026, 6, 26, 9, 30)
    trades = [
        Trade("ES", Side.LONG, 1, 5000, 5020, t0, t0, pnl=100.0, r_multiple=2.0),
        Trade("ES", Side.LONG, 1, 5000, 4995, t0, t0, pnl=-50.0, r_multiple=-1.0),
        Trade("ES", Side.LONG, 1, 5000, 5010, t0, t0, pnl=50.0, r_multiple=1.0),
    ]
    m = compute_metrics(trades, 10_000)
    assert m.trades == 3 and m.wins == 2
    assert abs(m.profit_factor - (150 / 50)) < 1e-9   # gross profit 150 / loss 50
    assert m.net_pnl == 100.0
    assert len(m.equity_curve) == 4 and m.equity_curve[-1] == 10_100.0


def test_breaker_block():
    from pb_trader.models import Direction, OrderBlock
    from pb_trader.strategy.order_blocks import find_breakers
    bars = [_bar(i, 100, 101, 99, 100) for i in range(6)]
    bars.append(_bar(6, 100, 100, 95, 96))   # closes below the block -> breaker
    ob = OrderBlock(Direction.BULL, top=101, bottom=99, ts=bars[2].ts, index=2)
    breakers = find_breakers([ob], bars)
    assert breakers and breakers[0].direction is Direction.BEAR


def test_liquidity_void_detection():
    from pb_trader.strategy.voids import detect_voids
    from pb_trader.models import Direction
    # Calm bars then a huge bullish displacement leaving an oversized gap.
    bars = [_bar(i, 100, 100.3, 99.7, 100) for i in range(20)]
    bars.append(_bar(20, 100, 101, 100, 101))
    bars.append(_bar(21, 110, 116, 109, 115))   # big gap vs bars[19].high
    voids = detect_voids(bars, atr_n=14, mult=2.0)
    assert any(v.direction is Direction.BULL for v in voids)


def test_tradovate_root_symbol():
    from pb_trader.execution.tradovate_parse import root_symbol
    assert root_symbol("ESM6") == "ES"
    assert root_symbol("MNQU6") == "MNQ"
    assert root_symbol("MESZ6") == "MES"


def test_tradovate_parse_chart_bars():
    from pb_trader.execution.tradovate_parse import parse_chart_bars
    packet = {"charts": [{"id": 1, "bars": [
        {"timestamp": "2026-06-26T13:30:00.000Z", "open": 5500.0, "high": 5502.0,
         "low": 5499.5, "close": 5501.0, "upVolume": 100, "downVolume": 80},
        {"timestamp": "2026-06-26T13:31:00.000Z", "open": 5501.0, "high": 5503.0,
         "low": 5500.5, "close": 5502.5, "upVolume": 60, "downVolume": 40},
    ]}]}
    bars = parse_chart_bars(packet, "ES")
    assert len(bars) == 2
    assert bars[0].close == 5501.0 and bars[0].volume == 180
    assert bars[0].symbol == "ES" and bars[1].ts > bars[0].ts


def test_tradovate_parse_fill_pairs():
    from pb_trader.execution.tradovate_parse import parse_fill_pairs
    from pb_trader.models import Side
    pairs = [
        {"id": 1, "contractId": 99, "qty": 2, "buyPrice": 5000.0, "sellPrice": 5010.0,
         "active": False, "timestamp": "2026-06-26T14:00:00Z",
         "buyFillTimestamp": "2026-06-26T13:50:00Z", "sellFillTimestamp": "2026-06-26T14:00:00Z"},
        {"id": 2, "contractId": 99, "qty": 1, "buyPrice": 5020.0, "sellPrice": 5015.0,
         "active": True},   # still open -> ignored
    ]
    trades = parse_fill_pairs(pairs, {99: "MES"})
    assert len(trades) == 1
    t = trades[0]
    # (5010-5000)*2*$5 = $100; bought before sold -> long.
    assert t.symbol == "MES" and t.side is Side.LONG and t.pnl == 100.0


def test_goals_milestones():
    from pb_trader import goals
    assert goals.status(1_000).next_milestone == 10_000
    assert goals.status(25_000).stage == 1 and goals.status(25_000).next_milestone == 50_000
    assert goals.status(100_000).next_milestone is None
    # positive expectancy -> finite trade estimate; non-positive -> None
    assert goals.trades_to_next(1_000, 0.5, 0.02) > 0
    assert goals.trades_to_next(1_000, -0.1, 0.02) is None


def test_draw_on_liquidity():
    from datetime import datetime
    from pb_trader.models import Direction, LiquidityPool
    from pb_trader.strategy.liquidity_draw import draw_on_liquidity, classify_liquidity
    ts = datetime(2026, 6, 26)
    pools = [LiquidityPool(5100, "BSL", ts), LiquidityPool(5050, "EQH", ts),
             LiquidityPool(4950, "SSL", ts)]
    up = draw_on_liquidity(pools, 5000, Direction.BULL)
    assert up.price == 5050        # nearest buy-side above price
    dn = draw_on_liquidity(pools, 5000, Direction.BEAR)
    assert dn.price == 4950
    rl = classify_liquidity(pools, 4900, 5060)
    assert any(p.price == 5100 for p in rl.external)  # 5100 outside range
    assert any(p.price == 5050 for p in rl.internal)


def test_report_and_validate_smoke():
    from pb_trader.report import build_report
    txt = build_report(["ES", "NQ"], "synthetic", bars=2500, session="morning")
    assert "PB ELITE" in txt and "GOAL PROGRESS" in txt
    txt2 = build_report(["ES", "NQ"], "synthetic", bars=2500, session="afternoon")
    assert "AFTERNOON" in txt2


def test_walk_forward_runs():
    from pb_trader.walkforward import walk_forward
    res = walk_forward(["ES", "NQ"], bars=6000, folds=2, is_ratio=2,
                       min_trades=1, grid={"swing_k": [2, 3]})
    assert len(res.folds) == 2
    assert res.aggregate is not None
    # Each fold recorded a chosen parameter set and an OOS metric block.
    for f in res.folds:
        assert "swing_k" in f.params and f.oos is not None


def test_optimizer_runs_and_ranks():
    from pb_trader.optimize import optimize
    # Tiny grid + few bars keeps the unit test fast while exercising ranking logic.
    best = optimize(["ES", "NQ"], bars=1500, metric="expectancy_r",
                    min_trades=1, top=3, grid={"swing_k": [2, 3]})
    assert isinstance(best, list) and len(best) <= 3
    # Sorted descending by robust score.
    scores = [r.robust_score for r in best]
    assert scores == sorted(scores, reverse=True)


def test_validate_setup_min_rr():
    good = Setup("ES", Side.LONG, 5000, 4990, [5020], datetime(2026, 6, 26), 0.8)
    bad = Setup("ES", Side.LONG, 5000, 4990, [5005], datetime(2026, 6, 26), 0.8)
    assert validate_setup(good)[0] is True       # 1:2 ok
    assert validate_setup(bad, min_rr=1.0)[0] is False  # 1:0.5 rejected


def test_one_to_one_rr_allowed():
    # Per the account-growth plan we accept down to 1:1.
    one_r = Setup("ES", Side.LONG, 5000, 4990, [5010], datetime(2026, 6, 26), 0.8)
    assert one_r.rr() == 1.0
    assert validate_setup(one_r, min_rr=1.0)[0] is True


def test_aggressive_risk_flag():
    from pb_trader.config import Settings
    assert Settings(risk_pct=0.10).risk_is_aggressive is True
    assert Settings(risk_pct=0.005).risk_is_aggressive is False


def test_risk_ceiling_caps_size():
    # Even if env asked for 50%, sizing must clamp to the 5% ceiling.
    s = Setup("MES", Side.LONG, 5000, 4990, [5030], datetime(2026, 6, 26), 0.8)
    sized = position_size(s, equity=1_000, risk_pct=0.50)
    # 5% of $1000 = $50 budget; MES 10pt stop = $50/contract -> 1 contract, not 10.
    assert sized.qty == 1
