"""轻量重部署 v2：触发后台构建 → 断开 SSH → 短连接轮询状态。

每次 SSH 操作都是短连接（连上→执行→断开），避免腾讯云空闲断连导致
脚本假死。构建在服务器 nohup 后台跑，与本机连接无关。
"""
import sys
import time

# Windows 终端默认 GBK，print 中文/emoji 抛 UnicodeEncodeError → 强制 UTF-8
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import paramiko

SERVER = sys.argv[1]
PASSWORD = sys.argv[2]
REMOTE_DIR = "/home/ubuntu/ai-diagnosis"


def short_ssh(retries: int = 6, wait: int = 15):
    """短连接 + 重试：腾讯云 sshd 对频繁连接有频率限制，失败退避重试。"""
    last: Exception | None = None
    for i in range(retries):
        try:
            ssh = paramiko.SSHClient()
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            ssh.connect(SERVER, username="ubuntu", password=PASSWORD, timeout=15)
            return ssh
        except Exception as e:  # noqa: BLE001
            last = e
            print(f"      SSH 连接失败({i + 1}/{retries}): {type(e).__name__}，{wait}s 后重试…")
            time.sleep(wait)
    raise last  # type: ignore[misc]


def run(cmd: str, timeout: int = 30) -> str:
    """短连接执行命令，返回 stdout+stderr。"""
    ssh = short_ssh()
    try:
        _, out, err = ssh.exec_command(cmd, timeout=timeout)
        return (out.read() + err.read()).decode().strip()
    finally:
        ssh.close()


print("[1/2] 上传新包…")
ssh = short_ssh()
run(f"mkdir -p {REMOTE_DIR}")
sftp = ssh.open_sftp()
t0 = time.time()
sftp.put(r"d:/ai-diagnosis-mvp/_deploy/app.tar.gz", "/tmp/app.tar.gz")
sftp.close()
print(f"      上传 {time.time() - t0:.0f}s，解压中…")
run(f"cd {REMOTE_DIR} && tar -xzf /tmp/app.tar.gz && rm -rf data/chroma")
ssh.close()
print("      完成（旧 chroma 数据已清）")

print("[2/2] 触发后台构建（nohup，与本机连接无关）…")
try:
    run(
        f"cd {REMOTE_DIR} && nohup docker compose up -d --build "
        f"> /tmp/diag-build.log 2>&1 & disown; echo triggered",
        timeout=10,
    )
except Exception as e:
    print(f"      触发命令返回（后台已启动）: {type(e).__name__}")

print("\n轮询构建状态（每次短连接，最多 25 分钟）…")
deadline = time.time() + 25 * 60
last_len = 0
while time.time() < deadline:
    time.sleep(30)
    try:
        state = run(
            "docker compose -f " + REMOTE_DIR + "/docker-compose.yml ps "
            "--format '{{.Name}}|{{.State}}' 2>/dev/null | sort | tr '\\n' ' '"
        )
        log_tail = run("tail -c 300 /tmp/diag-build.log 2>/dev/null")
        print(f"[{time.strftime('%H:%M:%S')}] 容器: {state or '（构建中…）'}")
        if state.count("Running") >= 3:
            print("\n✅ 三个容器全部运行！")
            time.sleep(5)
            print("健康检查:", run("curl -s -m 10 http://localhost/api/health"))
            break
        # 构建报错检测（日志变长时才检查，避免重复）
        if len(log_tail) != last_len and ("ERROR" in log_tail or "error" in log_tail):
            if "CANCELED" in log_tail or "failed to solve" in log_tail:
                print("\n❌ 构建失败，日志尾部:\n", log_tail[-800:])
                break
        last_len = len(log_tail)
    except Exception as e:
        print(f"[{time.strftime('%H:%M:%S')}] 轮询异常（重试）: {type(e).__name__}")
else:
    print("超时未完成，上服务器看: tail -f /tmp/diag-build.log")