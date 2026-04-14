from fastapi import APIRouter, Header, Depends, HTTPException
from datetime import datetime, timedelta, timezone
import logging
import os
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
stats_cache = {"timestamp": 0, "data": None}

def clear_cache():
    stats_cache["timestamp"] = 0

@router.post("/generate")
def admin_generate(req: GenerateRequest, _=Depends(check_admin)):
    new_key = generate_serial_number()
    now_ts = datetime.now(timezone.utc)
    created_at = now_ts.isoformat()
    expires_at = (now_ts + timedelta(days=req.duration_days)).isoformat() if req.duration_days > 0 else None
    pids_str = ",".join([p.strip() for p in req.product_ids if p.strip()])
    
    conn = get_db()
    c = conn.cursor()
    try:
        c.execute("""INSERT INTO licenses 
                     (key, max_seats, activated_devices, user_contact, order_id, 
                      created_at, expires_at, status, product_id, remark, is_trial)
                     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                  (new_key, req.seats, "", req.contact, req.order_id,
                   created_at, expires_at, "active", pids_str, req.remark, 1 if req.is_trial else 0))
        conn.commit()
    finally:
        conn.close()
    
    clear_cache()
    logger.info(f"Admin_Generate: key={new_key[:8]}*** products={pids_str}")
    return {"status": "ok", "key": new_key}

@router.get("/stats")
def admin_stats(_=Depends(check_admin)):
    now_ts = datetime.now(timezone.utc).timestamp()
    if now_ts - stats_cache["timestamp"] < 5 and stats_cache["data"] is not None:
        logger.info("Admin_Stats: cache_hit")
        return stats_cache["data"]

    logger.info("Admin_Stats: cache_miss_refreshing")
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM licenses ORDER BY created_at DESC")
    rows = c.fetchall()

    licenses_result = []
    product_ids_set = set()
    product_names = {}

    for r in rows:
        d = dict(r)
        pids = [p.strip() for p in d.get("product_id", "").split(",") if p.strip()]
        for pid in pids: product_ids_set.add(pid)
        main_pid = pids[0] if pids else "GENERIC_ID"
        if main_pid not in product_names:
            c.execute("SELECT value FROM system_config WHERE key=?", (f"display_name_{main_pid}",))
            dn_row = c.fetchone()
            product_names[main_pid] = dn_row[0] if dn_row else main_pid
        d["display_name"] = product_names[main_pid]
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
    full_product_names = {}
    for pid in product_ids_set:
        c.execute("SELECT value FROM system_config WHERE key=?", (f"display_name_{pid}",))
        dn_row = c.fetchone()
        full_product_names[pid] = dn_row[0] if dn_row else pid

    conn.close()
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
def admin_ban(req: BanRequest, _=Depends(check_admin)):
    new_status = "banned" if req.action == "ban" else "active"
    conn = get_db()
    c = conn.cursor()
    c.execute("UPDATE licenses SET status=? WHERE key=?", (new_status, req.license_key))
    conn.commit()
    conn.close()
    clear_cache()
    logger.info(f"Admin_Ban: key={req.license_key[:8]}*** status={new_status}")
    return {"status": "ok"}

@router.post("/reset")
def admin_reset(req: ResetRequest, _=Depends(check_admin)):
    from datetime import datetime, timezone
    conn = get_db()
    c = conn.cursor()
    # 清空绑定设备列表
    c.execute("UPDATE licenses SET activated_devices='', last_error=NULL WHERE key=?", (req.license_key,))
    # [FIX] 同时清零当月换绑计数，否则用户解绑后立刻重新激活仍会触发"每月仅限换绑 1 次"限制
    cur_month = datetime.now(timezone.utc).strftime("%Y-%m")
    c.execute("DELETE FROM device_history WHERE license_key=? AND change_date=?", (req.license_key, cur_month))
    conn.commit()
    conn.close()
    clear_cache()
    logger.info(f"Admin_Reset: key={req.license_key[:8]}*** month={cur_month} history_cleared")
    return {"status": "ok"}

@router.post("/clear_expired_trials")
def admin_clear_expired_trials(req: AdminRequest, _=Depends(check_admin)):
    conn = get_db()
    c = conn.cursor()
    now_ts = datetime.now(timezone.utc).isoformat()
    c.execute("UPDATE licenses SET status='deleted' WHERE is_trial=1 AND status != 'deleted' AND expires_at < ?", (now_ts,))
    deleted_count = c.rowcount
    conn.commit()
    conn.close()
    clear_cache()
    logger.info(f"Admin_ClearExpiredTrials: deleted_count={deleted_count}")
    return {"status": "ok", "deleted_count": deleted_count}

@router.get("/get_announcement")
def get_announcement(product_id: str, _=Depends(check_admin)):
    conn = get_db()
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
    conn.close()
    return {
        "message": row["value"] if row else "",
        "display_name": dn_row[0] if dn_row else product_id,
        "anno_mode": mode_row[0] if mode_row else "once",
        "promo_url": promo_row[0] if promo_row else "",
        "default_trial_days": int(days_row[0]) if days_row else 7,
    }

@router.post("/announcement")
def admin_announcement(req: AnnouncementRequest, _=Depends(check_admin)):
    conn = get_db()
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
    conn.close()
    return {"status": "ok"}

@router.post("/clear_all_announcements")
def admin_clear_all_announcements(req: AdminRequest, _=Depends(check_admin)):
    conn = get_db()
    c = conn.cursor()
    # 彻底撤回所有公告和显示模式设置
    c.execute("DELETE FROM system_config WHERE key LIKE 'announcement_%' OR key LIKE 'anno_mode_%'")
    conn.commit()
    conn.close()
    logger.warning("Admin_ClearAllAnnouncements: all notices revoked")
    return {"status": "success"}

@router.post("/update_license")
def admin_update_license(req: UpdateLicenseRequest, _=Depends(check_admin)):
    conn = get_db()
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
        updates.append("product_id=?"); params.append(p_str)
    
    if not updates:
        conn.close()
        return {"status": "error", "message": "Nothing to update"}
    
    params.append(req.license_key)
    c.execute(f"UPDATE licenses SET {', '.join(updates)} WHERE key=?", tuple(params))
    conn.commit()
    conn.close()
    clear_cache()
    logger.info(f"Admin_UpdateLicense: key={req.license_key[:8]}*** fields={list(updates)}")
    return {"status": "success"}

@router.post("/delete")
def admin_delete(req: DeleteRequest, _=Depends(check_admin)):
    conn = get_db()
    c = conn.cursor()
    c.execute("DELETE FROM licenses WHERE key=?", (req.license_key,))
    c.execute("DELETE FROM device_history WHERE license_key=?", (req.license_key,))
    conn.commit()
    conn.close()
    clear_cache()
    logger.warning(f"Admin_Delete: key={req.license_key[:8]}***")
    return {"status": "ok"}

@router.post("/restore")
def admin_restore(req: AdminRequest, _=Depends(check_admin)):
    conn = get_db()
    c = conn.cursor()
    c.execute("UPDATE licenses SET status='active' WHERE key=?", (req.license_key,))
    conn.commit()
    conn.close()
    clear_cache()
    logger.info(f"Admin_Restore: key={req.license_key[:8]}***")
    return {"status": "ok"}

@router.post("/register_product")
def admin_register_product(req: RegisterProductRequest, _=Depends(check_admin)):
    conn = get_db()
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO system_config (key, value) VALUES (?, ?)", (f"display_name_{req.pid}", req.name))
    c.execute("DELETE FROM system_config WHERE key=?", (f"product_status_{req.pid}",))
    conn.commit()
    conn.close()
    clear_cache()
    logger.info(f"Admin_RegisterProduct: pid={req.pid} name={req.name}")
    return {"status": "success"}

@router.post("/purge_trash")
def admin_purge_trash(req: PurgeTrashRequest, _=Depends(check_admin)):
    conn = get_db()
    c = conn.cursor()
    c.execute("DELETE FROM licenses WHERE status='deleted'")
    licenses_count = c.rowcount
    c.execute("SELECT key FROM system_config WHERE key LIKE 'product_status_%' AND value='deleted'")
    deleted_pids = [row[0].replace("product_status_", "") for row in c.fetchall()]
    for pid in deleted_pids:
        for suffix in ("product_status_", "display_name_", "announcement_", "anno_mode_", "promo_url_"):
            c.execute("DELETE FROM system_config WHERE key=?", (f"{suffix}{pid}",))
    conn.commit()
    conn.close()
    clear_cache()
    logger.info(f"Admin_PurgeTrash: licenses_deleted={licenses_count} products_purged={len(deleted_pids)}")
    return {"status": "success", "count": licenses_count}

@router.post("/purge_trash_single")
def admin_purge_trash_single(req: DeleteProductRequest, _=Depends(check_admin)):
    pid = req.product_id
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT key, product_id FROM licenses")
    to_delete = []
    for row in c.fetchall():
        pids_in_row = [p.strip() for p in row["product_id"].split(",")]
        if pid in pids_in_row: to_delete.append(row["key"])

    for key in to_delete:
        c.execute("DELETE FROM licenses WHERE key=?", (key,))

    for suffix in ("product_status_", "display_name_", "announcement_", "anno_mode_", "promo_url_"):
        c.execute("DELETE FROM system_config WHERE key=?", (f"{suffix}{pid}",))

    conn.commit()
    conn.close()
    clear_cache()
    logger.warning(f"Admin_PurgeTrashSingle: pid={pid} deleted_count={len(to_delete)}")
    return {"status": "success", "deleted_count": len(to_delete)}

@router.post("/update_promo_url")
def admin_update_promo_url(req: UpdatePromoUrlRequest, _=Depends(check_admin)):
    conn = get_db()
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
    conn.close()
    return {"status": "success"}
