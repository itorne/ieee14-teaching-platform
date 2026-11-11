@echo off
REM Inicia a plataforma. Na primeira vez cria o ambiente e instala as dependencias.
cd /d "%~dp0"
if exist venv\Scripts\python.exe goto run
echo Primeira execucao: instalando a plataforma. Isso leva alguns minutos e precisa de internet.
py -3.13 -m venv venv 2>nul
if not exist venv\Scripts\python.exe python -m venv venv
if not exist venv\Scripts\python.exe goto nopython
venv\Scripts\python.exe -m pip install --upgrade pip
venv\Scripts\python.exe -m pip install -r requirements.txt
if errorlevel 1 goto failinstall
:run
echo Abrindo a plataforma no navegador em http://localhost:8501
echo Para encerrar, feche esta janela.
start "" cmd /c "timeout /t 6 >nul & start http://localhost:8501"
venv\Scripts\python.exe -m streamlit run app.py
pause
exit /b 0
:nopython
echo Python nao encontrado. Instale o Python 3.13 em https://www.python.org marcando a opcao Add python.exe to PATH.
pause
exit /b 1
:failinstall
echo Falha na instalacao. Verifique a conexao com a internet e execute iniciar.bat novamente.
rmdir /s /q venv
pause
exit /b 1
