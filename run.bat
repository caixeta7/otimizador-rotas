@echo off
REM RotaHub - sobe o backend e o frontend juntos, mesmo processo.
REM Rode este script de dentro do terminal, na pasta raiz do projeto:
REM   cd caminho\ate\rotahub
REM   .\run.bat

cd /d "%~dp0backend"

if exist venv goto SKIP_VENV
echo Criando ambiente virtual pela primeira vez...
python -m venv venv
if errorlevel 1 goto ERRO_VENV
:SKIP_VENV

call venv\Scripts\activate.bat

echo Instalando/atualizando dependencias...
pip install -q -r requirements.txt
if errorlevel 1 goto ERRO_PIP

echo.
echo Subindo o RotaHub em http://localhost:8000
echo Aperte Ctrl+C para parar
echo.
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
goto FIM

:ERRO_VENV
echo.
echo ERRO ao criar o ambiente virtual.
echo Verifique se o Python esta instalado e se o comando "python" funciona.
echo Se abrir a Microsoft Store em vez do Python, va em Configuracoes,
echo depois Aplicativos, depois Aliases de execucao de aplicativos,
echo e desative "python.exe" e "python3.exe" da Microsoft Store.
pause
exit /b 1

:ERRO_PIP
echo.
echo ERRO ao instalar as dependencias. Veja a mensagem de erro acima.
pause
exit /b 1

:FIM
pause
