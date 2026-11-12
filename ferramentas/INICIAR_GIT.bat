@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0.."
title Preparar repositorio Git
where git >nul 2>nul
if errorlevel 1 (
  echo O Git nao esta instalado. Instala com:  winget install --id Git.Git -e
  echo Depois corre este ficheiro outra vez.
  pause & exit /b 1
)
if exist ".git" ( echo O repositorio Git ja existe. & git status --short & pause & exit /b 0 )
git init -b main || ( echo Falhou git init & pause & exit /b 1 )
git config user.name >nul 2>nul || echo [info] Ainda nao tens nome no Git. Define depois:  git config --global user.name "O Teu Nome"
git config user.email >nul 2>nul || echo [info] Define tambem:  git config --global user.email "o.teu@email"
git add -A
echo.
echo Ficheiros que NAO vao para o Git ^(segredos/dados^) estao no .gitignore.
git status --short | find /c /v "" 
git commit -m "Dashboard Rucodel 2.0 - base organizada por modulos" && echo Primeiro commit feito. || echo [!] O commit falhou ^(provavelmente falta o nome/email acima^). Define-os e corre: git commit -m "Base"
echo.
echo Para ligar ao GitHub mais tarde:  git remote add origin ^<url do repositorio PRIVADO^>  e  git push -u origin main
pause
