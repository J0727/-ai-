#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
智汇研途 · 非交互远程部署器（paramiko）

用法：
    python scripts/oracle/deploy_remote.py <公网IP> <root密码>

做：本地打包（排除 .venv/.git/向量库）→ SFTP 上传 → 远程解压 → bootstrap.sh → deploy.sh
输出实时回显。改完代码重跑即可更新。
"""
import io
import os
import sys
import tarfile
import time

import paramiko

EXCLUDE_DIRS = {".git", ".venv", "__pycache__", "chroma_data", "node_modules", ".pytest_cache"}
REMOTE_PKG = "/tmp/zhihui-yantu.tgz"
REMOTE_DIR = "/root/zhihui"


def build_package(root: str, buf: io.BytesIO) -> int:
    count = 0
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in EXCLUDE_DIRS]
            rel_dir = os.path.relpath(dirpath, root)
            for name in filenames:
                if name.endswith(".pyc"):
                    continue
                full = os.path.join(dirpath, name)
                arc = name if rel_dir == "." else os.path.join(rel_dir, name)
                try:
                    tf.add(full, arcname=arc, recursive=False)
                    count += 1
                except (PermissionError, OSError):
                    continue
    return count


def stream(chan, tag=""):
    out = []
    while True:
        if chan.recv_ready():
            data = chan.recv(65536).decode("utf-8", "replace")
            sys.stdout.write(data)
            sys.stdout.flush()
            out.append(data)
        if chan.exit_status_ready() and not chan.recv_ready():
            break
        time.sleep(0.15)
    return chan.recv_exit_status(), "".join(out)


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)
    host, password = sys.argv[1], sys.argv[2]
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

    if not os.path.exists(os.path.join(root, ".env")):
        print("[x] 缺少 .env")
        sys.exit(1)

    print(f"[1/4] 打包 {root}")
    buf = io.BytesIO()
    n = build_package(root, buf)
    size = buf.tell()
    print(f"      {n} 个文件，{size/1024/1024:.2f} MB")

    print(f"[2/4] 连接 root@{host}")
    cli = paramiko.SSHClient()
    cli.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        cli.connect(host, port=22, username="root", password=password,
                    timeout=20, banner_timeout=25, auth_timeout=25,
                    look_for_keys=False, allow_agent=False)
    except paramiko.AuthenticationException:
        print("[x] 认证失败：密码不对，或 root 密码尚未生效（重置密码后需重启实例）")
        sys.exit(2)
    print("      登录成功")

    print(f"[3/4] 上传到 {REMOTE_PKG}")
    sftp = cli.open_sftp()
    buf.seek(0)
    sftp.putfo(buf, REMOTE_PKG)
    sftp.close()
    print("      上传完成")

    print("[4/4] 远程构建部署（首次 5~10 分钟，输出实时回显）")
    cmd = (
        "set -e; "
        f"mkdir -p {REMOTE_DIR}; "
        f"tar -xzf {REMOTE_PKG} -C {REMOTE_DIR}; "
        f"cd {REMOTE_DIR}; "
        "bash scripts/oracle/bootstrap.sh; "
        "bash scripts/oracle/deploy.sh; "
        "echo '===HEALTH==='; curl -fsS -m 5 http://127.0.0.1:8000/api/health || echo HEALTH_FAIL"
    )
    chan = cli.get_transport().open_session()
    chan.get_pty()
    chan.exec_command(cmd)
    code, output = stream(chan)
    cli.close()

    print()
    if "HEALTH_FAIL" in output or code != 0:
        print(f"[x] 部署未完全成功（exit={code}），上面日志里有原因")
        sys.exit(3)

    print(f"[ok] 部署完成 → http://{host}:8000")


if __name__ == "__main__":
    main()
