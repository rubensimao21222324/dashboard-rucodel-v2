@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0.."
title Configurar acessos (DEV)
for %%I in ("%~dp0..") do set "NOME=%%~nxI"
set "VENV=%~dp0..\execucao\.venv"
if not exist "%VENV%\Scripts\python.exe" ( echo Corre primeiro ARRANCAR_DASHBOARD_2.0.bat & pause & exit /b 1 )
"%VENV%\Scripts\python.exe" "%~dp0configurar_dev.py"
pause
