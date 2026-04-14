from fastapi import FastAPI, HTTPException, status
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import sqlite3
import os
import uuid
from datetime import datetime
import random
import string
from typing import Optional, List

app = FastAPI()

# ===================== 配置与工具 =====================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

def generate_serial_number():
    """生成专业级的激活码格式: YS-XXXX-XXXX-XXXX"""
    def get_seg(n):
        return ''.join(random.choices(string.ascii_uppercase + string.digits, k=n))
    return f"YS-{get_seg(4)}-{get_seg(4)}-{get_seg(4)}"

# 优先使用 /data 挂载点，否则使用当前目录
DB_DIR = "/data" if os.path.exists("/data") and os.access("/data", os.W_OK) else BASE_DIR
DB_FILE = os.path.join(DB_DIR, "license.db")

# Admin Token (建议生产环境设为复杂密码)
ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "sk-spirit")

@app.get("/admin")
def admin_page():
    return FileResponse(os.path.join(BASE_DIR, "admin.html"), headers={"Cache-Control": "no-cache, no-store, must-revalidate"})

# 挂载静态文件目录 (用于本地加载 Vue, Tailwind)
STATIC_DIR = os.path.join(BASE_DIR, "static")
if not os.path.exists(STATIC_DIR):
    os.makedirs(STATIC_DIR, exist_ok=True)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

@app.get("/favicon.ico")
def favicon():
    return FileResponse(os.path.join(STATIC_DIR, "favicon.ico")) if os.path.exists(os.path.join(STATIC_DIR, "favicon.ico")) else None

# 默认公告 (重启后重置，建议存数据库更持久，但这版简便起见只存内存，或简单存文件)
# 为了持久化，我们建一个 config 表
ANNOUNCEMENTS = {} # cache

def get_db():
    conn = sqlite3.connect(DB_FILE, timeout=10)
    conn.row_factory = sqlite3.Row # enable column access by name
    return conn

def init_db():
    print(f"Using database file: {DB_FILE}")
    conn = get_db()
    c = conn.cursor()
    
    # 核心授权表 (自动升级：检查列是否存在)
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
                  product_id TEXT DEFAULT 'ArchivePro',
                  remark TEXT)''')
    
    # 检查并添加缺失的列 (简单的迁移逻辑)
    existing_cols = [row[1] for row in c.execute("PRAGMA table_info(licenses)")]
    new_cols = {
        "user_contact": "TEXT",
        "order_id": "TEXT", 
        "created_at": "TIMESTAMP",
        "last_active_at": "TIMESTAMP",
        "expires_at": "TIMESTAMP",
        "status": "TEXT DEFAULT 'active'",
        "product_id": "TEXT DEFAULT 'ArchivePro'",
        "last_error": "TEXT",
        "remark": "TEXT",
        "is_trial": "INTEGER DEFAULT 0"
    }
    for col, definition in new_cols.items():
        if col not in existing_cols:
            print(f"Migrating DB: Adding column {col}...")
            try:
                c.execute(f"ALTER TABLE licenses ADD COLUMN {col} {definition}")
            except Exception as e:
                print(f"Migration warning for {col}: {e}")

    # 系统配置表 (用于存公告等)
    c.execute('''CREATE TABLE IF NOT EXISTS system_config 
                 (key TEXT PRIMARY KEY, value TEXT)''')

    # 设备变动记录表 (用于防滥用/频率限制)
    c.execute('''CREATE TABLE IF NOT EXISTS device_history 
                 (license_key TEXT, 
                  change_date TEXT, -- YYYY-MM for monthly limit
                  change_count INTEGER,
                  PRIMARY KEY (license_key, change_date))''')

    # 心跳日志表 (用于历史审计)
    c.execute('''CREATE TABLE IF NOT EXISTS heartbeat_logs
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  license_key TEXT,
                  device_id TEXT,
                  timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')

    conn.commit()
    conn.close()

init_db()

# ===================== Pydantic Models =====================

class VerifyRequest(BaseModel):
    license_key: str
    device_id: str
    product_id: Optional[str] = "ArchivePro"

class GenerateRequest(BaseModel):
    token: str
    seats: int = 1
    duration_days: int = 0  # 0 = 永久
    contact: Optional[str] = ""
    order_id: Optional[str] = ""
    remark: Optional[str] = ""
    product_ids: Optional[List[str]] = ["ArchivePro"] # 支持多个产品
    is_trial: bool = False

