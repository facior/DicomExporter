@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo Tworzenie srodowiska wirtualnego...
    python -m venv .venv || goto :error
    ".venv\Scripts\python.exe" -m pip install --upgrade pip >nul
    echo Instalowanie zaleznosci...
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt || goto :error
)

start "" ".venv\Scripts\pythonw.exe" main.py %*
exit /b 0

:error
echo.
echo Nie udalo sie przygotowac srodowiska. Upewnij sie, ze Python 3.10+ jest zainstalowany.
pause
exit /b 1
