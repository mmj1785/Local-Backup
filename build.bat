@echo off
REM =========================================================
REM  build.bat – يبني BackupTool.exe باستخدام PyInstaller
REM  المتطلبات: Python 3.12 + PyQt6 + pyyaml + pyinstaller
REM  شغّله مرة واحدة ثم خذ dist\BackupTool\BackupTool.exe
REM =========================================================

echo [1/3] تثبيت المتطلبات...
py -3.12 -m pip install -r requirements.txt --quiet

echo [2/3] بناء الملف التنفيذي...
py -3.12 -m PyInstaller ^
    --noconfirm ^
    --onedir ^
    --windowed ^
    --name "BackupTool" ^
    --icon "icon.ico" ^
    --add-data "icon.png;." ^
    --hidden-import "backup_tool" ^
    --hidden-import "yaml" ^
    --hidden-import "PyQt6.sip" ^
    --hidden-import "PyQt6.QtCore" ^
    --hidden-import "PyQt6.QtGui" ^
    --hidden-import "PyQt6.QtWidgets" ^
    --exclude-module "tkinter" ^
    --exclude-module "matplotlib" ^
    --exclude-module "numpy" ^
    --exclude-module "pandas" ^
    --exclude-module "scipy" ^
    --exclude-module "PIL" ^
    --exclude-module "PySide6" ^
    --exclude-module "PySide2" ^
    --exclude-module "PyQt6.QtWebEngineCore" ^
    --exclude-module "PyQt6.QtWebEngineWidgets" ^
    --exclude-module "PyQt6.QtQuick" ^
    --exclude-module "PyQt6.QtQml" ^
    --exclude-module "PyQt6.QtMultimedia" ^
    --exclude-module "PyQt6.QtPdf" ^
    --exclude-module "PyQt6.QtDesigner" ^
    --exclude-module "PyQt6.QtBluetooth" ^
    --exclude-module "PyQt5" ^
    gui_backup_tool.py

echo [3/3] اكتمل البناء.
if exist "dist\BackupTool\BackupTool.exe" (
    echo.
    echo ============================================
    echo  النتيجة: dist\BackupTool\BackupTool.exe
    echo ============================================
) else (
    echo خطأ: لم يُنشأ الملف التنفيذي – راجع الأخطاء أعلاه.
)
pause
