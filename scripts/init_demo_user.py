# -*- coding: utf-8 -*-
"""
创建评审专用演示账号。

用法（在仓库根目录执行）：
    python scripts/init_demo_user.py
    python scripts/init_demo_user.py --username demo --password demo123456

默认写入 ZHIHUI_DATA_DIR（未设置时为 ~/zhihui-data）下的 users.db。
若数据库尚未创建，脚本会自行建表，因此可以在服务启动前后任意时刻执行。
"""
import argparse
import hashlib
import os
import sqlite3
import sys
from datetime import datetime


def data_dir() -> str:
    return (os.getenv("ZHIHUI_DATA_DIR") or "").strip() or os.path.join(os.path.expanduser("~"), "zhihui-data")


def main() -> int:
    ap = argparse.ArgumentParser(description="创建智汇研途演示账号")
    ap.add_argument("--username", default="demo", help="账号名（默认 demo）")
    ap.add_argument("--password", default="demo123456", help="密码（默认 demo123456）")
    ap.add_argument("--admin", action="store_true", help="同时授予管理员角色")
    args = ap.parse_args()

    d = data_dir()
    os.makedirs(d, exist_ok=True)
    db = os.path.join(d, "users.db")

    conn = sqlite3.connect(db)
    try:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS users ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "username TEXT UNIQUE NOT NULL, "
            "password_hash TEXT NOT NULL, "
            "created_at TEXT NOT NULL, "
            "last_login TEXT)"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS user_meta ("
            "username TEXT PRIMARY KEY, "
            "role TEXT NOT NULL DEFAULT 'member', "
            "consented INTEGER NOT NULL DEFAULT 0, "
            "created_at TEXT NOT NULL, "
            "last_seen TEXT)"
        )
        now = datetime.now().isoformat(timespec="seconds")
        pw_hash = hashlib.sha256(args.password.encode("utf-8")).hexdigest()

        row = conn.execute("SELECT username FROM users WHERE username = ?", (args.username,)).fetchone()
        if row:
            conn.execute("UPDATE users SET password_hash = ? WHERE username = ?", (pw_hash, args.username))
            action = "已重置密码"
        else:
            conn.execute(
                "INSERT INTO users (username, password_hash, created_at) VALUES (?, ?, ?)",
                (args.username, pw_hash, now),
            )
            action = "已创建"

        role = "admin" if args.admin else "member"
        conn.execute(
            "INSERT INTO user_meta (username, role, consented, created_at) VALUES (?, ?, 1, ?) "
            "ON CONFLICT(username) DO UPDATE SET role = excluded.role, consented = 1",
            (args.username, role, now),
        )
        conn.commit()
        print(f"[ok] {action}账号：{args.username} / {args.password}（角色 {role}）")
        print(f"[ok] 数据库：{db}")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
