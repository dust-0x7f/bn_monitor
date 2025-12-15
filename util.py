from datetime import datetime, timezone


def str_to_ms_utc(s: str) -> int:
    dt = datetime.strptime(s, "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)

def find_end_idx_by_time(klines, t_ms: int) -> int:
    # 返回最后一个 close_time <= t_ms 的索引；如果都大于 t_ms，则返回 -1
    lo, hi = 0, len(klines) - 1
    ans = -1
    while lo <= hi:
        mid = (lo + hi) // 2
        if klines[mid].close_time <= t_ms:
            ans = mid
            lo = mid + 1
        else:
            hi = mid - 1
    return ans