from typing import List, Optional

import numpy as np
# import talib

from bn_tool import KlineData


from typing import List, Tuple, Dict
import numpy as np

def _range_ratio(k: KlineData) -> float:
    # 你也可以改成 (high-low)/close，这里用 close 更贴近实际波动
    if k.close_price <= 0:
        return 0.0
    return (k.high_price - k.low_price) / k.close_price

def _candle_body_ratio(k: KlineData) -> float:
    rng = max(1e-12, k.high_price - k.low_price)
    body = abs(k.close_price - k.open_price)
    return body / rng

def _upper_wick_ratio(k: KlineData) -> float:
    rng = max(1e-12, k.high_price - k.low_price)
    upper = k.high_price - max(k.open_price, k.close_price)
    return upper / rng

def _lower_wick_ratio(k: KlineData) -> float:
    rng = max(1e-12, k.high_price - k.low_price)
    lower = min(k.open_price, k.close_price) - k.low_price
    return lower / rng

def _linreg_slope(y: np.ndarray) -> float:
    # 简单线性回归斜率，衡量 pre-window 是不是在下跌/上升
    n = len(y)
    if n < 3:
        return 0.0
    x = np.arange(n, dtype=float)
    x = x - x.mean()
    y = y - y.mean()
    denom = np.sum(x * x)
    if denom <= 0:
        return 0.0
    return float(np.sum(x * y) / denom)



