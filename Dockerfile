FROM python:3.11-slim

WORKDIR /app

# 先安装依赖以利用缓存
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制源码、静态资源及主入口
COPY app/ ./app/
COPY static/ ./static/
COPY main.py admin.html requirements.txt ./
RUN mkdir -p /data static

# 数据库持久化挂载点
VOLUME ["/data"]

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
