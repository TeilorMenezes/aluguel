@echo off
setlocal
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0agente_expansao\iniciar_agente.ps1"
if errorlevel 1 (
  echo.
  echo Nao foi possivel iniciar o Agente de Expansao.
  pause
)
