#!/usr/bin/env bash
# ============================================================
# 智汇研途 · 本地一键部署到云服务器
#
# 用法（本地 Git Bash）：
#   bash scripts/oracle/deploy-remote.sh 139.224.206.77
#
# 做的事：打包（排除 .venv / .git / 本地向量库）→ 通过 SSH 管道直接送到服务器
#        → 解压 → bootstrap.sh（装 Docker / swap / 防火墙）→ deploy.sh（构建启动）
# 全程只输一次 root 密码；改完代码重跑同一条命令即可更新
# ============================================================
set -euo pipefail

HOST="${1:-}"
if [ -z "$HOST" ]; then
    echo "用法: bash scripts/oracle/deploy-remote.sh <服务器公网IP>" >&2
    exit 1
fi

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

# ---------- 0. 前置检查 ----------
for c in tar ssh; do
    command -v "$c" >/dev/null 2>&1 || { echo "[x] 缺少 $c，请安装 Git for Windows" >&2; exit 1; }
done
[ -f .env ] || { echo "[x] 缺少 .env（至少要有 DEEPSEEK_API_KEY）" >&2; exit 1; }

c_ok()   { printf '\033[32m[ok]\033[0m %s\n' "$*"; }
c_info() { printf '\033[36m[..]\033[0m %s\n' "$*"; }

# ---------- 1. 连通性 ----------
c_info "检查 $HOST:22"
if ! (timeout 8 bash -c "cat < /dev/null > /dev/tcp/$HOST/22") 2>/dev/null; then
    echo "[x] 22 端口不通：实例没开机 / 公网 IP 不对 / 防火墙没放行 22" >&2
    exit 1
fi
c_ok "22 端口可达"

# ---------- 2. 打包 + 上传 + 远程执行（一次密码，管道直传） ----------
c_info "打包并推送（约 7 MB，随后在服务器上构建 5~10 分钟）"
c_info "接下来会提示输入 root 密码，输完请等它跑完，中途别按 Ctrl+C"

tar -czf - \
    --exclude='.git' \
    --exclude='.venv' \
    --exclude='__pycache__' \
    --exclude='chroma_data' \
    --exclude='*.pyc' \
    --exclude='node_modules' \
    . | ssh -o StrictHostKeyChecking=no -o ConnectTimeout=20 "root@$HOST" '
set -e
mkdir -p /root/zhihui
tar -xzf - -C /root/zhihui
cd /root/zhihui
bash scripts/oracle/bootstrap.sh
bash scripts/oracle/deploy.sh
'

echo
c_ok "部署完成"
echo "  访问地址: http://$HOST:8000"
echo "  打不开先看：阿里云控制台 → 轻量应用服务器 → 防火墙 → 放行 TCP 8000"
