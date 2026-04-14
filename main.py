import uvicorn
from app.main import app

if __name__ == "__main__":
    # 保持与旧版本一致的端口与主机配置，确保 ClawCloud 部署零改动
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
