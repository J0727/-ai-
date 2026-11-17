#!/usr/bin/env bash
# ============================================================
# 智汇研途 · 阿里云一键部署脚本
# 适用：Alibaba Cloud Linux 3 / CentOS 7+ / Ubuntu 20.04+ / Debian 11+
# 用法（在服务器上以 root 执行）：
#   curl -fsSL https://raw.githubusercontent.com/J0727/-ai-/main/deploy.sh | bash
# 或先把仓库拉下来再执行：
#   bash deploy.sh
# ============================================================
set -euo pipefail

REPO_URL="${REPO_URL:-https://github.com/J0727/-ai-.git}"
APP_DIR="${APP_DIR:-/opt/zhihui}"
PORT="${PORT:-8000}"
BASE_IMAGE="${BASE_IMAGE:-}"

log()  { printf '\n\033[1;35m[zhihui]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[warn]\033[0m %s\n' "$*"; }
die()  { printf '\033[1;31m[error]\033[0m %s\n' "$*" >&2; exit 1; }

[[ $EUID -eq 0 ]] || die "请用 root 执行：sudo bash deploy.sh"

# ---------------------------------------------------------------- 1. Docker
if command -v docker >/dev/null 2>&1; then
  log "已检测到 Docker：$(docker --version)"
else
  log "安装 Docker（使用阿里云镜像源）"
  if command -v apt-get >/dev/null 2>&1; then
    export DEBIAN_FRONTEND=noninteractive
    apt-get update -y
    apt-get install -y ca-certificates curl gnupg
    install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://mirrors.aliyun.com/docker-ce/linux/ubuntu/gpg \
      | gpg --dearmor -o /etc/apt/keyrings/docker.gpg || true
    CODENAME="$(. /etc/os-release && echo "${VERSION_CODENAME:-jammy}")"
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://mirrors.aliyun.com/docker-ce/linux/ubuntu ${CODENAME} stable" \
      > /etc/apt/sources.list.d/docker.list
    apt-get update -y
    apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
  elif command -v dnf >/dev/null 2>&1 || command -v yum >/dev/null 2>&1; then
    PM=$(command -v dnf || command -v yum)
    $PM install -y yum-utils
    yum-config-manager --add-repo https://mirrors.aliyun.com/docker-ce/linux/centos/docker-ce.repo || true
    $PM install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
  else
    die "无法识别的系统，请手动安装 Docker"
  fi
fi

systemctl enable --now docker

# 镜像加速（Docker Hub 国内不稳，配置多个镜像源，失败不影响）
mkdir -p /etc/docker
if [[ ! -f /etc/docker/daemon.json ]]; then
  cat > /etc/docker/daemon.json <<'JSON'
{
  "registry-mirrors": [
    "https://docker.m.daocloud.io",
    "https://docker.1panel.live",
    "https://hub.rat.dev"
  ]
}
JSON
  systemctl restart docker
fi

# ---------------------------------------------------------------- 2. 代码
if [[ -d "$APP_DIR/.git" ]]; then
  log "更新代码：$APP_DIR"
  git -C "$APP_DIR" fetch --depth=1 origin main
  git -C "$APP_DIR" reset --hard origin/main
else
  log "拉取代码到：$APP_DIR"
  mkdir -p "$(dirname "$APP_DIR")"
  git clone --depth=1 "$REPO_URL" "$APP_DIR"
fi
cd "$APP_DIR"

# ---------------------------------------------------------------- 3. 环境变量
if [[ ! -f .env ]]; then
  log "生成 .env"
  [[ -f .env.example ]] && cp .env.example .env || touch .env
  KEY="${DEEPSEEK_API_KEY:-}"
  if [[ -z "$KEY" ]]; then
    # curl | bash 时 stdin 是脚本本身，必须从终端读，否则会吞掉脚本内容
    if [[ -t 0 ]]; then
      echo
      read -r -p "请输入 DeepSeek API Key（sk- 开头，直接回车可稍后手动填写）: " KEY || true
    elif [[ -r /dev/tty ]]; then
      echo
      read -r -p "请输入 DeepSeek API Key（sk- 开头，直接回车可稍后手动填写）: " KEY < /dev/tty || true
    else
      warn "非交互环境，跳过 Key 输入；请稍后编辑 $APP_DIR/.env"
    fi
  fi
  SECRET="$(head -c 32 /dev/urandom | od -An -tx1 | tr -d ' \n')"
  {
    echo "DEEPSEEK_API_KEY=${KEY}"
    echo "DEEPSEEK_MODEL=deepseek-chat"
    echo "ZHIHUI_DATA_DIR=/data"
    echo "ZHIHUI_SESSION_SECRET=${SECRET}"
  } > .env
  chmod 600 .env
  [[ -z "$KEY" ]] && warn "未填写 Key，请编辑 $APP_DIR/.env 后再执行 docker compose up -d"
fi

# ---------------------------------------------------------------- 4. 构建启动
# 国内 pip 走清华源，构建快很多（可用 PIP_INDEX_URL=... 覆盖）
export PIP_INDEX_URL="${PIP_INDEX_URL:-https://pypi.tuna.tsinghua.edu.cn/simple}"
# compose 用 ZHIHUI_PORT 决定对外端口（PORT=80 bash deploy.sh 即可用 80 端口）
export ZHIHUI_PORT="${ZHIHUI_PORT:-$PORT}"

BUILD_ARGS=()
if [[ -n "$BASE_IMAGE" ]]; then
  BUILD_ARGS=(--build-arg "BASE_IMAGE=$BASE_IMAGE")
fi

log "构建镜像（首次约 5~10 分钟）"
# 空数组在 set -u 下会被视为未定义，需用 ${arr[@]+...} 形式展开
docker compose build ${BUILD_ARGS[@]+"${BUILD_ARGS[@]}"}

log "启动服务"
docker compose up -d

# ---------------------------------------------------------------- 5. 评审账号
sleep 6
log "创建评审演示账号"
docker compose exec -T zhihui python /app/scripts/init_demo_user.py || \
  warn "演示账号创建失败，可稍后手动执行：docker compose exec zhihui python /app/scripts/init_demo_user.py"

# ---------------------------------------------------------------- 6. 结果
IP="$(curl -fsS --max-time 5 https://api.ipify.org 2>/dev/null || true)"
[[ -z "$IP" ]] && IP="<你的服务器公网IP>"

cat <<EOF

============================================================
 部署完成
------------------------------------------------------------
 访问地址 : http://${IP}:${PORT}
 健康检查 : http://${IP}:${PORT}/api/health
 演示账号 : demo / demo123456
 项目目录 : ${APP_DIR}
 数据目录 : Docker 卷 zhihui-data

 常用命令：
   cd ${APP_DIR}
   docker compose logs -f          # 看日志
   docker compose restart          # 重启
   docker compose pull && docker compose up -d --build   # 更新
------------------------------------------------------------
 ⚠️ 如果访问不了，请到阿里云控制台「安全组」放行 TCP ${PORT} 端口
============================================================

EOF
