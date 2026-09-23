"""远程运维小工具：查看服务器构建/运行状态。

用法：
  python _deploy/status.py <IP> <密码>          # 概览（日志尾部 + 容器状态）
"""
import sys

import paramiko

SERVER = sys.argv[1]
PASSWORD = sys.argv[2]
REMOTE_DIR = "/home/ubuntu/ai-diagnosis"

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(SERVER, username="ubuntu", password=PASSWORD, timeout=15)


def run(cmd: str, timeout: int = 30) -> str:
    _, out, err = ssh.exec_command(cmd, timeout=timeout)
    out.channel.recv_exit_status()
    return ((out.read() + err.read()).decode()).strip()


print("=== 容器状态 ===")
print(run(f"cd {REMOTE_DIR} && docker compose ps -a --format 'table {{{{.Name}}}}\\t{{{{.State}}}}\\t{{{{.Status}}}}'"))

print("\n=== 构建进程（还活着吗）===")
print(run("ps aux | grep -E 'docker (compose|build)' | grep -v grep | head -3") or "（无构建进程在跑）")

print("\n=== 磁盘/内存 ===")
print(run("df -h / | tail -1; free -m | head -2"))

print("\n=== 构建日志最后 25 行 ===")
print(run("tail -25 /tmp/diag-build.log"))

ssh.close()
