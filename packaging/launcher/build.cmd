@echo off
rem Compila o Morpho.exe (o programa que abre o app, com icone).
rem
rem     build.cmd [pasta de saida]
rem
rem Precisa do Visual Studio 2019 Build Tools (C++). O icone (morpho.ico) e gerado
rem antes por packaging\make_icon.py.
setlocal
set "HERE=%~dp0"
set "OUT=%~1"
if "%OUT%"=="" set "OUT=C:\Users\vinic\dlc-lab\dist\launcher"
if not exist "%OUT%" mkdir "%OUT%"
set "VSDIR=C:\Program Files (x86)\Microsoft Visual Studio\2019\BuildTools\VC\Auxiliary\Build"
if not exist "%VSDIR%\vcvars64.bat" (
  echo Nao achei o Visual Studio 2019 Build Tools em "%VSDIR%".
  exit /b 1
)
call "%VSDIR%\vcvars64.bat" >nul || exit /b 1
cd /d "%HERE%"
rc /nologo /fo "%OUT%\morpho.res" morpho.rc || exit /b 1
cl /nologo /c /O1 /MT /W3 /EHsc /DUNICODE /D_UNICODE /Fo"%OUT%\\" launcher.cpp || exit /b 1
link /nologo /SUBSYSTEM:WINDOWS /OPT:REF /OPT:ICF /OUT:"%OUT%\Morpho.exe" "%OUT%\launcher.obj" "%OUT%\morpho.res" ^
     kernel32.lib user32.lib shell32.lib || exit /b 1
echo Pronto: %OUT%\Morpho.exe
