$ErrorActionPreference = 'Stop'

$driverPath = Join-Path $env:SystemRoot 'System32\drivers\npcap.sys'
if (Test-Path $driverPath) {
    Write-Output 'Npcap already installed.'
    exit 0
}

$downloadUrls = @(
    'https://npcap.com/dist/npcap-1.88.exe'
)

$bundledCandidates = @(
    (Join-Path $PSScriptRoot 'npcap-1.88.exe'),
    (Join-Path (Split-Path -Parent $PSScriptRoot) 'dist\npcap-1.88.exe')
)
$bundledInstallerPath = $bundledCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1
$installerPath = Join-Path $env:TEMP 'ikusa-npcap-installer.exe'
$downloaded = $false

if ($bundledInstallerPath -and (Test-Path $bundledInstallerPath)) {
    Copy-Item -Path $bundledInstallerPath -Destination $installerPath -Force
    if ((Test-Path $installerPath) -and ((Get-Item $installerPath).Length -gt 0)) {
        $downloaded = $true
        Write-Output 'Using bundled Npcap installer.'
    }
}

if (-not $downloaded) {
    foreach ($url in $downloadUrls) {
        try {
            Invoke-WebRequest -Uri $url -OutFile $installerPath -UseBasicParsing -TimeoutSec 120
            if ((Test-Path $installerPath) -and ((Get-Item $installerPath).Length -gt 0)) {
                $downloaded = $true
                break
            }
        }
        catch {
            Write-Warning ("Failed to download Npcap from: {0}" -f $url)
        }
    }
}

if (-not $downloaded) {
    throw 'Npcap download failed from all known URLs.'
}

$arguments = '/S /winpcap_mode=yes /loopback_support=yes'
$process = Start-Process -FilePath $installerPath -ArgumentList $arguments -Wait -PassThru

if ($process.ExitCode -ne 0) {
    throw ("Npcap installer exited with code {0}." -f $process.ExitCode)
}

if (-not (Test-Path $driverPath)) {
    throw 'Npcap install completed but npcap.sys was not found.'
}

Write-Output 'Npcap installed successfully.'
exit 0
