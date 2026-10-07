@echo off
title Purchase Portal
cd /d "%~dp0"
rem Uses Docker if it is running, otherwise runs directly with Python + MS Office.
docker info >nul 2>&1
if %errorlevel%==0 (
  docker compose up -d
  timeout /t 3 >nul
  start "" http://localhost:5050
  exit /b
)
python app.py
if errorlevel 1 pause
