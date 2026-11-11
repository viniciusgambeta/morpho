@echo off
rem Abre o app com dois cliques, sem janela de terminal.
rem (Para ver mensagens ou passar opcoes de teste, use preview.bat.)
setlocal
cd /d "%~dp0"
set "PYTHONPATH=%~dp0"
rem Dados e logs numa pasta que qualquer programa enxerga igual (ver app\paths.py).
set "MORPHO_DATA_DIR=C:\Users\vinic\dlc-lab\app-data"
set "ENGINE_PYW=C:\Users\vinic\dlc-lab\beekamai\venv\Scripts\pythonw.exe"
if not exist "%ENGINE_PYW%" (
    echo Nao encontrei o Python do motor em %ENGINE_PYW%
    pause
    exit /b 1
)
start "" "%ENGINE_PYW%" -m app.ui %*
