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


def test_validate_setup_min_rr():
    good = Setup("ES", Side.LONG, 5000, 4990, [5020], datetime(2026, 6, 26), 0.8)
    bad = Setup("ES", Side.LONG, 5000, 4990, [5005], datetime(2026, 6, 26), 0.8)
    assert validate_setup(good)[0] is True
    assert validate_setup(bad)[0] is False
