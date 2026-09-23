"""等待构建完成：短连接+重试，每 3 分钟查一次，最多 45 分钟。

编码修复：Windows 终端默认 GBK，直接 print 中文/emoji 抛 UnicodeEncodeError，
会被轮询的 except 吞掉 → 明明容器已 running 也判定失败、无限重试。
顶部强制 stdout/stderr 为 UTF-8（errors=replace 兜底），并让状态打印永不
中断成功判定。
"""
import sys

# 强制控制台输出 utf-8，解决中文日志编码报错（Python 3.7+）
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import time

import paramiko

# 服务器地址/密码从命令行传入（与 deploy.py 同款口径，严禁硬编码入库）
HOST, USER, PWD = sys.argv[1], "ubuntu", sys.argv[2]


def run(cmd: str, timeout: int = 30) -> str:
    last: Exception | None = None
    for i in range(5):
        try:
            ssh = paramiko.SSHClient()
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            ssh.connect(HOST, username=USER, password=PWD, timeout=15)
            try:
                _, out, err = ssh.exec_command(cmd, timeout=timeout)
                return (out.read() + err.read()).decode().strip()
            finally:
                ssh.close()
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(10)
    raise last  # type: ignore[misc]


STATE_CMD = (
    "docker compose -f /home/ubuntu/ai-diagnosis/docker-compose.yml ps "
    "--format '{{.Name}}|{{.State}}' 2>/dev/null | sort | tr '\\n' ' '"
)


def say(msg: str) -> None:
    """打印失败（编码/管道断开）绝不影响成功判定逻辑。"""
    try:
        print(msg)
    except Exception:  # noqa: BLE001
        pass


deadline = time.time() + 45 * 60
while time.time() < deadline:
    time.sleep(180)
    try:
        state = run(STATE_CMD)
        tail = run("tail -c 500 /tmp/diag-build.log 2>/dev/null")
        mem = run("free -h | sed -n 2p")
        say(f"[{time.strftime('%H:%M:%S')}] 容器: {state or '构建中'}")
        say(f"    内存: {mem}")
        say(f"    日志尾: {tail[-200:].replace(chr(10), ' | ')}")
        if state.count("running") >= 3 or state.count("Running") >= 3:
            say("\n✅ 三容器全部运行")
            time.sleep(6)
            say("健康检查: " + run("curl -s -m 10 http://localhost/api/health"))
            say("前端: " + run("curl -s -o /dev/null -w '%{http_code}' -m 10 http://localhost/"))
            break
        if ("ERROR" in tail and "CANCELED" in tail) or "failed to solve" in tail:
            say("\n❌ 构建失败:\n" + tail[-800:])
            break
    except Exception as e:  # noqa: BLE001
        say(f"[{time.strftime('%H:%M:%S')}] 轮询失败重试: {type(e).__name__}")
else:
    say("45 分钟超时，需上服务器看 tail -f /tmp/diag-build.log")