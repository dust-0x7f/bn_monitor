from enum import Enum


class KlineInterval(Enum):
    """K线周期枚举（基础版）"""
    MINUTE_1 = "1m"    # 1分钟
    MINUTE_3 = "3m"    # 3分钟
    MINUTE_5 = "5m"    # 5分钟
    MINUTE_15 = "15m"  # 15分钟
    MINUTE_30 = "30m"  # 30分钟
    HOUR_1 = "1h"      # 1小时
    HOUR_2 = "2h"      # 2小时
    HOUR_4 = "4h"      # 4小时
    HOUR_6 = "6h"      # 6小时
    HOUR_8 = "8h"      # 8小时
    HOUR_12 = "12h"    # 12小时
    DAY_1 = "1d"       # 1天
    DAY_3 = "3d"       # 3天
    WEEK_1 = "1w"      # 1周
    MONTH_1 = "1M"     # 1月（注意是大写M，避免与分钟m冲突）