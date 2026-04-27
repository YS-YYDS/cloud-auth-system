from fastapi import APIRouter, HTTPException, Request, Depends
from datetime import datetime, timedelta, timezone
import logging
from ..core.crypto import derive_session_key, encrypt_response
from ..core.utils import SimpleRateLimiter, generate_serial_number, get_promo_url
from ..db.session import get_db
from ..models.schemas import VerifyRequest, RequestTrialRequest

router = APIRouter()
logger = logging.getLogger("CloudAuth.Auth")

# [ARCHITECTURE] 注入解耦后的模块类
limiter = SimpleRateLimiter(60)


def _fetch_announcement(cursor, product_id: str) -> tuple[str, str]:
    """统一读取公告内容与模式 (全局优先 > 产品级 > 默认空)"""
    announcement = ""
    anno_mode = "once"
    try:
        cursor.execute("SELECT value FROM system_config WHERE key='announcement_global'")
        global_anno = cursor.fetchone()
        if global_anno and global_anno[0]:
            announcement = global_anno[0]
            cursor.execute("SELECT value FROM system_config WHERE key='anno_mode_global'")
            mode_row = cursor.fetchone()
            anno_mode = mode_row[0] if mode_row else "once"
        else:
            cursor.execute("SELECT value FROM system_config WHERE key=?", (f"announcement_{product_id}",))
            anno_row = cursor.fetchone()
            announcement = anno_row[0] if anno_row else ""
            cursor.execute("SELECT value FROM system_config WHERE key=?", (f"anno_mode_{product_id}",))
            mode_row = cursor.fetchone()
            anno_mode = mode_row[0] if mode_row else "once"
    except Exception as e:
        logger.warning(f"AnnoErr: prod={product_id} err={e}")
    return announcement, anno_mode

@router.post("/verify")
def verify_license(req: VerifyRequest, request: Request, conn=Depends(get_db)):
    dyn_armor_key = derive_session_key(req.license_key, req.product_id) if req.version == "2.0" else None
    
    def _respond(data: dict):
        return encrypt_response(data, req.device_id, dyn_armor_key=dyn_armor_key)

    client_ip = request.client.host if request.client else "127.0.0.1"
    if not limiter.is_allowed(client_ip):
        logger.warning(f"RateLimit_Exceeded: ip={client_ip}")
        raise HTTPException(status_code=429, detail="Too many requests.")


    c = conn.cursor()
    promo_url = get_promo_url(c, req.product_id)

    c.execute("SELECT * FROM licenses WHERE key=?", (req.license_key,))
    row = c.fetchone()

    if not row:
# 已由 Depends 自动管理
        return _respond({"status": "error", "message": "激活码不存在", "promo_url": promo_url})

    allowed_pids = [p.strip() for p in row["product_id"].split(",")]
    is_subscription = "ALL" in allowed_pids
    
    if req.product_id == "0":
        # [LDK-FIX] 脱敏日志：仅记录产品数量而非完整列表，防止业务泄密
        logger.info(f"Verify_Wildcard: key={req.license_key[:8]} product_count={len(allowed_pids)}")
    else:
        if req.product_id not in allowed_pids and not is_subscription:
            # 由 Depends(get_db) 自动管理
            return _respond({"status": "error", "message": f"不包含产品: {req.product_id}", "promo_url": promo_url})

    if row["status"] == "banned":
        # conn.close() 移除
        return _respond({"status": "error", "message": "授权已封禁", "promo_url": promo_url})

    now_ts = datetime.now(timezone.utc)
    if row["expires_at"]:
        try:
            exp_date = datetime.fromisoformat(row["expires_at"])
            # 兼容带有时区的解析
            if exp_date.tzinfo is None:
                exp_date = exp_date.replace(tzinfo=timezone.utc)
            if now_ts > exp_date:
                # conn.commit() 移除：验证逻辑原则上不应在此强制 commit，由生命周期管理
                # conn.close() 移除
                return _respond({"status": "error", "message": "授权已过期", "promo_url": promo_url})
        except Exception as e:
            logger.warning(f"Verify_ExpiryErr: key={req.license_key} err={e}")

    # 获取公告
    announcement, anno_mode = _fetch_announcement(c, req.product_id)

    is_trial = bool(row["is_trial"])
    expiry_ts = 0
    if row["expires_at"]:
        try:
            dt = datetime.fromisoformat(row["expires_at"])
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            expiry_ts = int(dt.timestamp())
        except (ValueError, TypeError) as e:
            logger.warning(f"Verify_ParseErr: key={req.license_key[:8]} err={e}")

    server_time = int(datetime.now(timezone.utc).timestamp())
    current_devices = [d for d in (row["activated_devices"] or "").split(",") if d]

    if req.device_id in current_devices:
        c.execute("UPDATE licenses SET last_active_at=?, last_error=NULL WHERE key=?", (now_ts.isoformat(), req.license_key))
        conn.commit()
