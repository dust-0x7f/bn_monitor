from dataclasses import dataclass
from datetime import timezone, datetime
from typing import List, Dict, Tuple, Optional
from zoneinfo import ZoneInfo

import numpy as np

from util import find_end_idx_by_time


# ---------- 基础特征 ----------
def price_range_ratio(k) -> float:
    return (k.high_price - k.low_price) / k.close_price if k.close_price else 0.0

def body_high(k) -> float:
    return max(k.open_price, k.close_price)

def body_low(k) -> float:
    return min(k.open_price, k.close_price)

def upper_wick_ratio(k) -> float:
    denom = (k.high_price - k.low_price)
    if denom <= 0:
        return 0.0
    return (k.high_price - max(k.open_price, k.close_price)) / denom

def candle_body_ratio(k) -> float:
    denom = (k.high_price - k.low_price)
    if denom <= 0:
        return 0.0
    return abs(k.close_price - k.open_price) / denom

def linreg_slope(y: np.ndarray) -> float:
    n = len(y)
    if n < 3:
        return 0.0
    x = np.arange(n, dtype=float)
    x -= x.mean()
    y = y.astype(float) - float(y.mean())
    denom = float(np.sum(x * x))
    if denom <= 0:
        return 0.0
    return float(np.sum(x * y) / denom)

def weighted_buy_ratio(ks: List) -> float:
    v = float(sum(k.volume for k in ks))
    if v <= 0:
        return 0.0
    b = float(sum(k.buy_volume for k in ks))
    return b / v


# ---------- 静默检测（动态找段） ----------
def _is_quiet_window(win: List,
                     quiet_p90=0.015,
                     quiet_max=0.04,
                     forbid_down_slope=-0.0008) -> Tuple[bool, Dict]:
    ranges = np.array([price_range_ratio(k) for k in win], dtype=float)
    p90 = float(np.percentile(ranges, 90))
    mx = float(np.max(ranges)) if len(ranges) else 0.0
    if p90 > quiet_p90 or mx > quiet_max:
        return False, {"reason": "not_quiet", "p90": p90, "max": mx}

    closes = np.array([k.close_price for k in win], dtype=float)
    slope = linreg_slope(closes[-min(40, len(closes)):])
    if slope < forbid_down_slope:
        return False, {"reason": "down_context", "p90": p90, "max": mx, "slope": slope}

    return True, {"reason": "ok", "p90": p90, "max": mx, "slope": slope}

def _box_from_silent(silent: List) -> Tuple[float, float]:
    # 用实体边界分位数抗针（比 high/low 更稳）
    highs = np.array([body_high(k) for k in silent], dtype=float)
    lows  = np.array([body_low(k)  for k in silent], dtype=float)
    box_top = float(np.percentile(highs, 95))
    box_bot = float(np.percentile(lows, 5))
    return box_top, box_bot

def _find_best_silent_segment(w: List,
                              min_silent=50,
                              scan_win=30,
                              step=2,
                              quiet_p90=0.015,
                              quiet_max=0.04,
                              forbid_down_slope=-0.0008) -> Optional[Tuple[int, int, Dict]]:
    """
    在 w 内找静默段：[s,e)（偏向最靠右且够长的静默区）
    """
    n = len(w)
    if n < min_silent:
        return None

    quiet_flags = np.zeros(n, dtype=np.int8)

    for start in range(0, n - scan_win + 1, step):
        ok, _ = _is_quiet_window(w[start:start + scan_win], quiet_p90, quiet_max, forbid_down_slope)
        if ok:
            quiet_flags[start:start + scan_win] = 1

    segs = []
    i = 0
    while i < n:
        if quiet_flags[i] == 0:
            i += 1
            continue
        s = i
        while i < n and quiet_flags[i] == 1:
            i += 1
        e = i
        if e - s >= min_silent:
            segs.append((s, e))

    if not segs:
        return None

    best, best_score, best_meta = None, -1e18, None
    for (s, e) in segs:
        seg = w[s:e]
        ranges = np.array([price_range_ratio(k) for k in seg], dtype=float)
        p90 = float(np.percentile(ranges, 90))
        mx  = float(np.max(ranges))
        closes = np.array([k.close_price for k in seg], dtype=float)
        slope = linreg_slope(closes[-min(40, len(closes)):])

        length = e - s
        rightness = e  # 越靠右越大

        # 靠右 > 长度 > 安静程度
        score = rightness * 3.0 + length * 2.0 - p90 * 5000.0 - mx * 2000.0
        if score > best_score:
            best_score = score
            best = (s, e)
            best_meta = {"p90": p90, "max": mx, "slope": slope, "len": length, "score": score}

    return best[0], best[1], best_meta


