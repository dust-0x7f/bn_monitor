import threading
from datetime import datetime, timedelta
import time
from typing import List, Optional, Tuple

import schedule

from alert import send_beautiful_notification
from bn_tool import BNMonitor
from interal_enum import KlineInterval
from qps_limiter import QPSLimiter
from strategy import check_sum_volume, check_avg_volume, check_last_k_volume, check_increase
from symbols import symbols
from concurrent.futures import ThreadPoolExecutor, wait, ALL_COMPLETED

bn_monitor = BNMonitor()
POLL_INTERVAL = 1  # 定时任务间隔（分钟）
LOOK_BACK_MINUTES = 90 # 回溯时间（当前时间前30分钟）
KLINE_INTERVAL = 3  # K线周期（5分钟，与接口保持一致）

# 1. 创建所有线程
MAX_QPS = 9  # 限制≤10QPS
MAX_WORKERS = 9  # 线程池最大并发数（建议等于MAX_QPS）
# 1. 创建线程池（限制并发数）
executor = ThreadPoolExecutor(max_workers=MAX_WORKERS)



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
        except ValueError:
            raise ValueError(f"❌ 指定时间格式错误！请使用 {TIME_FORMAT}（如 2025-11-19 22:00）")
        target_time = target_time - timedelta(hours=delta_hours,minutes=delta_minutes)
    else:
        # 无指定时间：当前时间前30分钟
        target_time = datetime.now() - timedelta(hours=delta_hours,minutes=delta_minutes)

    return int(target_time.timestamp() * 1000)


def job(specified_time: Optional[str] = None,specified_symbol: Optional[str] = None):
    """定时任务核心逻辑：遍历symbols，获取K线数据"""

    # 计算startTimeUnix（支持指定时间）
    start_time_unix = calculate_start_time(specified_time,pre_delta_minutes=90)
    result = []  # 存储满足条件的symbol
    lock = threading.Lock()  # 线程锁，保证result安全
    qps_limiter = QPSLimiter(MAX_QPS)

    # 2. 遍历所有symbol，逐个获取K线
    if specified_symbol:
        process_symbol(specified_symbol,start_time_unix,result,lock,qps_limiter)
    else:
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
    if len(result) > 0:
        result_symbols_str = ",".join(result)
        send_beautiful_notification(message=f"二级告警{result_symbols_str}")
        print("\n" + "=" * 80)
        ans = '\n'.join(result)
        print(f"{ans} 满足条件")
        print("\n" + "=" * 80)



def process_symbol(symbol, start_time_unix, result, lock, qps_limiter):
    """单个symbol的处理逻辑（线程执行体）"""
    try:
        # 先获取QPS许可（核心：控制请求速率）
        qps_limiter.acquire()

        # 获取KlineData列表（完全复用你的代码）
        klines_3min = bn_monitor.getSymbolKlines(symbol,KlineInterval.MINUTE_3.value, start_time_unix)
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

            def check1Minutes():
                klines_1min = bn_monitor.getSymbolKlines(symbol,KlineInterval.MINUTE_1.value,calculate_start_time(pre_delta_minutes=20))
                if klines_1min[-1].buy_volume > 5 * sum(v.buy_volume for v in klines_1min[:-1]):
                    return False
                if klines_1min[-1].close_price > 2 * sum(v.close_price for v in klines_1min[:-1]):
                    return True
                return False

            def check4Hours():
                klines_4_hours = bn_monitor.getSymbolKlines(symbol, KlineInterval.HOUR_4.value,pre_4hours_unix)
                if klines_4_hours[-1].volume > sum(v.volume for v in klines_4_hours[:-1]) / (len(klines_4_hours) - 1):
                    return True

                # 线程安全添加结果
            if check1Minutes() and check4Hours():
                with lock:
                    send_beautiful_notification(message=f"一级异常提醒:\n 合约: {symbol}")
            result.append(symbol)

    except Exception as e:
        print(f"❌ {symbol} 处理异常：{e}")




if __name__ == "__main__":
    # 1. 立即执行一次任务（可选）
    print("🚀 程序启动，立即执行一次任务...\n")
    job()
    # 2. 配置定时任务：每POLL_INTERVAL分钟执行一次
    schedule.every(POLL_INTERVAL).minutes.do(job)
    print(f"⏱️  定时任务已配置：每{POLL_INTERVAL}分钟执行一次")

    # 3. 持续运行定时任务
    while True:
        schedule.run_pending()  # 检查是否有任务需要执行


