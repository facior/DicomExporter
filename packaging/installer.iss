; Instalator DICOM Exporter (Inno Setup 6). Budowanie: python packaging\build.py --installer

#ifndef AppVersion
  #define AppVersion "1.0.0"
#endif
#define AppName "DICOM Exporter"
#define AppExe "DicomExporter.exe"

[Setup]
AppId={{8C5D3E1A-4B7F-4E2D-9A61-2F0B9C7D5E13}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=Łukasz Kubieniec
AppPublisherURL=https://github.com/facior
AppSupportURL=https://github.com/facior/DicomExporter/issues
AppUpdatesURL=https://github.com/facior/DicomExporter/releases
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
; Instalacja bez uprawnień administratora (dla bieżącego użytkownika) lub – po wyborze – dla wszystkich
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
LicenseFile=..\LICENSE
OutputDir=..\dist
OutputBaseFilename=DicomExporter-{#AppVersion}-setup
SetupIconFile=app.ico
UninstallDisplayIcon={app}\{#AppExe}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
ChangesAssociations=yes

[Languages]
Name: "polish"; MessagesFile: "compiler:Languages\Polish.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[CustomMessages]
polish.ShellOpen=Otwórz w DICOM Exporter
english.ShellOpen=Open in DICOM Exporter
polish.ShellConvert=Konwertuj do PNG (obok pliku)
english.ShellConvert=Convert to PNG (next to the file)
polish.ContextMenu=Dodaj polecenia do menu kontekstowego Eksploratora (pliki .dcm i foldery)
english.ContextMenu=Add commands to the Explorer context menu (.dcm files and folders)

[Tasks]
Name: "contextmenu"; Description: "{cm:ContextMenu}"
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "..\dist\DicomExporter\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Registry]
; HKA = HKCU przy instalacji dla użytkownika, HKLM przy instalacji dla wszystkich.
; Pliki .dcm i .dicom
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.dcm\shell\DicomExporter.Open"; ValueType: string; ValueName: ""; ValueData: "{cm:ShellOpen}"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.dcm\shell\DicomExporter.Open"; ValueType: string; ValueName: "Icon"; ValueData: """{app}\{#AppExe}"""; Tasks: contextmenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.dcm\shell\DicomExporter.Open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExe}"" ""%1"""; Tasks: contextmenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.dcm\shell\DicomExporter.Convert"; ValueType: string; ValueName: ""; ValueData: "{cm:ShellConvert}"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.dcm\shell\DicomExporter.Convert"; ValueType: string; ValueName: "Icon"; ValueData: """{app}\{#AppExe}"""; Tasks: contextmenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.dcm\shell\DicomExporter.Convert\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExe}"" --quick-png ""%1"""; Tasks: contextmenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.dicom\shell\DicomExporter.Open"; ValueType: string; ValueName: ""; ValueData: "{cm:ShellOpen}"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.dicom\shell\DicomExporter.Open"; ValueType: string; ValueName: "Icon"; ValueData: """{app}\{#AppExe}"""; Tasks: contextmenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.dicom\shell\DicomExporter.Open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExe}"" ""%1"""; Tasks: contextmenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.dicom\shell\DicomExporter.Convert"; ValueType: string; ValueName: ""; ValueData: "{cm:ShellConvert}"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.dicom\shell\DicomExporter.Convert"; ValueType: string; ValueName: "Icon"; ValueData: """{app}\{#AppExe}"""; Tasks: contextmenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.dicom\shell\DicomExporter.Convert\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExe}"" --quick-png ""%1"""; Tasks: contextmenu
; Foldery (np. płyty z badaniami)
Root: HKA; Subkey: "Software\Classes\Directory\shell\DicomExporter.Open"; ValueType: string; ValueName: ""; ValueData: "{cm:ShellOpen}"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKA; Subkey: "Software\Classes\Directory\shell\DicomExporter.Open"; ValueType: string; ValueName: "Icon"; ValueData: """{app}\{#AppExe}"""; Tasks: contextmenu
Root: HKA; Subkey: "Software\Classes\Directory\shell\DicomExporter.Open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExe}"" ""%1"""; Tasks: contextmenu
Root: HKA; Subkey: "Software\Classes\Directory\shell\DicomExporter.Convert"; ValueType: string; ValueName: ""; ValueData: "{cm:ShellConvert}"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKA; Subkey: "Software\Classes\Directory\shell\DicomExporter.Convert"; ValueType: string; ValueName: "Icon"; ValueData: """{app}\{#AppExe}"""; Tasks: contextmenu
Root: HKA; Subkey: "Software\Classes\Directory\shell\DicomExporter.Convert\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExe}"" --quick-png ""%1"""; Tasks: contextmenu

[Run]
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent
