import threading
import time
import schedule
from concurrent.futures import ThreadPoolExecutor, wait, ALL_COMPLETED
from datetime import datetime, timedelta

from alert import send_beautiful_notification
from strategy import is_accumulation_phase_5m, is_real_volume_breakout_5m_strict, trap_score_after_breakout
from state import StateManager, SignalState
from bn_tool import BNMonitor
from interal_enum import KlineInterval
from symbols import symbols

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

# 只处理新5m bar
LAST_SEEN = {}
LAST_SEEN_LOCK = threading.Lock()

# 突破候选缓存：只要候选还在，就不追第一根
PENDING = {}   # symbol -> dict
PENDING_LOCK = threading.Lock()

# 参数：你可以先用这套
SCORE_MIN = 85               # 候选门槛：启动质量
TRAP_MAX = 35                # 诱多阈值：越低越严格（建议 25~40 之间试）
CONFIRM_BARS = 2             # 突破后至少等2根（10分钟）再确认
PENDING_TTL_BARS = 6         # 30分钟内不确认就丢（避免一直挂着）
BAR_MS = 5 * 60 * 1000

def process_symbol(symbol: str):
    try:
        start_time = calculate_start_time(16)
        klines = bn_monitor.getSymbolKlines(symbol, KlineInterval.MINUTE_5.value, start_time)
        if not klines or len(klines) < 50:
            return

        now_ms = klines[-1].open_time

        # 只在新5m K 出现时处理
        with LAST_SEEN_LOCK:
            prev = LAST_SEEN.get(symbol)
            if prev is not None and now_ms == prev:
                return
            LAST_SEEN[symbol] = now_ms

        # -----------------------------
        # 0) 如果已经有 pending：优先做“二次确认 + 诱多过滤”
        # -----------------------------
        with PENDING_LOCK:
            pend = PENDING.get(symbol)

        if pend:
            box_top = pend["box_top"]
            bidx = pend["breakout_idx_in_window"]  # 在当前窗口 w 内的 index
            created_ms = pend["created_ms"]
            score0 = pend["score"]

            # 超时丢弃
            max_age_ms = PENDING_TTL_BARS * BAR_MS
            if now_ms - created_ms > max_age_ms:
                with PENDING_LOCK:
                    PENDING.pop(symbol, None)
                return

            # 取“突破后的bars”
            # 注意：bidx 是 pend 创建时基于当时 window 的索引；现在 klines 可能长度变化
            # 所以我们改成用 breakout_open_time 来定位更稳
            bo_time = pend["breakout_open_time"]
            # 找到 breakout bar 在当前 klines 里的位置
            pos = None
            for i in range(len(klines)-1, -1, -1):
                if klines[i].open_time == bo_time:
                    pos = i
                    break
            if pos is None:
                # 找不到（数据截断/接口变动），丢弃
                with PENDING_LOCK:
                    PENDING.pop(symbol, None)
                return

            bars_after = klines[pos+1:]
            if len(bars_after) < CONFIRM_BARS:
                return  # 还没等够确认根数

            # 诱多评分
            trap, detail = trap_score_after_breakout(bars_after[:3], box_top)

            # 站稳条件：最近2根收盘都在箱体上沿之上（防假突破）
            last2 = bars_after[:2]
            hold_ok = all(k.close_price > box_top for k in last2)

            if hold_ok and trap <= TRAP_MAX:
                # ✅ 通过确认：现在才算“真启动”
                info = state_manager.update(symbol, SignalState.BREAKOUT, now_ms=now_ms)

                # 你仍然可以优先只从ACCUM->BREAKOUT报警，但我建议真启动就报
                duration_str = ""
                if info["from_state"] == SignalState.ACCUM and info["accum_duration"] > 0:
                    duration_str = f"\n吸筹时长: {info['accum_duration']/60:.1f} 分钟"

                send_beautiful_notification(
                    f"✅ 真启动确认\n合约: {symbol}{duration_str}\nScore: {score0:.0f}\nTrap: {trap:.0f}",
                    subtitle="BREAKOUT_CONFIRMED"
                )

                with PENDING_LOCK:
                    PENDING.pop(symbol, None)
                return

            # ❌ 诱多判死：跌回箱体直接清
            if detail.get("back_into_box"):
                with PENDING_LOCK:
                    PENDING.pop(symbol, None)
                # 你也可以选择发一个“诱多提示”，但可能太吵，这里默认不发
                return

            # 没确认也没判死：继续等待
            return

        # -----------------------------
        # 1) 没有 pending 才做“突破候选”检测（不追第一根）
        # -----------------------------
        ok, binfo = is_real_volume_breakout_5m_strict(klines)
        if ok:
            score = float(binfo.get("score", 0.0))
            if score < SCORE_MIN:
                return

            box_top = binfo.get("box_top")
            if box_top is None:
                # strict info 必须带 box_top，否则无法做诱多确认
                return

            # 创建 pending：等后续2根确认
            with PENDING_LOCK:
                PENDING[symbol] = {
                    "created_ms": now_ms,
                    "breakout_open_time": klines[-1].open_time,  # 当前触发那根bar
                    "box_top": float(box_top),
                    "score": score,
                    "breakout_idx_in_window": len(klines) - 1,
                }

            # 同时更新状态（可选）：这里先不切到 BREAKOUT，避免状态机混乱
            # 你可以标记为 ACCUM 或保持原样；这里保持原样不动
            return

        # -----------------------------
        # 2) 吸筹期归档（不告警）
        # -----------------------------
        if is_accumulation_phase_5m(klines):
            state_manager.update(symbol, SignalState.ACCUM, now_ms=now_ms)
            return

        # -----------------------------
        # 3) NONE 状态
        # -----------------------------
        state_manager.update(symbol, SignalState.NONE, now_ms=now_ms)

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
