#!/usr/bin/env bash
# ============================================================
# 智汇研途 · 公网演示隧道（Cloudflare Quick Tunnel）
# 免费、无需注册账号、无需信用卡：把本机 8000 端口映射成 https 地址
#
# 用法：
#   bash scripts/public-demo/start-tunnel.sh
#   PORT=8080 bash scripts/public-demo/start-tunnel.sh
# ============================================================
set -euo pipefail

BACKEND="http://127.0.0.1:${PORT:-8000}"
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MIRROR="https://gh-proxy.com/https://github.com/cloudflare/cloudflared/releases/latest/download"

c_ok()   { printf '\033[32m[ok]\033[0m %s\n' "$*"; }
c_info() { printf '\033[36m[..]\033[0m %s\n' "$*"; }
c_err()  { printf '\033[31m[x]\033[0m %s\n' "$*" >&2; }

echo "============================================================"
echo "  公网演示隧道：本机 ${BACKEND} → https 公网地址"
echo "============================================================"

# ---------- 1. 后端检查 ----------
c_info "检查后端"
curl -fsS -m 3 "${BACKEND}/api/health" >/dev/null 2>&1 || {
    c_err "后端未启动，请先运行：uvicorn main:app --host 0.0.0.0 --port 8000 --app-dir backend"
    exit 1
}
c_ok "后端正常"

# ---------- 2. cloudflared ----------
CF="$DIR/cloudflared"
if command -v cloudflared >/dev/null 2>&1; then
    CF="$(command -v cloudflared)"
    c_ok "使用已安装的 cloudflared"
elif [ -x "$CF" ]; then
    c_ok "使用已下载的 cloudflared"
else
    OS=$(uname -s); ARCH=$(uname -m)
    case "$OS-$ARCH" in
        Linux-x86_64)   FILE="cloudflared-linux-amd64" ;;
        Linux-aarch64)  FILE="cloudflared-linux-arm64" ;;
        Darwin-arm64)   FILE="cloudflared-darwin-arm64.tgz" ;;
        Darwin-x86_64)  FILE="cloudflared-darwin-amd64.tgz" ;;
        *) c_err "不支持的平台：$OS-$ARCH，请手动安装 cloudflared"; exit 1 ;;
    esac
    c_info "下载 cloudflared（$FILE，走国内镜像）"
    if ! curl -fL --connect-timeout 15 --retry 2 -o "$DIR/$FILE" "$MIRROR/$FILE"; then
        c_err "下载失败。可手动下载后放到：$DIR/"
        c_err "地址：$MIRROR/$FILE"
        exit 1
    fi
    case "$FILE" in
        *.tgz) tar xzf "$DIR/$FILE" -C "$DIR" && rm -f "$DIR/$FILE" ;;
        *)     mv "$DIR/$FILE" "$CF" ;;
    esac
    chmod +x "$CF"
    c_ok "下载完成"
fi

# ---------- 3. 起隧道 ----------
echo
c_info "建立隧道，稍等 5~15 秒…"
echo "    下面出现的 https://xxxx.trycloudflare.com 就是公网地址"
echo "    Ctrl+C 结束（结束即断开）"
echo "------------------------------------------------------------"
exec "$CF" tunnel --url "$BACKEND" --no-autoupdate
