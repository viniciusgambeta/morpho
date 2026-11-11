@echo off
rem Compila o MorphoDiagnostico.exe (um arquivo so, sem instalacao).
rem
rem     build.cmd [pasta de saida]
rem
rem Precisa do Visual Studio 2019 Build Tools (C++). O endereco da pagina fica em src\site.h.
setlocal
set "HERE=%~dp0"
set "OUT=%~1"
if "%OUT%"=="" set "OUT=C:\Users\vinic\dlc-lab\dist\diagnostico"
if not exist "%OUT%\obj" mkdir "%OUT%\obj"
set "VSDIR=C:\Program Files (x86)\Microsoft Visual Studio\2019\BuildTools\VC\Auxiliary\Build"
if not exist "%VSDIR%\vcvars64.bat" (
  echo Nao achei o Visual Studio 2019 Build Tools em "%VSDIR%".
  exit /b 1
)
call "%VSDIR%\vcvars64.bat" >nul || exit /b 1
cd /d "%HERE%src"
rc /nologo /fo "%OUT%\obj\app.res" app.rc || exit /b 1
cl /nologo /c /O2 /MT /W3 /EHsc /utf-8 /DUNICODE /D_UNICODE /Fo"%OUT%\obj\\" main.cpp probe.cpp || exit /b 1
link /nologo /SUBSYSTEM:WINDOWS /OPT:REF /OPT:ICF /MANIFEST:NO /OUT:"%OUT%\MorphoDiagnostico.exe" ^
     "%OUT%\obj\main.obj" "%OUT%\obj\probe.obj" "%OUT%\obj\app.res" ^
     kernel32.lib user32.lib gdi32.lib gdiplus.lib shell32.lib ole32.lib oleaut32.lib uuid.lib strmiids.lib ^
     dxgi.lib dwmapi.lib wininet.lib bcrypt.lib advapi32.lib || exit /b 1
echo Pronto: %OUT%\MorphoDiagnostico.exe
