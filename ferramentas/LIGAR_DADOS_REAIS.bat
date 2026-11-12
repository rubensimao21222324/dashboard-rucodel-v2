@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0.."
title Ligar o Dashboard 2.0 aos dados reais (arranca em LEITURA)
for %%I in ("%~dp0..") do set "NOME=%%~nxI"
set "RUNTIME=%~dp0..\execucao\runtime"
set "PROD=%USERPROFILE%\Jarvis_Central_Pro"

echo.
echo  Liga a instancia DEV aos MESMOS servicos reais que o Jarvis de producao usa
echo  (site de gestao + contas dos setores), para veres tudo com dados verdadeiros.
echo  - Copia so os ficheiros de acesso. A pasta de producao NAO e alterada.
echo  - A DEV arranca SEMPRE em modo LEITURA: nada e alterado no software de producao
echo    ate carregares em "Escrita" no topo do painel.
echo.

rem Seguranca: so continua se a protecao Leitura/Escrita ja estiver no codigo.
if not exist "%~dp0..\3_setores_tablets\modo_escrita.py" goto sem_protecao
if not exist "%PROD%\gestao_rucodel.dpapi" goto sem_producao

echo [1/3] A parar a Central DEV (porta 22396), se estiver a correr ...
powershell -NoProfile -Command "$c=Get-NetTCPConnection -LocalPort 22396 -State Listen -ErrorAction SilentlyContinue; if($c){$c | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force }; Start-Sleep -Seconds 2}" >nul 2>nul

echo [2/3] A copiar os acessos da producao ^(so leitura da pasta de producao^) ...
if not exist "%RUNTIME%" mkdir "%RUNTIME%"
copy /y "%PROD%\gestao_rucodel.dpapi" "%RUNTIME%\gestao_rucodel.dpapi" >nul || goto erro_copia
echo       site de gestao: ok
if exist "%PROD%\setores.dpapi" copy /y "%PROD%\setores.dpapi" "%RUNTIME%\setores.dpapi" >nul && echo       contas dos setores: ok
if exist "%PROD%\colaboradores.json" if not exist "%RUNTIME%\colaboradores.json" copy /y "%PROD%\colaboradores.json" "%RUNTIME%\colaboradores.json" >nul && echo       colaboradores: ok

echo [3/3] A arrancar o Dashboard 2.0 ...
echo.
call "%~dp0..\ARRANCAR_DASHBOARD_2.0.bat"
exit /b 0

:sem_protecao
echo [!] Nao encontrei a protecao Leitura/Escrita no codigo ^(3_setores_tablets\modo_escrita.py^).
echo     Por seguranca nao copio os acessos. Nada foi alterado.
pause
exit /b 1

:sem_producao
echo [!] Nao encontrei os acessos da producao em: %PROD%
echo     Usa antes ferramentas\CONFIGURAR_ACESSOS.bat. Nada foi alterado.
pause
exit /b 1

:erro_copia
echo [!] Nao consegui copiar os acessos. Nada foi arrancado.
pause
exit /b 1