class AdminRequest(BaseModel):
    token: str
    license_key: Optional[str] = None # 部分操作需要

class BanRequest(AdminRequest):
    action: str # 'ban' or 'unban'

class ResetRequest(AdminRequest):
    pass

class AnnouncementRequest(BaseModel):
    token: str
    product_id: str = "ArchivePro"
    message: str # 空字符串代表删除公告
    anno_mode: str = "once" # once or always

class DeleteRequest(AdminRequest):
    pass

class RenameProductRequest(BaseModel):
    token: str
    old_name: str
    new_name: str

class DeleteProductRequest(BaseModel):
    token: str
    product_id: str

class DisplayNameRequest(BaseModel):
    token: str
    product_id: str
    display_name: str

class UpdatePromoUrlRequest(BaseModel):
    token: str
    product_id: str
    promo_url: str
    default_trial_days: int = 7

class RequestTrialRequest(BaseModel):
    hardware_id: str
    product_id: str = "ArchivePro"

class UpdateLicenseRequest(BaseModel):
    token: str
    license_key: str
    user_contact: Optional[str] = None
    remark: Optional[str] = None

import base64
import json

def encrypt_response(data: dict, device_id: str) -> dict:
    json_str = json.dumps(data)
    dyn_key = (device_id[:8] + "YS_Secure_26") if device_id else "YS_Secure_26"
    key = dyn_key.encode('utf-8')
    encrypted = bytearray()
    for i, b in enumerate(json_str.encode('utf-8')):
        encrypted.append(b ^ key[i % len(key)])
    b64_str = base64.b64encode(encrypted).decode('utf-8')
    return {"payload": b64_str}

# ===================== 核心业务逻辑 =====================



