@echo off
chcp 65001 >nul 2>&1
title Ruitalk卖家系统

echo 启动Ruitalk卖家系统...

:: 停止所有python进程
taskkill /F /IM python.exe >nul 2>&1

:: 等待2秒
timeout /t 2 /nobreak >nul

:: 找到卖家终端目录
set SELLER_DIR=
for /d %%i in ("%~dp0*") do (
    if exist "%%i\backend\main.py" (
        set SELLER_DIR=%%i
    )
)

if not defined SELLER_DIR (
    echo 错误：找不到卖家终端目录
    pause
    exit
)

echo 卖家目录: %SELLER_DIR%

:: 启动FastAPI (8000)
echo 启动FastAPI (端口8000)...
start "FastAPI" cmd /c "cd /d %SELLER_DIR%\backend && python main.py"

timeout /t 4 /nobreak >nul

:: 启动GoldCS (5001)
echo 启动GoldCS (端口5001)...
start "GoldCS" cmd /c "cd /d %SELLER_DIR%\backend && python gold_customer_service.py"

timeout /t 3 /nobreak >nul

:: 启动GraphRAG (5050)
echo 启动GraphRAG (端口5050)...
start "GraphRAG" cmd /c "cd /d %SELLER_DIR%\backend && python graphrag_proxy.py"

echo.
echo 所有服务已启动！
echo.
echo 请访问: http://127.0.0.1:8000
echo.
start http://127.0.0.1:8000
pause
