# monitor.py
import time
import threading
from typing import Optional

import schedule
from concurrent.futures import ThreadPoolExecutor

from bn_tool import BNMonitor
from interal_enum import KlineInterval
from symbols import symbols

from warm_up import replay_symbol
from replay_engine import step_symbol
from alert import send_beautiful_notification

# ========= 参数 =========
LOOKBACK_HOURS = 24
SCORE_MIN = 80
TRAP_MAX = 150  # 正常应该是70
CONFIRM_BARS = 2
PENDING_TTL_BARS = 6
MAX_WORKERS = 10
POLL_INTERVAL = 3

bn = BNMonitor()
executor = ThreadPoolExecutor(max_workers=MAX_WORKERS)

RUNTIME = {}   # symbol -> SymbolRuntimeState
LOCK = threading.Lock()


def init_warmup(specific_symbol:Optional[str] = None):
    print("🔥 warmup replay...")
    start_ms = int(time.time() * 1000) - LOOKBACK_HOURS * 3600 * 1000

    # if specific_symbol is not None:
    #     symbols = [specific_symbol]

    for s in symbols:
        kl = bn.getSymbolKlines(s, KlineInterval.MINUTE_5.value, start_ms)
        if not kl or len(kl) < 60:
            continue

        runtime = replay_symbol(
            kl,
            lookback_hours=LOOKBACK_HOURS,
            score_min=SCORE_MIN,
            trap_max=TRAP_MAX,
            confirm_bars=CONFIRM_BARS,
            pending_ttl_bars=PENDING_TTL_BARS,
        )
        RUNTIME[s] = runtime

    print("✅ warmup done")


def process_symbol(symbol):
    runtime = RUNTIME[symbol]
    kl = bn.getSymbolKlines(symbol, KlineInterval.MINUTE_5.value, runtime.last_seen_ms)
    if not kl or len(kl) < 2:
        return

    # 只取新增的 bar
    new_bars = [k for k in kl if k.open_time > runtime.last_seen_ms]
    for bar in new_bars:
        view = kl[: kl.index(bar)+1]
        events = step_symbol(
            runtime,
            view,
            bar.open_time,
            score_min=SCORE_MIN,
            trap_max=TRAP_MAX,
            confirm_bars=CONFIRM_BARS,
            pending_ttl_bars=PENDING_TTL_BARS,
        )

        for evt, pend, trap in events:
            send_beautiful_notification(
                f"🚀 真启动\n{symbol}\nScore:{pend['score']:.0f}\nTrap:{trap:.0f}",
                subtitle="BREAKOUT"
            )


def job():
    for s in symbols:
        executor.submit(process_symbol, s)


if __name__ == "__main__":
    # init_warmup()
    job()
    schedule.every(POLL_INTERVAL).minutes.do(job)
    while True:
        schedule.run_pending()
        time.sleep(1)
