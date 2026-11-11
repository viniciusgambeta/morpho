; Instalador do Morpho (Inno Setup 6). Gerado por packaging\make_installer.py, que chama:
;
;   ISCC.exe /DSource="<pasta do pacote>" /DOutput="<pasta de saida>" /DGpuName="<placa de video daqui>" morpho.iss
;
; "Source" e a pasta montada por packaging\build.py. O instalador nao pede permissao de
; administrador: instala para o usuario atual, em AppData\Local\Programs\Morpho.
; Como o pacote tem varios GB, o resultado sao o MorphoSetup.exe e arquivos .bin ao lado
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
DiskSliceSize=2000000000
CloseApplications=yes
RestartApplications=no
LicenseFile=..\licencas\LEIA-ME.txt
InfoBeforeFile=antes-de-instalar.txt

[Languages]
Name: "ptbr"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"

[Tasks]
Name: "desktopicon"; Description: "Criar um atalho na área de trabalho"; GroupDescription: "Atalhos:"

[Files]
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
