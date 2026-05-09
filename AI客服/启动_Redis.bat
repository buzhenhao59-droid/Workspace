@echo off
chcp 65001 >nul
title Ruitalk Redis 启动器

echo ================================================
echo         Ruitalk Redis 启动器
echo ================================================
echo.
echo 请选择 Redis 安装方式：
echo.
echo   1. 使用 Memurai (Windows 原生，推荐)
echo   2. 使用 Docker (需要 Docker Desktop)
echo   3. 仅检查 Redis 状态
echo   4. 退出
echo.
echo ================================================
echo.

set /p choice=请输入选项 (1-4): 

if "%choice%"=="1" goto :memurai
if "%choice%"=="2" goto :docker
if "%choice%"=="3" goto :check
if "%choice%"=="4" goto :exit

:memurai
echo.
echo 正在检查 Memurai...
memurai --version >nul 2>&1
if %errorlevel%==0 (
    echo Memurai 已安装，正在启动服务...
    memurai --service install >nul 2>&1
    memurai --service start
    echo.
    echo Memurai 服务已启动！
    echo 端口: 6379
    echo.
    echo 下一步：将 .env 中的 REDIS_USE_FAKE=1 改为 REDIS_USE_FAKE=0
    pause
) else (
    echo.
    echo Memurai 未安装。请按以下步骤安装：
    echo.
    echo 1. 访问 https://www.memurai.com/get-download
    echo 2. 下载 Memurai 安装程序
    echo 3. 运行安装程序并完成安装
    echo 4. 重新运行此脚本
    echo.
    echo 或者使用管理员权限运行：
    echo powershell -Command "Invoke-WebRequest -Uri 'https://www.memurai.com/get-download' -OutFile 'memurai-installer.exe'"
    echo.
    pause
)
goto :exit

:docker
echo.
echo 正在检查 Docker...
docker --version >nul 2>&1
if %errorlevel%==0 (
    echo Docker 已安装。
    echo.
    echo 正在启动 Redis 容器...
    docker run -d --name ruitalk-redis ^
        -p 6379:6379 ^
        -v ruitalk-redis-data:/data ^
        redis:7-alpine ^
        redis-server --appendonly yes --maxmemory 256mb --maxmemory-policy allkeys-lru
    if %errorlevel%==0 (
        echo.
        echo Redis 容器已启动！
        echo 端口: 6379
        echo 数据卷: ruitalk-redis-data
        echo.
        echo 下一步：将 .env 中的 REDIS_USE_FAKE=1 改为 REDIS_USE_FAKE=0
    ) else (
        echo.
        echo Docker 启动失败。请确保 Docker Desktop 正在运行。
    )
) else (
    echo.
    echo Docker 未安装。请先安装 Docker Desktop:
    echo https://www.docker.com/products/docker-desktop/
)
echo.
pause
goto :exit

:check
echo.
echo 检查 Redis 状态...
echo.

:: 检查 Memurai
memurai --version >nul 2>&1
if %errorlevel%==0 (
    echo [Memurai] 已安装
    net start | findstr /i "memurai" >nul 2>&1
    if %errorlevel%==0 (
        echo [Memurai] 服务正在运行
    ) else (
        echo [Memurai] 服务未运行（运行 memurai --service start 启动）
    )
) else (
    echo [Memurai] 未安装
)

:: 检查 Docker
docker ps 2>nul | findstr /i "redis" >nul 2>&1
if %errorlevel%==0 (
    echo [Docker Redis] 正在运行
) else (
    echo [Docker Redis] 未运行
)

:: 检查端口
netstat -ano | findstr ":6379 " >nul 2>&1
if %errorlevel%==0 (
    echo [端口 6379] 已被占用
) else (
    echo [端口 6379] 可用
)

echo.
pause
goto :exit

:exit
exit /b
