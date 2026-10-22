@echo off
setlocal
chcp 65001 >nul
title Ally Legal Flex Setup
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\setup_ally.ps1" %*
set "ALLY_SETUP_EXIT=%ERRORLEVEL%"
if "%~1"=="" pause
exit /b %ALLY_SETUP_EXIT%