from fastapi import APIRouter, HTTPException, Depends
from ..db.session import get_db
from ..models.schemas import ScriptUpdateCheck, ScriptRegisterRequest
from ..core.config import ADMIN_TOKEN
from .deps import check_admin
import logging

router = APIRouter()
logger = logging.getLogger("CloudAuth.Update")

from packaging import version

@router.post("/check")
def check_update(req: ScriptUpdateCheck, db=Depends(get_db)):
    """检查特定脚本是否有更新"""
    c = db.cursor()
    c.execute("SELECT * FROM scripts_registry WHERE script_id=?", (req.script_id,))
    script = c.fetchone()
    
    if not script:
        return {"update_available": False, "message": "Script not registered"}
    
    latest_version = script["latest_version"]
    # [P0-FIX] 使用 packaging.version 进行精准语义化对比 (适配 2.0 > 1.9 等情况)
    try:
        has_update = version.parse(latest_version) > version.parse(req.current_version)
    except Exception:
        has_update = latest_version != req.current_version
    
    return {
        "update_available": has_update,
        "latest_version": latest_version,
        "name": script["name"],
        "url_primary": script["download_url_primary"],
        "url_fallback": script["download_url_fallback"],
        "changelog": script["changelog"],
        "min_reaper": script["min_reaper_version"]
    }

@router.get("/list")
def list_all_scripts(db=Depends(get_db)):
    """列出所有受管辖的脚本及其最新状态"""
    c = db.cursor()
    c.execute("SELECT script_id, name, latest_version, updated_at FROM scripts_registry")
    return [dict(row) for row in c.fetchall()]

@router.post("/register")
def register_or_update_script(req: ScriptRegisterRequest, _=Depends(check_admin), db=Depends(get_db)):
    """管理员录入或更新脚本版本信息"""
    
    c = db.cursor()
    c.execute('''INSERT OR REPLACE INTO scripts_registry 
                 (script_id, name, latest_version, download_url_primary, download_url_fallback, changelog, min_reaper_version)
                 VALUES (?, ?, ?, ?, ?, ?, ?)''', 
              (req.script_id, req.name, req.latest_version, req.url_primary, req.url_fallback, req.changelog, req.min_reaper))
    db.commit()
    logger.info(f"Admin_Update_Script_Registry: id={req.script_id} version={req.latest_version}")
    return {"status": "success", "script_id": req.script_id}
