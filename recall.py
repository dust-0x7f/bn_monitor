from typing import List, Dict, Any, Tuple

from gainers_predict_main import bn_monitor, calculate_start_time
from interal_enum import KlineInterval
from process_symbol import SignalState
from strategy import is_accumulation_phase_5m, is_real_volume_breakout_5m_strict, trap_score_after_breakout


def backtest_one_symbol_5m(
    symbol: str,
    klines: List,  # List[KlineData]
    window_hours: int = 10,
    score_min: float = 60,
    trap_max: float = 70,
    confirm_bars: int = 2,
    pending_ttl_bars: int = 6,
) -> List[Dict[str, Any]]:
    """
    逐根K线回放（walk-forward）。
    返回 events 列表：记录策略在历史上每次产生的信号与决策。
    """

    BAR_MS = 5 * 60 * 1000
    WINDOW_MS = window_hours * 60 * 60 * 1000

    # 离线状态（不要用线程锁）
    state = SignalState.NONE
    accum_start_ms = None

    pending = None  # dict or None
    events = []

    def state_update(new_state: SignalState, now_ms: int) -> Tuple[SignalState, float]:
        """简化版状态机：用bar时间做duration。"""
        nonlocal state, accum_start_ms
        accum_dur = 0.0
        old = state

        if new_state == SignalState.ACCUM and old != SignalState.ACCUM:
            accum_start_ms = now_ms

        if old == SignalState.ACCUM and new_state == SignalState.BREAKOUT:
            if accum_start_ms is not None:
                accum_dur = (now_ms - accum_start_ms) / 1000.0
            accum_start_ms = None

        if new_state != SignalState.ACCUM and old == SignalState.ACCUM and new_state == SignalState.NONE:
            # 如果你想统计“吸筹被打断”也可以在这里算一次
            pass

        state = new_state
        return old, accum_dur

    # 从足够早的地方开始跑（保证 window_len 有数据）
    for i in range(len(klines)):
        now_ms = klines[i].open_time

        # 只用“当时能看到的窗口数据”（16小时）
        start_ms = now_ms - WINDOW_MS
        # 找窗口起点索引（简单线性，数据大可以二分）
        j = 0
        while j < i and klines[j].open_time < start_ms:
            j += 1
        view = klines[j:i+1]  # 当时可见数据

        # ========== 0) 先处理 pending（二次确认 / 诱多过滤） ==========
        if pending is not None:
            # 超时
            if now_ms - pending["created_ms"] > pending_ttl_bars * BAR_MS:
                events.append({
                    "t": now_ms,
                    "symbol": symbol,
                    "event": "PENDING_EXPIRE",
                    "score": pending["score"],
                })
                pending = None
            else:
                # 定位 breakout_bar
                bo_time = pending["breakout_open_time"]
                pos = None
                for k in range(len(view)-1, -1, -1):
                    if view[k].open_time == bo_time:
                        pos = k
                        break
                if pos is None:
                    events.append({"t": now_ms, "symbol": symbol, "event": "PENDING_LOST_BAR"})
                    pending = None
                else:
                    bars_after = view[pos:]
                    if len(bars_after) >= confirm_bars:
                        box_top = pending["box_top"]
                        eps = pending["break_eps"]
                        trap, detail = trap_score_after_breakout(bars_after[:3], box_top, eps=eps)
                        hold_ok = all(x.close_price > box_top * (1.0 + eps/2) for x in bars_after[:2])

                        if hold_ok and trap <= trap_max:
                            old, accum_dur = state_update(SignalState.BREAKOUT, now_ms)
                            events.append({
                                "t": now_ms,
                                "symbol": symbol,
                                "event": "BREAKOUT_CONFIRMED",
                                "from": old.name,
                                "score": pending["score"],
                                "trap": trap,
                                "accum_sec": accum_dur,
                            })
                            pending = None
                        elif detail.get("back_into_box"):
                            events.append({
                                "t": now_ms,
                                "symbol": symbol,
                                "event": "TRAP_KILL",
                                "score": pending["score"],
                                "trap": trap,
                                "detail": detail,
                            })
                            pending = None

        # ========== 1) 如果还没有 pending：用 strict 生成候选 ==========
        if pending is None:
            ok, binfo = is_real_volume_breakout_5m_strict(view)
            if ok:
                score = float(binfo.get("score", 0.0))
                if score >= score_min:
                    pending = {
                        "created_ms": now_ms,
                        "breakout_open_time": int(binfo["breakout_open_time"]),
                        "box_top": float(binfo["box_top"]),
                        "break_eps": float(binfo.get("break_eps", 0.003)),
                        "score": score,
                    }
                    events.append({
                        "t": now_ms,
                        "symbol": symbol,
                        "event": "PENDING_CREATE",
                        "score": score,
                        "box_top": pending["box_top"],
                    })
                    # 注意：这里不直接 BREAKOUT（因为你不追第一根）
                    continue

        # ========== 2) 吸筹归档 / NONE ==========
        if is_accumulation_phase_5m(view):
            old, _ = state_update(SignalState.ACCUM, now_ms)
            if old != SignalState.ACCUM:
                events.append({"t": now_ms, "symbol": symbol, "event": "ACCUM_START"})
        else:
            old, _ = state_update(SignalState.NONE, now_ms)
            # 你也可以记录 ACCUM_END / 回到NONE，但会很多日志

    return events


if __name__ == '__main__':
    klines = bn_monitor.getSymbolKlines("FHEUSDT",KlineInterval.MINUTE_5.value,calculate_start_time(24))

    events = backtest_one_symbol_5m("FHEUSDT", klines)
    print(events)