@app.post("/verify")
def verify_license(req: VerifyRequest):
    conn = get_db()
    c = conn.cursor()
    
    # 提前获取推广网页 URL，确保即使验证失败也能下发给客户端供关闭时外跳
    c.execute("SELECT value FROM system_config WHERE key=?", (f"promo_url_{req.product_id}",))
    promo_row = c.fetchone()
    
    # 优先使用单品专属链接，假如单品未配置或为空，则回退读取全局的 _ALL_ 和 GLOBAL
    if not promo_row or not promo_row[0]:
        c.execute("SELECT value FROM system_config WHERE key='promo_url__ALL_'")
        promo_row = c.fetchone()
        
        if not promo_row or not promo_row[0]:
            c.execute("SELECT value FROM system_config WHERE key='promo_url_GLOBAL'")
            promo_row = c.fetchone()
            
    promo_url = promo_row[0] if promo_row else ""
    
    # 1. 查找授权
    c.execute("SELECT * FROM licenses WHERE key=?", (req.license_key,))
    row = c.fetchone()
    
    if not row:
        conn.close()
        return encrypt_response({"status": "error", "message": "激活码不存在，请检查或联系作者。", "promo_url": promo_url}, req.device_id)
    
    # 2. 产品匹配检查 (核心解耦：支持逗号分隔列表)
    allowed_pids = [p.strip() for p in row['product_id'].split(",")]
    if req.product_id not in allowed_pids:
        conn.close()
        return encrypt_response({"status": "error", "message": f"此激活码不包含产品: {req.product_id}", "promo_url": promo_url}, req.device_id)
    
    # 2. 检查状态
    if row['status'] == 'banned':
        conn.close()
        return encrypt_response({"status": "error", "message": "此激活码已被封禁，请联系作者。", "promo_url": promo_url}, req.device_id)
    
    # 3. 检查过期
    now_ts = datetime.utcnow() # Use UTC
    if row['expires_at']:
        # 解析 timestamp 字符串 (sqlite 默认存的是 string)
        try:
            exp_date = datetime.fromisoformat(row['expires_at'])
            if now_ts > exp_date:
                conn.close()
                c.execute("UPDATE licenses SET status='expired' WHERE key=?", (req.license_key,))
                conn.commit()
                return encrypt_response({"status": "error", "message": "授权已过期。", "promo_url": promo_url}, req.device_id)
        except:
            pass # 格式解析失败则忽略，当做永久

    current_devices = row['activated_devices'].split(",") if row['activated_devices'] else []
    
    # 4. 获取公告与推广信息
    c.execute("SELECT value FROM system_config WHERE key='announcement_global'")
    global_anno = c.fetchone()
    
    if global_anno and global_anno[0]:
        announcement = global_anno[0]
        c.execute("SELECT value FROM system_config WHERE key='anno_mode_global'")
        mode_row = c.fetchone()
        anno_mode = mode_row[0] if mode_row else "once"
    else:
        c.execute("SELECT value FROM system_config WHERE key=?", (f"announcement_{req.product_id}",))
        anno_row = c.fetchone()
        announcement = anno_row[0] if anno_row else ""
        c.execute("SELECT value FROM system_config WHERE key=?", (f"anno_mode_{req.product_id}",))
        mode_row = c.fetchone()
        anno_mode = mode_row[0] if mode_row else "once"
    
    # 全局推广 URL 已经在头部提早获取过了，此处无需再次查询
    
    # 试用期元数据准备
    is_trial = bool(row['is_trial'])
    expiry_ts = 0
    if row['expires_at']:
        try:
            exp_date = datetime.fromisoformat(row['expires_at'])
            expiry_ts = int(exp_date.timestamp())
        except:
            pass
    
    server_time = int(datetime.utcnow().timestamp())

    # 5. 验证设备
    if req.device_id in current_devices:
        # 已授权设备：更新最后活跃时间 + 清除错误信息
        c.execute("UPDATE licenses SET last_active_at=?, last_error=NULL WHERE key=?", (now_ts.isoformat(), req.license_key))
        conn.commit()
        conn.close()
        return encrypt_response({
            "status": "success", 
            "message": "验证通过", 
            "announcement": announcement, 
            "anno_mode": anno_mode,
            "is_trial": is_trial,
            "expiry_ts": expiry_ts,
            "promo_url": promo_url,
            "server_time": server_time
        }, req.device_id)
    
    # 6. 新设备处理与挤号逻辑 (严格安全策略)
    max_seats = row['max_seats']
    
    # 频率限制：按月计费，每月仅限换绑 1 次 (Prevent Account Sharing)
    cur_month = now_ts.strftime("%Y-%m")
    c.execute("SELECT change_count FROM device_history WHERE license_key=? AND change_date=?", (req.license_key, cur_month))
    hist_row = c.fetchone()
    current_changes = hist_row[0] if hist_row else 0
    
    if current_changes >= 1: # 每月限 1 次
        # 72小时冷却豁免逻辑 (Human-Centric Grace Period)
        can_bypass = False
        if row['last_active_at']:
            try:
                last_active = datetime.fromisoformat(row['last_active_at'])
                delta = now_ts - last_active
                if delta.total_seconds() >= 259200: # 72 Hours
                    can_bypass = True
            except:
                pass
        
        if not can_bypass:
            # 记录报错以便管理员售后诊断
            c.execute("UPDATE licenses SET last_error=? WHERE key=?", (f"换绑超限: {cur_month} 已换绑 {current_changes} 次 (上限 1)", req.license_key))
            conn.commit()
            conn.close()
            return encrypt_response({"status": "error", "message": f"该授权每月仅限换绑设备 1 次，本月 ({cur_month}) 额度已用完。如果由于更换硬件导致无法激活，请在上次活跃 72 小时后尝试，或联系管理员手动重置。"}, req.device_id)

    # 执行绑定/挤号
    new_devices = current_devices
    if len(current_devices) < max_seats:
        new_devices.append(req.device_id)
    else:
        # 挤号策略：FIFO (挤掉第一个)
        # 如果只有1个位置，直接替换；如果有多个，挤掉列表里的第一个
        if len(new_devices) > 0:
            new_devices.pop(0) 
        new_devices.append(req.device_id)
    
    # 更新数据库
    c.execute("UPDATE licenses SET activated_devices=?, last_active_at=?, last_error=NULL WHERE key=?", 
              (",".join(new_devices), now_ts.isoformat(), req.license_key))
    
    # 更新变动记录 (按月统计)
    if hist_row:
        c.execute("UPDATE device_history SET change_count=change_count+1 WHERE license_key=? AND change_date=?", (req.license_key, cur_month))
    else:
        c.execute("INSERT INTO device_history (license_key, change_date, change_count) VALUES (?, ?, ?)", (req.license_key, cur_month, 1))
        
    # 写入心跳审计日志 (无论是否是新设备，验证成功即记录)
    c.execute("INSERT INTO heartbeat_logs (license_key, device_id, timestamp) VALUES (?, ?, ?)", 
              (req.license_key, req.device_id, now_ts.isoformat()))

    conn.commit()
    conn.close()
    
    return encrypt_response({
        "status": "success", 
        "message": "激活成功 (新设备已成功绑定)", 
        "announcement": announcement, 
        "anno_mode": anno_mode,
        "is_trial": is_trial,
        "expiry_ts": expiry_ts,
        "promo_url": promo_url,
        "server_time": server_time
    }, req.device_id)

