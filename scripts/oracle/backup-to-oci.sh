#!/usr/bin/env bash
# ============================================================
# 智汇研途 · 备份数据到 Oracle 对象存储（OCI Object Storage）
#
# 前置：装好 rclone 并配好一个指向 OCI 的远端（跑一次 setup-rclone-oci.sh 即可）
#
# 用法：
#   bash scripts/oracle/backup-to-oci.sh                 # 备份（暂停服务数秒，最安全）
#   bash scripts/oracle/backup-to-oci.sh --hot           # 不停服务直接打包
#   KEEP=30 bash scripts/oracle/backup-to-oci.sh         # 云端保留 30 天
#
# 备份内容：/data 整个数据目录（users.db、chroma 向量库、术语缓存、归档文件）
# 建议：加到 crontab 每天凌晨自动跑
#   0 3 * * * cd ~/zhihui && bash scripts/oracle/backup-to-oci.sh --hot >> /var/log/zhihui-backup.log 2>&1
# ============================================================
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

REMOTE=${OCI_REMOTE:-oci}          # rclone 远端名
BUCKET=${OCI_BUCKET:-zhihui-backups}
KEEP=${KEEP:-14}                   # 云端保留天数
HOT=0
[ "${1:-}" = "--hot" ] && HOT=1

c_ok()   { printf '\033[32m[ok]\033[0m %s\n' "$*"; }
c_info() { printf '\033[36m[..]\033[0m %s\n' "$*"; }
c_err()  { printf '\033[31m[x]\033[0m %s\n' "$*" >&2; }

SUDO=""; [ "$(id -u)" -ne 0 ] && command -v sudo >/dev/null 2>&1 && SUDO="sudo"
DOCKER="docker"; $SUDO docker info >/dev/null 2>&1 || DOCKER="$SUDO docker"

command -v rclone >/dev/null 2>&1 || {
    c_err "未安装 rclone。安装：curl https://rclone.org/install.sh | sudo bash"
    exit 1
}
rclone listremotes 2>/dev/null | grep -q "^${REMOTE}:" || {
    c_err "rclone 远端 ${REMOTE}: 未配置，先执行：bash scripts/oracle/setup-rclone-oci.sh"
    exit 1
}
$DOCKER compose ps --status running --services 2>/dev/null | grep -q '^zhihui$' || {
    c_err "容器未运行，先执行：bash scripts/oracle/deploy.sh"
    exit 1
}

STAMP=$(date +%Y%m%d-%H%M%S)
NAME="zhihui-data-${STAMP}.tar.gz"
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

if [ "$HOT" -eq 0 ]; then
    c_info "暂停服务以保证数据一致（约 5~15 秒）"
    $DOCKER compose stop zhihui >/dev/null
    START_BACK=1
else
    c_info "热备份模式（服务不中断，SQLite 可能出现瞬时不一致）"
    START_BACK=0
fi

c_info "打包数据目录"
$DOCKER compose run --rm --no-deps -T --entrypoint sh zhihui \
    -c 'tar czf - -C /data .' > "$TMP/$NAME"

if [ "$START_BACK" -eq 1 ]; then
    $DOCKER compose start zhihui >/dev/null
    c_ok "服务已恢复"
fi

SIZE=$(du -h "$TMP/$NAME" | cut -f1)
c_ok "打包完成：$NAME（$SIZE）"

c_info "上传到 ${REMOTE}:${BUCKET}/daily/$(date +%Y/%m)/"
rclone copy "$TMP/$NAME" "${REMOTE}:${BUCKET}/daily/$(date +%Y/%m)/" \
    --s3-chunk-size 10M --s3-upload-cutoff 10M --progress

# 校验云端大小一致
REMOTE_SIZE=$(rclone size "${REMOTE}:${BUCKET}/daily/$(date +%Y/%m)/$NAME" --json 2>/dev/null | sed -n 's/.*"bytes":\([0-9]*\).*/\1/p')
LOCAL_SIZE=$(stat -c%s "$TMP/$NAME" 2>/dev/null || stat -f%z "$TMP/$NAME")
if [ "$REMOTE_SIZE" = "$LOCAL_SIZE" ]; then
    c_ok "云端校验通过（$LOCAL_SIZE 字节）"
else
    c_err "云端大小不一致（本地 $LOCAL_SIZE / 云端 ${REMOTE_SIZE:-未知}）"
    exit 1
fi

# 清理过期备份
c_info "清理 ${KEEP} 天前的云端备份"
rclone delete "${REMOTE}:${BUCKET}/daily" --min-age "${KEEP}d" --include "zhihui-data-*.tar.gz" 2>/dev/null || true

c_ok "备份完成"