# -----------------------------
# 爆发判断（严格版）
# -----------------------------
def is_real_volume_breakout_5m_strict(
    klines: List,
    window_len: int = 120,         # 120根=10小时
    min_silent: int = 50,          # 静默区最少长度
    confirm_len: int = 12,         # 右侧确认窗口（最近12根=1小时）
    vol_mult: float = 2.5,         # 放量倍数阈值（相对静默基准）
    vol_k: int = 4,                # confirm_len 里至少 vol_k 根满足单根放量
    break_eps: float = 0.003,      # 突破幅度，0.3%
    max_wick: float = 0.55,        # 上影线占比上限
    min_body: float = 0.30,        # 实体占比下限
    buy_ratio_min: float = 0.58,   # 主动买占比下限（加权）
    forbid_down_slope: float = -0.0008,  # pre 段斜率太负：判为反抽环境
) -> Tuple[bool, Dict]:
    """
    返回 (ok, info)

    ok=True 表示：
    - 之前存在静默箱体（波动收敛）
    - confirm 窗口量能持续显著抬升（不是单根尖峰）
    - 价格结构性突破箱体上沿，并在 confirm 内“站住”
    - 突破K线形态不过分插针
    - buy_ratio 足够高
    """
    info: Dict = {"ok": False, "reason": "", "score": 0.0}

    # 0) 数据长度
    if len(klines) < window_len:
        info["reason"] = "not_enough_klines"
        return False, info

    w = klines[-window_len:]

    # 1) 静默箱体：取 window_len-confirm_len 作为静默候选
    silent = w[: window_len - confirm_len]
    if len(silent) < min_silent:
        info["reason"] = "silent_too_short"
        return False, info

    # 静默判定：分位数 + 最大值，避免均值被针影响
    silent_ranges = np.array([_range_ratio(k) for k in silent], dtype=float)
    p90 = float(np.percentile(silent_ranges, 90))
    mx = float(np.max(silent_ranges))
    if p90 > 0.015 or mx > 0.04:
        info["reason"] = f"silent_not_quiet(p90={p90:.4f},max={mx:.4f})"
        return False, info

    # 箱体上下沿：用分位数避免单根针
    silent_highs = np.array([k.high_price for k in silent], dtype=float)
    silent_lows  = np.array([k.low_price  for k in silent], dtype=float)
    box_top = float(np.percentile(silent_highs, 95))
    box_bot = float(np.percentile(silent_lows, 5))

    # 2) 语境过滤：避免明显下跌反抽
    tail = silent[-min(40, len(silent)):]
    pre_closes = np.array([k.close_price for k in tail], dtype=float)
    slope = _linreg_slope(pre_closes)
    if slope < forbid_down_slope:
        info["reason"] = f"downtrend_context(slope={slope:.6f})"
        return False, info

    # 3) 量能持续性：基准用 median，确认窗口看 median 强度 + 单根计数
    base_vol = float(np.median([k.volume for k in silent]))
    if base_vol <= 0:
        info["reason"] = "base_vol_zero"
        return False, info

    confirm = w[-confirm_len:]
    confirm_vols = np.array([k.volume for k in confirm], dtype=float)

    vol_strength = float(np.median(confirm_vols) / base_vol)  # 稳健强度
    vol_count = int(np.sum(confirm_vols > base_vol * vol_mult))

    if vol_strength < vol_mult:
        info["reason"] = f"vol_not_strong(med_ratio={vol_strength:.2f})"
        return False, info
    if vol_count < min(vol_k, confirm_len):
        info["reason"] = f"vol_not_persistent(count={vol_count})"
        return False, info

    # 4) 结构突破：最后一根必须站上 box_top*(1+break_eps)
    last = confirm[-1]
    if last.close_price <= box_top * (1.0 + break_eps):
        info["reason"] = f"no_structure_break(close={last.close_price:.6f},top={box_top:.6f})"
        return False, info

    # 站住确认：倒数第二根也应当已经在上沿之上（更严格，降低误报）
    if len(confirm) >= 2:
        if confirm[-2].close_price <= box_top * (1.0 + break_eps / 2):
            info["reason"] = "no_close_hold(need_2closes_above_top)"
            return False, info

    # 5) 形态限制：防插针/假突破
    if _upper_wick_ratio(last) > max_wick:
        info["reason"] = f"too_much_upper_wick({_upper_wick_ratio(last):.2f})"
        return False, info
    if _candle_body_ratio(last) < min_body:
        info["reason"] = f"body_too_small({_candle_body_ratio(last):.2f})"
        return False, info

    # 6) 主动买占比：最近5根加权
    last5 = confirm[-5:] if len(confirm) >= 5 else confirm
    vol_sum = float(sum(k.volume for k in last5))
    if vol_sum <= 0:
        info["reason"] = "vol_sum_zero"
        return False, info

    buy_sum = float(sum(k.buy_volume for k in last5))
    buy_ratio = float(buy_sum / vol_sum)
    if buy_ratio < buy_ratio_min:
        info["reason"] = f"buy_ratio_low({buy_ratio:.2f})"
        return False, info

    # 7) score：用于优先级（0~100）
    box_height = float(max(1e-12, (box_top - box_bot) / max(1e-12, box_top)))
    breakout_mag = float((last.close_price - box_top) / max(1e-12, box_top))

    score = 0.0
    score += min(1.0, vol_strength) * 30.0                    # 量强：>=1封顶
    score += min(1.0, breakout_mag / 0.01) * 25.0             # 突破幅度：>=1%封顶
    score += min(1.0, (buy_ratio - 0.5) / 0.2) * 20.0         # 买盘集中：0.7封顶
    score += max(0.0, 1.0 - box_height / 0.03) * 25.0         # 箱体窄：<=3%才给分

    # breakout_open_time：confirm 内“首次收盘真正突破”的那根（更适合 pending 二次确认）
    breakout_bar = None
    for k in confirm:
        if k.close_price > box_top * (1.0 + break_eps):
            breakout_bar = k
            break
    if breakout_bar is None:
        # 理论上不会发生（因为 last 已经突破），但为健壮性保留
        breakout_bar = last

    info.update({
        "ok": True,
        "reason": "pass",
        "score": float(score),

        "box_top": float(box_top),
        "box_bot": float(box_bot),
        "break_eps": float(break_eps),

        "vol_strength": float(vol_strength),
        "vol_count": int(vol_count),
        "buy_ratio": float(buy_ratio),

        "breakout_mag": float(breakout_mag),
        "box_height": float(box_height),
        "slope": float(slope),

        "breakout_open_time": int(breakout_bar.open_time),
    })

    return True, info



def price_range_ratio(k: KlineData):
    return (k.high_price - k.low_price) / k.close_price if k.close_price != 0 else 0






