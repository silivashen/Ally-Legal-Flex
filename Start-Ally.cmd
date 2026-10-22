@echo off
setlocal
chcp 65001 >nul
title Ally Legal Flex
if not exist "%~dp0.venv\Scripts\python.exe" (
    echo Project Python environment not found: %~dp0.venv
    echo Run Setup-Ally.cmd first, then start again.
    pause
    exit /b 1
)
"%~dp0.venv\Scripts\python.exe" "%~dp0scripts\start_ally.py" %*
set "ALLY_EXIT_CODE=%ERRORLEVEL%"
if not "%ALLY_EXIT_CODE%"=="0" pause
exit /b %ALLY_EXIT_CODE%