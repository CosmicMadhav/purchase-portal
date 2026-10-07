@echo off
title Purchase Portal
cd /d "%~dp0"
python app.py
if errorlevel 1 pause
