@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Instalador do Data-SUS
echo.
echo  ============================================
echo   Instalador do Data-SUS
echo  ============================================
echo.

rem --- 1. Procura o Python (3.11 ou mais novo) ---
set "PY="
py -3.12 -c "import sys" >nul 2>nul && set "PY=py -3.12"
if not defined PY py -3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>nul && set "PY=py -3"
if not defined PY python -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>nul && set "PY=python"

if not defined PY (
    echo  [!] O Python nao foi encontrado neste computador.
    echo.
    echo  Para resolver:
    echo   1. Vai abrir a pagina de download do Python.
    echo   2. Baixe e abra o instalador.
    echo   3. Na primeira tela, MARQUE a caixa "Add python.exe to PATH".
    echo   4. Clique em "Install Now" e espere terminar.
    echo   5. Depois, de dois cliques neste instalar.bat de novo.
    echo.
    pause
    start "" "https://www.python.org/downloads/"
    exit /b 1
)
echo  [1/3] Python encontrado.

rem --- 2. Cria o ambiente do programa (so na primeira vez) ---
if not exist ".venv\Scripts\python.exe" (
    echo  [2/3] Preparando o ambiente do programa...
    %PY% -m venv .venv
    if errorlevel 1 (
        echo.
        echo  [!] Nao foi possivel criar o ambiente. Tente de novo.
        pause
        exit /b 1
    )
) else (
    echo  [2/3] Ambiente ja existe.
)

rem --- 3. Instala as bibliotecas ---
echo  [3/3] Baixando e instalando as bibliotecas (pode levar de 3 a 10 minutos)...
echo.
".venv\Scripts\python.exe" -m pip install --upgrade pip --quiet --disable-pip-version-check
".venv\Scripts\python.exe" -m pip install -r requirements.txt --disable-pip-version-check
if errorlevel 1 (
    echo.
    echo  [!] A instalacao falhou. Confira se o computador esta conectado a internet
    echo      e de dois cliques em instalar.bat de novo.
    pause
    exit /b 1
)

echo.
echo  ============================================
echo   Pronto! O Data-SUS esta instalado.
echo   Para usar, de dois cliques em interface.bat
echo  ============================================
echo.
choice /c SN /m " Quer abrir o programa agora"
if errorlevel 2 exit /b 0
call "%~dp0interface.bat"
