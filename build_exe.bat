@echo off
rem Builds dist\checker.exe (one file, no Python needed to run it).
rem PyInstaller is only needed here, for building; the checker itself uses the standard library only.
cd /d "%~dp0"
.venv\Scripts\python.exe -m pip install --quiet pyinstaller || exit /b 1
.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean --onefile --windowed --name checker ^
    --icon "%~dp0checker\icon.ico" --add-data "%~dp0checker\icon.ico;checker" ^
    --add-data "%~dp0checker\*.vrs;checker" --add-data "%~dp0checker\eng.vrs.LICENSE;checker" ^
    --workpath build --distpath dist --specpath build checker_app.py || exit /b 1
echo.
echo Done: dist\checker.exe
