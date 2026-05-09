@echo off
setlocal EnableExtensions
REM ASCII-only batch: avoids cmd garbling UTF-8. Never uses PATH "python" (may be broken e.g. D:\python.exe).
cd /d "%~dp0"
set "HERE=%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command ^
  "$here=[System.IO.Path]::GetFullPath($env:HERE.TrimEnd([char]92)); $root=[System.IO.Path]::GetDirectoryName($here); $sd=-join [char[]](0x5356,0x65B9,0x7EC8,0x7AEF); $py=Join-Path (Join-Path $root $sd) '.venv\Scripts\python.exe'; $sc=Join-Path $here 'run_buyer.py'; if(-not(Test-Path -LiteralPath $py)){Write-Host '[ERROR] venv not found:' $py; exit 2}; & $py $sc; exit $LASTEXITCODE"
if errorlevel 1 (
  echo.
  echo [ERROR] Failed. Check messages above.
  pause
  exit /b %ERRORLEVEL%
)