# 已由 Depends 自动管理
        logger.info(f"Verify: success key={req.license_key[:8]}***")
        return _respond({
            "status": "success", "message": "验证通过",
            "announcement": announcement, "anno_mode": anno_mode,
            "is_trial": is_trial, "is_subscription": is_subscription, "expiry_ts": expiry_ts,
            "products": {pid: {"expiry_ts": expiry_ts} for pid in allowed_pids}, 
            "promo_url": promo_url, "server_time": server_time,
        })

    # 换绑限制
    cur_month = now_ts.strftime("%Y-%m")
    c.execute("SELECT change_count FROM device_history WHERE license_key=? AND change_date=?", (req.license_key, cur_month))
    hist_row = c.fetchone()
    current_changes = hist_row[0] if hist_row else 0

    if current_changes >= 1:
        can_bypass = False
        if row["last_active_at"]:
            try:
                last_active = datetime.fromisoformat(row["last_active_at"])
                if last_active.tzinfo is None:
                    last_active = last_active.replace(tzinfo=timezone.utc)
                if now_ts - last_active >= timedelta(days=3): # 3 days bypass
                    can_bypass = True
            except (ValueError, TypeError, Exception) as e:
                logger.warning(f"Verify_ActiveParseErr: key={req.license_key[:8]} err={e}")

        if not can_bypass:
            c.execute("UPDATE licenses SET last_error=? WHERE key=?", (f"换绑超限: {cur_month}", req.license_key))
            conn.commit()
            # conn.close() 移除：由 Depends(get_db) 自动管理
            return _respond({"status": "error", "message": "该授权每月仅限换绑设备 1 次"})

    # 挤号 FIFO
    max_seats = row["max_seats"]
    if len(current_devices) < max_seats:
        current_devices.append(req.device_id)
    else:
        if current_devices: current_devices.pop(0)
        current_devices.append(req.device_id)

    c.execute("UPDATE licenses SET activated_devices=?, last_active_at=?, last_error=NULL WHERE key=?",
              (",".join(current_devices), now_ts.isoformat(), req.license_key))
    if hist_row:
        c.execute("UPDATE device_history SET change_count=change_count+1 WHERE license_key=? AND change_date=?", (req.license_key, cur_month))
    else:
        c.execute("INSERT INTO device_history (license_key, change_date, change_count) VALUES (?, ?, ?)", (req.license_key, cur_month, 1))

    c.execute("INSERT INTO heartbeat_logs (license_key, device_id, timestamp) VALUES (?, ?, ?)",
              (req.license_key, req.device_id, now_ts.isoformat()))
    conn.commit()
    # conn.close() 移除：由 Depends(get_db) 自动管理
    logger.info(f"Verify: new_device_bound key={req.license_key[:8]}***")
    return _respond({
        "status": "success", "message": "激活成功",
        "announcement": announcement, "anno_mode": anno_mode,
        "is_trial": is_trial, "is_subscription": is_subscription, "expiry_ts": expiry_ts,
        "products": {pid: {"expiry_ts": expiry_ts} for pid in allowed_pids},
        "promo_url": promo_url, "server_time": server_time,
    })

