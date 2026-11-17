#!/usr/bin/env bash
# ============================================================
# 智汇研途 · Oracle Cloud 免费主机一键初始化
#
# 用法（在 Oracle 云主机的 SSH 里执行）：
#   curl -fsSL <你的仓库地址>/raw/main/scripts/oracle/bootstrap.sh -o bootstrap.sh
#   bash bootstrap.sh
#
# 做四件事：
#   1. 创建 2G swap（小内存机型防 OOM，1GB 的 E2.1.Micro 必做）
#   2. 安装 Docker + Compose 插件（可走国内镜像）
#   3. 放行 80 / 443 / 8000 端口（同时处理 Oracle 镜像自带的 iptables 拦截）
#   4. 打印后续部署命令
#
# 注意：Oracle 云控制台的「安全列表 / Security List」要在网页上单独放行，
#       脚本只能改主机内部防火墙，两边都通才可访问（见 docs/部署指南.md）。
# ============================================================
set -euo pipefail

PORTS=${PORTS:-"80 443 8000"}
SWAP_SIZE=${SWAP_SIZE:-2G}
DOCKER_MIRROR=${DOCKER_MIRROR:-""}   # 例：Aliyun；留空用官方源

c_ok()   { printf '\033[32m[ok]\033[0m %s\n' "$*"; }
c_info() { printf '\033[36m[..]\033[0m %s\n' "$*"; }
c_warn() { printf '\033[33m[!]\033[0m %s\n' "$*"; }
c_err()  { printf '\033[31m[x]\033[0m %s\n' "$*" >&2; }

SUDO=""
if [ "$(id -u)" -ne 0 ]; then
    if command -v sudo >/dev/null 2>&1; then SUDO="sudo"; else
        c_err "需要 root 权限，请用 sudo 执行"; exit 1
    fi
fi

# ---------- 环境识别 ----------
. /etc/os-release 2>/dev/null || true
OS_ID="${ID:-unknown}"
c_info "系统：${PRETTY_NAME:-$OS_ID}　架构：$(uname -m)"

# ---------- 1. swap ----------
ensure_swap() {
    local mem_mb
    mem_mb=$(awk '/MemTotal/{print int($2/1024)}' /proc/meminfo)
    if [ "$mem_mb" -ge 3800 ]; then
        c_info "内存 ${mem_mb}MB，无需 swap"
        return
    fi
    if swapon --show | grep -q '/swapfile'; then
        c_ok "swap 已存在，跳过"
        return
    fi
    c_info "内存仅 ${mem_mb}MB，创建 ${SWAP_SIZE} swap（构建镜像时防 OOM）"
    $SUDO fallocate -l "$SWAP_SIZE" /swapfile 2>/dev/null \
        || $SUDO dd if=/dev/zero of=/swapfile bs=1M count=2048 status=none
    $SUDO chmod 600 /swapfile
    $SUDO mkswap /swapfile >/dev/null
    $SUDO swapon /swapfile
    grep -q '^/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' | $SUDO tee -a /etc/fstab >/dev/null
    c_ok "swap ${SWAP_SIZE} 已启用"
}

# ---------- 2. Docker ----------
# 通过阿里云镜像源装 docker-ce：get.docker.com 在内地常被 TLS reset
install_docker_aliyun() {
    $SUDO install -m 0755 -d /etc/apt/keyrings || return 1
    curl -fsSL --max-time 40 https://mirrors.aliyun.com/docker-ce/linux/ubuntu/gpg \
        | $SUDO gpg --dearmor --yes -o /etc/apt/keyrings/docker.gpg || return 1
    $SUDO chmod a+r /etc/apt/keyrings/docker.gpg
    local codename
    codename=$(. /etc/os-release && echo "${VERSION_CODENAME:-jammy}")
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://mirrors.aliyun.com/docker-ce/linux/ubuntu ${codename} stable" \
        | $SUDO tee /etc/apt/sources.list.d/docker.list >/dev/null || return 1
    $SUDO apt-get update -qq || return 1
    $SUDO env DEBIAN_FRONTEND=noninteractive apt-get install -y -qq \
        docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin >/dev/null || return 1
}

# Docker Hub 内地基本直连不上，配几个可用加速器
configure_docker_mirror() {
    local f=/etc/docker/daemon.json
    if [ -f "$f" ] && grep -q registry-mirrors "$f" 2>/dev/null; then
        c_ok "Docker 镜像加速已配置"
        return
    fi
    $SUDO mkdir -p /etc/docker
    [ -f "$f" ] && $SUDO cp "$f" "${f}.bak.$(date +%s)"
    $SUDO tee "$f" >/dev/null <<'JSON'
{
  "registry-mirrors": [
    "https://docker.m.daocloud.io",
    "https://docker.1panel.live",
    "https://docker.nju.edu.cn"
  ],
  "log-driver": "json-file",
  "log-opts": { "max-size": "20m", "max-file": "3" }
}
JSON
    $SUDO systemctl restart docker >/dev/null 2>&1 || true
    c_ok "已配置 Docker 镜像加速"
}

