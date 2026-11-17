# 智汇研途 · 科研文献辅助平台
# 单容器镜像：FastAPI 后端 + 前端静态文件（x86_64 / ARM64 均可构建）
# Docker Hub 拉不动时改用镜像站：
#   docker compose build --build-arg BASE_IMAGE=docker.m.daocloud.io/library/python:3.11-slim
ARG BASE_IMAGE=python:3.11-slim
FROM ${BASE_IMAGE}

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    ZHIHUI_DATA_DIR=/data \
    ZHIHUI_FRONTEND_DIR=/app/frontend \
    TZ=Asia/Shanghai

WORKDIR /app

# PyMuPDF 需要 libgl / libglib；onnxruntime（OCR）需要 libgomp；curl 用于健康检查
# build-essential / python3-dev：Oracle 免费 ARM 机型（A1）没有 chroma-hnswlib 预编译包，
# 需要现场编译，缺了这两个会构建失败（x86 机型不受影响）
# 国内网络：Debian 源换阿里云镜像，否则 apt 阶段能卡 3~5 分钟（海外构建传 --build-arg APT_MIRROR=deb.debian.org）
ARG APT_MIRROR=mirrors.aliyun.com
RUN if [ -f /etc/apt/sources.list.d/debian.sources ]; then \
        sed -i "s|deb.debian.org|${APT_MIRROR}|g" /etc/apt/sources.list.d/debian.sources; \
    elif [ -f /etc/apt/sources.list ]; then \
        sed -i "s|deb.debian.org|${APT_MIRROR}|g" /etc/apt/sources.list; \
    fi \
    && apt-get update && apt-get install -y --no-install-recommends \
        curl \
        libgl1 \
        libglib2.0-0 \
        libgomp1 \
        build-essential \
        python3-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /app/requirements.txt
# 国内网络可换成镜像源，例如：
#   docker compose build --build-arg PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
ARG PIP_INDEX_URL=https://pypi.org/simple
RUN pip install --no-cache-dir -i "$PIP_INDEX_URL" -r /app/requirements.txt

COPY backend /app/backend
COPY frontend /app/frontend
COPY scripts /app/scripts

RUN mkdir -p /data

VOLUME ["/data"]
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8000/api/health || exit 1

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--app-dir", "/app/backend"]
