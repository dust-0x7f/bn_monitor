from typing import List, Dict, Any, Tuple

from env import RunMode
from gainers_predict_main import init_warmup
from interal_enum import KlineInterval
from process_symbol import SignalState
from strategy import is_accumulation_phase_5m, is_real_volume_breakout_5m_strict, trap_score_after_breakout




if __name__ == '__main__':
    globalRunMode = RunMode.BACKTEST
    init_warmup(specific_symbol="BASUSDT")