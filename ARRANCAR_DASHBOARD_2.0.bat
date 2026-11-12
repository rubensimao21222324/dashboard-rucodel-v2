@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"
title Dashboard Rucodel 2.0 (DEV)

rem ===== Tudo fica DENTRO desta pasta: o que e gerado vai para a subpasta "execucao" (fora do Git) =====
for %%I in ("%~dp0.") do set "NOME=%%~nxI"
set "EXEC=%~dp0execucao"
set "VENV=%EXEC%\.venv"
set "JARVIS_PORT=22396"
set "JARVIS_REMOTE_PORT=22397"

echo.
echo  Dashboard Rucodel 2.0 (DEV)  -  painel em http://127.0.0.1:22396/
echo  Nao mexe no Jarvis de producao (porta 12396); podem correr os dois.
echo.

rem ---- 1) Ja esta a correr? Reinicia, para carregar sempre o codigo novo ----
rem (Antes so abria o painel e ficava a versao antiga. So mexe na DEV, porta 22396; a producao 12396 nao e tocada.)
powershell -NoProfile -Command "try{(Invoke-WebRequest -UseBasicParsing http://127.0.0.1:22396/health -TimeoutSec 2).StatusCode}catch{exit 1}" >nul 2>nul
if errorlevel 1 goto livre
echo A Central DEV ja esta a correr. A reiniciar para carregar o codigo novo...
powershell -NoProfile -Command "$c=Get-NetTCPConnection -LocalPort 22396 -State Listen -ErrorAction SilentlyContinue; $c | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }; Start-Sleep -Seconds 3"
:livre
powershell -NoProfile -Command "if(Get-NetTCPConnection -LocalPort 22396 -State Listen -ErrorAction SilentlyContinue){exit 1}" >nul 2>nul
if errorlevel 1 (
  echo A porta 22396 esta ocupada por outro programa. Nao vou fechar nada.
  pause & exit /b 1
)

rem ---- 2) Python 3.11+ (so se ainda nao houver ambiente) ---------------------
rem Sem blocos ( ) de proposito: dentro de um bloco o %PY% era lido antes de ser definido e ficava vazio.
if exist "%VENV%\Scripts\python.exe" goto dependencias
set "PY="
py -3 -c "import sys;sys.exit(0 if sys.version_info>=(3,11) else 1)" >nul 2>nul && set "PY=py -3"
if not defined PY python -c "import sys;sys.exit(0 if sys.version_info>=(3,11) else 1)" >nul 2>nul && set "PY=python"
if not defined PY goto sem_python
echo [1/3] A criar o ambiente Python ^(so na primeira vez^) com: %PY%
if not exist "%EXEC%" mkdir "%EXEC%"
%PY% -m venv "%VENV%"
if errorlevel 1 goto erro_venv
if not exist "%VENV%\Scripts\python.exe" goto erro_venv
goto dependencias

:sem_python
echo [!] Nao encontrei o Python 3.11 ou mais recente.
where winget >nul 2>nul
if errorlevel 1 goto sem_winget
choice /m "    Instalar o Python 3.12 agora com o winget"
if errorlevel 2 goto cancelado
winget install -e --id Python.Python.3.12 --accept-package-agreements --accept-source-agreements
echo.
echo     Python instalado. FECHA esta janela e faz duplo clique neste ficheiro outra vez.
pause
exit /b 0

:sem_winget
echo     Instala-o em https://www.python.org/downloads/ ^(marca "Add python.exe to PATH"^) e corre este ficheiro outra vez.
pause
exit /b 1

:cancelado
echo Cancelado.
pause
exit /b 1

:erro_venv
echo ERRO a criar o ambiente Python em: %VENV%
echo Apaga a pasta "%EXEC%\.venv" ^(se existir^) e corre este ficheiro outra vez.
pause
exit /b 1

:dependencias
rem ---- 3) Dependencias: so se o requirements.txt mudou -----------------------
set "SELO=%EXEC%\requirements.instalado"
fc /b "%~dp0requirements.txt" "%SELO%" >nul 2>nul
if errorlevel 1 (
  echo [2/3] A instalar dependencias ^(pillow, openpyxl, reportlab, edge-tts^) ...
  "%VENV%\Scripts\python.exe" -m pip install --disable-pip-version-check -q -r "%~dp0requirements.txt" || ( echo ERRO a instalar dependencias. Verifica a internet. & pause & exit /b 1 )
  copy /y "%~dp0requirements.txt" "%SELO%" >nul
) else (
  echo [2/3] Dependencias ja instaladas.
)

rem ---- 4) Montar o codigo a partir dos modulos (rapido, sempre) --------------
echo [3/3] A montar o codigo e a arrancar ...
"%VENV%\Scripts\python.exe" "%~dp0ferramentas\montar_runtime.py" || ( echo ERRO a montar o codigo. & pause & exit /b 1 )

rem ---- 5) Arrancar -----------------------------------------------------------
if not exist "%EXEC%\runtime\logs" mkdir "%EXEC%\runtime\logs"
start "Dashboard Rucodel 2.0 - Central DEV" /min cmd /c ""%VENV%\Scripts\python.exe" -u "%EXEC%\runtime\backend\central.py" --project "%EXEC%\dados_locais\projeto" >> "%EXEC%\runtime\logs\central_dev.log" 2>&1"

set /a N=0
:espera
set /a N+=1
powershell -NoProfile -Command "try{(Invoke-WebRequest -UseBasicParsing http://127.0.0.1:22396/health -TimeoutSec 2).StatusCode}catch{exit 1}" >nul 2>nul
if not errorlevel 1 goto pronto
if %N% GEQ 30 (
  echo A Central nao respondeu em 60 s. Ve o registo: %EXEC%\runtime\logs\central_dev.log
  pause & exit /b 1
)
timeout /t 2 /nobreak >nul
goto espera

:pronto
echo.
echo  Pronto.  Painel:  http://127.0.0.1:22396/
start "" http://127.0.0.1:22396/
echo.
echo  Ligar ao site de gestao / setores:  ferramentas\CONFIGURAR_ACESSOS.bat
echo  Parar:  PARAR_DASHBOARD_2.0.bat
timeout /t 8 >nul
exit /b 0
