@echo off
rem 后端 uvicorn 一键启动（双击即可跑；0.0.0.0 = 本机+手机都能访问）
cd /d d:\ai-diagnosis-mvp\backend
echo Starting backend at http://localhost:8000 ...
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
pause
