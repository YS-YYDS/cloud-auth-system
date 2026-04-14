import time
import random
import string
from typing import Dict, List

class SimpleRateLimiter:
    """
    轻量级速率限制器：基于内存的 IP 限流。
    """
    def __init__(self, requests_per_minute=60):
        self.requests: Dict[str, List[float]] = {}
        self.limit = requests_per_minute

    def is_allowed(self, ip: str) -> bool:
        now = time.time()
        self.requests.setdefault(ip, [])
        # 清理 60 秒之前的过期记录
        self.requests[ip] = [t for t in self.requests[ip] if now - t < 60]
        if len(self.requests[ip]) >= self.limit:
            return False
        self.requests[ip].append(now)
        return True

def generate_serial_number() -> str:
    """
    生成 YS-XXXX-XXXX-XXXX 格式的序列号。
    """
    def get_seg(n: int) -> str:
        return ''.join(random.choices(string.ascii_uppercase + string.digits, k=n))
    return f"YS-{get_seg(4)}-{get_seg(4)}-{get_seg(4)}"

def get_promo_url(cursor, product_id: str) -> str:
    """
    [ARCHITECTURE] 分层提取：获取对应产品的推广公告链接。
    优先顺序: 对应产品链接 > 全局链接 > 默认链接。
    """
    for key in (f"promo_url_{product_id}", "promo_url__ALL_", "promo_url_GLOBAL"):
        cursor.execute("SELECT value FROM system_config WHERE key=?", (key,))
        row = cursor.fetchone()
        if row and row[0]:
            return row[0]
    return ""
