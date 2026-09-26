@echo off
chcp 65001 >nul
rem ============================================================
rem W10 Day1 冒烟一键脚本（唯一入口）
rem   一条命令 = 起后端 -> 等就绪 -> 跑冒烟 -> PASS/FAIL 汇总 -> 清理进程
rem
rem 数据隔离：
rem   服务起在独立 data\smoke\ 库（每次全新重建），主库 / 主 checkpoint / 主 trace 零接触；
rem   CHROMA_DIR 沿用主库（只读检索，冒烟更接近真实线上行为）。
rem   全新库保证首个注册用户 id=1 = ADMIN_USER_IDS=1（冒烟 admin）。
rem
rem 成本：真实 LLM 一轮（约 4 分钱）。日志：logs\smoke_server.log
rem ============================================================
setlocal EnableDelayedExpansion
set PY=C:\Users\31905\miniconda3\python.exe
cd /d "%~dp0.."

rem ---- 0. 端口预检：8000 被占用则拒绝（本脚本只清理自己起的进程，避免误杀） ----
netstat -aon | findstr ":8000 " | findstr "LISTENING" >nul 2>&1
if not errorlevel 1 (
    echo [SKIP] 8000 端口已被占用——请先停掉现有后端再跑冒烟（脚本只清理自己起的服务）
    exit /b 1
)

rem ---- 1. 冒烟数据目录（全新库，见文件头说明） ----
if exist data\smoke rmdir /s /q data\smoke
mkdir data\smoke 2>nul
if not exist logs mkdir logs

set SQLITE_PATH=%CD%\data\smoke\sqlite.db
set CHECKPOINTS_PATH=%CD%\data\smoke\checkpoints.sqlite
set TRACE_PATH=%CD%\logs\smoke_trace.jsonl
set ADMIN_USER_IDS=1
set RATE_LIMIT_ENABLED=true
set SMOKE_E2E=1
set SMOKE_BASE_URL=http://127.0.0.1:8000
set SMOKE_DB=%SQLITE_PATH%
set PYTHONIOENCODING=utf-8

rem ---- 2. 起后端（独立最小化进程，日志进 logs\smoke_server.log） ----
echo [1/3] 启动后端（独立冒烟库）...
start "smoke_backend" /min cmd /c "%PY% -m uvicorn app.main:app --host 127.0.0.1 --port 8000 > logs\smoke_server.log 2>&1"

rem ---- 3. 等就绪（健康检查，最多约 180 秒） ----
set /a TRIES=0
:WAIT
%PY% -c "import sys,urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=2).status==200 else 1)" >nul 2>&1
if not errorlevel 1 goto READY
set /a TRIES+=1
if !TRIES! GEQ 90 (
    echo [FAIL] 后端 180 秒未就绪，详见 logs\smoke_server.log
    set RC=1
    goto SUMMARY
)
timeout /t 2 /nobreak >nul
goto WAIT

:READY
echo [2/3] 后端就绪，跑冒烟套件（真实 LLM 一轮，约 1-2 分钟）...
%PY% -m pytest tests/test_smoke_e2e.py -m smoke -v --tb=short
set RC=%ERRORLEVEL%

:SUMMARY
rem ---- 4. 清理：杀掉本脚本起的后端（按端口定位 PID；起前已确认端口空闲） ----
for /f "tokens=5" %%a in ('netstat -aon ^| findstr ":8000 " ^| findstr "LISTENING"') do taskkill /PID %%a /T /F >nul 2>&1
echo [3/3] 后端已停。

if not defined RC set RC=1
if "%RC%"=="0" (
    echo ============================================================
    echo   冒烟 PASS
    echo ============================================================
) else (
    echo ============================================================
    echo   冒烟 FAIL  ^(exit %RC%^)  排查：logs\smoke_server.log
    echo ============================================================
)
endlocal & exit /b %RC%
