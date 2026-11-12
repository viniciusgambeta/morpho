@echo off
rem Uso interno do build.cmd:  build-one.cmd <64|32> <pasta de saida> [opcoes extras do compilador]
rem A camera de teste das medicoes (bench/vcam) sai com:  build-one.cmd 64 <pasta> /DMORPHO_TEST
setlocal
set "BITS=%~1"
set "OUT=%~2"
set "EXTRA=%~3"
rem A revisao entra no nome do arquivo (o mesmo numero de FILTER_REVISION em app/engine/morphocam.py).
rem Um programa de video com a camera aberta segura o arquivo antigo; com outro nome, a versao
rem nova instala e passa a valer sem precisar fechar esse programa. Mudou o filtro? Suba o numero.
set "REV=2"
set "VSDIR=C:\Program Files (x86)\Microsoft Visual Studio\2019\BuildTools\VC\Auxiliary\Build"
if not exist "%VSDIR%\vcvars%BITS%.bat" (
  echo Nao achei o Visual Studio 2019 Build Tools em "%VSDIR%".
  exit /b 1
)
call "%VSDIR%\vcvars%BITS%.bat" >nul || exit /b 1
set "OBJ=%OUT%\obj%BITS%"
if not exist "%OBJ%" mkdir "%OBJ%"
cd /d "%~dp0"
cl /nologo /c /O2 /Ob2 /Oi /Ot /GL /Gw /Gy /GF /GS- /GR- /MT /W3 /DWIN32 /DNDEBUG /D_WINDOWS /D_USRDLL %EXTRA% ^
   /Fo"%OBJ%\\" streams.cpp MorphoCameraFilter.cpp || exit /b 1
link /nologo /DLL /LTCG /OPT:REF /OPT:ICF /SUBSYSTEM:WINDOWS /SAFESEH:NO /DEF:MorphoCameraFilter.def ^
     /OUT:"%OUT%\MorphoCamera%BITS%-%REV%.dll" /IMPLIB:"%OBJ%\MorphoCamera%BITS%.lib" ^
     "%OBJ%\streams.obj" "%OBJ%\MorphoCameraFilter.obj" ^
     kernel32.lib user32.lib gdi32.lib advapi32.lib ole32.lib oleaut32.lib uuid.lib strmiids.lib winmm.lib || exit /b 1
