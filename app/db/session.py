import sqlite3
import logging
from ..core.config import DB_FILE

logger = logging.getLogger("CloudAuth.DB")

def get_db():
    """获取数据库连接 (含 Row Factory)"""
    conn = sqlite3.connect(DB_FILE, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    """初始化数据库表结构 (自动迁移)"""
    logger.info(f"Database_Init: using file={DB_FILE}")
    conn = get_db()
    c = conn.cursor()

    # 1. 核心授权表
    c.execute('''CREATE TABLE IF NOT EXISTS licenses
                 (key TEXT PRIMARY KEY,
                  max_seats INTEGER,
                  activated_devices TEXT,
                  user_contact TEXT,
                  order_id TEXT,
                  created_at TIMESTAMP,
                  last_active_at TIMESTAMP,
                  expires_at TIMESTAMP,
                  status TEXT DEFAULT 'active',
                  product_id TEXT DEFAULT 'GENERIC_ID',
                  remark TEXT)''')

    # 2. 字段生存性检查与增量迁移
    existing_cols = [row[1] for row in c.execute("PRAGMA table_info(licenses)")]
    new_cols = {
        "user_contact": "TEXT",
        "order_id": "TEXT",
        "created_at": "TIMESTAMP",
        "last_active_at": "TIMESTAMP",
        "expires_at": "TIMESTAMP",
        "status": "TEXT DEFAULT 'active'",
        "product_id": "TEXT DEFAULT 'GENERIC_ID'",
        "last_error": "TEXT",
        "remark": "TEXT",
        "is_trial": "INTEGER DEFAULT 0",
    }
    for col, definition in new_cols.items():
        if col not in existing_cols:
            try:
                c.execute(f"ALTER TABLE licenses ADD COLUMN {col} {definition}")
                logger.info(f"Database_Migrate: added column={col}")
            except Exception as e:
                logger.warning(f"Database_Migrate: col={col} warning={e}")

    # 3. 系统配置与历史记录
    c.execute('''CREATE TABLE IF NOT EXISTS system_config (key TEXT PRIMARY KEY, value TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS device_history 
                 (license_key TEXT, change_date TEXT, change_count INTEGER, 
                  PRIMARY KEY (license_key, change_date))''')
    c.execute('''CREATE TABLE IF NOT EXISTS heartbeat_logs 
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, license_key TEXT, 
                  device_id TEXT, timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')

    # 4. 脚本管理中心 (New: Version Hub)
    c.execute('''CREATE TABLE IF NOT EXISTS scripts_registry
                 (script_id TEXT PRIMARY KEY,
                  name TEXT,
                  latest_version TEXT,
                  download_url_primary TEXT,
                  download_url_fallback TEXT,
                  changelog TEXT,
                  min_reaper_version TEXT,
                  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')

    conn.commit()
    conn.close()
