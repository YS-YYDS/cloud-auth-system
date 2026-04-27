import os
import hashlib
from typing import Optional

# ===================== 应用元数据 =====================
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROOT_DIR = os.path.dirname(BASE_DIR)

# ===================== 安全配置 =====================
# [DEBUG] 打印检测到的密钥键名（不显示值），用于定位环境同步问题
detected_keys = [k for k in os.environ.keys() if "TOKEN" in k or "SECRET" in k or "KEY" in k]
print(f"🚀 [INIT] 检测到以下安全变量: {detected_keys}")

ADMIN_TOKEN = os.getenv("ADMIN_TOKEN")
# HMAC_SECRET_KEY 是系统的“安全钢印”，用于离线签名与系统级安全对齐
HMAC_SECRET_KEY = os.getenv("HMAC_SECRET_KEY")

if not ADMIN_TOKEN:
    if os.getenv("PYTEST_CURRENT_TEST") is None:
        raise RuntimeError("[SECURITY] ADMIN_TOKEN 必须通过环境变量设置。")

if not HMAC_SECRET_KEY:
    if os.getenv("PYTEST_CURRENT_TEST") is None:
        raise RuntimeError("[SECURITY] HMAC_SECRET_KEY 必须通过环境变量设置，否则无法建立系统级信任。")

# [P0-FIX] 动态 XOR 盐值生成器
XOR_SALT = hashlib.sha256(HMAC_SECRET_KEY.encode("utf-8")).hexdigest()[:16]

# ===================== 数据库配置 =====================
# [FIX] 用实际写入测试代替 os.access()：
# os.access() 在容器启动时因 volume 挂载时序问题可能返回 False（假阴性），
# 实际写测试是唯一可靠的方式，确保 /data 优先于容器内路径。
def _detect_db_dir():
    _data = "/data"
    if os.path.isdir(_data):
        try:
            _probe = os.path.join(_data, ".write_probe")
            with open(_probe, "w") as f:
                f.write("ok")
            os.remove(_probe)
            return _data
        except Exception:
            pass
    return ROOT_DIR

DB_FILE = os.getenv("DB_FILE", os.path.join(_detect_db_dir(), "license.db"))
