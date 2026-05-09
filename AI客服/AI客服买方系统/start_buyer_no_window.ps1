param(
    [string]$LogPath = ""
)

if ($LogPath -eq "") { $LogPath = "$PSScriptRoot\buyer_start.log" }

$ErrorActionPreference = "SilentlyContinue"

function Write-Log {
    param([string]$Msg, [string]$Level = "INFO")
    $ts = Get-Date -Format "HH:mm:ss"
    $line = "[$ts][$Level] $Msg"
    try {
        [System.IO.File]::AppendAllText($LogPath, "$line`r`n", [Text.Encoding]::UTF8)
    } catch { }
}

$buyerDir = $PSScriptRoot

try {
    if ((Test-Path $LogPath) -and (Get-Item $LogPath).Length -gt 5242880) {
        Remove-Item $LogPath -Force
    }
    $hdr = "================== $($((Get-Date).ToString('yyyy-MM-dd HH:mm:ss'))) =================="
    [System.IO.File]::WriteAllText($LogPath, "$hdr`r`n", [Text.Encoding]::UTF8)
} catch { }

Write-Log "Buyer AI starting (zero-window)..."
Write-Log "Dir: $buyerDir"

# ── Find Python ─────────────────────────────────────────────────────────────────
# Returns: @($executable, $argPrefix) e.g. @("C:\path\python.exe", "")
#                          or   @("cmd", "/c py -3")
function Find-Python($dir) {
    # 1. self .venv
    $selfVenv = Join-Path $dir ".venv\Scripts\python.exe"
    if (Test-Path $selfVenv) {
        return @($selfVenv, "")
    }
    # 2. sibling 卖方终端\.venv
    $seller = Join-Path (Split-Path $dir) "卖方终端\.venv\Scripts\python.exe"
    if (Test-Path $seller) {
        return @($seller, "")
    }
    # 4. system python
    # Try py -3 (Windows Python Launcher) first
    $testCmd = 'cmd /c ""py -3" -c "import uvicorn; print(1)" 2>nul'
    $null = & cmd /c $testCmd
    if ($LASTEXITCODE -eq 0) {
        return @("cmd", "/c ""py -3"")
    }
    foreach ($py in @("py", "python3", "python")) {
        $null = & cmd /c "$py -c `"import uvicorn; print(1)`" 2>nul"
        if ($LASTEXITCODE -eq 0) {
            return @($py, "")
            break
        }
    }
    return $null
}

$result = Find-Python $buyerDir
if ($null -eq $result) {
    Write-Log "Python not found. Install Python 3.9+ and restart." ERR
    exit 1
}
$pythonExec = $result[0]
$pythonArgPrefix = $result[1]
Write-Log "Python: $pythonExec $pythonArgPrefix"

# ── Pick port ───────────────────────────────────────────────────────────────────
$envPortRaw = [System.Environment]::GetEnvironmentVariable("BUYER_PORT")
if ([string]::IsNullOrEmpty($envPortRaw)) { $envPortRaw = "8001" }
$preferred = [int]$envPortRaw
$chosenPort = $null

for ($p = $preferred; $p -le 8010; $p++) {
    $taken = $false
    try {
        $l = New-Object System.Net.Sockets.TcpListener([System.Net.IPAddress]::Loopback, $p)
        $l.Start()
        $l.Stop()
        $l = $null
    } catch {
        $taken = $true
    }
    if (-not $taken) {
        $chosenPort = $p
        break
    }
}

if ($null -eq $chosenPort) {
    Write-Log "No free port 8001-8010. Stop another buyer instance." ERR
    exit 1
}
if ($chosenPort -ne $preferred) {
    Write-Log "Port $preferred busy, using $chosenPort"
}

$buyerUrl = "http://127.0.0.1:$chosenPort/"

# ── Build command line ──────────────────────────────────────────────────────────
$targetArgs = "-m uvicorn backend.main_buyer:app --host 127.0.0.1 --port $chosenPort --log-level info"
if ($pythonArgPrefix.Length -gt 0) {
    $fullCmd = "$pythonArgPrefix $targetArgs"
    $filePath = "cmd"
    $argList = $fullCmd
} else {
    $filePath = $pythonExec
    $argList = $targetArgs
}

# ── Start uvicorn via Start-Process (hidden window) ──────────────────────────────
Write-Log "Starting uvicorn on :$chosenPort ..."

$env:BUYER_PORT = [string]$chosenPort
$env:PYTHONIOENCODING = "utf8"

try {
    if ($pythonArgPrefix.Length -gt 0) {
        # cmd /c "py -3 ..."
        $proc = Start-Process -FilePath $filePath -ArgumentList $argList `
            -WorkingDirectory $buyerDir -WindowStyle Hidden -NoNewWindow -PassThru
    } else {
        $proc = Start-Process -FilePath $filePath -ArgumentList $argList `
            -WorkingDirectory $buyerDir -WindowStyle Hidden -PassThru
    }
    if ($null -eq $proc) {
        Write-Log "Start-Process returned null." ERR
        exit 1
    }
    if ($proc.HasExited) {
        Write-Log "Process exited immediately with code $($proc.ExitCode)." ERR
        exit 1
    }
    Write-Log "uvicorn started PID=$($proc.Id)"
} catch {
    Write-Log "Exception starting uvicorn: $_" ERR
    exit 1
}

# ── Wait for port ───────────────────────────────────────────────────────────────
Write-Log "Waiting for server..."
$ready = $false
for ($i = 0; $i -lt 60; $i++) {
    Start-Sleep -Milliseconds 250
    try {
        $c = New-Object System.Net.Sockets.TcpClient
        $c.Connect("127.0.0.1", $chosenPort)
        $c.Close()
        $ready = $true
        break
    } catch { }
}
if ($ready) {
    Write-Log "Server ready (took $($i * 0.25)s)"
} else {
    Write-Log "Server not ready after 15s; continuing" WARN
}

# ── Open browser ────────────────────────────────────────────────────────────────
Start-Sleep -Milliseconds 500
try {
    [System.Diagnostics.Process]::Start($buyerUrl)
    Write-Log "Browser opened: $buyerUrl"
} catch {
    Write-Log "Could not open browser. Open manually: $buyerUrl" WARN
}

Write-Log "Done. URL: $buyerUrl"
exit 0
