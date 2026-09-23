@echo off
rem 前端 dev server 一键启动（热更新，改代码浏览器自动刷新）
rem 后端请先跑 backend\start-backend.bat（http://localhost:8000）
cd /d d:\ai-diagnosis-mvp\frontend
set PATH=C:\Users\31905\.workbuddy\binaries\node\versions\20.18.0;%PATH%
echo Starting frontend dev at http://localhost:3000 ...
npm run dev
pause
