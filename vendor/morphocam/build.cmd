@echo off
rem Compila o filtro da camera virtual (Morpho Camera) para 64 e 32 bits.
rem
rem     build.cmd [pasta de saida]
rem
rem Precisa do Visual Studio 2019 Build Tools (C++). O resultado sao os arquivos
rem MorphoCamera64-N.dll e MorphoCamera32-N.dll na pasta de saida (N = revisao, ver build-one.cmd).
setlocal
set "HERE=%~dp0"
set "OUT=%~1"
if "%OUT%"=="" set "OUT=C:\Users\vinic\dlc-lab\morphocam"
if not exist "%OUT%" mkdir "%OUT%"
cmd /c ""%HERE%build-one.cmd" 64 "%OUT%"" || exit /b 1
cmd /c ""%HERE%build-one.cmd" 32 "%OUT%"" || exit /b 1
echo.
echo Pronto: os arquivos MorphoCamera64-N.dll e MorphoCamera32-N.dll estao em %OUT%
