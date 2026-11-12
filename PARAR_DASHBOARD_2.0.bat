@echo off
chcp 65001 >nul
title Parar Dashboard Rucodel 2.0 (DEV)
rem Pára SO a instancia DEV: o processo que ouve na porta 22396. Nunca toca na de producao (12396).
powershell -NoProfile -Command "$c=Get-NetTCPConnection -LocalPort 22396 -State Listen -ErrorAction SilentlyContinue; if(-not $c){'A Central DEV nao esta a correr.';exit 0}; $c | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force }; 'Central DEV parada.'"
pause
