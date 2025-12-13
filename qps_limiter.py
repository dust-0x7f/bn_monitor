import threading
import time

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