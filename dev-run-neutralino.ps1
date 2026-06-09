param(
    [Parameter(Mandatory = $true)]
    [string]$Launcher,

    [Parameter(Mandatory = $true)]
    [string]$ProjectRoot,

    [Parameter(Mandatory = $false)]
    [string]$Arguments = ""
)

$ErrorActionPreference = 'Stop'

function Get-ChildProcessIds {
    param([int]$ParentId)

    $children = @(Get-CimInstance Win32_Process -Filter "ParentProcessId=$ParentId" -ErrorAction SilentlyContinue)
    $ids = @()
    foreach ($child in $children) {
        $childId = [int]$child.ProcessId
        $ids += $childId
        $ids += Get-ChildProcessIds -ParentId $childId
    }
    return $ids
}

function Stop-ProcessTree {
    param([int]$RootId)

    $ids = @($RootId) + (Get-ChildProcessIds -ParentId $RootId)
    $ids = $ids | Sort-Object -Unique -Descending

    foreach ($id in $ids) {
        try {
            Stop-Process -Id $id -Force -ErrorAction Stop
        } catch {
            # Ignore processes that already exited.
        }
    }
}

if (-not (Test-Path -LiteralPath $Launcher)) {
    Write-Host "[ERROR] Launcher not found: $Launcher"
    exit 1
}

$neuProcess = Start-Process -FilePath $Launcher -ArgumentList $Arguments -WorkingDirectory $ProjectRoot -PassThru
Write-Host "[INFO] Started dev launcher PID $($neuProcess.Id)"

$neutralinoPid = $null

while ($true) {
    $neuProcess.Refresh()
    if ($neuProcess.HasExited) {
        exit $neuProcess.ExitCode
    }

    $children = @(Get-CimInstance Win32_Process -Filter "ParentProcessId=$($neuProcess.Id)" -ErrorAction SilentlyContinue)

    if (-not $neutralinoPid) {
        $neutralino = $children | Where-Object { $_.Name -ieq 'neutralino-win_x64.exe' } | Select-Object -First 1
        if ($neutralino) {
            $neutralinoPid = [int]$neutralino.ProcessId
            Write-Host "[INFO] Detected Neutralino app PID $neutralinoPid"
        }
    }

    if ($neutralinoPid) {
        $neutralinoAlive = Get-Process -Id $neutralinoPid -ErrorAction SilentlyContinue
        if (-not $neutralinoAlive) {
            Write-Host "[INFO] Neutralino app closed. Stopping dev launcher and child processes..."
            Stop-ProcessTree -RootId $neuProcess.Id
            exit 0
        }
    }

    Start-Sleep -Milliseconds 400
}
