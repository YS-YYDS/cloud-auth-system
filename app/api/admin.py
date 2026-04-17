from fastapi import APIRouter, Header, Depends, HTTPException
from datetime import datetime, timedelta, timezone
import logging
import os
import threading
from ..db.session import get_db
from ..api.deps import check_admin
from ..core.utils import generate_serial_number
from ..models.schemas import (
    GenerateRequest, BanRequest, ResetRequest, AnnouncementRequest,
    UpdateLicenseRequest, DeleteRequest, RenameProductRequest,
    DisplayNameRequest, DeleteProductRequest, RegisterProductRequest,
    AdminRequest, UpdatePromoUrlRequest, PurgeTrashRequest
)

router = APIRouter(prefix="/admin", tags=["Admin"])
logger = logging.getLogger("CloudAuth.Admin")

# 统计信息缓存
stats_lock = threading.Lock()
stats_cache = {"timestamp": 0, "data": None}

def clear_cache():
    with stats_lock:
        stats_cache["timestamp"] = 0

@router.post("/generate")
def admin_generate(req: GenerateRequest, conn=Depends(get_db), _=Depends(check_admin)):
    new_key = generate_serial_number()
    now_ts = datetime.now(timezone.utc)
    created_at = now_ts.isoformat()
    expires_at = (now_ts + timedelta(days=req.duration_days)).isoformat() if req.duration_days > 0 else None
    pids_str = ",".join([p.strip() for p in req.product_ids if p.strip()])
    
    
    c = conn.cursor()
    c.execute("""INSERT INTO licenses 
                 (key, max_seats, activated_devices, user_contact, order_id, 
                  created_at, expires_at, status, product_id, remark, is_trial)
                 VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
              (new_key, req.seats, "", req.contact, req.order_id,
               created_at, expires_at, "active", pids_str, req.remark, 1 if req.is_trial else 0))
    conn.commit()
# conn.close() 移除
    
    clear_cache()
    logger.info(f"Admin_Generate: key={new_key[:8]}*** products={pids_str}")
    return {"status": "ok", "key": new_key}

@router.get("/stats")
def admin_stats(conn=Depends(get_db), _=Depends(check_admin)):
    now_ts = datetime.now(timezone.utc).timestamp()
    with stats_lock:
        if now_ts - stats_cache["timestamp"] < 5 and stats_cache["data"] is not None:
            logger.info("Admin_Stats: cache_hit")
            return stats_cache["data"]

    logger.info("Admin_Stats: cache_miss_refreshing")
    c = conn.cursor()
    c.execute("SELECT * FROM licenses ORDER BY created_at DESC")
    rows = c.fetchall()

    licenses_result = []
    product_ids_set = set()

    # N+1 优化：预抓取所有显示名称
    c.execute("SELECT key, value FROM system_config WHERE key LIKE 'display_name_%'")
    display_names_map = {r[0].replace("display_name_", ""): r[1] for r in c.fetchall()}

    for r in rows:
        d = dict(r)
        pids = [p.strip() for p in d.get("product_id", "").split(",") if p.strip()]
        for pid in pids: product_ids_set.add(pid)
        main_pid = pids[0] if pids else "GENERIC_ID"
        d["display_name"] = display_names_map.get(main_pid, main_pid)
        d["is_subscription"] = any(p in ("ALL", "_ALL_") for p in pids)
        licenses_result.append(d)

    c.execute("SELECT key FROM system_config WHERE key LIKE 'display_name_%' OR key LIKE 'announcement_%'")
    for cr in c.fetchall():
        key = cr[0]
        if key.startswith("display_name_"):
            product_ids_set.add(key.replace("display_name_", ""))
        elif key.startswith("announcement_"):
            pid = key.replace("announcement_", "")
            if pid != "global": product_ids_set.add(pid)

    trial_devices, permanent_devices = set(), set()
    for r in rows:
        devices = [d.strip() for d in (r["activated_devices"] or "").split(",") if d.strip()]
        if r["is_trial"]: trial_devices.update(devices)
        else: permanent_devices.update(devices)

    converted_devices = trial_devices & permanent_devices
    conversion_rate = (len(converted_devices) / len(trial_devices) * 100) if trial_devices else 0

    issued_today = sum(1 for r in rows if r["created_at"] and r["created_at"].startswith(datetime.now(timezone.utc).strftime("%Y-%m-%d")))
    total_unique_devices = len(trial_devices | permanent_devices)
    permanent_ratio = (len(permanent_devices) / total_unique_devices * 100) if total_unique_devices > 0 else 0

    deleted_products = set()
    c.execute("SELECT key FROM system_config WHERE key LIKE 'product_status_%' AND value='deleted'")
    for status_row in c.fetchall():
        deleted_products.add(status_row[0].replace("product_status_", ""))

    active_products = product_ids_set - deleted_products
    # 结果已在 display_names_map 中
    full_product_names = display_names_map
    with stats_lock:
        stats_cache["timestamp"] = now_ts
        stats_cache["data"] = {
            "licenses": licenses_result,
            "all_products": sorted(active_products),
            "deleted_products": sorted(deleted_products),
            "product_names": full_product_names,
            "stats": {
                "total_trial_devices": len(trial_devices),
                "total_permanent_devices": len(permanent_devices),
                "converted_devices": len(converted_devices),
                "conversion_rate": round(conversion_rate, 2),
                "issued_today": issued_today,
                "trial_churn": len(trial_devices) - len(converted_devices),
                "permanent_ratio": round(permanent_ratio, 2),
            },
        }
    return stats_cache["data"]

@router.post("/ban")
def admin_ban(req: BanRequest, conn=Depends(get_db), _=Depends(check_admin)):
    new_status = "banned" if req.action == "ban" else "active"
    c = conn.cursor()
    c.execute("UPDATE licenses SET status=? WHERE key=?", (new_status, req.license_key))
    conn.commit()
# 已由 Depends 自动管理
    clear_cache()
    logger.info(f"Admin_Ban: key={req.license_key[:8]}*** status={new_status}")
    return {"status": "ok"}

@router.post("/reset")
def admin_reset(req: ResetRequest, conn=Depends(get_db), _=Depends(check_admin)):
# conn = get_db() -> 移除
    c = conn.cursor()
    # 清空绑定设备列表
    c.execute("UPDATE licenses SET activated_devices='', last_error=NULL WHERE key=?", (req.license_key,))
    # [FIX] 同时清零当月换绑计数，否则用户解绑后立刻重新激活仍会触发"每月仅限换绑 1 次"限制
    cur_month = datetime.now(timezone.utc).strftime("%Y-%m")
    c.execute("DELETE FROM device_history WHERE license_key=? AND change_date=?", (req.license_key, cur_month))
    conn.commit()
# conn.close() -> 移除
    clear_cache()
    logger.info(f"Admin_Reset: key={req.license_key[:8]}*** month={cur_month} history_cleared")
    return {"status": "ok"}

@router.post("/clear_expired_trials")
def admin_clear_expired_trials(req: AdminRequest, conn=Depends(get_db), _=Depends(check_admin)):
# conn = get_db() -> 移除
    c = conn.cursor()
    now_ts = datetime.now(timezone.utc).isoformat()
    c.execute("UPDATE licenses SET status='deleted' WHERE is_trial=1 AND status != 'deleted' AND expires_at < ?", (now_ts,))
    deleted_count = c.rowcount
    conn.commit()
# conn.close() -> 移除
    clear_cache()
    logger.info(f"Admin_ClearExpiredTrials: deleted_count={deleted_count}")
    return {"status": "ok", "deleted_count": deleted_count}

@router.get("/get_announcement")
def get_announcement(product_id: str, conn=Depends(get_db), _=Depends(check_admin)):
# conn = get_db() -> 移除
    c = conn.cursor()
    key_name = f"announcement_{product_id}" if product_id != "GLOBAL" else "announcement_global"
    c.execute("SELECT value FROM system_config WHERE key=?", (key_name,))
    row = c.fetchone()
    c.execute("SELECT value FROM system_config WHERE key=?", (f"display_name_{product_id}",))
    dn_row = c.fetchone()
    mode_key = f"anno_mode_{product_id}" if product_id != "GLOBAL" else "anno_mode_global"
    c.execute("SELECT value FROM system_config WHERE key=?", (mode_key,))
    mode_row = c.fetchone()
    c.execute("SELECT value FROM system_config WHERE key=?", (f"promo_url_{product_id}",))
    promo_row = c.fetchone()
    c.execute("SELECT value FROM system_config WHERE key='default_trial_days__ALL_'")
    days_row = c.fetchone()
# conn.close() -> 移除
    return {
        "message": row["value"] if row else "",
        "display_name": dn_row[0] if dn_row else product_id,
        "anno_mode": mode_row[0] if mode_row else "once",
        "promo_url": promo_row[0] if promo_row else "",
        "default_trial_days": int(days_row[0]) if days_row and days_row[0] else 7,
    }

@router.post("/announcement")
def admin_announcement(req: AnnouncementRequest, conn=Depends(get_db), _=Depends(check_admin)):
# conn = get_db() -> 移除
    c = conn.cursor()
    key_name = f"announcement_{req.product_id}" if req.product_id != "GLOBAL" else "announcement_global"
    mode_key = f"anno_mode_{req.product_id}" if req.product_id != "GLOBAL" else "anno_mode_global"
    if req.message and req.message.strip():
        c.execute("INSERT OR REPLACE INTO system_config (key, value) VALUES (?, ?)", (key_name, req.message))
        c.execute("INSERT OR REPLACE INTO system_config (key, value) VALUES (?, ?)", (mode_key, req.anno_mode))
        safe_msg = req.message.replace("\n", " ").replace("\r", " ")[:50]
        logger.info(f"Admin_Announcement: updated product={req.product_id} mode={req.anno_mode} msg_preview='{safe_msg}...'")
    else:
        c.execute("DELETE FROM system_config WHERE key=?", (key_name,))
        c.execute("DELETE FROM system_config WHERE key=?", (mode_key,))
        logger.info(f"Admin_Announcement: deleted product={req.product_id}")
    conn.commit()
# conn.close() -> 移除
    return {"status": "ok"}

@router.post("/clear_all_announcements")
def admin_clear_all_announcements(req: AdminRequest, conn=Depends(get_db), _=Depends(check_admin)):
# conn = get_db() -> 移除
    c = conn.cursor()
    # 彻底撤回所有公告和显示模式设置
    c.execute("DELETE FROM system_config WHERE key LIKE 'announcement_%' OR key LIKE 'anno_mode_%'")
    conn.commit()
# conn.close() -> 移除
    logger.warning("Admin_ClearAllAnnouncements: all notices revoked")
    return {"status": "success"}

@router.post("/update_license")
def admin_update_license(req: UpdateLicenseRequest, conn=Depends(get_db), _=Depends(check_admin)):
# conn = get_db() -> 移除
    c = conn.cursor()
    updates, params = [], []
    if req.user_contact is not None:
        updates.append("user_contact=?"); params.append(req.user_contact)
    if req.remark is not None:
        updates.append("remark=?"); params.append(req.remark)
    if req.max_seats is not None:
        updates.append("max_seats=?"); params.append(req.max_seats)
    if req.product_ids is not None:
        p_str = ",".join([p.strip() for p in req.product_ids if p.strip()])
        # [SEC-WARN] 此处 updates 键名硬编码且绝对安全，切勿修改为外部动态拼接
        updates.append("product_id=?"); params.append(p_str)
    
    if not updates:
    # conn.close() -> 移除
        return {"status": "error", "message": "Nothing to update"}
    
    params.append(req.license_key)
    c.execute(f"UPDATE licenses SET {', '.join(updates)} WHERE key=?", tuple(params))
    conn.commit()
# conn.close() -> 移除
    clear_cache()
    logger.info(f"Admin_UpdateLicense: key={req.license_key[:8]}*** fields={list(updates)}")
    return {"status": "success"}

@router.post("/delete")
def admin_delete(req: DeleteRequest, conn=Depends(get_db), _=Depends(check_admin)):
# conn = get_db() -> 移除
    c = conn.cursor()
    c.execute("DELETE FROM licenses WHERE key=?", (req.license_key,))
    c.execute("DELETE FROM device_history WHERE license_key=?", (req.license_key,))
    conn.commit()
# conn.close() -> 移除
    clear_cache()
    logger.warning(f"Admin_Delete: key={req.license_key[:8]}***")
    return {"status": "ok"}

@router.post("/restore")
def admin_restore(req: AdminRequest, conn=Depends(get_db), _=Depends(check_admin)):
# conn = get_db() -> 移除
    c = conn.cursor()
    c.execute("UPDATE licenses SET status='active' WHERE key=?", (req.license_key,))
    conn.commit()
# conn.close() -> 移除
    clear_cache()
    logger.info(f"Admin_Restore: key={req.license_key[:8]}***")
    return {"status": "ok"}

@router.post("/register_product")
def admin_register_product(req: RegisterProductRequest, conn=Depends(get_db), _=Depends(check_admin)):
# conn = get_db() -> 移除
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO system_config (key, value) VALUES (?, ?)", (f"display_name_{req.pid}", req.name))
    c.execute("DELETE FROM system_config WHERE key=?", (f"product_status_{req.pid}",))
    conn.commit()
# conn.close() -> 移除
    clear_cache()
    logger.info(f"Admin_RegisterProduct: pid={req.pid} name={req.name}")
    return {"status": "success"}

@router.post("/delete_product")
def admin_delete_product(req: DeleteProductRequest, conn=Depends(get_db), _=Depends(check_admin)):
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO system_config (key, value) VALUES (?, ?)", 
              (f"product_status_{req.product_id}", "deleted"))
    conn.commit()
    clear_cache()
    logger.warning(f"Admin_DeleteProduct: pid={req.product_id}")
    return {"status": "success"}

@router.post("/restore_product")
def admin_restore_product(req: DeleteProductRequest, conn=Depends(get_db), _=Depends(check_admin)):
    c = conn.cursor()
    c.execute("DELETE FROM system_config WHERE key=?", (f"product_status_{req.product_id}",))
    conn.commit()
    clear_cache()
    logger.info(f"Admin_RestoreProduct: pid={req.product_id}")
    return {"status": "success"}

@router.post("/rename_product")
def admin_rename_product(req: RenameProductRequest, conn=Depends(get_db), _=Depends(check_admin)):
    old_pid, new_pid = req.old_id, req.new_id
    c = conn.cursor()
    # 更新所有相关配置键名
    for suffix in ("display_name_", "announcement_", "anno_mode_", "promo_url_", "product_status_"):
        c.execute("SELECT value FROM system_config WHERE key=?", (f"{suffix}{old_pid}",))
        row = c.fetchone()
        if row:
            c.execute("INSERT OR REPLACE INTO system_config (key, value) VALUES (?, ?)", (f"{suffix}{new_pid}", row[0]))
            c.execute("DELETE FROM system_config WHERE key=?", (f"{suffix}{old_pid}",))
    
    # [IMPORTANT] 注意：这里不自动更新 licenses 表中的 product_id 字段，
    # 因为 licenses 往往是历史记录，且 product_id 是逗号分隔的。
    # 重命名产品 ID 通常是一个“伪重命名”，主要影响显示和配置。
    
    conn.commit()
    clear_cache()
    logger.info(f"Admin_RenameProduct: {old_pid} -> {new_pid}")
    return {"status": "success"}

@router.post("/update_display_name")
def admin_update_display_name(req: DisplayNameRequest, conn=Depends(get_db), _=Depends(check_admin)):
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO system_config (key, value) VALUES (?, ?)", 
              (f"display_name_{req.product_id}", req.display_name))
    conn.commit()
    clear_cache()
    logger.info(f"Admin_UpdateDisplayName: pid={req.product_id} name={req.display_name}")
    return {"status": "success"}

@router.post("/purge_trash")
def admin_purge_trash(req: PurgeTrashRequest, conn=Depends(get_db), _=Depends(check_admin)):
# conn = get_db() -> 移除
    c = conn.cursor()
    c.execute("DELETE FROM licenses WHERE status='deleted'")
    licenses_count = c.rowcount
    c.execute("SELECT key FROM system_config WHERE key LIKE 'product_status_%' AND value='deleted'")
    deleted_pids = [row[0].replace("product_status_", "") for row in c.fetchall()]
    for pid in deleted_pids:
        for suffix in ("product_status_", "display_name_", "announcement_", "anno_mode_", "promo_url_"):
            c.execute("DELETE FROM system_config WHERE key=?", (f"{suffix}{pid}",))
    conn.commit()
# conn.close() -> 移除
    clear_cache()
    logger.info(f"Admin_PurgeTrash: licenses_deleted={licenses_count} products_purged={len(deleted_pids)}")
    return {"status": "success", "count": licenses_count}

@router.post("/purge_trash_single")
def admin_purge_trash_single(req: DeleteProductRequest, conn=Depends(get_db), _=Depends(check_admin)):
    pid = req.product_id
    c = conn.cursor()
    # 性能优化：使用 SQL LIKE 过滤代替全表内存遍历
    c.execute("DELETE FROM licenses WHERE product_id LIKE ? OR product_id LIKE ? OR product_id LIKE ? OR product_id = ?", 
              (f"{pid},%", f"%,{pid},%", f"%,{pid}", pid))
    deleted_count = c.rowcount

    for suffix in ("product_status_", "display_name_", "announcement_", "anno_mode_", "promo_url_"):
        c.execute("DELETE FROM system_config WHERE key=?", (f"{suffix}{pid}",))

    conn.commit()
    clear_cache()
    logger.warning(f"Admin_PurgeTrashSingle: pid={pid} deleted_count={deleted_count}")
    return {"status": "success", "deleted_count": deleted_count}

@router.post("/update_promo_url")
def admin_update_promo_url(req: UpdatePromoUrlRequest, conn=Depends(get_db), _=Depends(check_admin)):
# conn = get_db() -> 移除
    c = conn.cursor()
    key_name = f"promo_url_{req.product_id}"
    if req.promo_url and req.promo_url.strip():
        c.execute("INSERT OR REPLACE INTO system_config (key, value) VALUES (?, ?)", (key_name, req.promo_url))
        if req.product_id in ("_ALL_", "GLOBAL"):
            c.execute("INSERT OR REPLACE INTO system_config (key, value) VALUES (?, ?)",
                      ("default_trial_days__ALL_", str(req.default_trial_days)))
        safe_url = req.promo_url.replace("\n", "").replace("\r", "")[:100]
        logger.info(f"Admin_UpdatePromoUrl: product={req.product_id} url={safe_url}")
    else:
        c.execute("DELETE FROM system_config WHERE key=?", (key_name,))
        logger.info(f"Admin_UpdatePromoUrl: deleted for product={req.product_id}")
    
    conn.commit()
# conn.close() -> 移除
    return {"status": "success"}
