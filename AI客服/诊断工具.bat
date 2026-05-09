@echo off
chcp 65001 >nul 2>&1
title Ruitalk 系统诊断

echo ================================================
echo    Ruitalk 系统诊断工具
echo ================================================
echo.

:: 检查 Python
where python >nul 2>&1
if errorlevel 1 (
    echo [错误] 未找到 Python，请先安装 Python 3.11+
    pause
    exit /b 1
)

:: 找到项目目录
set PROJECT_DIR=
for /d %%i in ("%~dp0*") do (
    if exist "%%i\backend\main.py" (
        set PROJECT_DIR=%%i
    )
)
if not defined PROJECT_DIR (
    for /d %%i in ("%~dp0卖方终端") do (
        if exist "%%i\backend\main.py" (
            set PROJECT_DIR=%%i\..
        )
    )
)

if not defined PROJECT_DIR (
    echo [错误] 找不到项目目录
    pause
    exit /b 1
)

echo 项目目录: %PROJECT_DIR%
echo.

:: ================================================
:: 1. 检查端口状态
echo ================================================
echo [1/6] 检查服务端口...
echo.

echo   FastAPI (8000):
netstat -ano | findstr ":8000 " | findstr "LISTENING" >nul 2>&1
if %errorlevel%==0 (
    echo   [OK]   端口 8000 已监听
) else (
    echo   [未启动] 端口 8000 未监听
)

echo   GraphRAG 代理 (5050):
netstat -ano | findstr ":5050 " | findstr "LISTENING" >nul 2>&1
if %errorlevel%==0 (
    echo   [OK]   端口 5050 已监听
) else (
    echo   [未启动] 端口 5050 未监听 - 需要启动 graphrag_proxy.py
)

echo   Redis (6379):
netstat -ano | findstr ":6379 " | findstr "LISTENING" >nul 2>&1
if %errorlevel%==0 (
    echo   [OK]   端口 6379 已监听
) else (
    echo   [警告] 端口 6379 未监听 - 将使用内存会话存储
)

echo.
:: ================================================
:: 2. 测试 API 状态端点
echo ================================================
echo [2/6] 测试 API 状态端点...
echo.

curl -s -o nul -w "   HTTP 状态码: %%{http_code}\n" http://127.0.0.1:8000/api/status 2>nul
if errorlevel 1 (
    echo   [错误] 无法连接 FastAPI (端口 8000)
    echo   请先运行: 卖家系统启动.bat
)

echo.
:: ================================================
:: 3. 测试 GraphRAG 健康检查
echo ================================================
echo [3/6] 测试 GraphRAG 健康检查...
echo.

curl -s http://127.0.0.1:5050/health 2>nul
if errorlevel 1 (
    echo   [错误] GraphRAG 代理未运行
    echo.
    echo   解决方法:
    echo   1. 打开新的命令行窗口
    echo   2. 运行: cd /d "%PROJECT_DIR%\卖方终端\backend"
    echo   3. 运行: python graphrag_proxy.py
) else (
    echo   [OK] GraphRAG 健康检查成功
)

echo.
:: ================================================
:: 4. 检查配置文件
echo ================================================
echo [4/6] 检查配置文件...
echo.

if exist "%PROJECT_DIR%\.env" (
    echo   [OK] .env 文件存在
) else (
    echo   [错误] .env 文件不存在！
)

if exist "%PROJECT_DIR%\卖方终端\backend\.env" (
    echo   [OK] 卖方终端 .env 存在
) else (
    echo   [警告] 卖方终端 .env 不存在
)

echo.
:: ================================================
:: 5. 检查 Python 依赖
echo ================================================
echo [5/6] 检查 Python 依赖...
echo.

cd /d "%PROJECT_DIR%\卖方终端\backend"
python -c "import fastapi; import uvicorn; import neo4j" 2>nul
if errorlevel 1 (
    echo   [错误] 缺少必要的 Python 包
    echo.
    echo   请运行安装命令:
    echo   pip install fastapi uvicorn neo4j python-dotenv
) else (
    echo   [OK] 核心依赖已安装
)

echo.
:: ================================================
:: 6. 启动建议
echo ================================================
echo [6/6] 启动建议...
echo.

echo   如果看到任何 [未启动] 或 [错误] 标记:
echo.
echo   方法 1 - 使用启动脚本:
echo   双击运行 "卖家系统启动.bat"
echo.
echo   方法 2 - 手动启动各服务:
echo   1. cd /d "%PROJECT_DIR%\卖方终端\backend"
echo   2. start python main.py          # FastAPI (端口 8000)
echo   3. start python graphrag_proxy.py  # GraphRAG (端口 5050)
echo.
echo   诊断完成后，请访问:
echo   http://127.0.0.1:8000/diagnose  - 系统诊断页面
echo   http://127.0.0.1:8000           - 客服系统首页
echo.
echo ================================================
echo    诊断完成
echo ================================================
pause
