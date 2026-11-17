# -*- coding: utf-8 -*-
"""把 setup-tunnel.sh 上传到服务器并执行，返回 Cloudflare 公网地址。

用法: python scripts/oracle/start-tunnel-remote.py <IP> <root密码>
"""
import sys
import time

import paramiko

HOST = sys.argv[1] if len(sys.argv) > 1 else "139.224.206.77"
PWD = sys.argv[2] if len(sys.argv) > 2 else ""
LOCAL_SH = "scripts/oracle/setup-tunnel.sh"


def main():
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="root", password=PWD, timeout=15)

    sftp = c.open_sftp()
    sftp.put(LOCAL_SH, "/root/setup-tunnel.sh")
    sftp.close()

    # 单独一条命令执行脚本：命令行里不含 cloudflared 关键字，pkill 不会自伤
    _, out, err = c.exec_command("bash /root/setup-tunnel.sh 2>&1", timeout=90)
    text = out.read().decode(errors="replace")
    text += err.read().decode(errors="replace")
    print(text.strip())
    c.close()

    # 二次兜底：地址若还没出现，直接读日志
    for _ in range(6):
        if "TUNNEL_URL=http" in text:
            break
        time.sleep(5)
        c2 = paramiko.SSHClient()
        c2.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        c2.connect(HOST, username="root", password=PWD, timeout=15)
        _, o2, _ = c2.exec_command("grep -o 'https://[a-z0-9-]*\\.trycloudflare\\.com' /var/log/zhihui-tunnel.log | head -1")
        url = o2.read().decode().strip()
        c2.close()
        if url:
            print("TUNNEL_URL=" + url)
            break


if __name__ == "__main__":
    main()
