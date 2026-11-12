@echo off
setlocal
title Desativar vigilante do Jarvis
del "%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\Jarvis Vigilante.vbs" 2>nul
schtasks /Delete /TN "Jarvis Vigilante" /F >nul 2>nul
powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*vigilante.py*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"
echo Vigilante desligado e retirado do arranque do Windows. A Central continua a correr.
echo.
pause