@app.post("/api/request_trial")
def api_request_trial(req: RequestTrialRequest):
    conn = get_db()
    c = conn.cursor()
    
    # 1. 检查此 hardware_id 是否已经用过该产品的试用
    query = """
    SELECT key FROM licenses 
    WHERE is_trial = 1 
      AND product_id LIKE ? 
      AND (activated_devices = ? OR activated_devices LIKE ? OR activated_devices LIKE ? OR activated_devices LIKE ?)
    """
    pid_param = f"%{req.product_id}%"
    d_exact = req.hardware_id
    d_start = f"{req.hardware_id},%"
    d_end = f"%,{req.hardware_id}"
    d_mid = f"%,{req.hardware_id},%"
    
    c.execute(query, (pid_param, d_exact, d_start, d_end, d_mid))
    existing_trial = c.fetchone()
    
    # 提前获取 promo_url 以备弹窗跳转
    c.execute("SELECT value FROM system_config WHERE key=?", (f"promo_url_{req.product_id}",))
    promo_row = c.fetchone()
    if not promo_row or promo_row[0] == "" or promo_row[0] is None:
        c.execute("SELECT value FROM system_config WHERE key='promo_url__ALL_'")
        promo_row = c.fetchone()
        if not promo_row or promo_row[0] == "" or promo_row[0] is None:
            c.execute("SELECT value FROM system_config WHERE key='promo_url_GLOBAL'")
            promo_row = c.fetchone()
    promo_url = promo_row[0] if promo_row and promo_row[0] else ""
    
    if existing_trial:
        conn.close()
        return encrypt_response({"status": "error", "message": "试用名额已用完，快去解锁正式版吧", "already_used": True, "promo_url": promo_url}, req.hardware_id)
        
    # 2. 全局剥夺单品配置：统一强制获取全局默认试用天数
    c.execute("SELECT value FROM system_config WHERE key='default_trial_days__ALL_'")
    days_row = c.fetchone()
    trial_days = int(days_row[0]) if days_row and days_row[0] else 7
    
    if trial_days <= 0:
        conn.close()
        return encrypt_response({"status": "error", "message": "该产品当前未开放自助试用", "promo_url": promo_url}, req.hardware_id)
        
    # 3. 生成新试用卡并绑定
    new_key = generate_serial_number()
    created_at = datetime.utcnow().isoformat()
    from datetime import timedelta
    expires_at = (datetime.utcnow() + timedelta(days=trial_days)).isoformat()
    
    c.execute('''INSERT INTO licenses 
                 (key, max_seats, activated_devices, user_contact, order_id, created_at, expires_at, status, product_id, remark, is_trial)
                 VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''', 
               (new_key, 1, req.hardware_id, "Auto-Trial", "TRIAL", created_at, expires_at, "active", req.product_id, "机器自发", 1))
    
    conn.commit()
    conn.close()
    
    return encrypt_response({"status": "success", "license_key": new_key, "trial_days": trial_days, "promo_url": promo_url}, req.hardware_id)

@app.get("/api/get_promo")
def api_get_promo(product_id: str):
    """
    静默拉取指定产品的推广链接 (用于在用户弹出授权界面但未激活时进行引流)
    """
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT value FROM system_config WHERE key=?", (f"promo_url_{product_id}",))
    row = c.fetchone()
    
    # 修改：必须显式判断 row["value"] 是否为空字符串，防止仅仅因为键存在而跳过回退
    if not row or row["value"] == "" or row["value"] is None:
        c.execute("SELECT value FROM system_config WHERE key='promo_url__ALL_'")
        row = c.fetchone()
        
        # Add a secondary fallback because the modern Vue frontend uses 'GLOBAL' instead of '_ALL_'
        if not row or row["value"] == "" or row["value"] is None:
            c.execute("SELECT value FROM system_config WHERE key='promo_url_GLOBAL'")
            row = c.fetchone()
            
    conn.close()
    
    url = row["value"] if row and row["value"] else ""
    return {"promo_url": url}

# ===================== 管理员接口 =====================

