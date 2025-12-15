# warmup.py
from replay_engine import step_symbol
from state import SymbolRuntimeState

def replay_symbol(
    klines,
    *,
    lookback_hours,
    score_min,
    trap_max,
    confirm_bars,
    pending_ttl_bars,
):
    runtime = SymbolRuntimeState()
    WINDOW_MS = lookback_hours * 60 * 60 * 1000

    for i in range(len(klines)):
        now_ms = klines[i].open_time
        start_ms = now_ms - WINDOW_MS

        j = 0
        while j < i and klines[j].open_time < start_ms:
            j += 1

        view = klines[j:i+1]
        if len(view) < 60:
            continue

        events = step_symbol(
            runtime,
            view,
            now_ms,
            score_min=score_min,
            trap_max=trap_max,
            confirm_bars=confirm_bars,
            pending_ttl_bars=pending_ttl_bars,
        )

        for _,v in events:
            print(v)

    # 如果是测试文件进来的，就直接打印把
    return runtime
