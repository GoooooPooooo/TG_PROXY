@echo off
chcp 65001 >nul
docker rm -f tg-ws-proxy 2>nul
docker run -d --name tg-ws-proxy --restart=always -p 1443:1443 tg-ws-proxy:latest
echo.
timeout /t 2 /nobreak >nul
docker logs tg-ws-proxy 2>&1 | findstr "tg://proxy"
echo.
pause