@app.post("/admin/generate")
def admin_generate(req: GenerateRequest):
    if req.token != ADMIN_TOKEN:
        raise HTTPException(status_code=403, detail="Invalid Token")
    
    new_key = generate_serial_number()
    created_at = datetime.utcnow().isoformat()
    expires_at = None
    if req.duration_days > 0:
        # 计算过期时间
        from datetime import timedelta
        expires_at = (datetime.utcnow() + timedelta(days=req.duration_days)).isoformat()

    conn = get_db()
    c = conn.cursor()
    
    # 将产品列表转为逗号分隔字符串
    pids_str = ",".join(req.product_ids)
    
    c.execute('''INSERT INTO licenses 
                 (key, max_seats, activated_devices, user_contact, order_id, created_at, expires_at, status, product_id, remark, is_trial)
                 VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''', 
               (new_key, req.seats, "", req.contact, req.order_id, created_at, expires_at, "active", pids_str, req.remark, 1 if req.is_trial else 0))
    conn.commit()
    conn.close()
    return {"status": "ok", "key": new_key}

stats_cache = {"timestamp": 0, "data": None}

@app.get("/admin/stats")
def admin_stats(token: str):
    global stats_cache
    if token != ADMIN_TOKEN:
        raise HTTPException(status_code=403, detail="Invalid Token")
    
    # Check cache (5 seconds refresh)
    now_ts = datetime.utcnow().timestamp()
    if now_ts - stats_cache["timestamp"] < 5 and stats_cache["data"] is not None:
        return stats_cache["data"]

    conn = get_db()
    c = conn.cursor()
    # 联查所有记录
    c.execute("SELECT * FROM licenses ORDER BY created_at DESC")
    rows = c.fetchall()
    
    # 转 Dict，并附带显示名称信息
    licenses_result = []
    product_ids_set = {"ArchivePro"}
    product_names = {} # cache
    
    for r in rows:
        d = dict(r)
        pids = [p.strip() for p in d.get('product_id', '').split(",") if p.strip()]
        for pid in pids: product_ids_set.add(pid)
        
        # 为当前行展示主要产品（列表里暂时取第一个作为主显，或保持逗号字符串）
        main_pid = pids[0] if pids else 'ArchivePro'
        if main_pid not in product_names:
            c.execute("SELECT value FROM system_config WHERE key=?", (f"display_name_{main_pid}",))
            dn_row = c.fetchone()
            product_names[main_pid] = dn_row[0] if dn_row else main_pid
        
        d['display_name'] = product_names[main_pid]
        licenses_result.append(d)
    
    # 额外发现：从 system_config 中查找没有任何授权但有配置的产品
    c.execute("SELECT key FROM system_config WHERE key LIKE 'display_name_%' OR key LIKE 'announcement_%'")
    cfg_rows = c.fetchall()
    for cr in cfg_rows:
        key = cr[0]
        if key.startswith("display_name_"): product_ids_set.add(key.replace("display_name_", ""))
        elif key.startswith("announcement_"): 
            potential_pid = key.replace("announcement_", "")
            if potential_pid != "global": product_ids_set.add(potential_pid)

    # 计算转化率 (Conversion Tracking)
    # 逻辑: 找到所有用过 trial=1 授权的 device_id，看他们是否也出现在 trial=0 的授权列表中
    trial_devices = set()
    permanent_devices = set()
    
    for r in rows:
        devices = [d.strip() for d in (r['activated_devices'] or "").split(",") if d.strip()]
        if r['is_trial']:
            for d_id in devices: trial_devices.add(d_id)
        else:
            for d_id in devices: permanent_devices.add(d_id)
            
    converted_devices = trial_devices.intersection(permanent_devices)
    conversion_rate = (len(converted_devices) / len(trial_devices) * 100) if trial_devices else 0

    # 扩展销售数据核算 (Batch 4)
    nowUtc = datetime.utcnow()
    today_str = nowUtc.strftime("%Y-%m-%d")
    issued_today = sum(1 for r in rows if r['created_at'] and r['created_at'].startswith(today_str))
    
    trial_churn = len(trial_devices) - len(converted_devices)
    total_unique_devices = len(trial_devices.union(permanent_devices))
    permanent_ratio = (len(permanent_devices) / total_unique_devices * 100) if total_unique_devices > 0 else 0

    # 获取产品状态
    deleted_products = set()
    c.execute("SELECT key FROM system_config WHERE key LIKE 'product_status_%' AND value='deleted'")
    for status_row in c.fetchall():
        deleted_products.add(status_row[0].replace("product_status_", ""))
    
    active_products = product_ids_set - deleted_products

    # 获取所有产品的显示名称映射
    full_product_names = {}
    for pid in product_ids_set:
        c.execute("SELECT value FROM system_config WHERE key=?", (f"display_name_{pid}",))
        dn_row = c.fetchone()
        full_product_names[pid] = dn_row[0] if dn_row else pid

    conn.close()
    
    stats_cache["timestamp"] = now_ts
    stats_cache["data"] = {
        "licenses": licenses_result,
        "all_products": sorted(list(active_products)),
        "deleted_products": sorted(list(deleted_products)),
        "product_names": full_product_names,
        "stats": {
            "total_trial_devices": len(trial_devices),
            "total_permanent_devices": len(permanent_devices),
            "converted_devices": len(converted_devices),
            "conversion_rate": round(conversion_rate, 2),
            "issued_today": issued_today,
            "trial_churn": trial_churn,
            "permanent_ratio": round(permanent_ratio, 2)
        }
    }
    return stats_cache["data"]

