from typing import List

from bn_tool import KlineData

# 最后一根线的交易量大于3倍的前面交易量的均值
def check_last_k_volume_with(kines: List[KlineData]) -> bool:
    return kines[-1].buy_volume > 3 * sum([k.buy_volume for k in kines[:-1]]) / len(kines[:-1])

# 最后一根线的交易量大于5倍的前面交易量的均值
def check_last_k_volume(kines: List[KlineData]) -> bool:
    return kines[-1].buy_volume > 5 * sum([k.buy_volume for k in kines[:-1]]) / len(kines[:-1])

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
    return True
