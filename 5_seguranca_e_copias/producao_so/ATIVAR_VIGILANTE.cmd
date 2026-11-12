@echo off
setlocal
cd /d "%~dp0"
title Ativar vigilante do Jarvis
set "PYW=%~dp0.venv\Scripts\pythonw.exe"
set "STARTUP=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"
if not exist "%PYW%" (echo Nao encontrei %PYW% & goto end)
echo A por o vigilante no arranque do Windows...
copy /Y "%~dp0Jarvis Vigilante.vbs" "%STARTUP%\Jarvis Vigilante.vbs"
if exist "%STARTUP%\Jarvis Vigilante.vbs" (echo OK: arranque automatico pela pasta de Arranque do Windows. & goto run)
echo A pasta de Arranque recusou. A tentar pelo Agendador de Tarefas...
schtasks /Create /SC ONLOGON /TN "Jarvis Vigilante" /TR "wscript.exe \"%~dp0Jarvis Vigilante.vbs\"" /F
if errorlevel 1 (echo. & echo NAO FOI POSSIVEL configurar o arranque automatico. Tira uma foto a esta janela e manda ao Claude. & goto run)
echo OK: arranque automatico pelo Agendador de Tarefas.
:run
echo.
echo A ligar o vigilante agora (e a enviar um aviso de teste para o telemovel)...
start "" "%PYW%" "%~dp0vigilante.py" --teste
echo Deves receber no telemovel o aviso "Jarvis: teste" dentro de 1 minuto.
echo Registo: logs\vigilante.log
:end
echo.
pause
