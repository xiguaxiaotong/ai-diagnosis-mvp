"""大文件断点续传上传：SFTP append 模式，断线后从已传位置继续。

上传 app.tar.gz 后解压并触发构建。
"""
import os
import sys
import time

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import paramiko

# 服务器地址/密码从命令行传入（与 deploy.py 同款口径，严禁硬编码入库）
HOST, USER, PWD = sys.argv[1], "ubuntu", sys.argv[2]
LOCAL = r"d:/ai-diagnosis-mvp/_deploy/app.tar.gz"
REMOTE = "/tmp/app.tar.gz"
REMOTE_DIR = "/home/ubuntu/ai-diagnosis"

size = os.path.getsize(LOCAL)
print(f"本地文件: {size/1048576:.0f} MB")

import hashlib
local_md5 = hashlib.md5(open(LOCAL, "rb").read()).hexdigest()

t0 = time.time()
while True:
    try:
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(HOST, username=USER, password=PWD, timeout=20)
        sftp = ssh.open_sftp()
        try:
            done = sftp.stat(REMOTE).st_size
        except FileNotFoundError:
            done = 0
        if done == size:
            # 大小相同也可能是旧包 → md5 内容级校验
            _, out, _ = ssh.exec_command(f"md5sum {REMOTE} | awk '{{print $1}}'", timeout=30)
            remote_md5 = out.read().decode().strip()
            if remote_md5 == local_md5:
                print(f"已传完且 md5 一致（{local_md5[:8]}）")
                sftp.close()
                break
            print(f"大小相同但 md5 不一致（旧包残留）→ 删除重传")
            sftp.remove(REMOTE)
            done = 0
        if done > 0:
            # 服务器残留旧包且大小与本包不一致 → 必须重传（追加会造成 tar 污染！）
            print(f"服务器残留 {done}B ≠ 本地 {size}B → 删除重传")
            sftp.remove(REMOTE)
            done = 0
        print(f"断点续传：从 {done/1048576:.0f} MB 继续…")
        print(f"断点续传：从 {done/1048576:.0f} MB 继续…")
        with open(LOCAL, "rb") as f:
            f.seek(done)
            with sftp.open(REMOTE, "ab") as rf:
                chunk_size = 256 * 1024
                sent = done
                while True:
                    data = f.read(chunk_size)
                    if not data:
                        break
                    rf.write(data)
                    sent += len(data)
                    if sent % (10 * 1048576) < chunk_size:
                        speed = (sent - done) / max(time.time() - t0, 1) / 1024
                        print(f"  {sent/1048576:.0f}/{size/1048576:.0f} MB ({speed:.0f} KB/s)")
        # 校验
        remote_size = sftp.stat(REMOTE).st_size
        sftp.close()
        if remote_size == size:
            print(f"✅ 上传完成 {time.time()-t0:.0f}s，大小校验一致")
            break
        print(f"⚠️ 大小不一致 {remote_size} != {size}，重新续传…")
    except Exception as e:  # noqa: BLE001
        print(f"中断: {type(e).__name__}，10s 后续传…")
        time.sleep(10)

# 解压 + 触发构建
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(HOST, username=USER, password=PWD, timeout=20)
_, out, _ = ssh.exec_command(
    f"md5sum {REMOTE} | awk '{{print $1}}'", timeout=30)
remote_md5 = out.read().decode().strip()
if remote_md5 != local_md5:
    print(f"❌ md5 不一致（本地 {local_md5[:8]} vs 远端 {remote_md5[:8]}）—— tar 是旧包，终止！")
    ssh.close()
    sys.exit(1)
print(f"md5 校验一致（{local_md5[:8]}）")
_, out, _ = ssh.exec_command(
    f"cd {REMOTE_DIR} && tar -xzf {REMOTE} && rm -rf data/chroma && echo 解压完成", timeout=300)
print(out.read().decode())
ssh.close()

# 触发后台构建（短连接触发，断开不影响）
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(HOST, username=USER, password=PWD, timeout=20)
try:
    _, out, _ = ssh.exec_command(
        f"cd {REMOTE_DIR} && nohup docker compose up -d --build > /tmp/diag-build.log 2>&1 & disown",
        timeout=10)
    time.sleep(2)
    print("构建已触发（后台）")
except Exception as e:  # noqa: BLE001
    print(f"触发命令返回: {type(e).__name__}（后台已启动）")
ssh.close()
print("用 python _deploy/_wait_build.py 轮询构建状态")