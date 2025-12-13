import threading
from datetime import datetime, timedelta
import time
from typing import List, Optional, Tuple

import schedule

from alert import pop_up
from bn_tool import BNMonitor, KlineData, fail_symbols
from qps_limiter import QPSLimiter
from symbols import symbols

bn_monitor = BNMonitor()
POLL_INTERVAL = 1  # 定时任务间隔（分钟）
LOOK_BACK_MINUTES = 90 # 回溯时间（当前时间前30分钟）
KLINE_INTERVAL = 5  # K线周期（5分钟，与接口保持一致）
KLINE_LIMIT = 10  # 获取的K线总数（最后3根+前7根）
VOLUME_MULTIPLE = 3  # 成交量倍数阈值

NEWEST_KLINES_COUNT = 5


def calculate_start_time(specified_time: Optional[str] = None, pre_delta_minutes: Optional[int] = None, pre_delta_hours: Optional[int] = None) -> int:
    TIME_FORMAT = "%Y-%m-%d %H:%M"
    """
    计算startTimeUnix：
    - 若传入specified_time（格式YYYY-MM-DD HH:mm），则用该时间对齐到5分钟整
    - 若未传入，则用当前时间前30分钟对齐到5分钟整
    """
    delta_hours = pre_delta_hours if pre_delta_hours is not None else 0
    delta_minutes = pre_delta_minutes if pre_delta_minutes is not None else 0
    if specified_time:
        # 解析指定时间
        try:
            target_time = datetime.strptime(specified_time, TIME_FORMAT)
            # print(f"\n📅 已指定时间：{target_time.strftime(TIME_FORMAT)}")
        except ValueError:
            raise ValueError(f"❌ 指定时间格式错误！请使用 {TIME_FORMAT}（如 2025-11-19 22:00）")
    else:
        # 无指定时间：当前时间前30分钟
        target_time = datetime.now() - timedelta(hours=delta_hours,minutes=delta_minutes)
        # print(f"\n📅 未指定时间，使用当前时间前{LOOK_BACK_MINUTES}分钟：{target_time.strftime(TIME_FORMAT)}")

    # 对齐到5分钟整数倍（核心逻辑不变）
    aligned_minute = (target_time.minute // KLINE_INTERVAL) * KLINE_INTERVAL
    aligned_time = target_time.replace(
        minute=aligned_minute,
        second=0,
        microsecond=0
    )
    start_time_unix = int(aligned_time.timestamp() * 1000)

    # 打印结果
    # print(f"📅 对齐后时间：{aligned_time.strftime('%Y-%m-%d %H:%M:%S')} → 时间戳：{start_time_unix}")
    return start_time_unix


def job(specified_time: Optional[str] = None,specified_symbol: Optional[str] = None):
    """定时任务核心逻辑：遍历symbols，获取K线数据"""

    # 计算startTimeUnix（支持指定时间）
    start_time_unix = calculate_start_time(specified_time,pre_delta_minutes=90)
    result = []  # 存储满足条件的symbol

    # 2. 遍历所有symbol，逐个获取K线
    if specified_symbol:
        klines_3min = bn_monitor.getSymbol3MinutesKlines(specified_symbol, start_time_unix)
        if not klines_3min:
            print(f"⚠️ {specified_symbol} 未获取到有效K线数据")
            time.sleep(0.5)
        # 检查成交量条件，并获取详细分析
        volume_check = 0
        if check_sum_volume(klines_3min):
            volume_check |= 1
        elif check_avg_volume(klines_3min):
            volume_check |= 2
        elif check_last_k_volume(klines_3min):
            volume_check |= 4
        if volume_check > 0 and  check_increase(klines_3min):
            result.append(specified_symbol)
    else:
        from concurrent.futures import ThreadPoolExecutor, wait, ALL_COMPLETED
        lock = threading.Lock()  # 线程锁，保证result安全
        # 1. 创建所有线程
        MAX_QPS = 10  # 限制≤10QPS
        MAX_WORKERS = 10  # 线程池最大并发数（建议等于MAX_QPS）
        qps_limiter = QPSLimiter(MAX_QPS)

        # 1. 创建线程池（限制并发数）
        executor = ThreadPoolExecutor(max_workers=MAX_WORKERS)
        # 2. 提交所有symbol的处理任务
        futures = []
        for symbol in symbols:
            future = executor.submit(
                process_symbol,
                symbol, start_time_unix, result, lock, qps_limiter
            )
            futures.append(future)

        # 3. 等待所有任务执行完毕（所有symbol处理完才停止）
        wait(futures, return_when=ALL_COMPLETED)
        executor.shutdown()  # 关闭线程池
        if len(result) > 0:
            pop_up(','.join(result))
            print("\n" + "=" * 80)
            ans = '\n'.join(result)
            print(f"{ans} 满足条件")
            print("\n" + "=" * 80)



def check_last_k_volume(kines: List[KlineData]) -> bool:
    return kines[-1].volume > 5 * sum([k.volume for k in kines[:-1]]) / len(kines[:-1])

def check_sum_volume(klines: List[KlineData]) -> bool:
    last_3_klines = klines[-3:]
    prev_klines = klines[:-3]
    return sum([k.volume for k in last_3_klines]) >  sum([k.volume for k in prev_klines])

def check_avg_volume(klines: List[KlineData]) -> bool:
    # 分割最后3根和历史K线
    last_3_klines = klines[-NEWEST_KLINES_COUNT:]
    prev_klines = klines[:-NEWEST_KLINES_COUNT]
    avg_last_3 = round(sum([k.volume for k in last_3_klines]) / NEWEST_KLINES_COUNT, 6)
    avg_prev = round(sum([k.volume for k in prev_klines]) / len(prev_klines), 6)
    if avg_prev == 0:
        return False
    return avg_last_3 >= avg_prev * VOLUME_MULTIPLE

# 当前收盘价大于前面所有k线的平均收盘价
def check_increase(klines: List[KlineData]) -> bool:
    close_price = klines[-1].close_price
    prev_klines = klines[:-1]
    avg_prev_close = sum(k.close_price for k in prev_klines) / len(prev_klines)
    if close_price > avg_prev_close:
        return True
    return False


def check_volume_condition(klines: List[KlineData], symbol: str) -> bool:
    return (check_sum_volume(klines) or check_avg_volume(klines) or check_last_k_volume(klines)) and \
        check_increase(klines)

def check_last_3min_klines_increase(klines: List[KlineData]) -> bool:
    last_3_klines = klines[-3:]
    for i in range(1,len(last_3_klines)):
        pre = last_3_klines[i - 1]
        now = last_3_klines[i]
        if not (now.close_price > now.open_price and pre.close_price > pre.open_price):
            return False
    return True


def process_symbol(symbol, start_time_unix, result, lock, qps_limiter):
    """单个symbol的处理逻辑（线程执行体）"""
    try:
        # 先获取QPS许可（核心：控制请求速率）
        qps_limiter.acquire()

        # 获取KlineData列表（完全复用你的代码）
        klines_3min = bn_monitor.getSymbol3MinutesKlines(symbol, start_time_unix)
        if not klines_3min:
            print(f"⚠️ {symbol} 未获取到有效K线数据")
            time.sleep(0.5)
            return

        # 检查成交量条件，并获取详细分析（完全复用）
        volume_check = 0
        if check_sum_volume(klines_3min):
            volume_check |= 1
        elif check_avg_volume(klines_3min):
            volume_check |= 2
        elif check_last_k_volume(klines_3min):
            volume_check |= 4

        if volume_check > 0 and check_increase(klines_3min):
            # 再次控QPS（4小时线请求也计入QPS）
            qps_limiter.acquire()
            pre_4hours_unix = calculate_start_time(pre_delta_hours=4 * 20)
            # 然后去check4小时线（完全复用）
            klines_4_hours = bn_monitor.getSymbol4HoursKlines(symbol, pre_4hours_unix)
            if klines_4_hours[-1].volume > sum(v.volume for v in klines_4_hours[:-1]) / (len(klines_4_hours) - 1):
                # 线程安全添加结果
                with lock:
                    result.append(symbol)

                # 非常重要（完全复用）
                if check_last_3min_klines_increase(klines_3min):
                    pop_up(symbol)
    except Exception as e:
        print(f"❌ {symbol} 处理异常：{e}")


if __name__ == "__main__":
    # 1. 立即执行一次任务（可选）
    print("🚀 程序启动，立即执行一次任务...")
    job()
    # 2. 配置定时任务：每POLL_INTERVAL分钟执行一次
    schedule.every(POLL_INTERVAL).minutes.do(job)
    print(f"\n⏱️  定时任务已配置：每{POLL_INTERVAL}分钟执行一次")

    # 3. 持续运行定时任务
    while True:
        schedule.run_pending()  # 检查是否有任务需要执行


