"""远程部署：本地打包 → SFTP 上传 → 服务器解压 → docker compose 构建启动。

用法：python _deploy/deploy.py <服务器IP> <ubuntu密码>
构建在服务器后台跑（torch 等依赖下载 5-10 分钟），日志落 /tmp/diag-build.log。
"""
import sys
import time

import paramiko

SERVER = sys.argv[1] if len(sys.argv) > 1 else "134.175.137.41"
PASSWORD = sys.argv[2]
REMOTE_DIR = "/home/ubuntu/ai-diagnosis"


def main() -> None:
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(SERVER, username="ubuntu", password=PASSWORD, timeout=15)
    print(f"[1/4] SSH 连接成功 {SERVER}")

    def run(cmd: str, timeout: int = 120) -> tuple[int, str]:
        _, out, err = ssh.exec_command(cmd, timeout=timeout)
        code = out.channel.recv_exit_status()
        return code, (out.read().decode() + err.read().decode()).strip()

    # 判定构建是否已完成：所有容器 running 且 build.log 无进行中的输出
    code, out = run("docker --version")
    print("[2/4] 服务器 Docker:", out or "(不可用)")

    print("[3/4] 上传项目包（SFTP）…")
    run(f"mkdir -p {REMOTE_DIR}")
    sftp = ssh.open_sftp()
    t0 = time.time()
    sftp.put(r"d:/ai-diagnosis-mvp/_deploy/app.tar.gz", "/tmp/app.tar.gz")
    sftp.close()
    print(f"      上传完成 {time.time() - t0:.1f}s")

    code, out = run(f"cd {REMOTE_DIR} && tar -xzf /tmp/app.tar.gz && ls")
    print("      解压完成，根目录：", out.replace("\n", " ")[:200])

    print("[4/4] 触发构建（后台运行，日志 /tmp/diag-build.log）…")
    run(
        f"cd {REMOTE_DIR} && nohup docker compose up -d --build > /tmp/diag-build.log 2>&1 & echo started",
    )

    # 轮询构建状态（最长 15 分钟）
    deadline = time.time() + 900
    while time.time() < deadline:
        time.sleep(20)
        # 模板段是普通字符串字面量（非 f-string），{{}} 原样保留 → 用双花括号即可
        code, out = run(
            f"docker compose -f {REMOTE_DIR}/docker-compose.yml"
            " ps --format '{{.Name}} {{.State}}' 2>/dev/null"
            " | sort | tr '\\n' ' '"
        )
        code2, tail = run("tail -c 400 /tmp/diag-build.log 2>/dev/null")
        print(f"      [{time.strftime('%H:%M:%S')}] 容器: {out or '构建中'}")
        if "diag-backend Running diag-frontend Running diag-nginx Running" in (out or ""):
            print("\n构建完成，全部容器已运行！")
            code, health = run("sleep 5; curl -s -m 10 http://localhost/api/health")
            print("健康检查:", health)
            break
        if "ERROR" in (tail or "") and "still running" not in tail:
            print("\n构建日志尾部（疑似出错）：\n", tail)
            break
    else:
        print("超时：15 分钟未构建完成，手动看日志：tail -f /tmp/diag-build.log")

    ssh.close()


if __name__ == "__main__":
    main()