install_docker() {
    if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
        c_ok "Docker 已安装：$(docker --version | cut -d, -f1)"
    else
        c_info "安装 Docker（首次约 1~3 分钟）"
        if [ "$OS_ID" = "ubuntu" ] || [ "$OS_ID" = "debian" ]; then
            $SUDO apt-get update -qq
            $SUDO env DEBIAN_FRONTEND=noninteractive apt-get install -y -qq ca-certificates curl gnupg >/dev/null
            if install_docker_aliyun; then
                c_ok "Docker 安装完成（阿里云镜像源）"
            else
                c_warn "阿里云源失败，回退官方脚本"
                curl -fsSL --max-time 60 https://get.docker.com | $SUDO sh
            fi
        else
            if [ -n "$DOCKER_MIRROR" ]; then
                curl -fsSL --max-time 60 https://get.docker.com | $SUDO sh -s -- --mirror "$DOCKER_MIRROR"
            else
                curl -fsSL --max-time 60 https://get.docker.com | $SUDO sh
            fi
        fi
        $SUDO systemctl enable --now docker >/dev/null 2>&1 || true
    fi
    # 当前用户加入 docker 组，免 sudo
    if [ -n "${SUDO_USER:-}" ]; then
        $SUDO usermod -aG docker "$SUDO_USER" || true
        c_warn "已把 $SUDO_USER 加入 docker 组，重新登录（或 newgrp docker）后免 sudo"
    fi
    c_ok "Docker 可用：$(docker --version | cut -d, -f1)"
    configure_docker_mirror
}

# ---------- 3. 端口放行 ----------
# 关键：Oracle 的 Ubuntu 镜像自带 iptables 规则，默认 REJECT 除 22 以外的入站，
#      只改云控制台安全列表是不够的 —— 必须同时在主机内放行。
allow_port_iptables() {
    local p=$1
    if $SUDO iptables -C INPUT -p tcp --dport "$p" -j ACCEPT 2>/dev/null; then
        c_ok "iptables 已放行 TCP/$p"
    else
        $SUDO iptables -I INPUT 1 -p tcp --dport "$p" -j ACCEPT
        c_ok "iptables 放行 TCP/$p"
    fi
    if command -v ip6tables >/dev/null 2>&1; then
        if ! $SUDO ip6tables -C INPUT -p tcp --dport "$p" -j ACCEPT 2>/dev/null; then
            $SUDO ip6tables -I INPUT 1 -p tcp --dport "$p" -j ACCEPT 2>/dev/null || true
        fi
    fi
}

persist_iptables() {
    # 去掉 Oracle 镜像里那条兜底的 REJECT，避免 Docker 发布端口被拦
    for chain in FORWARD INPUT; do
        while $SUDO iptables -D "$chain" -j REJECT --reject-with icmp-host-prohibited 2>/dev/null; do :; done
        while $SUDO iptables -D "$chain" -j REJECT 2>/dev/null; do :; done
    done
    if [ "$OS_ID" = "ubuntu" ] || [ "$OS_ID" = "debian" ]; then
        $SUDO env DEBIAN_FRONTEND=noninteractive apt-get install -y -qq iptables-persistent netfilter-persistent >/dev/null 2>&1 || true
        if command -v netfilter-persistent >/dev/null 2>&1; then
            $SUDO netfilter-persistent save >/dev/null 2>&1 && c_ok "iptables 规则已持久化（重启不丢）"
        elif command -v iptables-save >/dev/null 2>&1; then
            $SUDO mkdir -p /etc/iptables
            $SUDO sh -c 'iptables-save > /etc/iptables/rules.v4'
            c_ok "规则已写入 /etc/iptables/rules.v4"
        fi
    else
        # Oracle Linux / RHEL 系
        if command -v firewall-cmd >/dev/null 2>&1; then
            for p in $PORTS; do
                $SUDO firewall-cmd --permanent --add-port="${p}/tcp" >/dev/null 2>&1 || true
            done
            $SUDO firewall-cmd --reload >/dev/null 2>&1 || true
            c_ok "firewalld 已放行端口"
        fi
    fi
}

open_ports() {
    c_info "放行端口：$PORTS"
    if command -v ufw >/dev/null 2>&1 && $SUDO ufw status 2>/dev/null | grep -q "Status: active"; then
        for p in $PORTS; do $SUDO ufw allow "${p}/tcp" >/dev/null 2>&1 || true; done
        c_ok "ufw 已放行"
    fi
    for p in $PORTS; do allow_port_iptables "$p"; done
    persist_iptables
}

# ---------- 执行 ----------
ensure_swap
install_docker
open_ports

PUBIP=$(curl -fsS -m 5 https://ifconfig.me 2>/dev/null || curl -fsS -m 5 https://api.ipify.org 2>/dev/null || echo "<公网IP>")
echo
c_ok "初始化完成。"
cat <<EOF

下一步（把代码放上服务器后执行）：
  git clone <仓库地址> ~/zhihui && cd ~/zhihui
  bash scripts/oracle/deploy.sh

部署完成后访问：
  http://${PUBIP}:8000

提醒：若打不开，先确认 Oracle 控制台「安全列表」也放行了 $PORTS 端口。
EOF
