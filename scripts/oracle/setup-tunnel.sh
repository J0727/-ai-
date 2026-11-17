#!/bin/bash
# 重新拉取完整的 cloudflared 并校验可用性
set -u

BIN=/usr/local/bin/cloudflared
SRC=https://gh-proxy.com/https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64

systemctl stop zhihui-tunnel 2>/dev/null || true
rm -f /tmp/cf2.part "$BIN"

echo "[*] 下载中"
curl -L -s --retry 3 -o /tmp/cf2.part "$SRC"
SIZE=$(stat -c %s /tmp/cf2.part 2>/dev/null || echo 0)
echo "[*] 大小: $SIZE bytes"

if [ "$SIZE" -lt 30000000 ]; then
    echo "[x] 下载不完整，放弃"
    exit 1
fi

install -m 755 /tmp/cf2.part "$BIN"
echo "[*] 版本: $("$BIN" --version 2>&1 | head -1)"

if ! "$BIN" --version >/dev/null 2>&1; then
    echo "[x] 二进制无法执行"
    exit 1
fi
echo "[ok] 二进制可用"

systemctl restart zhihui-tunnel
sleep 12

URL=$(grep -o 'https://[a-z0-9-]*\.trycloudflare\.com' /var/log/zhihui-tunnel.log | head -1)
if [ -n "$URL" ]; then
    echo "$URL" > /root/.tunnel_url
    echo "TUNNEL_URL=$URL"
else
    echo "TUNNEL_URL="
    echo "--- 服务状态 ---"
    systemctl is-active zhihui-tunnel
    tail -20 /var/log/zhihui-tunnel.log 2>/dev/null
fi
