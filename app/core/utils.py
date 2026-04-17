import time
import random
import string
from typing import Dict, List

class SimpleRateLimiter:
    """
    轻量级速率限制器：基于内存的 IP 限流。
    [注意] 在多实例部署（如 ClawCloud 多容器/多Worker）时：
    每个实例/进程维护独立的内存记录。因此，实际的整体速率上限将是 limit * 实例数。
    为了实现真正的全局分布式限流，后续建议将存储后端替换为 Redis。
    """
    def __init__(self, requests_per_minute=60):
        self.requests: Dict[str, List[float]] = {}
        self.limit = requests_per_minute

    def is_allowed(self, ip: str) -> bool:
        now = time.time()
        
        # [P0-FIX] 内存泄漏修复：全局定期强制清理不活跃 IP 记录 (10% 概率触发清理)
        if random.random() < 0.1:
            expired_ips = [k for k, v in self.requests.items() if not v or now - v[-1] > 60]
            for e_ip in expired_ips:
                del self.requests[e_ip]

        self.requests.setdefault(ip, [])
        # 清理该 IP 本身 60 秒之前的过期记录
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