@router.post("/api/request_trial")
def api_request_trial(req: RequestTrialRequest, request: Request, conn=Depends(get_db)):
    client_ip = request.client.host if request.client else "127.0.0.1"
    if not limiter.is_allowed(client_ip):
        logger.warning(f"RateLimit_Exceeded: ip={client_ip} route=request_trial")
        raise HTTPException(status_code=429, detail="Too many requests.")


    c = conn.cursor()
    promo_url = get_promo_url(c, req.product_id)
    
    # [P0-FIX] 安全修复：使用精确分段匹配替代不安全的 LIKE，防止通配符注入攻击。
    # 对 hardware_id 进行转义以防 LIKE 注入
    d_raw = req.hardware_id or ""
    d_exact = d_raw.replace("/", "//").replace("%", "/%").replace("_", "/_")
    
    c.execute("""SELECT key, expires_at FROM licenses WHERE is_trial=1 AND product_id=? 
                 AND (activated_devices=? OR activated_devices LIKE ? ESCAPE '/'
                      OR activated_devices LIKE ? ESCAPE '/' OR activated_devices LIKE ? ESCAPE '/')""",
              (req.product_id, d_raw, f"{d_exact},%", f"%,{d_exact}", f"%,{d_exact},%"))
    
    existing_row = c.fetchone()
    
    # [LDK-TRIAL] 使用 hardware_id 派生加密密钥，客户端可对称重建，无需共享密钥
    trial_armor_key = derive_session_key(req.hardware_id, req.product_id)

    if existing_row:
        logger.info(f"Trial_Request: recovered_existing device={d_raw[:12]}...")
        existing_key = existing_row["key"]
        recovered_expiry = 0
        if existing_row["expires_at"]:
            try:
                recovered_expiry = int(datetime.fromisoformat(existing_row["expires_at"]).timestamp())
            except Exception: pass

        # [FIX] 补齐 is_trial/is_subscription/announcement/anno_mode/server_time
        # 与 /verify 返回契约对齐，避免客户端跳过二次 Sync 后试用被误判为终身
        announcement, anno_mode = _fetch_announcement(c, req.product_id)
        server_time = int(datetime.now(timezone.utc).timestamp())

        # 由 Depends 自动管理
        return encrypt_response({
            "status": "error", 
            "already_used": True, 
            "recovered": True, 
            "license_key": existing_key, 
            "is_trial": True,
            "is_subscription": False,
            "expiry_ts": recovered_expiry,
            "announcement": announcement, "anno_mode": anno_mode,
            "products": {req.product_id: {"expiry_ts": recovered_expiry, "is_trial": True, "is_subscription": False}},
            "promo_url": promo_url, "server_time": server_time,
            "message": "检测到已有试用记录，正在自动找回..."
        }, d_raw, dyn_armor_key=trial_armor_key)

    c.execute("SELECT value FROM system_config WHERE key='default_trial_days__ALL_'")
    trial_days_row = c.fetchone()
    trial_days = int(trial_days_row[0]) if trial_days_row and trial_days_row[0] else 7
    
    new_key = generate_serial_number()
    expires_at = (datetime.now(timezone.utc) + timedelta(days=trial_days)).isoformat()
    c.execute("INSERT INTO licenses (key, max_seats, activated_devices, status, product_id, is_trial, expires_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
              (new_key, 1, d_raw, 'active', req.product_id, 1, expires_at))
    conn.commit()
    # conn.close() 移除：由 Depends(get_db) 自动管理
    # [FIX] 补齐 is_trial/is_subscription/announcement/anno_mode/server_time
    # 与 /verify 返回契约对齐，避免客户端跳过二次 Sync 后试用被误判为终身
    announcement, anno_mode = _fetch_announcement(c, req.product_id)
    trial_expiry_ts = int(datetime.fromisoformat(expires_at).timestamp())
    server_time = int(datetime.now(timezone.utc).timestamp())

    logger.info(f"Trial_Request: success device={d_raw[:12]}... key={new_key[:8]}***")
    return encrypt_response({
        "status": "success", 
        "license_key": new_key, 
        "is_trial": True,
        "is_subscription": False,
        "expiry_ts": trial_expiry_ts,
        "announcement": announcement, "anno_mode": anno_mode,
        "products": {req.product_id: {"expiry_ts": trial_expiry_ts, "is_trial": True, "is_subscription": False}},
        "promo_url": promo_url, "server_time": server_time,
    }, d_raw, dyn_armor_key=trial_armor_key)
