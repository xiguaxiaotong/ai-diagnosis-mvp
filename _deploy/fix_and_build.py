"""修复 Docker Hub 拉取被墙：配置国内镜像加速器 + 重新触发构建 + 轮询到完成。

腾讯云轻量服务器走 mirror.ccs.tencentyun.com（内网，免费不限速），
备选 daocloud 公共镜像。写 /etc/docker/daemon.json → 重启 docker → 重新构建。
"""
import sys
import time

import paramiko

SERVER = sys.argv[1]
PASSWORD = sys.argv[2]
REMOTE_DIR = "/home/ubuntu/ai-diagnosis"

DAEMON_JSON = (
    '{"registry-mirrors": ['
    '"https://mirror.ccs.tencentyun.com", '
    '"https://docker.m.daocloud.io"]}'
)

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(SERVER, username="ubuntu", password=PASSWORD, timeout=15)


def run(cmd: str, timeout: int = 60) -> tuple[int, str]:
    _, out, err = ssh.exec_command(cmd, timeout=timeout)
    code = out.channel.recv_exit_status()
    return code, ((out.read() + err.read()).decode()).strip()


# 1. 配置镜像加速（腾讯云内网源优先）
code, out = run(f"echo '{DAEMON_JSON}' | sudo tee /etc/docker/daemon.json")
print("[1/3] 镜像加速配置:", out)

code, out = run("sudo systemctl restart docker && sleep 3 && docker info 2>/dev/null | grep -A3 'Registry Mirrors'")
print("[2/3] Docker 重启完成：\n", out)

# 2. 验证能拉镜像（拉 hello-world 测试）
code, out = run("sudo docker pull hello-world 2>&1 | tail -2", timeout=120)
print("[3/3] 拉取测试:", out.replace("\n", " | "))

# 3. 清掉失败残留，重新构建
run(f"cd {REMOTE_DIR} && docker compose down --remove-orphans 2>/dev/null")
run(
    f"cd {REMOTE_DIR} && nohup docker compose up -d --build > /tmp/diag-build.log 2>&1 & echo restarted"
)
print("\n重新构建已触发，开始轮询（最长 30 分钟）…")

deadline = time.time() + 1800
done = False
while time.time() < deadline:
    time.sleep(30)
    code, out = run(
        "docker compose -f "
        f"{REMOTE_DIR}/docker-compose.yml ps --format '{{.Name}} {{.State}}' 2>/dev/null"
        " | sort | tr '\\n' ' '"
    )
    code2, tail = run("tail -c 300 /tmp/diag-build.log 2>/dev/null")
    print(f"  [{time.strftime('%H:%M:%S')}] {out or tail[:120]}")
    if "diag-backend Running diag-frontend Running diag-nginx Running" in (out or ""):
        done = True
        break
    if "ERROR" in (tail or ""):
        print("  构建日志尾部:\n", tail)
        break

if done:
    print("\n构建完成，全部容器运行中！")
    code, out = run("sleep 8; curl -s -m 10 http://localhost/api/health")
    print("健康检查:", out or "(无响应，稍后再试)")
ssh.close()
