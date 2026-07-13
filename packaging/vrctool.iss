#define MyAppVersion GetEnv("VRCTOOL_VERSION")
#if MyAppVersion == ""
  #error VRCTOOL_VERSION environment variable is required
#endif

#define MyAppName "vrctool"
#define MyAppPublisher "danglong0313"
#define MyAppURL "https://github.com/danglong0313/vrctool"
#define MyAppExeName "vrctool.exe"

[Setup]
AppId={{92E1B03A-88D5-4BB7-92F1-7B1E839A9B42}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}/issues
AppUpdatesURL={#MyAppURL}/releases
DefaultDirName={localappdata}\Programs\vrctool
DefaultGroupName=vrctool
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir=..\dist
OutputBaseFilename=vrctool-setup-{#MyAppVersion}
SetupIconFile=..\build\logo.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
LicenseFile=..\LICENSE
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ShowLanguageDialog=auto
CloseApplications=yes
RestartApplications=no
AppMutex=Local\vrctool-single-instance
ChangesEnvironment=yes

[Languages]
Name: "chinesesimp"; MessagesFile: "languages\ChineseSimplified.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalShortcuts}"; Flags: unchecked

[CustomMessages]
chinesesimp.CreateDesktopIcon=创建桌面快捷方式
chinesesimp.AdditionalShortcuts=附加快捷方式
chinesesimp.UninstallShortcut=卸载 vrctool
chinesesimp.LaunchApp=启动 vrctool
english.CreateDesktopIcon=Create a desktop shortcut
english.AdditionalShortcuts=Additional shortcuts
english.UninstallShortcut=Uninstall vrctool
english.LaunchApp=Launch vrctool

[Files]
Source: "..\build\package\vrctool_v{#MyAppVersion}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\third_party\presentmon\PresentMon.exe"; DestDir: "{app}\tools"; DestName: "PresentMon.exe"; Flags: ignoreversion
Source: "..\third_party\presentmon\LICENSE.txt"; DestDir: "{app}\licenses"; DestName: "PresentMon-LICENSE.txt"; Flags: ignoreversion

[InstallDelete]
Type: filesandordirs; Name: "{app}\_internal"

[Icons]
Name: "{group}\vrctool"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"
Name: "{group}\{cm:UninstallShortcut}"; Filename: "{uninstallexe}"; WorkingDir: "{app}"
Name: "{autodesktop}\vrctool"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; Description: "{cm:LaunchApp}"; Flags: nowait postinstall skipifsilent; Check: ShouldLaunch
Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; Flags: nowait skipifnotsilent; Check: ShouldLaunch

[Code]
function HasCommandLineParameter(Name: String): Boolean;
var
  Index: Integer;
begin
  Result := False;
  for Index := 1 to ParamCount do
    if Lowercase(ParamStr(Index)) = Lowercase(Name) then
    begin
      Result := True;
      Exit;
    end;
end;

function ShouldLaunch: Boolean;
begin
  Result := not HasCommandLineParameter('/nolaunch');
end;

function NormalizePathEntry(Value: String): String;
begin
  Result := Trim(Value);
  if (Length(Result) >= 2) and (Result[1] = '"') and
     (Result[Length(Result)] = '"') then
    Result := Copy(Result, 2, Length(Result) - 2);
  while (Length(Result) > 3) and (Result[Length(Result)] = '\') do
    Delete(Result, Length(Result), 1);
  Result := Lowercase(Result);
end;

procedure TakePathPart(var Remaining: String; var Part: String);
var
  Separator: Integer;
begin
  Separator := Pos(';', Remaining);
  if Separator = 0 then
  begin
    Part := Remaining;
    Remaining := '';
  end
  else
  begin
    Part := Copy(Remaining, 1, Separator - 1);
    Delete(Remaining, 1, Separator);
  end;
end;

function ContainsPathEntry(PathValue, Entry: String): Boolean;
var
  Remaining: String;
  Part: String;
  Target: String;
begin
  Result := False;
  Remaining := PathValue;
  Target := NormalizePathEntry(Entry);
  while Remaining <> '' do
  begin
    TakePathPart(Remaining, Part);
    if NormalizePathEntry(Part) = Target then
    begin
      Result := True;
      Exit;
    end;
  end;
end;

function RemovePathEntry(PathValue, Entry: String): String;
var
  Remaining: String;
  Part: String;
  Target: String;
  Suffix: String;
begin
  if NormalizePathEntry(PathValue) = NormalizePathEntry(Entry) then
  begin
    Result := '';
    Exit;
  end;
  Suffix := ';' + Entry;
  if (Length(PathValue) >= Length(Suffix)) and
     (Lowercase(Copy(PathValue, Length(PathValue) - Length(Suffix) + 1,
       Length(Suffix))) = Lowercase(Suffix)) then
  begin
    Result := Copy(PathValue, 1, Length(PathValue) - Length(Suffix));
    Exit;
  end;
  Result := '';
  Remaining := PathValue;
  Target := NormalizePathEntry(Entry);
  while Remaining <> '' do
  begin
    TakePathPart(Remaining, Part);
    Part := Trim(Part);
    if (Part <> '') and (NormalizePathEntry(Part) <> Target) then
    begin
      if Result <> '' then
        Result := Result + ';';
      Result := Result + Part;
    end;
  end;
end;

procedure AddAppToUserPath;
var
  PathValue: String;
  AppDir: String;
begin
  AppDir := ExpandConstant('{app}');
  if not RegQueryStringValue(HKCU, 'Environment', 'Path', PathValue) then
    PathValue := '';
  if ContainsPathEntry(PathValue, AppDir) then
    Exit;
  if PathValue = '' then
    PathValue := AppDir
  else
    PathValue := PathValue + ';' + AppDir;
  if not RegWriteStringValue(HKCU, 'Environment', 'Path', PathValue) then
    RaiseException('Unable to add vrctool to the user PATH.');
end;

procedure RemoveAppFromUserPath;
var
  PathValue: String;
  NewPathValue: String;
begin
  if not RegQueryStringValue(HKCU, 'Environment', 'Path', PathValue) then
    Exit;
  NewPathValue := RemovePathEntry(PathValue, ExpandConstant('{app}'));
  if NewPathValue = PathValue then
    Exit;
  if NewPathValue = '' then
    RegDeleteValue(HKCU, 'Environment', 'Path')
  else
    RegWriteStringValue(HKCU, 'Environment', 'Path', NewPathValue);
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
    AddAppToUserPath;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usUninstall then
    RemoveAppFromUserPath;
end;
