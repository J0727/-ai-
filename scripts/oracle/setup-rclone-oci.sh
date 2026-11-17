#!/usr/bin/env bash
# ============================================================
# 智汇研途 · 配置 rclone 连接 Oracle 对象存储（S3 兼容接口）
#
# 需要先在 OCI 控制台准备好三样东西：
#   1. 存储桶 Bucket（例如 zhihui-backups，可见性 Private）
#   2. 命名空间 Namespace（对象存储页面右上角显示）
#   3. Customer Secret Key（右上角头像 → Customer secret keys → 生成）
#      —— 注意不是 API Key，S3 兼容接口用的是 Access Key / Secret Key
#
# 用法：
#   bash scripts/oracle/setup-rclone-oci.sh
# 或非交互：
#   OCI_NAMESPACE=xxx OCI_REGION=ap-tokyo-1 \
#   OCI_ACCESS_KEY=xxx OCI_SECRET_KEY=xxx OCI_BUCKET=zhihui-backups \
#   bash scripts/oracle/setup-rclone-oci.sh
# ============================================================
set -euo pipefail

REMOTE=${OCI_REMOTE:-oci}

c_ok()   { printf '\033[32m[ok]\033[0m %s\n' "$*"; }
c_info() { printf '\033[36m[..]\033[0m %s\n' "$*"; }
c_err()  { printf '\033[31m[x]\033[0m %s\n' "$*" >&2; }

command -v rclone >/dev/null 2>&1 || {
    c_info "安装 rclone"
    curl -fsSL https://rclone.org/install.sh | ${SUDO:-sudo} bash
}

read_val() { # read_val 变量名 提示 默认值
    local var=$1 prompt=$2 def=${3:-} cur
    cur=$(eval "echo \"\${$var:-}\"")
    if [ -n "$cur" ]; then eval "$var=\$cur"; return; fi
    if [ -t 0 ]; then
        read -r -p "$prompt${def:+（$def）}: " cur
        [ -z "$cur" ] && cur=$def
        eval "$var=\$cur"
    else
        eval "$var=\$def"
    fi
}

if [ -z "${OCI_NAMESPACE:-}" ]; then
cat <<'EOF'
============================================================
OCI 对象存储连接信息（在云控制台「存储 → 对象存储」页可查）
============================================================
EOF
fi

read_val OCI_NAMESPACE "命名空间 Namespace"
read_val OCI_REGION    "区域 Region" "ap-tokyo-1"
read_val OCI_ACCESS_KEY "Access Key（Customer Secret Key 的 Access Key）"
read_val OCI_SECRET_KEY "Secret Key"
read_val OCI_BUCKET    "存储桶名 Bucket" "zhihui-backups"

[ -n "$OCI_NAMESPACE" ] && [ -n "$OCI_ACCESS_KEY" ] && [ -n "$OCI_SECRET_KEY" ] \
    || { c_err "信息不完整"; exit 1; }

ENDPOINT="https://${OCI_NAMESPACE}.compat.objectstorage.${OCI_REGION}.oraclecloud.com"
c_info "写入 rclone 远端：${REMOTE}: → ${ENDPOINT}"

rclone config create "$REMOTE" s3 \
    provider=Other \
    env_auth=false \
    access_key_id="$OCI_ACCESS_KEY" \
    secret_access_key="$OCI_SECRET_KEY" \
    endpoint="$ENDPOINT" \
    region="$OCI_REGION" \
    force_path_style=true \
    --non-interactive >/dev/null

c_ok "rclone 远端已写入 ~/.config/rclone/rclone.conf"

c_info "测试连通性"
if rclone lsd "${REMOTE}:" >/dev/null 2>&1; then
    c_ok "连接成功"
else
    c_err "连接失败：请检查 Access Key/Secret Key 是否正确、区域与命名空间是否匹配"
    c_err "常见原因：用了 API Key 而非 Customer Secret Key；或桶的可见性不是 Private"
    exit 1
fi

c_info "确认存储桶 ${OCI_BUCKET} 存在"
if rclone lsd "${REMOTE}:" 2>/dev/null | awk '{print $NF}' | grep -qx "$OCI_BUCKET"; then
    c_ok "存储桶已存在"
else
    c_info "创建存储桶"
    rclone mkdir "${REMOTE}:${OCI_BUCKET}" && c_ok "存储桶 ${OCI_BUCKET} 已创建"
fi

cat <<EOF

下一步：
  bash scripts/oracle/backup-to-oci.sh          # 立即备份一次
  crontab -e                                    # 加定时任务，例如每天 3 点：
  0 3 * * * cd \$HOME/zhihui && bash scripts/oracle/backup-to-oci.sh --hot >> /var/log/zhihui-backup.log 2>&1

恢复：
  bash scripts/oracle/restore-from-oci.sh       # 恢复最新一份
  bash scripts/oracle/restore-from-oci.sh zhihui-data-20261115-030001.tar.gz
EOF
