@echo off
rem W8: 后端启动脚本（dev 用 --reload，改代码自动重载，不用手动重启）
cd /d d:\ai-diagnosis-mvp\backend
C:\Users\31905\miniconda3\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
