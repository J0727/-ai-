#!/usr/bin/env bash
# ============================================================
# 智汇研途 · 一键部署 / 更新（Docker Compose）
#
# 用法（在项目根目录执行）：
#   bash scripts/oracle/deploy.sh              # 部署或更新
#   bash scripts/oracle/deploy.sh --no-pull    # 跳过 git pull
#   PORT=80 bash scripts/oracle/deploy.sh      # 改用 80 端口对外（推荐，省得输 :8000）
#
# 做的事：
#   1. 检查 Docker / Compose / .env
#   2. git pull（若当前是 git 仓库）
#   3. docker compose 构建并启动
#   4. 等健康检查通过，初始化演示账号
#   5. 打印访问地址
# ============================================================
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

PULL=1
for a in "$@"; do
    case "$a" in
        --no-pull) PULL=0 ;;
        -h|--help) sed -n '2,16p' "$0"; exit 0 ;;
    esac
done

c_ok()   { printf '\033[32m[ok]\033[0m %s\n' "$*"; }
c_info() { printf '\033[36m[..]\033[0m %s\n' "$*"; }
c_warn() { printf '\033[33m[!]\033[0m %s\n' "$*"; }
c_err()  { printf '\033[31m[x]\033[0m %s\n' "$*" >&2; }

SUDO=""
[ "$(id -u)" -ne 0 ] && command -v sudo >/dev/null 2>&1 && SUDO="sudo"

# ---------- 1. 前置检查 ----------
command -v docker >/dev/null 2>&1 || { c_err "未安装 Docker，请先执行：bash scripts/oracle/bootstrap.sh"; exit 1; }
DOCKER="docker"; $SUDO docker info >/dev/null 2>&1 || DOCKER="$SUDO docker"
$DOCKER compose version >/dev/null 2>&1 || { c_err "缺少 docker compose 插件"; exit 1; }

if [ ! -f .env ]; then
    cp .env.example .env
    c_warn "已从 .env.example 生成 .env，请填写 DEEPSEEK_API_KEY 后重新执行："
    c_warn "  nano .env"
    exit 1
fi

if grep -q '^DEEPSEEK_API_KEY=sk-your-key-here' .env || ! grep -q '^DEEPSEEK_API_KEY=.\+' .env; then
    c_err ".env 里的 DEEPSEEK_API_KEY 还是占位值，请先填写真实 Key"
    exit 1
fi
c_ok ".env 已配置"

# ---------- 2. 更新代码 ----------
if [ "$PULL" -eq 1 ] && [ -d .git ]; then
    c_info "拉取最新代码"
    git pull --ff-only || c_warn "git pull 失败（本地有改动？），继续用当前代码部署"
fi

# ---------- 3. 构建启动 ----------
export ZHIHUI_PORT="${PORT:-8000}"
export BUILDKIT_PROGRESS=plain   # 关掉 docker 的 TUI 动画，日志才看得清

# 阿里云/腾讯云内网机器自动切国内 pip 镜像：chromadb + onnxruntime 约 1 GB 依赖，
# 走 pypi.org 内地可能要 20 分钟甚至超时，走镜像 2~3 分钟。
if [ -z "${PIP_INDEX_URL:-}" ]; then
    if curl -s --max-time 2 -o /dev/null "http://100.100.100.200/latest/meta-data/instance-id" 2>/dev/null; then
        export PIP_INDEX_URL="https://mirrors.aliyun.com/pypi/simple/"
        c_info "检测到阿里云主机，pip 走阿里云内网镜像"
    elif curl -s --max-time 2 -o /dev/null "http://metadata.tencentyun.com/latest/meta-data/instance-id" 2>/dev/null; then
        export PIP_INDEX_URL="https://mirrors.cloud.tencent.com/pypi/simple/"
        c_info "检测到腾讯云主机，pip 走腾讯云内网镜像"
    fi
fi

c_info "构建并启动容器（首次 5~10 分钟，取决于网络与机型）"
if [ "$ZHIHUI_PORT" != "8000" ]; then
    c_info "对外端口：$ZHIHUI_PORT"
fi
$DOCKER compose up -d --build

# ---------- 4. 等健康检查 ----------
c_info "等待服务就绪"
ok=0
for i in $(seq 1 60); do
    if curl -fsS -m 3 "http://127.0.0.1:${ZHIHUI_PORT}/api/health" >/dev/null 2>&1; then ok=1; break; fi
    sleep 3
done
if [ "$ok" -ne 1 ]; then
    c_err "健康检查未通过，最近日志："
    $DOCKER compose logs --tail=40 zhihui || true
    exit 1
fi
c_ok "服务已就绪"

# ---------- 5. 演示账号 ----------
$DOCKER compose exec -T zhihui python /app/scripts/init_demo_user.py 2>/dev/null \
    && c_ok "演示账号 demo / demo123456 已就绪" \
    || c_warn "演示账号初始化跳过（可能已存在）"

# ---------- 6. 汇总 ----------
PUBIP=$(curl -fsS -m 5 https://ifconfig.me 2>/dev/null || curl -fsS -m 5 https://api.ipify.org 2>/dev/null || echo "<公网IP>")
PORT_SUFFIX=""; [ "$ZHIHUI_PORT" != "80" ] && PORT_SUFFIX=":${ZHIHUI_PORT}"
echo
c_ok "部署完成"
cat <<EOF
  访问地址： http://${PUBIP}${PORT_SUFFIX}
  健康检查： http://${PUBIP}${PORT_SUFFIX}/api/health
  演示账号： demo / demo123456

常用命令：
  docker compose logs -f --tail=100   # 看日志
  docker compose restart              # 重启
  bash scripts/oracle/deploy.sh       # 更新到最新代码
  bash scripts/oracle/backup-to-oci.sh  # 备份数据到对象存储
EOF
