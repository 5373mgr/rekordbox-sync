; Inno Setup script for rekordbox-sync.
; Expects the PyInstaller executables to already exist in ..\..\dist\
; (rekordbox-sync.exe, rekordbox-sync-gui.exe) before compiling.
; Version is passed in at compile time: iscc /DMyAppVersion=0.1.1 setup.iss
; (falls back to 0.0.0-dev if not provided, e.g. for local test compiles).

#ifndef MyAppVersion
  #define MyAppVersion "0.0.0-dev"
#endif

#define MyAppName "rekordbox-sync"
#define MyAppPublisher "5373mgr"
#define MyAppURL "https://github.com/5373mgr/rekordbox-sync"
#define DistDir "..\..\dist"
#define RepoRoot "..\.."

[Setup]
AppId={{6E2A6C0B-6E4D-4E8F-9C36-5F1C6E7B7E2A}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputBaseFilename=rekordbox-sync-setup
OutputDir={#RepoRoot}\dist_installer
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible
; No code signing certificate yet -- see DESIGN.md "known risks".

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "addtopath"; Description: "Add {#MyAppName} to PATH (lets you run 'rekordbox-sync' from any terminal)"; Flags: unchecked

[Files]
Source: "{#DistDir}\rekordbox-sync.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#DistDir}\rekordbox-sync-gui.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#RepoRoot}\config.example.yaml"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#RepoRoot}\README.md"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\rekordbox-sync"; Filename: "{app}\rekordbox-sync-gui.exe"
Name: "{group}\Uninstall rekordbox-sync"; Filename: "{uninstallexe}"

[Registry]
; Machine-wide PATH, matching the admin-mode Program Files install above.
Root: HKLM; Subkey: "SYSTEM\CurrentControlSet\Control\Session Manager\Environment"; \
    ValueType: expandsz; ValueName: "Path"; ValueData: "{olddata};{app}"; \
    Tasks: addtopath; Check: NeedsAddPath(ExpandConstant('{app}'))

[Code]
function NeedsAddPath(Param: string): boolean;
var
  OrigPath: string;
begin
  if not RegQueryStringValue(
    HKLM, 'SYSTEM\CurrentControlSet\Control\Session Manager\Environment', 'Path', OrigPath)
  then
  begin
    Result := True;
    exit;
  end;
  Result := Pos(';' + Param + ';', ';' + OrigPath + ';') = 0;
end;

[Run]
Filename: "{app}\rekordbox-sync-gui.exe"; Description: "Launch rekordbox-sync"; Flags: postinstall nowait skipifsilent