@app.post("/admin/ban")
def admin_ban(req: BanRequest):
    if req.token != ADMIN_TOKEN:
        raise HTTPException(status_code=403, detail="Invalid Token")
    
    new_status = 'banned' if req.action == 'ban' else 'active'
    conn = get_db()
    c = conn.cursor()
    c.execute("UPDATE licenses SET status=? WHERE key=?", (new_status, req.license_key))
    conn.commit()
    conn.close()
    
    # Invalidate cache
    stats_cache["timestamp"] = 0
    
    return {"status": "ok", "msg": f"Key {req.license_key} is now {new_status}"}

@app.post("/admin/reset")
def admin_reset(req: ResetRequest):
    if req.token != ADMIN_TOKEN:
        raise HTTPException(status_code=403, detail="Invalid Token")
    
    conn = get_db()
    c = conn.cursor()
    # 清空设备绑定
    c.execute("UPDATE licenses SET activated_devices='' WHERE key=?", (req.license_key,))
    conn.commit()
    conn.close()
    
    # Invalidate cache
    stats_cache["timestamp"] = 0
    
    return {"status": "ok", "msg": f"Key {req.license_key} devices reset."}

@app.post("/admin/clear_expired_trials")
def admin_clear_expired_trials(req: dict):
    if req.get("token") != ADMIN_TOKEN:
        raise HTTPException(status_code=403, detail="Invalid Token")
    
    conn = get_db()
    c = conn.cursor()
    # 软删除所有已过期的试用凭证
    now_ts = datetime.utcnow().isoformat()
    c.execute("UPDATE licenses SET status='deleted' WHERE is_trial=1 AND status != 'deleted' AND expires_at < ?", (now_ts,))
    deleted_count = c.rowcount
    conn.commit()
    conn.close()
    
    # Invalidate cache
    stats_cache["timestamp"] = 0
    
    return {"status": "ok", "deleted_count": deleted_count}

@app.get("/admin/get_announcement")
def get_announcement(product_id: str, token: str):
    if token != ADMIN_TOKEN:
        raise HTTPException(status_code=403, detail="Invalid Token")
    conn = get_db()
    c = conn.cursor()
    
    # 获取公告
    key_name = f"announcement_{product_id}"
    c.execute("SELECT value FROM system_config WHERE key=?", (key_name,))
    row = c.fetchone()
    
    # 获取显示名称
    c.execute("SELECT value FROM system_config WHERE key=?", (f"display_name_{product_id}",))
    dn_row = c.fetchone()
    
    # 获取模式
    c.execute("SELECT value FROM system_config WHERE key=?", (f"anno_mode_{product_id}",))
    mode_row = c.fetchone()
    
    # 获取推广 URL
    c.execute("SELECT value FROM system_config WHERE key=?", (f"promo_url_{product_id}",))
    promo_row = c.fetchone()
    
    # 获取全局默认试用天数 (试用天数已剥夺单品权，全权由全局掌控)
    c.execute("SELECT value FROM system_config WHERE key='default_trial_days__ALL_'")
    days_row = c.fetchone()
    
    conn.close()
    return {
        "message": row["value"] if row else "",
        "display_name": dn_row[0] if dn_row else product_id,
        "anno_mode": mode_row[0] if mode_row else "once",
        "promo_url": promo_row[0] if promo_row else "",
        "default_trial_days": int(days_row[0]) if days_row else 7
    }

