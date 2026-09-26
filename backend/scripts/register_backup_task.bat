@echo off
rem ============================================================
rem 注册每日全量备份计划任务（W10 Day5）
rem
rem 任务名：AIDiagnosis-FullBackup    每天凌晨 03:00 跑一次
rem 日志：  backend\backups\backup_full.log
rem
rem 改 python 路径 / 项目路径就改下面两行，其余照抄。
rem 卸载：schtasks /Delete /TN AIDiagnosis-FullBackup /F
rem ============================================================
setlocal
set PY=C:\Users\31905\miniconda3\python.exe
set PROJECT=D:\ai-diagnosis-mvp\backend

schtasks /Create /TN "AIDiagnosis-FullBackup" /SC DAILY /ST 03:00 ^
  /TR "cmd /c cd /d %PROJECT% && %PY% scripts\backup_full.py >> backups\backup_full.log 2>&1" ^
  /F
if errorlevel 1 (
  echo [FAIL] 计划任务注册失败，看上方 schtasks 报错
  exit /b 1
)

echo.
echo [OK] 注册成功，验证：
schtasks /Query /TN "AIDiagnosis-FullBackup" /V /FO LIST
echo.
echo 手动触发一次试跑：schtasks /Run /TN "AIDiagnosis-FullBackup"
endlocal
