#!/usr/bin/env bash
# ============================================================
# 智汇研途 · 从 Oracle 对象存储恢复数据
#
# 用法：
#   bash scripts/oracle/restore-from-oci.sh                  # 恢复最新一份
#   bash scripts/oracle/restore-from-oci.sh zhihui-data-20261115-030001.tar.gz
#   bash scripts/oracle/restore-from-oci.sh --list           # 只看有哪些备份
#
# ⚠️ 恢复会覆盖容器 /data 目录中的现有数据，脚本会先自动存一份本地快照。
# ============================================================
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

REMOTE=${OCI_REMOTE:-oci}
BUCKET=${OCI_BUCKET:-zhihui-backups}
TARGET=${1:-latest}

c_ok()   { printf '\033[32m[ok]\033[0m %s\n' "$*"; }
c_info() { printf '\033[36m[..]\033[0m %s\n' "$*"; }
c_err()  { printf '\033[31m[x]\033[0m %s\n' "$*" >&2; }

SUDO=""; [ "$(id -u)" -ne 0 ] && command -v sudo >/dev/null 2>&1 && SUDO="sudo"
DOCKER="docker"; $SUDO docker info >/dev/null 2>&1 || DOCKER="$SUDO docker"

command -v rclone >/dev/null 2>&1 || { c_err "未安装 rclone"; exit 1; }

if [ "$TARGET" = "--list" ] || [ "$TARGET" = "-l" ]; then
    c_info "云端备份列表（新→旧）"
    rclone lsf "${REMOTE}:${BUCKET}/daily" -R --files-only 2>/dev/null \
        | grep 'zhihui-data-.*\.tar\.gz$' | sort -r | head -30
    exit 0
fi

if [ "$TARGET" = "latest" ]; then
    TARGET=$(rclone lsf "${REMOTE}:${BUCKET}/daily" -R --files-only 2>/dev/null \
        | grep 'zhihui-data-.*\.tar\.gz$' | sort | tail -1 | xargs -r basename)
    [ -n "$TARGET" ] || { c_err "云端没有找到备份文件"; exit 1; }
fi

c_info "准备恢复：$TARGET"

TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

c_info "下载备份"
rclone copy "${REMOTE}:${BUCKET}/daily" "$TMP" --include "$TARGET" --progress
[ -f "$TMP/$TARGET" ] || { c_err "下载失败：$TARGET"; exit 1; }

# 恢复前先本地快照，防手滑
SNAP="$ROOT/.backup-before-restore-$(date +%Y%m%d-%H%M%S).tar.gz"
c_info "恢复前快照当前数据 → $(basename "$SNAP")"
$DOCKER compose stop zhihui >/dev/null 2>&1 || true
$DOCKER compose run --rm --no-deps -T --entrypoint sh zhihui -c 'tar czf - -C /data .' > "$SNAP" || true
c_ok "本地快照完成（$(du -h "$SNAP" | cut -f1)）"

c_info "解包覆盖 /data"
$DOCKER compose run --rm --no-deps -T --entrypoint sh zhihui -c 'tar xzf - -C /data && echo extracted' < "$TMP/$TARGET"

c_info "启动服务"
$DOCKER compose up -d zhihui >/dev/null
for i in $(seq 1 40); do
    curl -fsS -m 3 http://127.0.0.1:8000/api/health >/dev/null 2>&1 && { c_ok "服务已恢复运行"; exit 0; }
    sleep 3
done
c_err "服务启动后健康检查未通过，请查看：docker compose logs --tail=50 zhihui"
exit 1
