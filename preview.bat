@echo off
rem Abre o preview do motor (marco 1). Exemplos:
rem   preview.bat --list-cameras
rem   preview.bat --source "C:\caminho\foto.jpg" --camera "HD Webcam"
rem   preview.bat --source "C:\caminho\foto.jpg" --camera "EOS Webcam Utility" --resolution 720p
setlocal
cd /d "%~dp0"
set "PYTHONPATH=%~dp0"
rem Dados e logs numa pasta que qualquer programa enxerga igual (ver app\paths.py).
set "MORPHO_DATA_DIR=C:\Users\vinic\dlc-lab\app-data"
set "ENGINE_PY=C:\Users\vinic\dlc-lab\beekamai\venv\Scripts\python.exe"
if not exist "%ENGINE_PY%" (
    echo Nao encontrei o Python do motor em %ENGINE_PY%
    exit /b 1
)
"%ENGINE_PY%" -m app.ui %*
