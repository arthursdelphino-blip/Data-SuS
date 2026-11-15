@echo off
cd /d "%~dp0"
echo Abrindo a interface DATASUS para Pesquisa no navegador...
echo (feche esta janela para encerrar)
"%~dp0.venv\Scripts\python.exe" -m streamlit run "%~dp0app.py"