@app.post("/admin/announcement")
def admin_announcement(req: AnnouncementRequest):
    if req.token != ADMIN_TOKEN:
        raise HTTPException(status_code=403, detail="Invalid Token")
    
    conn = get_db()
    c = conn.cursor()
    # 支持 GLOBAL 作为特殊产品 ID
    key_name = f"announcement_{req.product_id}" if req.product_id != "GLOBAL" else "announcement_global"
    
    if req.message and req.message.strip():
        c.execute("INSERT OR REPLACE INTO system_config (key, value) VALUES (?, ?)", (key_name, req.message))
        # 存入模式
        mode_key = f"anno_mode_{req.product_id}" if req.product_id != "GLOBAL" else "anno_mode_global"
        c.execute("INSERT OR REPLACE INTO system_config (key, value) VALUES (?, ?)", (mode_key, req.anno_mode))
    else:
        c.execute("DELETE FROM system_config WHERE key=?", (key_name,))
        mode_key = f"anno_mode_{req.product_id}" if req.product_id != "GLOBAL" else "anno_mode_global"
        c.execute("DELETE FROM system_config WHERE key=?", (mode_key,))
        
    conn.commit()
    conn.close()
    return {"status": "ok", "msg": "Announcement updated."}

@app.post("/admin/clear_all_announcements")
def clear_all_announcements(req: AdminRequest):
    if req.token != ADMIN_TOKEN:
        raise HTTPException(status_code=403, detail="Invalid Token")
    conn = get_db()
    c = conn.cursor()
    c.execute("DELETE FROM system_config WHERE key LIKE 'announcement_%'")
    conn.commit()
    conn.close()
    return {"status": "ok", "msg": "All announcements cleared."}

@app.post("/admin/update_license")
def admin_update_license(req: UpdateLicenseRequest):
    if req.token != ADMIN_TOKEN:
        raise HTTPException(status_code=403, detail="Invalid Token")
    
    conn = get_db()
    c = conn.cursor()
    
    updates = []
    params = []
    if req.user_contact is not None:
        updates.append("user_contact=?")
        params.append(req.user_contact)
    if req.remark is not None:
        updates.append("remark=?")
        params.append(req.remark)
        
    if not updates:
        conn.close()
        return {"status": "error", "message": "Nothing to update"}
        
    params.append(req.license_key)
    query = f"UPDATE licenses SET {', '.join(updates)} WHERE key=?"
    c.execute(query, tuple(params))
    
    conn.commit()
    conn.close()
    return {"status": "success", "msg": f"License {req.license_key} updated."}

@app.post("/admin/delete")
def admin_delete(req: DeleteRequest):
    if req.token != ADMIN_TOKEN:
        raise HTTPException(status_code=403, detail="Invalid Token")
    conn = get_db()
    c = conn.cursor()
    # 彻底物理删除 (依用户要求：“对于激活码删了就删了”)
    c.execute("DELETE FROM licenses WHERE key=?", (req.license_key,))
    c.execute("DELETE FROM device_history WHERE license_key=?", (req.license_key,))
    conn.commit()
    conn.close()
    
    global stats_cache
    stats_cache["timestamp"] = 0
    return {"status": "ok", "msg": f"Key {req.license_key} physically deleted."}

@app.post("/admin/restore")
def admin_restore(req: AdminRequest):
    if req.token != ADMIN_TOKEN:
        raise HTTPException(status_code=403, detail="Invalid Token")
    conn = get_db()
    c = conn.cursor()
    c.execute("UPDATE licenses SET status='active' WHERE key=?", (req.license_key,))
    conn.commit()
    conn.close()
    
    global stats_cache
    stats_cache["timestamp"] = 0
    return {"status": "ok", "msg": f"Key {req.license_key} restored."}



@app.post("/admin/rename_product")
def admin_rename_product(req: RenameProductRequest):
    if req.token != ADMIN_TOKEN:
        raise HTTPException(status_code=403, detail="Invalid Token")
    
    conn = get_db()
    c = conn.cursor()
    
    # 1. Update licenses table
    c.execute("UPDATE licenses SET product_id=? WHERE product_id=?", (req.new_name, req.old_name))
    license_updates = c.rowcount
    
    # 2. Update system_config (announcements)
    # Announcement keys are stored as "announcement_{product_id}"
    old_key = f"announcement_{req.old_name}"
    new_key = f"announcement_{req.new_name}"
    c.execute("UPDATE system_config SET key=? WHERE key=?", (new_key, old_key))
    
    conn.commit()
    conn.close()
    
    return {
        "status": "success", 
        "msg": f"Renamed product ID '{req.old_name}' to '{req.new_name}'. Updated {license_updates} licenses."
    }

