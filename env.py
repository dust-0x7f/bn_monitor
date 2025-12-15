from enum import Enum


class RunMode(Enum):
    LIVE = "live"        # 线上运行（monitor / warmup）
    BACKTEST = "backtest"  # 回测
    DEBUG = "debug"      # 单币手动调试

