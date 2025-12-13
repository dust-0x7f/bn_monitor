from typing import List, Optional

import numpy as np
import talib

from bn_tool import KlineData

# 最后一根线的交易量大于4倍的前面交易量的均值
def check_last_k_volume_with(kines: List[KlineData]) -> bool:
    return kines[-1].buy_volume > 4 * sum([k.buy_volume for k in kines[:-1]]) / len(kines[:-1])

# 最后一根线的交易量大于10倍的前面交易量的均值
def check_last_k_volume(kines: List[KlineData]) -> bool:
    return kines[-1].buy_volume > 10 * sum([k.buy_volume for k in kines[:-1]]) / len(kines[:-1])

def check_last_3_volume_increase(klines: List[KlineData]) -> bool:
    last_3_klines = klines[-3:]
    for i in range(1,len(last_3_klines)):
        pre = last_3_klines[i - 1]
        now = last_3_klines[i]
        if now.buy_volume < pre.buy_volume * 0.5:
            return False
    return True

# 最后三根交易量高于前面交易量的合
def check_sum_volume(klines: List[KlineData]) -> bool:
    last_3_klines = klines[-3:]
    prev_klines = klines[:-3]
    return sum([k.buy_volume for k in last_3_klines]) >  sum([k.buy_volume for k in prev_klines])

# 最后5根交易量的均值，大于前面所有交易量的均值的3倍
def check_avg_volume(klines: List[KlineData]) -> bool:
    # 分割最后3根和历史K线
    last_3_klines = klines[-3:]
    prev_klines = klines[:-3]
    avg_last_3 = round(sum([k.buy_volume for k in last_3_klines]) / 3, 6)
    avg_prev = round(sum([k.buy_volume for k in prev_klines]) / len(prev_klines), 6)
    if avg_prev == 0:
        return False
    return avg_last_3 >= avg_prev * 3

# 当前收盘价大于前面所有k线的平均收盘价
def check_increase(klines: List[KlineData]) -> bool:
    close_price = klines[-1].close_price
    prev_klines = klines[:-1]
    avg_prev_close = sum(k.close_price for k in prev_klines) / len(prev_klines)
    if close_price > avg_prev_close:
        return True
    return False

# 最后三根线趋势向上
def check_last3_klines_increase(klines: List[KlineData]) -> bool:
    last_3_klines = klines[-3:]
    for i in range(1,len(last_3_klines)):
        pre = last_3_klines[i - 1]
        now = last_3_klines[i]
        if not (now.close_price > now.open_price and pre.close_price > pre.open_price):
            return False
    # 看下最后三根线的最低价
    last_3_avg_low_price = sum(v.low_price for v in last_3_klines) / 3
    pre_low_price = sum(v.low_price for v in klines[:-3]) / len(klines[:-3])
    last_3_avg_high_price = sum(v.high_price for v in last_3_klines) / 3
    for v in last_3_klines[:-3]:
        if v.close_price > last_3_avg_high_price:
            return False
    if last_3_avg_low_price > pre_low_price:
        return True
    return False


def calculate_24_rsi_with_talib(kline_list: List[KlineData]) -> List[Optional[float]]:
    """
    用TA-Lib计算24周期RSI值
    :param kline_list: 按时间正序排列的K线数据列表（至少24根）
    :return: 每根K线对应的RSI值（前23个为None，第24个开始为计算值，保留2位小数）
    """
    # 校验K线数量
    if len(kline_list) < 24:
        raise ValueError(f"计算24周期RSI需要至少24根K线，当前仅提供{len(kline_list)}根")

    # 1. 提取所有K线的收盘价，转换为TA-Lib要求的numpy数组（float64类型）
    close_prices = np.array([k.close_price for k in kline_list], dtype=np.float64)

    # 2. 调用TA-Lib计算24周期RSI（核心一步）
    # TA-Lib返回的数组中，前23个值为nan（不足周期），第24个开始为有效RSI
    rsi_array = talib.RSI(close_prices, timeperiod=24)

    # 3. 处理结果：nan替换为None，保留2位小数
    rsi_results = []
    for rsi_val in rsi_array:
        if np.isnan(rsi_val):
            rsi_results.append(None)
        else:
            rsi_results.append(round(rsi_val, 2))

    return rsi_results