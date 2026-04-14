import logging
from fastapi import Header, HTTPException, Request
from ..core.config import ADMIN_TOKEN

logger = logging.getLogger("CloudAuth.API")

async def check_admin(request: Request, x_admin_token: str = Header(None)):
    """
    [P1-FIX] 增强型鉴权依赖：兼容 Header、Query String 及 Body 中的 Token。
    """
    token = x_admin_token
    
    # 1. 尝试从 Query Params 获取
    if not token:
        token = request.query_params.get("token")
        
    # 2. 尝试从 JSON Body 获取 (部分旧前端逻辑)
    if not token:
        try:
            # 仅在非 GET 请求且有内容时尝试读取 Body
            if request.method != "GET":
                body = await request.json()
                if isinstance(body, dict):
                    token = body.get("token")
        except Exception:
            pass

    if not token or token != ADMIN_TOKEN:
        logger.warning(f"Admin_Auth: unauthorized attempt, method={request.method}, path={request.url.path}")
        raise HTTPException(status_code=403, detail="Invalid Admin Token")
    return True
