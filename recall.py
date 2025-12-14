from datetime import datetime, timedelta
from typing import List
import csv

from bn_tool import BNMonitor
from interal_enum import KlineInterval
from strategy import KlineData, is_accumulation_phase_5m, is_real_volume_breakout_5m
from state import SignalState, StateManager

def backtest_symbol(symbol: str, end_time_str: str):
    """
    回测单个 symbol，使用 end_time 向前 8 小时的 K 线
    :param symbol: 交易对
    :param end_time_str: 结束时间，格式 "YYYY-MM-DD HH:MM"
    """
    TIME_FORMAT = "%Y-%m-%d %H:%M"
    end_dt = datetime.strptime(end_time_str, TIME_FORMAT)
    start_fetch_dt = end_dt - timedelta(hours=8)
    start_fetch_unix = int(start_fetch_dt.timestamp() * 1000)

    bn_monitor = BNMonitor()
    state_manager = StateManager()

    # 获取 K 线
    klines: List[KlineData] = bn_monitor.getSymbolKlines(
        symbol,
        KlineInterval.MINUTE_5.value,
        start_fetch_unix
    )

    if not klines or len(klines) < 80:
        print("⚠️ K线数据不足，无法回测")
        return

    results = []

    # 遍历每根 K 线，从第80根开始（保证有足够窗口）
    for i in range(len(klines)):
        window = klines[i-80:i]
        last_k = klines[i]
        ts = datetime.fromtimestamp(last_k.close_time / 1000)
        if ts > end_dt:
            break

        new_state = SignalState.NONE
        accum_duration = 0

        if is_real_volume_breakout_5m(window):
            # 如果之前是 ACCUM，计算吸筹持续时间
            old_state = state_manager.get(symbol)
            if old_state == SignalState.ACCUM:
                accum_start_time = getattr(state_manager, "_accum_start", {}).get(symbol)
                if accum_start_time:
                    accum_duration = (ts - accum_start_time).total_seconds()
            new_state = SignalState.BREAKOUT

        elif is_accumulation_phase_5m(window):
            old_state = state_manager.get(symbol)
            if old_state != SignalState.ACCUM:
                # 记录吸筹开始时间
                if not hasattr(state_manager, "_accum_start"):
                    state_manager._accum_start = {}
                state_manager._accum_start[symbol] = ts
            new_state = SignalState.ACCUM

        state_manager.update(symbol, new_state)

        results.append({
            "datetime": ts.strftime(TIME_FORMAT),
            "state": new_state.name,
            "accum_duration_sec": round(accum_duration, 1)
        })

    # 输出结果
    for r in results:
        print(f"{r['datetime']} -> {r['state']} -> 吸筹持续: {r['accum_duration_sec']} 秒")

    # 保存 CSV
    csv_file = f"{symbol}_backtest.csv"
    with open(csv_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["datetime", "state", "accum_duration_sec"])
        writer.writeheader()
        writer.writerows(results)

    print(f"✅ 回测完成，结果已保存: {csv_file}")

if __name__ == "__main__":
    symbol = "NIGHTUSDT"
    end = "2025-12-14 12:00"

    backtest_symbol(symbol, end)
