; =========================================================
;  BackupTool – Inno Setup Script
;  يُنشئ مثبّت احترافي لـ BackupTool.exe
;  متطلب: Inno Setup 6.x  (https://jrsoftware.org/isinfo.php)
;  كيفية الاستخدام:
;    1. ابنِ التطبيق أولاً بتشغيل build.bat
;    2. افتح هذا الملف بـ Inno Setup Compiler وانقر Compile
;    3. ستجد المثبّت في مجلد  Output\BackupToolSetup.exe
; =========================================================

#define AppName      "BackupTool"
#define AppVersion   "2.0"
#define AppPublisher "Mohammed Eydan"
#define AppURL       ""
#define AppExeName   "BackupTool.exe"
#define AppDescription "أداة النسخ الاحتياطي الاحترافية"

[Setup]
; ─── معلومات التطبيق الأساسية ───────────────────────────────────────────────
AppId={{E7A1C3F8-4B2D-4E9A-8F0D-1A2B3C4D5E6F}}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppURL}
AppSupportURL={#AppURL}
AppUpdatesURL={#AppURL}
AppComments={#AppDescription}

; ─── مسار التثبيت ────────────────────────────────────────────────────────────
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
AllowNoIcons=yes

; ─── ملف المخرجات ────────────────────────────────────────────────────────────
OutputDir=Output
OutputBaseFilename=BackupToolSetup-v{#AppVersion}

; ─── ضغط الملفات (LZMA أفضل ضغط) ───────────────────────────────────────────
Compression=lzma2/ultra64
SolidCompression=yes
LZMAUseSeparateProcess=yes

; ─── واجهة المثبّت ───────────────────────────────────────────────────────────
WizardStyle=modern
WizardResizable=no
SetupIconFile=icon.ico

; ─── الصلاحيات ───────────────────────────────────────────────────────────────
; يُتيح التثبيت للمستخدم الحالي دون الحاجة لصلاحيات Admin
; غيّره إلى "admin" إذا أردت تثبيتاً على مستوى النظام
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog

; ─── إصدار Windows المدعوم ───────────────────────────────────────────────────
MinVersion=10.0

; ─── Uninstaller ─────────────────────────────────────────────────────────────
UninstallDisplayName={#AppName}
UninstallDisplayIcon={app}\{#AppExeName}
Uninstallable=yes
CreateUninstallRegKey=yes

; ─── Restart ─────────────────────────────────────────────────────────────────
; لا يحتاج التطبيق إعادة تشغيل النظام عادةً
RestartIfNeededByRun=no


; =============================================================
[Languages]
Name: "arabic"; MessagesFile: "compiler:Languages\Arabic.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

; =============================================================
[Tasks]
Name: "desktopicon";    Description: "إنشاء اختصار على سطح المكتب";  GroupDescription: "اختصارات:"; Flags: unchecked
Name: "startupicon";    Description: "تشغيل مع بدء Windows (للجدولة)"; GroupDescription: "اختصارات:"; Flags: unchecked

; =============================================================
[Files]
; ── الملف التنفيذي الرئيسي (مخرج PyInstaller) ──────────────────────────────
Source: "dist\BackupTool\*";  DestDir: "{app}";  Flags: ignoreversion recursesubdirs createallsubdirs

; ── الأيقونة ────────────────────────────────────────────────────────────────
Source: "icon.ico";            DestDir: "{app}";  Flags: ignoreversion

; ── ملف الإعدادات النموذجي ──────────────────────────────────────────────────
Source: "config.sample.yaml";  DestDir: "{app}";  Flags: ignoreversion

; ── README (اختياري) ─────────────────────────────────────────────────────────
Source: "README.md";           DestDir: "{app}";  Flags: ignoreversion isreadme

; =============================================================
[Dirs]
; إنشاء مجلد اللوجات الافتراضي مع الصلاحيات الكاملة للمستخدم الحالي
Name: "{commonappdata}\BackupTool\logs"; Permissions: users-full

; =============================================================
[Icons]
; اختصار قائمة ابدأ
Name: "{group}\{#AppName}";          Filename: "{app}\{#AppExeName}"; Comment: {#AppDescription}
Name: "{group}\إلغاء التثبيت";       Filename: "{uninstallexe}"

; اختصار سطح المكتب (اختياري)
Name: "{autodesktop}\{#AppName}";    Filename: "{app}\{#AppExeName}"; Tasks: desktopicon

; =============================================================
[Registry]
; تسجيل برنامج في قائمة "البرامج المثبّتة" لـ Windows Add/Remove
Root: HKCU; Subkey: "Software\{#AppPublisher}\{#AppName}"; ValueType: string; ValueName: "InstallPath"; ValueData: "{app}"; Flags: uninsdeletekey

; =============================================================
[Run]
; فتح التطبيق بعد إتمام التثبيت (اختياري)
Filename: "{app}\{#AppExeName}"; Description: "تشغيل {#AppName} الآن"; Flags: nowait postinstall skipifsilent

; =============================================================
[UninstallDelete]
; حذف ملف الإعدادات المحلي (اختياري – علّق إذا أردت الإبقاء عليه)
; Type: files; Name: "{app}\config.yaml"


