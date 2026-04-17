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
# 优先使用 /data 挂载点，否则使用根目录
# 优先使用 /data 挂载点，并在没有写权限时强制回退，避免在容器只读层写入失败
try:
    if os.path.exists("/data") and os.access("/data", os.W_OK):
        DB_DIR = "/data"
    else:
        DB_DIR = ROOT_DIR
except Exception:
    DB_DIR = ROOT_DIR
DB_FILE = os.getenv("DB_FILE", os.path.join(DB_DIR, "license.db"))
