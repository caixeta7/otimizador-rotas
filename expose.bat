@echo off
REM RotaHub - expoe o backend local via tunel HTTPS do Cloudflare.
REM Use EM PARALELO com run.bat (que sobe o servidor em localhost:8000).
REM
REM Como usar:
REM   1. Abra um terminal e rode run.bat (sobe o RotaHub em http://localhost:8000)
REM   2. Abra OUTRO terminal e rode este expose.bat
REM   3. Copie a URL HTTPS que aparecera abaixo (algo como
REM      https://xxxx-xxxx.trycloudflare.com) e mande pra Bruna/Paulo
REM   4. Eles abrem no celular (4G ou WiFi) - GPS funciona por ser HTTPS
REM
REM Regras:
REM   - Mantenha seu PC ligado enquanto algum usuario estiver usando o app
REM   - A URL muda a cada vez que o expose.bat reinicia - avisar todos
REM   - Se quiser URL fixa (gratuita), verifique a secao "Tunel nomeado"
REM     no README.md

cd /d "%~dp0"

if not exist cloudflared.exe (
  echo.
  echo ERRO: cloudflared.exe nao encontrado na pasta do projeto.
  echo Baixe em:
  echo   https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe
  echo e salve como cloudflared.exe ao lado deste arquivo.
  pause
  exit /b 1
)

echo.
echo Subindo tunel Cloudflare para http://localhost:8000 ...
echo Procure no log abaixo pela linha com a URL HTTPS
echo (algo como: https://xxxx-xxxx-xxxx.trycloudflare.com)
echo.
echo Pressione Ctrl+C para parar o tunel.
echo.

cloudflared.exe tunnel --url http://localhost:8000

pause
