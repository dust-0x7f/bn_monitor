import threading
from enum import Enum
from datetime import datetime


class SignalState(Enum):
    NONE = 0
    ACCUM = 1
    BREAKOUT = 2


class StateManager:
    """
    线程安全状态管理 + 吸筹开始时间
    """
    def __init__(self):
        self._state = {}  # symbol -> SignalState
        self._accum_start = {}  # symbol -> datetime
        self._lock = threading.Lock()

    def update(self, symbol: str, new_state: SignalState) -> dict:
        """
        更新状态
        返回字典:
        {
            'changed': bool,        # 状态是否发生变化
            'from_state': SignalState,
            'to_state': SignalState,
            'accum_duration': float # 如果从ACCUM到BREAKOUT，返回秒数，否则0
        }
        """
        with self._lock:
            old = self._state.get(symbol, SignalState.NONE)
            accum_duration = 0

            # 记录吸筹开始时间
            if new_state == SignalState.ACCUM and old != SignalState.ACCUM:
                self._accum_start[symbol] = datetime.now()

            # 计算吸筹持续时间
            if old == SignalState.ACCUM and new_state == SignalState.BREAKOUT:
                start_time = self._accum_start.get(symbol)
                if start_time:
                    accum_duration = (datetime.now() - start_time).total_seconds()
                self._accum_start[symbol] = None

            # 更新状态
            self._state[symbol] = new_state

            return {
                'changed': old != new_state,
                'from_state': old,
                'to_state': new_state,
                'accum_duration': accum_duration
            }

    def get(self, symbol: str) -> SignalState:
        with self._lock:
            return self._state.get(symbol, SignalState.NONE)