@app.post("/admin/update_display_name")
def admin_update_display_name(req: DisplayNameRequest):
    if req.token != ADMIN_TOKEN:
        raise HTTPException(status_code=403, detail="Invalid Token")
    
    key_name = f"display_name_{req.product_id}"
    conn = get_db()
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO system_config (key, value) VALUES (?, ?)", (key_name, req.display_name))
    conn.commit()
    conn.close()
    return {"status": "success", "msg": f"Display name for {req.product_id} updated."}

@app.post("/admin/delete_product")
def admin_delete_product(req: DeleteProductRequest):
    if req.token != ADMIN_TOKEN:
        raise HTTPException(status_code=403, detail="Invalid Token")
    
    conn = get_db()
    c = conn.cursor()
    
    # 软删除：仅将关联授权标记为 deleted，保留基础数据以供报表统计和回收站恢复
    c.execute("SELECT key, product_id FROM licenses")
    rows = c.fetchall()
    deleted_licenses = 0
    for row in rows:
        key = row['key']
        pids = [p.strip() for p in row['product_id'].split(",")]
        if req.product_id in pids:
            if len(pids) == 1:
                # 仅包含该产品，软删除：改状态
                c.execute("UPDATE licenses SET status='deleted' WHERE key=?", (key,))
                deleted_licenses += 1
            else:
                # 包含多个产品，仅从中移除该产品标识
                new_pids = [p for p in pids if p != req.product_id]
                c.execute("UPDATE licenses SET product_id=? WHERE key=?", (",".join(new_pids), key))

    # 2. 软删除产品本身：打上回收站标记，不再清除显示名称和公告
    c.execute("INSERT OR REPLACE INTO system_config (key, value) VALUES (?, ?)", (f"product_status_{req.product_id}", "deleted"))
    
    conn.commit()
    conn.close()
    
    global stats_cache
    stats_cache["timestamp"] = 0
    
    return {
        "status": "success", 
        "msg": f"Product '{req.product_id}' archived and {deleted_licenses} licenses moved to recycle bin."
    }

@app.post("/admin/restore_product")
def admin_restore_product(req: DeleteProductRequest):
    if req.token != ADMIN_TOKEN:
        raise HTTPException(status_code=403, detail="Invalid Token")
    
    conn = get_db()
    c = conn.cursor()
    
    # 1. 恢复产品页本身
    c.execute("DELETE FROM system_config WHERE key=?", (f"product_status_{req.product_id}",))
    
    # 2. 批量恢复该页面的授权码
    # 此处粗略将包含该 PID 的处于 deleted 状态的授权全部激活
    c.execute("SELECT key, product_id FROM licenses WHERE status='deleted'")
    rows = c.fetchall()
    restored = 0
    for row in rows:
        pids = [p.strip() for p in row['product_id'].split(",")]
        if req.product_id in pids:
            c.execute("UPDATE licenses SET status='active' WHERE key=?", (row['key'],))
            restored += 1
            
    conn.commit()
    conn.close()
    
    global stats_cache
    stats_cache["timestamp"] = 0
    
    return {
        "status": "success", 
        "msg": f"Product '{req.product_id}' restored along with {restored} licenses."
    }

@app.post("/admin/update_promo_url")
def admin_update_promo_url(req: UpdatePromoUrlRequest):
    if req.token != ADMIN_TOKEN:
        raise HTTPException(status_code=403, detail="Invalid Token")
    
    key_name = f"promo_url_{req.product_id}"
    days_key = f"default_trial_days_{req.product_id}"
    conn = get_db()
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO system_config (key, value) VALUES (?, ?)", (key_name, req.promo_url))
    
    # 根据用户要求，试用天数仅限全局 (_ALL_ / GLOBAL) 唯一控制，保护单品不被脏数据覆盖
    if req.product_id in ('_ALL_', 'GLOBAL'):
        c.execute("INSERT OR REPLACE INTO system_config (key, value) VALUES (?, ?)", ("default_trial_days__ALL_", str(req.default_trial_days)))
        
    conn.commit()
    conn.close()
    return {"status": "success", "msg": f"推广配置已为 {req.product_id} 同步更新。"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
