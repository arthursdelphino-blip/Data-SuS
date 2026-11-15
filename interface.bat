@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo.
    echo  O Data-SUS ainda nao foi instalado neste computador.
    echo  Primeiro de dois cliques em instalar.bat e depois abra este arquivo de novo.
    echo.
    pause
    exit /b 1
)
echo Abrindo a interface do Data-SUS no navegador...
echo (feche esta janela para encerrar o programa)
"%~dp0.venv\Scripts\python.exe" -m streamlit run "%~dp0app.py"
if errorlevel 1 (
    echo.
    echo  [!] O programa parou com um erro. Veja a mensagem acima.
    echo      Se o erro persistir, de dois cliques em instalar.bat e tente de novo.
    echo.
    pause
)
