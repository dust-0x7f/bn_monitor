import threading
from enum import Enum
from datetime import datetime


import threading
from datetime import datetime
from enum import Enum

class SignalState(Enum):
    NONE = 0
    ACCUM = 1
    BREAKOUT = 2

class StateManager:
    def __init__(self, exit_confirm: int = 3):
        self._state = {}          # symbol -> SignalState
        self._accum_start_ms = {} # symbol -> int(ms)
        self._bad_count = {}      # symbol -> int
        self._lock = threading.Lock()
        self._exit_confirm = exit_confirm

    def update(self, symbol: str, new_state: SignalState, now_ms: int = None) -> dict:
        """
        now_ms: 建议传 klines[-1].open_time（毫秒）
        返回:
        {
          changed, from_state, to_state,
          accum_duration_sec,     # ACCUM->BREAKOUT 或 ACCUM->NONE 时都会给（有意义）
          exited_accum: bool      # 是否发生了从 ACCUM 退出（到 NONE）
        }
        """
        with self._lock:
            old = self._state.get(symbol, SignalState.NONE)
            accum_duration_sec = 0.0
            exited_accum = False

            # 没传 now_ms 就退化为墙钟（不推荐）
            if now_ms is None:
                now_ms = int(datetime.now().timestamp() * 1000)

            # 进入/维持吸筹
            if new_state == SignalState.ACCUM:
                # 防抖计数清零
                self._bad_count[symbol] = 0
                if old != SignalState.ACCUM:
                    self._accum_start_ms[symbol] = now_ms
                self._state[symbol] = SignalState.ACCUM
                return {
                    "changed": old != SignalState.ACCUM,
                    "from_state": old,
                    "to_state": SignalState.ACCUM,
                    "accum_duration": 0.0,
                    "exited_accum": False,
                }

            # 爆发：如果从吸筹来，计算时长
            if new_state == SignalState.BREAKOUT:
                if old == SignalState.ACCUM:
                    start_ms = self._accum_start_ms.get(symbol)
                    if start_ms is not None:
                        accum_duration_sec = (now_ms - start_ms) / 1000.0
                    self._accum_start_ms.pop(symbol, None)
                    self._bad_count.pop(symbol, None)

                self._state[symbol] = SignalState.BREAKOUT
                return {
                    "changed": old != SignalState.BREAKOUT,
                    "from_state": old,
                    "to_state": SignalState.BREAKOUT,
                    "accum_duration": accum_duration_sec,
                    "exited_accum": False,
                }

            # NONE：这里做吸筹退出防抖
            if new_state == SignalState.NONE:
                if old == SignalState.ACCUM:
                    bc = self._bad_count.get(symbol, 0) + 1
                    self._bad_count[symbol] = bc

                    # 未达到退出确认次数：仍保持 ACCUM（防抖）
                    if bc < self._exit_confirm:
                        return {
                            "changed": False,
                            "from_state": SignalState.ACCUM,
                            "to_state": SignalState.ACCUM,
                            "accum_duration": 0.0,
                            "exited_accum": False,
                        }

                    # 达到退出次数：正式退出吸筹，并给 duration（用于 pending）
                    start_ms = self._accum_start_ms.get(symbol)
                    if start_ms is not None:
                        accum_duration_sec = (now_ms - start_ms) / 1000.0
                    self._accum_start_ms.pop(symbol, None)
                    self._bad_count.pop(symbol, None)
                    exited_accum = True

                self._state[symbol] = SignalState.NONE
                return {
                    "changed": old != SignalState.NONE or exited_accum,
                    "from_state": old,
                    "to_state": SignalState.NONE,
                    "accum_duration": accum_duration_sec,
                    "exited_accum": exited_accum,
                }

            # 默认
            self._state[symbol] = new_state
            return {
                "changed": old != new_state,
                "from_state": old,
                "to_state": new_state,
                "accum_duration": 0.0,
                "exited_accum": False,
            }

    def get(self, symbol: str) -> SignalState:
        with self._lock:
            return self._state.get(symbol, SignalState.NONE)



class SymbolRuntimeState:
    """
    单 symbol 的运行时状态（可由 replay 完全恢复）
    """
    def __init__(self):
        self.state = SignalState.NONE
        self.accum_start_ms = None
        self.pending = None              # dict or None
        self.last_alert_ms = None         # 防重复报警
        self.last_seen_ms = None          # 最新处理的 bar

    def enter_accum(self, now_ms):
        if self.state != SignalState.ACCUM:
            self.state = SignalState.ACCUM
            self.accum_start_ms = now_ms

    def exit_accum(self):
        self.accum_start_ms = None

    def enter_breakout(self, now_ms):
        self.state = SignalState.BREAKOUT
        self.exit_accum()

    def enter_none(self):
        self.state = SignalState.NONE
        self.exit_accum()
