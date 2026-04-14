import os
import hashlib
from typing import Optional

# ===================== 应用元数据 =====================
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROOT_DIR = os.path.dirname(BASE_DIR)

# ===================== 安全配置 =====================
ADMIN_TOKEN = os.getenv("ADMIN_TOKEN")
# [P0-FIX] 允许环境变量缺省，使用预设安全值防止服务器启动崩溃 (no healthy upstream)
HMAC_SECRET_KEY = os.getenv("HMAC_SECRET_KEY") or "0f1440dcca463b44_LDK_SAFE_SEED"

if not ADMIN_TOKEN:
    # 仅在非测试环境下强制要求 ADMIN_TOKEN
    if os.getenv("PYTEST_CURRENT_TEST") is None:
        raise RuntimeError("[SECURITY] ADMIN_TOKEN 必须通过环境变量设置。")

# [P0-FIX] 动态 XOR 盐值
XOR_SALT = hashlib.sha256((HMAC_SECRET_KEY or "TEST").encode("utf-8")).hexdigest()[:16]

# ===================== 数据库配置 =====================
# 优先使用 /data 挂载点，否则使用根目录
DB_DIR = "/data" if os.path.exists("/data") and os.access("/data", os.W_OK) else ROOT_DIR
DB_FILE = os.getenv("DB_FILE", os.path.join(DB_DIR, "license.db"))
