FROM python:3.11-slim

# 创建非特权用户
RUN groupadd -r appgroup && useradd -r -g appgroup appuser

WORKDIR /app

# 先安装依赖以利用缓存
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制源码、静态资源及主入口
COPY app/ ./app/
COPY main.py admin.html requirements.txt ./
RUN mkdir -p /data static && chown -R appuser:appgroup /app /data

# 切换至非特权用户 (在云端环境中若由于权限冲突导致数据不可见，可暂时注释掉此行以使用 root 运行)
# USER appuser

# 数据库持久化挂载点
VOLUME ["/data"]

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
