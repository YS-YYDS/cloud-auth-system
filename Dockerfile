FROM python:3.11-slim

# 创建非特权用户
RUN groupadd -r appgroup && useradd -r -g appgroup appuser

WORKDIR /app

# 先安装依赖以利用缓存
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制源码、静态资源及主入口
COPY app/ ./app/
COPY static/ ./static/
COPY main.py admin.html requirements.txt ./
RUN mkdir -p /data static && chown -R appuser:appgroup /app /data

# 切换至非特权用户 (安全加固)
USER appuser

# 数据库持久化挂载点
# [注意] 如果在运行时通过 -v 挂载 /data，且宿主机目录属于 root，
# appuser 将无法写入。程序将自动降级退回到容器内的只读层或 /tmp。
# 请确保挂载的宿主机目录对 UID/GID（通常是 999 左右）可读写，或使用 docker volume。
VOLUME ["/data"]

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
