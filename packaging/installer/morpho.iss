; Instalador do Morpho (Inno Setup 6). Gerado por packaging\make_installer.py, que chama:
;
;   ISCC.exe /DSource="<pasta do pacote>" /DOutput="<pasta de saida>" /DGpuName="<placa de video daqui>" morpho.iss
;
; "Source" e a pasta montada por packaging\build.py. O instalador nao pede permissao de
; administrador: instala para o usuario atual, em AppData\Local\Programs\Morpho.
; Como o pacote tem varios GB, o resultado sao o MorphoSetup.exe e arquivos .bin de 256 MB ao lado
; dele (um executavel do Windows nao pode passar de 4 GB); eles andam juntos.
;
; Os modelos ja otimizados (engine\models\trt_cache) so servem para a placa de video em que
; foram criados. Com GpuName definido, eles so sao instalados num computador com essa mesma
; placa; nos outros, o app otimiza os modelos na primeira abertura.

#ifndef Source
  #define Source "C:\Users\vinic\dlc-lab\dist\Morpho"
#endif
#ifndef Output
  #define Output "C:\Users\vinic\dlc-lab\dist\instalador"
#endif
#define Version "1.0.0"
; Quantos quadros tem a animacao do ganso (GooseFrames) e o intervalo entre eles (GooseInterval).
; As imagens da pasta "arte" sao geradas por packaging\make_installer_art.py.
#include "arte\quadros.iss"

[Setup]
AppId={{8B3F2C54-6A1D-4E0B-9C77-2F5D1A9E4B10}
AppName=Morpho
AppVersion={#Version}
AppVerName=Morpho {#Version}
AppPublisher=Morpho
DefaultDirName={localappdata}\Programs\Morpho
DisableProgramGroupPage=yes
DisableDirPage=auto
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.17763
WizardStyle=modern
; A tela de boas-vindas mostra a faixa com o ganso; nas outras ele fica no canto, animado.
DisableWelcomePage=no
WizardImageFile=arte\lateral.bmp
WizardSmallImageFile=arte\ganso-00.bmp
SetupIconFile=..\launcher\morpho.ico
UninstallDisplayIcon={app}\Morpho.exe
UninstallDisplayName=Morpho
OutputDir={#Output}
OutputBaseFilename=MorphoSetup
Compression=lzma2/normal
LZMANumBlockThreads=6
LZMAUseSeparateProcess=yes
SolidCompression=no
DiskSpanning=yes
DiskSliceSize=268435456
CloseApplications=yes
RestartApplications=no
LicenseFile=..\licencas\LEIA-ME.txt
InfoBeforeFile=antes-de-instalar.txt

[Languages]
Name: "ptbr"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"

[Tasks]
Name: "desktopicon"; Description: "Criar um atalho na área de trabalho"; GroupDescription: "Atalhos:"

[Files]
; Os quadros da animacao do ganso: nao sao instalados, o proprio instalador os usa. Ficam no
; comeco para estarem no primeiro arquivo .bin.
Source: "arte\ganso-*.bmp"; Flags: dontcopy
Source: "{#Source}\*"; DestDir: "{app}"; Excludes: "\engine\models\trt_cache\*"; Flags: recursesubdirs createallsubdirs ignoreversion
#ifdef GpuName
Source: "{#Source}\engine\models\trt_cache\*"; DestDir: "{app}\engine\models\trt_cache"; Check: SameGpu; Flags: ignoreversion skipifsourcedoesntexist
#endif

[Icons]
Name: "{autoprograms}\Morpho"; Filename: "{app}\Morpho.exe"; WorkingDir: "{app}"
Name: "{autodesktop}\Morpho"; Filename: "{app}\Morpho.exe"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\Morpho.exe"; Description: "Abrir o Morpho agora"; Flags: nowait postinstall skipifsilent

[UninstallRun]
; Tira a camera virtual "Morpho Camera" do Windows antes de apagar os arquivos dela.
Filename: "{app}\Morpho.exe"; Parameters: "--remove-virtual-camera"; Flags: runhidden waituntilterminated; RunOnceId: "RemoveCamera"

[UninstallDelete]
; O que o app cria depois de instalado: modelos otimizados para a placa de video e arquivos compilados do Python.
Type: filesandordirs; Name: "{app}\engine"
Type: filesandordirs; Name: "{app}\python"
Type: filesandordirs; Name: "{app}\app"
Type: dirifempty; Name: "{app}"

[Code]
// O ganso do canto das telas pisca e se mexe: um temporizador troca a imagem pelo quadro
// seguinte da animacao "Parado". Se algo falhar, fica a imagem parada.
var
  GooseBitmaps: array of TBitmap;
  GooseIndex: Integer;
  GooseTimer: Longword;

function SetTimer(hWnd, nIDEvent, uElapse, lpTimerFunc: Longword): Longword;
external 'SetTimer@user32.dll stdcall';

function KillTimer(hWnd, nIDEvent: Longword): Bool;
external 'KillTimer@user32.dll stdcall';

procedure GooseTick(Arg1, Arg2, Arg3, Arg4: Longword);
begin
  if (WizardForm = nil) or (GetArrayLength(GooseBitmaps) = 0) then
    Exit;
  GooseIndex := (GooseIndex + 1) mod GetArrayLength(GooseBitmaps);
  WizardForm.WizardSmallBitmapImage.Bitmap := GooseBitmaps[GooseIndex];
end;

procedure InitializeWizard;
var
  Index: Integer;
  Name: String;
begin
  if WizardSilent then
    Exit;
  try
    SetArrayLength(GooseBitmaps, {#GooseFrames});
    for Index := 0 to {#GooseFrames} - 1 do
    begin
      Name := Format('ganso-%.2d.bmp', [Index]);
      ExtractTemporaryFile(Name);
      GooseBitmaps[Index] := TBitmap.Create;
      GooseBitmaps[Index].LoadFromFile(ExpandConstant('{tmp}\' + Name));
    end;
    GooseTimer := SetTimer(0, 0, {#GooseInterval}, CreateCallback(@GooseTick));
  except
    SetArrayLength(GooseBitmaps, 0);
  end;
end;

procedure DeinitializeSetup;
begin
  if GooseTimer <> 0 then
    KillTimer(0, GooseTimer);
  GooseTimer := 0;
end;

#ifdef GpuName
// A placa de video deste computador e a mesma em que os modelos foram otimizados?
function SameGpu: Boolean;
var
  Locator, Services, Items, Item: Variant;
  Index: Integer;
  Found: String;
begin
  Result := False;
  try
    Locator := CreateOleObject('WbemScripting.SWbemLocator');
    Services := Locator.ConnectServer('.', 'root\CIMV2');
    Items := Services.ExecQuery('SELECT Name FROM Win32_VideoController');
    for Index := 0 to Items.Count - 1 do
    begin
      Item := Items.ItemIndex(Index);
      Found := Item.Name;
      if CompareText(Trim(Found), '{#GpuName}') = 0 then
        Result := True;
    end;
  except
    Result := False;
  end;
end;
#endif
