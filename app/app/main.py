from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import os
import logging
from .api import auth, admin, update
from .db.session import init_db
from .core.config import ROOT_DIR

# ===================== 系统初始化 =====================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("CloudAuth")

init_db()

app = FastAPI(title="CloudAuthSystem Industrial")

# 挂载静态文件
STATIC_DIR = os.path.join(ROOT_DIR, "static")
os.makedirs(STATIC_DIR, exist_ok=True)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# ===================== 管理界面入口 =====================
@app.get("/admin")
def admin_page():
    return FileResponse(os.path.join(ROOT_DIR, "admin.html"), 
                        headers={"Cache-Control": "no-cache, no-store, must-revalidate"})

@app.get("/favicon.ico")
def favicon():
    fav = os.path.join(ROOT_DIR, "static", "favicon.ico")
    return FileResponse(fav) if os.path.exists(fav) else None

# ===================== 路由集成 =====================
app.include_router(auth.router)
app.include_router(admin.router)
app.include_router(update.router, prefix="/api/update", tags=["Update"])

logger.info("Application started with modular structure.")
