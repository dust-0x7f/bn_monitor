import threading
import time
import schedule
from concurrent.futures import ThreadPoolExecutor, wait, ALL_COMPLETED
from datetime import datetime, timedelta

from alert import send_beautiful_notification
from strategy import (
    is_accumulation_phase_5m,
    is_real_volume_breakout_5m_strict,
    trap_score_after_breakout,
)
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


# 只处理新5m bar
LAST_SEEN = {}  # symbol -> last_open_time(ms)
LAST_SEEN_LOCK = threading.Lock()

# 突破候选缓存（不追第一根）
PENDING = {}  # symbol -> dict
PENDING_LOCK = threading.Lock()

# 参数（先用这套，后面根据实际触发量再调）
SCORE_MIN = 85          # strict 通过后，score 低于该值不进入候选
TRAP_MAX = 35           # trap_score 高于该值视为诱多，不报警
CONFIRM_BARS = 2        # 候选后至少等 2 根 5m bar 再确认
PENDING_TTL_BARS = 6    # 候选最多挂 6 根（30分钟）不确认就丢
BAR_MS = 5 * 60 * 1000


def _drop_unclosed_last_bar(klines):
    """
    如果最后一根是未收盘K线（close_time > now），丢弃它，避免信号抖动。
    """
    if not klines:
        return klines
    now = int(time.time() * 1000)
    try:
        if klines[-1].close_time > now:
            return klines[:-1]
    except Exception:
        # 如果 close_time 字段不可靠/不存在，就不处理
        pass
    return klines


def process_symbol(symbol: str):
    try:
        start_time = calculate_start_time(16)
        klines = bn_monitor.getSymbolKlines(symbol, KlineInterval.MINUTE_5.value, start_time)
        if not klines:
            return

        # 过滤未收盘最后一根，增强稳定性
        klines = _drop_unclosed_last_bar(klines)
        if not klines or len(klines) < 60:
            return

        now_ms = klines[-1].open_time

        # 只在新 5m bar 出现时处理
        with LAST_SEEN_LOCK:
            prev = LAST_SEEN.get(symbol)
            if prev is not None and now_ms == prev:
                return
            LAST_SEEN[symbol] = now_ms

        # -----------------------------
        # 0) 如果已有 pending：先做二次确认 + 诱多过滤
        # -----------------------------
        with PENDING_LOCK:
            pend = PENDING.get(symbol)

        if pend:
            created_ms = pend["created_ms"]
            box_top = float(pend["box_top"])
            eps = float(pend.get("break_eps", 0.001))
            score0 = float(pend.get("score", 0.0))
            bo_time = int(pend["breakout_open_time"])

            # 超时丢弃
            max_age_ms = PENDING_TTL_BARS * BAR_MS
            if now_ms - created_ms > max_age_ms:
                with PENDING_LOCK:
                    PENDING.pop(symbol, None)
                return

            # 找到 breakout_bar 在当前 klines 中的位置
            pos = None
            for i in range(len(klines) - 1, -1, -1):
                if klines[i].open_time == bo_time:
                    pos = i
                    break
            if pos is None:
                # 数据窗口不包含那根了（或接口变化），丢弃候选
                with PENDING_LOCK:
                    PENDING.pop(symbol, None)
                return

            bars_after = klines[pos + 1 :]
            if len(bars_after) < CONFIRM_BARS:
                return  # 还没等够确认根数

            # 诱多评分（取 2~3 根）
            trap, detail = trap_score_after_breakout(bars_after[:3], box_top, eps=eps)

            # 站稳：前两根收盘都要“明显在箱体上沿之上”
            last2 = bars_after[:2]
            hold_ok = all(k.close_price > box_top * (1.0 + eps / 2.0) for k in last2)

            if hold_ok and trap <= TRAP_MAX:
                # ✅ 真启动确认：报警 + 更新状态
                info = state_manager.update(symbol, SignalState.BREAKOUT, now_ms=now_ms)

                duration_str = ""
                if info.get("from_state") == SignalState.ACCUM and info.get("accum_duration", 0) > 0:
                    duration_str = f"\n吸筹时长: {info['accum_duration']/60:.1f} 分钟"

                send_beautiful_notification(
                    f"✅ 真启动确认\n合约: {symbol}{duration_str}\nScore: {score0:.0f}\nTrap: {trap:.0f}",
                    subtitle="BREAKOUT_CONFIRMED",
                )

                with PENDING_LOCK:
                    PENDING.pop(symbol, None)
                return

            # ❌ 诱多判死：跌回箱体直接清理
            if detail.get("back_into_box"):
                with PENDING_LOCK:
                    PENDING.pop(symbol, None)
                return

            # 还在观察期：不动
            return

        # -----------------------------
        # 1) 没有 pending：检测 strict（作为候选）
        # -----------------------------
        ok, binfo = is_real_volume_breakout_5m_strict(klines)
        if ok:
            score = float(binfo.get("score", 0.0))
            if score < SCORE_MIN:
                return

            box_top = binfo.get("box_top")
            if box_top is None:
                return

            bo_time = binfo.get("breakout_open_time")
            if bo_time is None:
                # 兜底（不建议走到这里）
                bo_time = klines[-1].open_time

            with PENDING_LOCK:
                PENDING[symbol] = {
                    "created_ms": now_ms,
                    "breakout_open_time": int(bo_time),
                    "box_top": float(box_top),
                    "break_eps": float(binfo.get("break_eps", 0.003)),
                    "score": float(score),
                }
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
