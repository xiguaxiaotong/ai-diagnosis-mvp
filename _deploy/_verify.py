"""部署最终验证：健康检查 / 首页 / PDF 接口 / 容器资源占用。"""
import sys

# Windows 终端默认 GBK，print 中文/emoji 抛 UnicodeEncodeError → 强制 UTF-8
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import time

import paramiko

# 服务器地址/密码从命令行传入（与 deploy.py 同款口径，严禁硬编码入库）
SERVER = sys.argv[1] if len(sys.argv) > 1 else "134.175.137.41"
PASSWORD = sys.argv[2]

for i in range(5):
    try:
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(SERVER, username="ubuntu", password=PASSWORD, timeout=20)
        cmd = (
            "echo '--- 健康检查'; curl -s -m 10 http://localhost/api/health; echo; "
            "echo '--- 前端首页'; curl -s -o /dev/null -w '%{http_code}' -m 10 http://localhost/; echo; "
            "echo '--- 方案页'; curl -s -o /dev/null -w '%{http_code}' -m 10 http://localhost/project/35; echo; "
            "echo '--- 项目API'; curl -s -o /dev/null -w '%{http_code}' -m 10 http://localhost/api/projects; echo; "
            "echo '--- PDF导出'; curl -s -o /tmp/_t.pdf -w '%{http_code} %{content_type} %{size_download}B' -m 30 http://localhost/api/project/35/pdf; echo; "
            "echo '--- 容器资源'; docker stats --no-stream --format '{{.Name}} CPU={{.CPUPerc}} MEM={{.MemUsage}}'; "
            "echo '--- 磁盘'; df -h / | tail -1"
        )
        _, out, err = ssh.exec_command(cmd, timeout=60)
        print(out.read().decode("utf-8", errors="replace"))
        ssh.close()
        break
    except Exception as e:  # noqa: BLE001
        print(f"retry {i+1}: {type(e).__name__}")
        time.sleep(10)