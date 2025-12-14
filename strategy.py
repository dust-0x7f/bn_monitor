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




def is_real_volume_breakout_5m(klines: List[KlineData]) -> bool:
    """
    判断是否出现：完整吸筹后的放量启动（5min）
    需要 >= 80 根 K
    """
    if len(klines) < 80:
        return False

    silent = klines[-80:-50]   # 静默期（30）
    accum  = klines[-50:-25]   # 吸筹期（25）
    rotate = klines[-25:-10]   # 换手期（15）
    confirm = klines[-10:]     # 启动确认（10）

    # -----------------------------
    # 1️⃣ 静默期：低量 + 低波动
    # -----------------------------
    silent_vol = np.mean([k.volume for k in silent])
    silent_range = np.mean([
        (k.high_price - k.low_price) / k.close_price
        for k in silent
    ])

    if silent_range > 0.01:
        return False  # 早期就很活跃，排除

    # -----------------------------
    # 2️⃣ 吸筹期：量缓慢抬升
    # -----------------------------
    accum_vols = [k.volume for k in accum]
    accum_vol_up = np.mean(accum_vols[-10:]) > np.mean(accum_vols[:10]) * 1.3

    if not accum_vol_up:
        return False

    # -----------------------------
    # 3️⃣ 换手期：高量但价格不乱跑
    # -----------------------------
    rotate_vol = np.mean([k.volume for k in rotate])
    rotate_range = np.mean([
        (k.high_price - k.low_price) / k.close_price
        for k in rotate
    ])

    if rotate_vol < silent_vol * 2:
        return False

    if rotate_range > 0.02:
        return False  # 换手期不该剧烈波动

    # -----------------------------
    # 4️⃣ 启动确认：量价共振
    # -----------------------------
    confirm_vols = [k.volume for k in confirm]
    confirm_closes = [k.close_price for k in confirm]

    price_up = confirm_closes[-1] > confirm_closes[0]
    vol_spike = confirm_vols[-1] > np.mean(confirm_vols) * 1.3

    last = confirm[-1]
    bullish = last.close_price > last.open_price
    strong_buy = last.buy_volume / last.volume > 0.6

    if not all([price_up, vol_spike, bullish, strong_buy]):
        return False

    return True



def is_accumulation_phase_5m(klines: List[KlineData]) -> bool:
    ACCUM_WINDOW = 40  # 看最近 40 根 ≈ 3.3h
    SILENT_CHECK = 20
    ACCUM_CHECK = 20
    """
    判断是否处于吸筹期（非启动）
    """
    if len(klines) < ACCUM_WINDOW:
        return False

    silent = klines[-ACCUM_WINDOW:-ACCUM_CHECK]   # 前 20
    accum = klines[-ACCUM_CHECK:]                  # 后 20

    # -----------------------
    # 1️⃣ 静默期确认
    # -----------------------
    silent_vol = np.mean([k.volume for k in silent])
    silent_range = np.mean([
        (k.high_price - k.low_price) / k.close_price
        for k in silent
    ])

    if silent_range > 0.012:
        return False

    # -----------------------
    # 2️⃣ 成交量抬升（慢）
    # -----------------------
    vol_first = np.mean([k.volume for k in accum[:10]])
    vol_last = np.mean([k.volume for k in accum[-10:]])

    if vol_last < vol_first * 1.2:
        return False

    # -----------------------
    # 3️⃣ 价格稳定
    # -----------------------
    start = accum[0].close_price
    end = accum[-1].close_price
    price_change = abs(end - start) / start

    if price_change > 0.02:
        return False

    # -----------------------
    # 4️⃣ 下影线承接
    # -----------------------
    lower_wick_count = 0
    for k in accum:
        lower = min(k.open_price, k.close_price) - k.low_price
        upper = k.high_price - max(k.open_price, k.close_price)
        if lower > upper:
            lower_wick_count += 1

    if lower_wick_count < len(accum) * 0.5:
        return False

    # -----------------------
    # 5️⃣ 主动买入占比改善
    # -----------------------
    buy_ratio = np.mean([
        k.buy_volume / k.volume for k in accum if k.volume > 0
    ])

    if buy_ratio < 0.52:
        return False

    return True
