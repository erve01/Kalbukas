; Inno Setup script for Kalbukas.
;
; Build (after PyInstaller has produced dist\Kalbukas[-GPU]):
;   ISCC packaging\installer.iss          -> CPU installer
;   ISCC /DGPU packaging\installer.iss    -> GPU installer (CUDA bundled)

#ifdef GPU
  #define BaseName "Kalbukas-GPU"
  #define Suffix "-GPU"
#else
  #define BaseName "Kalbukas"
  #define Suffix ""
#endif
#define DistDir "..\dist\" + BaseName
#define AppVersion GetVersionNumbersString(DistDir + "\" + BaseName + ".exe")

[Setup]
AppId={{D7C2A6F4-3B8E-4C59-A1D2-9F6E0B7C4A31}
AppName=Kalbukas
AppVersion={#AppVersion}
AppPublisher=Ernestas
DefaultDirName={autopf}\Kalbukas
DefaultGroupName=Kalbukas
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
UninstallDisplayIcon={app}\{#BaseName}.exe
OutputDir=..\dist
OutputBaseFilename=Kalbukas-Setup-{#AppVersion}{#Suffix}
SetupIconFile=..\assets\icon.ico
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=yes

[Tasks]
Name: "startup"; Description: "Start Kalbukas when I sign in to Windows"
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; Flags: unchecked

[Files]
Source: "{#DistDir}\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion

[Icons]
Name: "{group}\Kalbukas"; Filename: "{app}\{#BaseName}.exe"
Name: "{autodesktop}\Kalbukas"; Filename: "{app}\{#BaseName}.exe"; Tasks: desktopicon
Name: "{userstartup}\Kalbukas"; Filename: "{app}\{#BaseName}.exe"; Tasks: startup

[Run]
Filename: "{app}\{#BaseName}.exe"; Description: "Launch Kalbukas now"; Flags: nowait postinstall skipifsilent

; user data (settings, history, models) in {localappdata}\Kalbukas is
; deliberately kept on uninstall — reinstalling picks it right back up
