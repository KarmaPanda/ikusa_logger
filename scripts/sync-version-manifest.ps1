param(
    [string]$ConfigPath = ".\neutralino.config.json",
    [string]$ManifestPath = ".\version\version-manifest.json",
    [string]$ResourcesSourcePath = ".\dist\ikusa-logger\resources.neu",
    [string]$ResourcesTargetPath = ".\version\resources.neu"
)

$ErrorActionPreference = 'Stop'

if (-not (Test-Path $ConfigPath)) {
    throw "Config file not found: $ConfigPath"
}

if (-not (Test-Path $ManifestPath)) {
    throw "Version manifest not found: $ManifestPath"
}

$config = Get-Content $ConfigPath -Raw | ConvertFrom-Json
$manifest = Get-Content $ManifestPath -Raw | ConvertFrom-Json

if (-not $config.version) {
    throw "No version value found in $ConfigPath"
}

$manifest.version = [string]$config.version

$manifestJson = $manifest | ConvertTo-Json -Depth 10
Set-Content -Path $ManifestPath -Value ($manifestJson + "`r`n") -Encoding utf8

if (-not (Test-Path $ResourcesSourcePath)) {
    throw "Built resources.neu not found: $ResourcesSourcePath"
}

$targetDirectory = Split-Path -Parent $ResourcesTargetPath
if ($targetDirectory -and -not (Test-Path $targetDirectory)) {
    New-Item -ItemType Directory -Path $targetDirectory | Out-Null
}

Copy-Item -Path $ResourcesSourcePath -Destination $ResourcesTargetPath -Force

Write-Host "Synced version manifest to $($manifest.version) and copied resources.neu." 