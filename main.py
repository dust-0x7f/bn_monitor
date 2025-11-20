from datetime import datetime, timedelta
import time
from typing import List, Optional, Tuple

import schedule

from alert import show_topmost_popup
from bn_tool import BNMonitor, KlineData, fail_symbols
from symbols import symbols

bn_monitor = BNMonitor()
POLL_INTERVAL = 5  # 定时任务间隔（分钟）
LOOK_BACK_MINUTES = 180 # 回溯时间（当前时间前30分钟）
KLINE_INTERVAL = 5  # K线周期（5分钟，与接口保持一致）
KLINE_LIMIT = 10  # 获取的K线总数（最后3根+前7根）
VOLUME_MULTIPLE = 3  # 成交量倍数阈值

NEWEST_KLINES_COUNT = 5


def calculate_start_time(specified_time: Optional[str] = None) -> int:
    TIME_FORMAT = "%Y-%m-%d %H:%M"
    """
    计算startTimeUnix：
    - 若传入specified_time（格式YYYY-MM-DD HH:mm），则用该时间对齐到5分钟整
    - 若未传入，则用当前时间前30分钟对齐到5分钟整
    """
    if specified_time:
        # 解析指定时间
        try:
            target_time = datetime.strptime(specified_time, TIME_FORMAT)
            print(f"\n📅 已指定时间：{target_time.strftime(TIME_FORMAT)}")
        except ValueError:
            raise ValueError(f"❌ 指定时间格式错误！请使用 {TIME_FORMAT}（如 2025-11-19 22:00）")
    else:
        # 无指定时间：当前时间前30分钟
        target_time = datetime.now() - timedelta(minutes=LOOK_BACK_MINUTES)
        print(f"\n📅 未指定时间，使用当前时间前{LOOK_BACK_MINUTES}分钟：{target_time.strftime(TIME_FORMAT)}")

    # 对齐到5分钟整数倍（核心逻辑不变）
    aligned_minute = (target_time.minute // KLINE_INTERVAL) * KLINE_INTERVAL
    aligned_time = target_time.replace(
        minute=aligned_minute,
        second=0,
        microsecond=0
    )
    start_time_unix = int(aligned_time.timestamp() * 1000)

    # 打印结果
    print(f"📅 对齐后时间：{aligned_time.strftime('%Y-%m-%d %H:%M:%S')} → 时间戳：{start_time_unix}")
    return start_time_unix


def job(specified_time: Optional[str] = None):
    """定时任务核心逻辑：遍历symbols，获取K线数据"""

    # 计算startTimeUnix（支持指定时间）
    start_time_unix = calculate_start_time(specified_time)
    result = []  # 存储满足条件的symbol
    volume_analysis = []  # 存储详细的成交量分析结果

    # 2. 遍历所有symbol，逐个获取K线
    for symbol in symbols:
        # 获取KlineData列表
        klines = bn_monitor.getSymbol5MinutesKlines(symbol, start_time_unix)
        if not klines:
            print(f"⚠️ {symbol} 未获取到有效K线数据")
            time.sleep(0.5)
            continue

        # 检查成交量条件，并获取详细分析
        meet_condition = check_volume_condition(klines, symbol)
        if meet_condition:
            result.append(symbol)

        time.sleep(0.5)  # 循环间隔0.5秒

    # 过滤条件：满足条件的symbol数量不超过总数量的一半（保持原有逻辑）
    if len(result) > 10 :
        return

    msg = '\n'.join(result)
    show_topmost_popup(msg)

    # 打印最终结果（包含详细成交量分析）
    print("\n" + "=" * 80)
    print(f"🚨 满足条件的合约列表（共 {len(result)} 个）：")
    print("=" * 80)
    if volume_analysis:
        for idx, analysis in enumerate(volume_analysis, 1):
            print(f"\n{idx}. 合约：{analysis['symbol']}")
    else:
        print("📭 暂无满足成交量条件的合约")
    print("=" * 80 + "\n")


def check_last_k_volume(kines: List[KlineData]) -> bool:
    return kines[-1].volume > 5 * sum([k.volume for k in kines[:-1]]) / len(kines[:-1])

def check_sum_volume(klines: List[KlineData]) -> bool:
    last_3_klines = klines[3:]
    prev_klines = klines[:-3]
    return sum([k.volume for k in last_3_klines]) >  sum([k.volume for k in prev_klines])

def check_avg_volume_2h(klines: List[KlineData]) -> bool:
    # 分割最后3根和历史K线
    last_3_klines = klines[-NEWEST_KLINES_COUNT:]
    prev_klines = klines[:-NEWEST_KLINES_COUNT]
    avg_last_3 = round(sum([k.volume for k in last_3_klines]) / NEWEST_KLINES_COUNT, 6)
    avg_prev = round(sum([k.volume for k in prev_klines]) / len(prev_klines), 6)
    if avg_prev == 0:
        return False
    return avg_last_3 >= avg_prev * VOLUME_MULTIPLE


def check_volume_condition(klines: List[KlineData], symbol: str) -> bool:
    return check_sum_volume(klines) or check_avg_volume_2h(klines) or check_last_k_volume(klines)


if __name__ == "__main__":
    # 1. 立即执行一次任务（可选）
    print("🚀 程序启动，立即执行一次任务...")
    job( )
    print(fail_symbols)

    # 2. 配置定时任务：每POLL_INTERVAL分钟执行一次
    schedule.every(POLL_INTERVAL).minutes.do(job)
    print(f"\n⏱️  定时任务已配置：每{POLL_INTERVAL}分钟执行一次")

    # 3. 持续运行定时任务
    while True:
        schedule.run_pending()  # 检查是否有任务需要执行
        time.sleep(1)  # 避免CPU占用过高

