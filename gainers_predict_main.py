import threading
import time
import schedule
from concurrent.futures import ThreadPoolExecutor, wait, ALL_COMPLETED
from datetime import datetime, timedelta

from alert import send_beautiful_notification
from strategy import is_accumulation_phase_5m, is_real_volume_breakout_5m_strict
from state import StateManager, SignalState
from bn_tool import BNMonitor
from interal_enum import KlineInterval
from symbols import symbols


# -----------------------------
# 全局对象
# -----------------------------
bn_monitor = BNMonitor()
state_manager = StateManager()

MAX_WORKERS = 10
POLL_INTERVAL = 3  # 分钟

executor = ThreadPoolExecutor(max_workers=MAX_WORKERS)

job_running = False
job_lock = threading.Lock()


def calculate_start_time(hours: int) -> int:
    t = datetime.now() - timedelta(hours=hours)
    return int(t.timestamp() * 1000)

def process_symbol(symbol: str):
    try:
        start_time = calculate_start_time(20)
        klines = bn_monitor.getSymbolKlines(
            symbol,
            KlineInterval.MINUTE_5.value,
            start_time
        )
        if not klines:
            return

        # -----------------------------
        # 1️⃣ 爆发检测
        # -----------------------------
        yes, _ = is_real_volume_breakout_5m_strict(klines)
        if yes:
            info = state_manager.update(symbol, SignalState.BREAKOUT)
            # 只有从 ACCUM 进入 BREAKOUT 才告警
            if info['from_state'] == SignalState.ACCUM:
                duration_sec = info['accum_duration']
                duration_str = f"{duration_sec/60:.1f} 分钟"
                send_beautiful_notification(
                    f"🚀 爆发确认\n合约: {symbol}\n吸筹时长: {duration_str}",
                    subtitle="BREAKOUT"
                )
            return

        # -----------------------------
        # 2️⃣ 吸筹期归档（不告警）
        # -----------------------------
        if is_accumulation_phase_5m(klines):
            state_manager.update(symbol, SignalState.ACCUM)
            return

        # -----------------------------
        # 3️⃣ NONE 状态
        # -----------------------------
        state_manager.update(symbol, SignalState.NONE)

    except Exception as e:
        print(f"❌ {symbol} 异常: {e}")



def job():
    global job_running

    with job_lock:
        if job_running:
            print("⚠️ 上一轮任务未完成，跳过")
            return
        job_running = True

    try:
        futures = [executor.submit(process_symbol, s) for s in symbols]
        wait(futures, return_when=ALL_COMPLETED)
    finally:
        with job_lock:
            job_running = False


if __name__ == "__main__":
    print("🚀 程序启动，立即执行一次\n")
    job()

    schedule.every(POLL_INTERVAL).minutes.do(job)
    print(f"⏱️ 每 {POLL_INTERVAL} 分钟扫描一次")

    while True:
        schedule.run_pending()
        time.sleep(1)