# ---------- 吸筹段判定（用于“连续段”） ----------
def _is_accum_segment(
    seg: List,
    *,
    box_top: float,
    box_bot: float,
    base_vol: float,
    buy_ratio_min: float = 0.52,  # 你坚持不改
    vol_floor: float = 1.4,       # 相对静默中位量至少抬升到 1.4x
    vol_ramp: float = 1.2,        # 后1/4中位量 >= 前3/4中位量 * 1.2
    tiny_eps: float = 0.0012,     # 允许贴上沿但不算突破
    mid_dev: float = 0.012,       # 你原来的中心偏离约束保留
) -> Tuple[bool, Dict]:
    info = {"ok": False, "reason": ""}

    if len(seg) < 20:
        info["reason"] = "seg_too_short"
        return False, info

    # 1) 横盘：范围分位数 + 最大值
    ranges = np.array([price_range_ratio(k) for k in seg], dtype=float)
    if np.percentile(ranges, 90) > 0.018 or float(np.max(ranges)) > 0.035:
        info["reason"] = "not_sideways"
        return False, info

    # 2) 量：相对静默 base_vol + 末段抬升 + 不只是尖峰
    if base_vol <= 0:
        info["reason"] = "base_vol_zero"
        return False, info

    vols = np.array([k.volume for k in seg], dtype=float)
    med_all = float(np.median(vols))
    if med_all < base_vol * vol_floor:
        info["reason"] = f"vol_not_above_base(med_ratio={med_all/base_vol:.2f})"
        return False, info

    q = max(5, len(seg) // 4)
    med_tail = float(np.median(vols[-q:]))
    med_head = float(np.median(vols[:len(seg)-q]))
    if med_tail < med_head * vol_ramp:
        info["reason"] = f"no_ramp(tail/head={med_tail/(med_head+1e-12):.2f})"
        return False, info

    if med_tail < float(np.mean(vols[-q:]) * 0.6):
        info["reason"] = "too_spiky"
        return False, info

    # 3) buy_ratio（硬条件）
    br = weighted_buy_ratio(seg)
    if br < buy_ratio_min:
        info["reason"] = f"buy_ratio_low({br:.2f})"
        return False, info

    # 4) 仍在箱体内/贴上沿（关键：用 box 约束）
    closes = np.array([k.close_price for k in seg], dtype=float)
    if float(np.max(closes)) > box_top * (1.0 + tiny_eps):
        info["reason"] = "already_breaking"
        return False, info
    if float(np.min(closes)) < box_bot * (1.0 - 0.004):
        info["reason"] = "fell_below_box"
        return False, info

    # 5) 你原来的“偏离中心”
    mid = float(np.mean(closes))
    if mid > 0 and abs(float(closes[-1]) - mid) / mid > mid_dev:
        info["reason"] = "price_off_center"
        return False, info

    info.update({
        "ok": True,
        "buy_ratio": float(br),
        "med_vol_ratio": float(med_all / base_vol),
        "tail_head_ratio": float(med_tail / (med_head + 1e-12)),
    })
    return True, info


def str_to_ms(s: str) -> int:
    dt = datetime.strptime(s, "%Y-%m-%d %H:%M").replace()
    return int(dt.timestamp() * 1000)

def detect_phase_event_5m_at_time(
    klines: list,
    time_str: str,
    lookback_len: int = 240,
):
    # ① 时间点 → ms
    t_ms = str_to_ms(time_str)

    # ② 找评估边界（只用过去）
    end_idx = find_end_idx_by_time(klines, t_ms)
    if end_idx < 0:
        return "NONE", {"reason": "time_before_first_kline"}

    # ③ 截断数据，防未来
    data = klines[:end_idx + 1]

    # ④ 直接调用你已经有的逻辑
    # 这里是真实代码，不是 ...
    return detect_phase_event_5m(
        data,
    )

# ---------- 统一：返回 ACCUM 或 BREAKOUT ----------
def detect_phase_event_5m(
    klines: List,
    *,
    lookback_len: int = 240,       # 用于动态找段：20小时
    # 静默
    min_silent: int = 50,
    scan_win: int = 30,
    step: int = 2,
    quiet_p90: float = 0.015,
    quiet_max: float = 0.04,
    forbid_down_slope: float = -0.0008,
    # 吸筹
    accum_min_len: int = 20,
    accum_max_len: int = 120,
    buy_ratio_min: float = 0.52,
    # 突破/爆发
    break_eps: float = 0.003,
    hold_need: bool = True,       # 你要“时间点告警”，建议先 False；要更稳再 True
    hold_eps: float = 0.0015,
    max_wick: float = 0.55,
    min_body: float = 0.30,
) -> Tuple[str, Dict]:
    """
    返回:
      ("ACCUM", info)   仍处于吸筹，未突破
      ("BREAKOUT", info) 已突破，info["breakout_open_time"] 是首次有效突破那根
      ("NONE", info)    没找到可靠静默/吸筹/突破
    """
    info: Dict = {"event": "NONE"}

    n = len(klines)
    if n < max(lookback_len, min_silent + scan_win + 10):
        info["reason"] = "not_enough_klines"
        return "NONE", info

    w_start = n - lookback_len
    w = klines[w_start:]

    # 1) 静默段
    best = _find_best_silent_segment(
        w,
        min_silent=min_silent,
        scan_win=scan_win,
        step=step,
        quiet_p90=quiet_p90,
        quiet_max=quiet_max,
        forbid_down_slope=forbid_down_slope
    )
    if best is None:
        info["reason"] = "no_silent_found"
        return "NONE", info

    s_sil, e_sil, sil_meta = best
    silent = w[s_sil:e_sil]
    box_top, box_bot = _box_from_silent(silent)
    base_vol = float(np.median([k.volume for k in silent])) if silent else 0.0

    # 2) 吸筹段：从静默结束开始，找“最长连续吸筹”
    acc_s = e_sil
    acc_e = e_sil
    acc_meta = {"ok": False, "reason": "no_accum"}

    search_to = min(len(w), e_sil + accum_max_len)
    # 固定起点=静默尾部，逐步扩展，取最长通过的 end
    for end in range(e_sil + accum_min_len, search_to + 1):
        seg = w[e_sil:end]
        ok, meta = _is_accum_segment(
            seg,
            box_top=box_top,
            box_bot=box_bot,
            base_vol=base_vol,
            buy_ratio_min=buy_ratio_min,
        )
        if ok:
            acc_s, acc_e = e_sil, end
            acc_meta = meta

    # 3) 突破：从 max(静默末尾, 吸筹末尾) 起找首次有效突破
    start_break = max(e_sil, acc_e)
    breakout_i = None
    for i in range(start_break, len(w)):
        if w[i].close_price > box_top * (1.0 + break_eps):
            breakout_i = i
            break

    # ----- 输出优先级：若已突破 -> BREAKOUT；否则若有吸筹 -> ACCUM -----
    if breakout_i is not None:
        b0 = w[breakout_i]

        # 形态过滤（可选但建议保留）
        if upper_wick_ratio(b0) > max_wick:
            info.update({"reason": "breakout_too_much_wick"})
            # 这里你要不要仍然告警“发生过突破但形态差”，看你策略；我默认不算 BREAKOUT
            # 你也可以改成返回 "BREAKOUT_WEAK"
            return "ACCUM" if acc_e > acc_s else "NONE", {
                **info,
                "event": "ACCUM" if acc_e > acc_s else "NONE",
                "box_top": box_top, "box_bot": box_bot, "base_vol": base_vol,
                "silent": (w_start + s_sil, w_start + e_sil),
                "accum": (w_start + acc_s, w_start + acc_e),
                "silent_meta": sil_meta, "accum_meta": acc_meta,
            }

        if candle_body_ratio(b0) < min_body:
            info.update({"reason": "breakout_body_too_small"})
            return "ACCUM" if acc_e > acc_s else "NONE", {
                **info,
                "event": "ACCUM" if acc_e > acc_s else "NONE",
                "box_top": box_top, "box_bot": box_bot, "base_vol": base_vol,
                "silent": (w_start + s_sil, w_start + e_sil),
                "accum": (w_start + acc_s, w_start + acc_e),
                "silent_meta": sil_meta, "accum_meta": acc_meta,
            }

        # 站稳确认（可选）
        if hold_need and breakout_i + 1 < len(w):
            b1 = w[breakout_i + 1]
            if b1.close_price < box_top * (1.0 + hold_eps):
                info.update({"reason": "no_hold_after_break"})
                return "ACCUM" if acc_e > acc_s else "NONE", {
                    **info,
                    "event": "ACCUM" if acc_e > acc_s else "NONE",
                    "box_top": box_top, "box_bot": box_bot, "base_vol": base_vol,
                    "silent": (w_start + s_sil, w_start + e_sil),
                    "accum": (w_start + acc_s, w_start + acc_e),
                    "silent_meta": sil_meta, "accum_meta": acc_meta,
                }

        # 通过：BREAKOUT
        out = {
            "event": "BREAKOUT",
            "reason": "breakout",
            "breakout_open_time": int(b0.open_time),
            "box_top": float(box_top),
            "box_bot": float(box_bot),
            "base_vol": float(base_vol),
            "silent": (w_start + s_sil, w_start + e_sil),
            "accum": (w_start + acc_s, w_start + acc_e),
            "silent_meta": sil_meta,
            "accum_meta": acc_meta,
            "break_eps": float(break_eps),
        }
        return "BREAKOUT", out

    # 未突破：若吸筹存在则 ACCUM
    if acc_e > acc_s:
        out = {
            "event": "ACCUM",
            "reason": "accum",
            "accum_start_open_time": int(w[acc_s].open_time),
            "accum_end_open_time": int(w[acc_e - 1].open_time),
            "box_top": float(box_top),
            "box_bot": float(box_bot),
            "base_vol": float(base_vol),
            "silent": (w_start + s_sil, w_start + e_sil),
            "accum": (w_start + acc_s, w_start + acc_e),
            "silent_meta": sil_meta,
            "accum_meta": acc_meta,
        }
        return "ACCUM", out

    # 静默也找到了，但吸筹/突破都没有：你如果不想告警，就 NONE
    out = {
        "event": "NONE",
        "reason": "only_silent",
        "box_top": float(box_top),
        "box_bot": float(box_bot),
        "base_vol": float(base_vol),
        "silent": (w_start + s_sil, w_start + e_sil),
        "silent_meta": sil_meta,
    }
    return "NONE", out
