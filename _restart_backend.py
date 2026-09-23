# -*- coding: utf-8 -*-
"""重启本地后端（--reload 模式；stdout/stderr 落 local-dev.log 便于排障）"""
import subprocess
import time
import urllib.request

out = subprocess.run(["netstat", "-ano"], capture_output=True, text=True).stdout
for line in out.splitlines():
    if ":8000" in line and "LISTENING" in line:
        pid = line.split()[-1]
        print("杀掉旧后端 pid:", pid)
        subprocess.run(["taskkill", "/F", "/PID", pid], capture_output=True)

time.sleep(2)
log = open(r"d:\ai-diagnosis-mvp\backend\local-dev.log", "ab")
subprocess.Popen(
    # Windows 分离进程下 --reload 重启会 WinError 6 崩溃（CTRL_C_EVENT 句柄无效），
    # 改代码后需手动重跑本脚本重启
    ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"],
    cwd=r"d:\ai-diagnosis-mvp\backend",
    stdout=log, stderr=log,
    creationflags=subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS,
)
for i in range(12):
    time.sleep(5)
    try:
        with urllib.request.urlopen("http://localhost:8000/api/health", timeout=5) as r:
            print(f"({(i+1)*5}s) 后端健康:", r.read().decode())
            break
    except Exception:
        pass
else:
    print("60s 后仍未就绪，看 backend/local-dev.log")
