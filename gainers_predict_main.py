import threading
import time
import schedule
from concurrent.futures import ThreadPoolExecutor, wait, ALL_COMPLETED
from datetime import datetime, timedelta

from alert import send_beautiful_notification
from strategy import detect_phase_event_5m, detect_phase_event_5m_at_time, str_to_ms
from state import StateManager, SignalState
from bn_tool import BNMonitor
from interal_enum import KlineInterval
from symbols import symbols


# -----------------------------
# 全局对象
# -----------------------------
bn_monitor = BNMonitor()
state_manager = StateManager()

global_breakout_symbol_cache = {

}

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
        start_time = calculate_start_time(30)
        # end_time = calculate_start_time()

        # start_time = str_to_ms("2025-12-14 10:00")
        # end_time = str_to_ms("2025-12-15 9:50")
        klines = bn_monitor.getSymbolKlines(
            symbol,
            KlineInterval.MINUTE_5.value,
            start_time,
        )
        if not klines:
            return

        # -----------------------------
        # 1️⃣ 爆发检测
        # -----------------------------

        # event, info = detect_phase_event_5m_at_time(klines,time_str="2025-12-15 18:40")
        event, info = detect_phase_event_5m(klines)
        if event == "ACCUM":
             # 告警：进入吸筹（info 里有 accum_start/end）
            # print(f"{symbol}吸筹")
            pass
        elif event == "BREAKOUT":
            def now_ms():
                return int(time.time() * 1000)
            now = now_ms()

            breakout_open_time = int(info["breakout_open_time"])  # ms
            now = now_ms()

            # ❶ 时间窗口过滤：不是“新发生”的，直接忽略
            ALERT_WINDOW_MS = 5 * 60 * 1000  # 5 分钟
            if now - breakout_open_time > ALERT_WINDOW_MS:
                return
             # 告警：发生突破（info["breakout_open_time"]）
            break_out_time = datetime.fromtimestamp(info['breakout_open_time'] / 1000).strftime("%Y-%m-%d %H:%M")
            print(f"🚀 爆发确认合约: {symbol}爆发时间点:{break_out_time}\n")
            send_beautiful_notification(
                f"🚀 爆发确认\n合约: {symbol}\n爆发时间点:{break_out_time}",
                subtitle="BREAKOUT"
            )


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
