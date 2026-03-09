@echo off
echo ========================================
echo   拓岳电商系统 - 启动后端服务
echo ========================================
echo.

cd /d "%~dp0backend"

if not exist "node_modules" (
    echo 正在安装依赖...
    call npm install
    echo.
)

echo 启动服务中...
echo.
echo 服务地址: http://localhost:3000
echo API文档:  http://localhost:3000/api/docs
echo.
echo 默认账号: admin / admin123
echo.
echo 按 Ctrl+C 停止服务
echo ========================================

call npm start
