; Inno Setup recipe for the KAPITA installer. Build both steps with scripts\build_installer.ps1,
; which freezes dist\KAPITA first and passes the version from financial_app.__version__.
; Installs per user (no administrator rights); the data in %LOCALAPPDATA%\KAPITA is never touched.

#ifndef AppVersion
  #error Pass /DAppVersion=x.y.z; scripts\build_installer.ps1 does
#endif

[Setup]
; Never change the AppId: it is how a new version finds and upgrades the installed one
AppId={{331C7EDD-40F2-491E-8618-9192B41C2DED}
AppName=KAPITA
AppVersion={#AppVersion}
AppVerName=KAPITA {#AppVersion}
AppPublisher=Gerruppa
VersionInfoVersion={#AppVersion}
DefaultDirName={autopf}\KAPITA
DefaultGroupName=KAPITA
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\dist
OutputBaseFilename=KAPITA-{#AppVersion}-setup
SetupIconFile=..\src\financial_app\ui\assets\kapita.ico
UninstallDisplayIcon={app}\KAPITA.exe
WizardStyle=modern
Compression=lzma2
SolidCompression=yes
CloseApplications=yes

[Languages]
Name: "polish"; MessagesFile: "compiler:Languages\Polish.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[InstallDelete]
; An upgrade replaces the bundled libraries whole, so no file of an older version lingers
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "..\dist\KAPITA\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\KAPITA"; Filename: "{app}\KAPITA.exe"
Name: "{autodesktop}\KAPITA"; Filename: "{app}\KAPITA.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\KAPITA.exe"; Description: "{cm:LaunchProgram,KAPITA}"; Flags: nowait postinstall skipifsilent
; The in-app update runs the installer silently (/SILENT), which skips the entry above: start the new version here
Filename: "{app}\KAPITA.exe"; Flags: nowait; Check: WizardSilent
