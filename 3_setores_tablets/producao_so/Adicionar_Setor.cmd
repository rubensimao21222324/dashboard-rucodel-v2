@echo off
setlocal
cd /d "%~dp0"
title Jarvis - Acrescentar setor
if exist "%~dp0.venv\Scripts\python.exe" (
  "%~dp0.venv\Scripts\python.exe" "%~dp0adicionar_setor.py"
) else (
  py -3 "%~dp0adicionar_setor.py"
)
