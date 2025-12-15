# replay_engine.py
from state import SignalState
from strategy import (
    is_accumulation_phase_5m,
    is_real_volume_breakout_5m_strict,
    trap_score_after_breakout,
)

BAR_MS = 5 * 60 * 1000


def step_symbol(
    runtime,            # SymbolRuntimeState
    klines_view,        # 截止当前 bar 的 K 线视图
    now_ms,
    *,
    score_min,
    trap_max,
    confirm_bars,
    pending_ttl_bars,
):
    """
    核心状态推进函数（一个 bar 一次）
    """
    events = []

    # ========== 0) pending 二次确认 ==========
    if runtime.pending is not None:
        pend = runtime.pending

        # TTL
        if now_ms - pend["created_ms"] > pending_ttl_bars * BAR_MS:
            runtime.pending = None
        else:
            bo_time = pend["breakout_open_time"]
            pos = None
            for i in range(len(klines_view)-1, -1, -1):
                if klines_view[i].open_time == bo_time:
                    pos = i
                    break

            if pos is None:
                runtime.pending = None
            else:
                bars_after = klines_view[pos+1:]
                if len(bars_after) >= confirm_bars:
                    box_top = pend["box_top"]
                    eps = pend["break_eps"]

                    trap, detail = trap_score_after_breakout(
                        bars_after[:3], box_top, eps=eps
                    )

                    hold_ok = all(
                        k.close_price > box_top * (1.0 + eps/2)
                        for k in bars_after[:2]
                    )

                    if hold_ok and trap <= trap_max:
                        runtime.enter_breakout(now_ms)
                        runtime.last_alert_ms = now_ms
                        runtime.pending = None
                        events.append(("BREAKOUT_CONFIRMED", pend, trap))

                    elif detail.get("back_into_box"):
                        runtime.pending = None

    # ========== 1) strict → 生成候选 ==========
    if runtime.pending is None:
        ok, binfo = is_real_volume_breakout_5m_strict(klines_view)
        if ok:
            score = float(binfo["score"])
            if score >= score_min:
                runtime.pending = {
                    "created_ms": now_ms,
                    "breakout_open_time": int(binfo["breakout_open_time"]),
                    "box_top": float(binfo["box_top"]),
                    "break_eps": float(binfo.get("break_eps", 0.003)),
                    "score": score,
                }

    # ========== 2) ACCUM / NONE ==========
    if runtime.pending is None:
        if is_accumulation_phase_5m(klines_view):
            runtime.enter_accum(now_ms)
        else:
            if runtime.state != SignalState.BREAKOUT:
                runtime.enter_none()

    runtime.last_seen_ms = now_ms
    return events