# -----------------------------
# 吸筹判断
# -----------------------------
def is_accumulation_phase_5m(klines: List[KlineData], window_len=40) -> bool:
    if len(klines) < window_len:
        return False
    window = klines[-window_len:]

    # 1) 横盘：用分位数/最大值更稳（避免1根针破坏均值）
    ranges = np.array([price_range_ratio(k) for k in window], dtype=float)
    if np.percentile(ranges, 90) > 0.018:   # 90分位阈值，可调
        return False
    if ranges.max() > 0.035:                # 允许少量波动，但不能太离谱
        return False

    # 2) 成交量放大：用中位数 + 最近1/4 vs 前3/4，避免单根暴量
    vols = np.array([k.volume for k in window], dtype=float)
    if np.median(vols[-10:]) < np.median(vols[:30]) * 1.2:
        return False
    # 同时要求最近一段不是“只有一根暴量”
    if np.median(vols[-10:]) < (np.mean(vols[-10:]) * 0.6):  # 均值远大于中位数说明尖峰太多
        return False

    # 3) 主动买占比：一定要 volume 加权
    total_vol = float(np.sum(vols))
    if total_vol <= 0:
        return False
    total_buy = float(np.sum([k.buy_volume for k in window]))
    buy_ratio = total_buy / total_vol
    if buy_ratio < 0.52:
        return False

    # 4) 可选：约束“价格仍在箱体中间”（防止已经明显启动）
    closes = np.array([k.close_price for k in window], dtype=float)
    mid = np.mean(closes)
    if abs(closes[-1] - mid) / mid > 0.012:  # 最新价偏离箱体中心太多，可能已启动
        return False

    return True








# 诱多评分
def candle_body(k):
    return abs(k.close_price - k.open_price)

def upper_wick(k):
    return k.high_price - max(k.open_price, k.close_price)

from typing import Tuple, Dict

def trap_score_after_breakout(
    bars_after: list,
    box_top: float,
    eps: float = 0.001
) -> Tuple[float, Dict]:
    """
    bars_after: 突破K线后的若干根K线（至少2根，最好3根）
    box_top: 箱体上沿
    eps: 回踩容忍比例（建议传 strict 里的 break_eps）
    """
    detail = {}
    score = 0.0

    if len(bars_after) < 2:
        return 0.0, {"reason": "need_more_bars"}

    b1 = bars_after[0]
    b2 = bars_after[1]

    body1 = abs(b1.close_price - b1.open_price)
    body2 = abs(b2.close_price - b2.open_price)
    vol1 = float(b1.volume)
    vol2 = float(b2.volume)

    # ① 第二根疲软
    if body2 < body1 * 0.5:
        score += 30
        detail["weak_2nd_body"] = True

    # ② 单峰量
    if vol2 < vol1 * 0.7:
        score += 20
        detail["single_peak_vol"] = True

    # ③ 不愿远离箱体
    max_close = max(b1.close_price, b2.close_price)
    if (max_close - box_top) / max(1e-12, box_top) < 0.005:
        score += 20
        detail["no_extension"] = True

    # ④ 回踩明显跌回箱体（用 eps 容忍）
    min_low = min(b1.low_price, b2.low_price)
    if min_low < box_top * (1.0 - eps):
        score += 40
        detail["back_into_box"] = True

    # ⑤ 上影线过长
    def upper_wick_ratio(k):
        rng = max(1e-12, k.high_price - k.low_price)
        upper = k.high_price - max(k.open_price, k.close_price)
        return upper / rng

    if upper_wick_ratio(b1) > 0.6 or upper_wick_ratio(b2) > 0.6:
        score += 15
        detail["long_upper_wick"] = True

    # ⑥ buy_ratio 下降
    def buy_ratio(k):
        return (k.buy_volume / k.volume) if k.volume > 0 else 0.0

    if buy_ratio(b2) < buy_ratio(b1) * 0.85:
        score += 15
        detail["buy_ratio_drop"] = True

    detail["trap_score"] = score
    return score, detail

