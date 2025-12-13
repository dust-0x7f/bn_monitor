import threading
from dataclasses import dataclass
from datetime import datetime

from binance import BinanceAPIException
from binance.client import Client  # 现货客户端


import time

# 读取配置
API_KEY = "h74Ci2vYD9ycl6zdO7wL2nhvfNImohYFmRaTjKg3Ze5MhVDWqg6MRJBsXrfoLBHg"
SECRET_KEY = "hx1WIRMRQ0uy4u1jGLepItfeQn0YA2RdiHlEUY24jDf4ICIZR7tRBXsGf5FNFOCf"


@dataclass
class KlineData:
    open_time: int  # 开盘时间（毫秒时间戳）
    open_price: float  # 开盘价
    high_price: float  # 最高价
    low_price: float  # 最低价
    close_price: float  # 收盘价
    volume: float  # 成交量
    close_time: int  # 收盘时间（毫秒时间戳）
    quote_volume: float  # 成交额
    trade_count: int  # 成交笔数
    buy_volume: float  # 主动买入成交量
    buy_quote_volume: float  # 主动买入成交额
    ignore: str  # 忽略字段

    # 可选：添加方法将时间戳转为可读格式
    def open_time_str(self):
        from datetime import datetime
        return datetime.fromtimestamp(self.open_time / 1000).strftime("%Y-%m-%d %H:%M:%S")

    def close_time_str(self):
        from datetime import datetime
        return datetime.fromtimestamp(self.close_time / 1000).strftime("%Y-%m-%d %H:%M:%S")

class QPSLimiter:
    def __init__(self, max_qps: int):
        self.max_qps = max_qps
        self.interval = 1.0 / max_qps  # 每次请求的最小间隔（秒）
        self.last_request_time = 0.0
        self.lock = threading.Lock()

    def acquire(self):
        """获取请求许可，确保QPS不超限"""
        with self.lock:
            current_time = time.time()
            # 计算需要等待的时间（确保两次请求间隔≥1/QPS）
            sleep_time = self.interval - (current_time - self.last_request_time)
            if sleep_time > 0:
                time.sleep(sleep_time)
            # 更新最后一次请求时间
            self.last_request_time = time.time()


class BNMonitor:
    def __init__(self):
        self.client = Client(api_key=API_KEY, api_secret=SECRET_KEY, testnet=False)
        self.qps_limiter = QPSLimiter(10)


    def getSymbolKlines(self,symbol,internal,startTimeUnix):
        self.qps_limiter.acquire()
        kline_list = []
        try:
            resp = self.client.futures_klines(symbol=symbol, interval=internal, startTime=startTimeUnix)
            for kline in resp:
                data = KlineData(
                    open_time=kline[0],
                    open_price=float(kline[1]),
                    high_price=float(kline[2]),
                    low_price=float(kline[3]),
                    close_price=float(kline[4]),
                    volume=float(kline[5]),
                    close_time=kline[6],
                    quote_volume=float(kline[7]),
                    trade_count=int(kline[8]),
                    buy_volume=float(kline[9]),
                    buy_quote_volume=float(kline[10]),
                    ignore=kline[11]
                )
                kline_list.append(data)
        except BinanceAPIException as e:
            if e.status_code == 429:
                error_msg = (
                    f"\n{'=' * 80}\n"
                    f"⚠️ 【{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}】获取K线失败 - 429限流警告\n"
                    f"{'=' * 80}\n"
                )
                print(error_msg)
            else:
                error_msg = (
                    f"\n{'=' * 80}\n"
                    f"❌ 【{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}】获取K线失败 - 币安API错误\n"
                    f"📋 请求参数：{symbol}\n"
                    f"🔍 异常类型：{type(e).__name__}\n"
                    f"📞 状态码：{e.status_code}\n"
                    f"💬 异常信息：{str(e)}\n"
                    f"{'=' * 80}\n"
                )
                print(error_msg)

        return kline_list

    def getTargetSymbols(self):
        resp = self.client.get_exchange_info()
        result = []
        for item in resp["symbols"]:
            if item["status"] == "TRADING":
                result.append(item["symbol"])
        print(result)



