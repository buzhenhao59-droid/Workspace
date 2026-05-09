Set-Location -LiteralPath $PSScriptRoot

$py = $null
# 从统一项目结构查找 venv
$searchPaths = @(
    "$PSScriptRoot\.venv\Scripts\python.exe",
    (Join-Path (Split-Path -Parent $PSScriptRoot) "卖方终端\.venv\Scripts\python.exe")
)
foreach ($p in $searchPaths) {
    if (Test-Path -LiteralPath $p) {
        $py = $p
        break
    }
}
if (-not $py) {
    Write-Host "[ERROR] Python venv not found."
    exit 1
}
$script = Join-Path $PSScriptRoot "run_buyer.py"
& $py $script
exit $LASTEXITCODE
