; ============================================================
; Telemetry Analysis Platform — NSIS Installer Script
; ============================================================
; Produces a Windows installer that:
;   1. Installs the PyInstaller-built exe + supporting files
;   2. Creates Desktop shortcuts:
;      - "Telemetry Analysis" (file picker / console mode)
;      - "Telemetry Dashboard" (web dashboard, auto-opens browser)
;   3. Creates Start Menu shortcuts + Uninstaller
;   4. Supports silent install: /S flag
;   5. Uninstaller preserves user data (telemetry.db, data/, results/)
; ============================================================

!include "MUI2.nsh"

; General
Name "Telemetry Analysis Platform"
OutFile "..\dist\TelemetryAnalysis_Setup.exe"
InstallDir "$PROGRAMFILES\TelemetryAnalysis"
InstallDirRegKey HKLM "Software\TelemetryAnalysis" "InstallDir"
RequestExecutionLevel admin

; Interface
!define MUI_ABORTWARNING
!define MUI_ICON "${NSISDIR}\Contrib\Graphics\Icons\modern-install.ico"
!define MUI_UNICON "${NSISDIR}\Contrib\Graphics\Icons\modern-uninstall.ico"

; Pages
!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_LICENSE "license.txt"
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH

; Uninstaller pages
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES

; Language
!insertmacro MUI_LANGUAGE "English"

; ============================================================
; Installer Section
; ============================================================
Section "Install"
    SetOutPath "$INSTDIR"

    ; Copy all files from the PyInstaller dist folder
    File /r "..\dist\telemetry_tool\*.*"

    ; Create data directories (if they don't exist)
    CreateDirectory "$INSTDIR\data"
    CreateDirectory "$INSTDIR\data\raw"
    CreateDirectory "$INSTDIR\results"

    ; Write uninstaller
    WriteUninstaller "$INSTDIR\Uninstall.exe"

    ; Write registry keys
    WriteRegStr HKLM "Software\TelemetryAnalysis" "InstallDir" "$INSTDIR"
    WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\TelemetryAnalysis" \
                     "DisplayName" "Telemetry Analysis Platform"
    WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\TelemetryAnalysis" \
                     "UninstallString" '"$INSTDIR\Uninstall.exe"'
    WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\TelemetryAnalysis" \
                     "InstallLocation" "$INSTDIR"
    WriteRegDWORD HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\TelemetryAnalysis" \
                      "NoModify" 1
    WriteRegDWORD HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\TelemetryAnalysis" \
                      "NoRepair" 1

    ; ---- Desktop Shortcuts ----

    ; Shortcut 1: Telemetry Analysis (console/file-picker mode)
    CreateShortCut "$DESKTOP\Telemetry Analysis.lnk" \
                   "$INSTDIR\telemetry_tool.exe" \
                   "" \
                   "$INSTDIR\telemetry_tool.exe" 0 \
                   SW_SHOWNORMAL "" \
                   "Run telemetry analysis on a CSV file"

    ; Shortcut 2: Telemetry Dashboard (web mode)
    CreateShortCut "$DESKTOP\Telemetry Dashboard.lnk" \
                   "$INSTDIR\telemetry_tool.exe" \
                   "--serve" \
                   "$INSTDIR\telemetry_tool.exe" 0 \
                   SW_SHOWNORMAL "" \
                   "Launch the telemetry web dashboard"

    ; ---- Start Menu ----
    CreateDirectory "$SMPROGRAMS\Telemetry Analysis"

    CreateShortCut "$SMPROGRAMS\Telemetry Analysis\Telemetry Analysis.lnk" \
                   "$INSTDIR\telemetry_tool.exe" \
                   "" "$INSTDIR\telemetry_tool.exe" 0

    CreateShortCut "$SMPROGRAMS\Telemetry Analysis\Telemetry Dashboard.lnk" \
                   "$INSTDIR\telemetry_tool.exe" \
                   "--serve" "$INSTDIR\telemetry_tool.exe" 0

    CreateShortCut "$SMPROGRAMS\Telemetry Analysis\Uninstall.lnk" \
                   "$INSTDIR\Uninstall.exe"
SectionEnd

; ============================================================
; Uninstaller Section
; ============================================================
Section "Uninstall"
    ; Remove program files (but NOT user data)
    Delete "$INSTDIR\telemetry_tool.exe"
    Delete "$INSTDIR\*.dll"
    Delete "$INSTDIR\*.pyd"
    Delete "$INSTDIR\Uninstall.exe"

    ; Remove internal directories (not data)
    RMDir /r "$INSTDIR\_internal"
    RMDir /r "$INSTDIR\web"
    RMDir /r "$INSTDIR\db"

    ; NOTE: We deliberately DO NOT delete:
    ;   $INSTDIR\telemetry.db
    ;   $INSTDIR\data\
    ;   $INSTDIR\results\
    ; These contain user data that should be preserved.

    ; Remove shortcuts
    Delete "$DESKTOP\Telemetry Analysis.lnk"
    Delete "$DESKTOP\Telemetry Dashboard.lnk"
    Delete "$SMPROGRAMS\Telemetry Analysis\Telemetry Analysis.lnk"
    Delete "$SMPROGRAMS\Telemetry Analysis\Telemetry Dashboard.lnk"
    Delete "$SMPROGRAMS\Telemetry Analysis\Uninstall.lnk"
    RMDir "$SMPROGRAMS\Telemetry Analysis"

    ; Remove registry keys
    DeleteRegKey HKLM "Software\TelemetryAnalysis"
    DeleteRegKey HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\TelemetryAnalysis"

    ; Try to remove install dir (will only succeed if empty/no user data)
    RMDir "$INSTDIR"
SectionEnd
