@echo off
title Purchase Portal
cd /d "%~dp0"
echo Starting Purchase Portal...

rem 1) Docker available? Start Docker Desktop if it is not running yet, then wait for it.
docker info >nul 2>&1
if %errorlevel%==0 goto docker_up
if exist "C:\Program Files\Docker\Docker\Docker Desktop.exe" (
  echo Starting Docker Desktop, please wait (up to 2 minutes)...
  start "" "C:\Program Files\Docker\Docker\Docker Desktop.exe"
  for /l %%i in (1,1,60) do (
    timeout /t 2 >nul
    docker info >nul 2>&1 && goto docker_up
  )
)
echo Docker did not start - running the portal directly with Python instead.
goto python

:docker_up
docker compose up -d
for /l %%i in (1,1,30) do (
  powershell -NoProfile -Command "try { Invoke-WebRequest -UseBasicParsing http://localhost:5050/login -TimeoutSec 2 | Out-Null; exit 0 } catch { exit 1 }" && goto open
  timeout /t 1 >nul
)
:open
start "" http://localhost:5050
exit /b

:python
python app.py
if errorlevel 1 pause
