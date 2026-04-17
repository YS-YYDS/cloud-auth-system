import sqlite3
import logging
from ..core.config import DB_FILE

logger = logging.getLogger("CloudAuth.DB")

import contextlib

@contextlib.contextmanager
def db_session():
    """数据库连接上下文管理器 (供非 FastAPI 路由使用)"""
    conn = sqlite3.connect(DB_FILE, timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()

def get_db():
    """FastAPI 依赖注入项 (标准生成器模式以确保连接释放)"""
    conn = sqlite3.connect(DB_FILE, timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()

def init_db():
    """初始化数据库表结构 (自动迁移)"""
    logger.info(f"Database_Init: using file={DB_FILE}")
    
    import time
    for i in range(5): # [P0-FIX] 竞态条件和锁定修复：增加重试机制
        try:
            with db_session() as conn:
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
                return # 成功执行，退出循环
        except sqlite3.OperationalError as e:
            if "database is locked" in str(e).lower():
                time.sleep(0.5)
                continue
            raise e
    raise RuntimeError("Failed to initialize database: database is locked after multiple retries.")
