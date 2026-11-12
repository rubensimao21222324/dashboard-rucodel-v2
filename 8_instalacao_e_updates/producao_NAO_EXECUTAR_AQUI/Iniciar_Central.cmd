@echo off
setlocal
cd /d "%~dp0"
title Jarvis Central Pro
if exist "%USERPROFILE%\Jarvis\.venv\Scripts\python.exe" goto oldpython
where py >nul 2>nul
if errorlevel 1 goto missing
py -3 "%~dp0bootstrap.py" start
goto end
:oldpython
"%USERPROFILE%\Jarvis\.venv\Scripts\python.exe" "%~dp0bootstrap.py" start
goto end
:missing
echo Nao encontrei o Python. Confirma a pasta C:\Users\simao\Jarvis.
:end
echo.
pause
