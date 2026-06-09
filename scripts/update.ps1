param(
    [Parameter(Mandatory = $true)]
    [string]$Version,
    [Parameter(Mandatory = $false)]
    [string]$OutputPath,
    [Parameter(Mandatory = $false)]
    [string]$AssetName = 'ikusa-logger-installer.exe',
    [Parameter(Mandatory = $false)]
    [switch]$ResolveOnly
)

$ErrorActionPreference = 'Stop'

$repoOwner = 'KarmaPanda'
$repoName = 'ikusa_logger'
$base = "https://api.github.com/repos/$repoOwner/$repoName"

$apiHeaders = @{
    'User-Agent' = 'ikusa-logger'
    Accept = 'application/vnd.github+json'
}

$contentsRawHeaders = @{
    'User-Agent' = 'ikusa-logger'
    Accept = 'application/vnd.github.raw'
}

function Download-HttpFile([string]$Uri, [string]$DestinationPath, [hashtable]$Headers) {
    $curlArgs = @('--location', '--fail', '--silent', '--show-error', '--output', $DestinationPath)

    foreach ($entry in $Headers.GetEnumerator()) {
        $curlArgs += @('--header', ([string]$entry.Key + ': ' + [string]$entry.Value))
    }

    $curlArgs += $Uri
    & curl.exe @curlArgs
    if ($LASTEXITCODE -ne 0) {
        throw "curl failed with exit code $LASTEXITCODE while downloading '$Uri'."
    }
}

function Find-AssetInRelease($releaseObj, [string]$targetAssetName) {
    if (-not $releaseObj -or -not $releaseObj.assets) {
        return $null
    }

    $assets = @($releaseObj.assets)
    if ($assets.Count -eq 0) {
        return $null
    }

    $exact = $assets | Where-Object { [string]$_.name -eq $targetAssetName } | Select-Object -First 1
    if ($exact) {
        return $exact
    }

    $installerExe = $assets |
        Where-Object {
            $name = [string]$_.name
            $name.ToLower().EndsWith('.exe') -and (
                $name.ToLower().Contains('installer') -or
                $name.ToLower().Contains('setup')
            )
        } |
        Select-Object -First 1
    if ($installerExe) {
        return $installerExe
    }

    $anyExe = $assets |
        Where-Object { ([string]$_.name).ToLower().EndsWith('.exe') } |
        Select-Object -First 1
    if ($anyExe) {
        return $anyExe
    }

    return $assets | Select-Object -First 1
}

$asset = $null
$downloadMode = $null
$downloadSource = $null

# 0) Prefer known installer path in repository via REST Contents API.
try {
    $primaryInstallerPath = 'dist/ikusa-logger-installer.exe'
    $encodedPrimaryPath = [uri]::EscapeDataString($primaryInstallerPath)
    $primaryUri = "$base/contents/$encodedPrimaryPath`?ref=main"
    $contentMeta = Invoke-RestMethod -Headers $apiHeaders -Uri $primaryUri
    if ($contentMeta -and [string]$contentMeta.type -eq 'file') {
        $downloadMode = 'contents-raw'
        $downloadSource = $primaryUri
    }
} catch {
    # Continue to release-based fallbacks.
}

# 1) Prefer exact tag match via /releases/tags/{tag}
if (-not $downloadSource) {
    try {
        $encodedTag = [uri]::EscapeDataString($Version)
        $releaseUri = "$base/releases/tags/$encodedTag"
        $release = Invoke-RestMethod -Headers $apiHeaders -Uri $releaseUri
        $asset = Find-AssetInRelease $release $AssetName
    } catch {
        # Continue to fallbacks
    }
}

# 2) Search releases list by matching tag_name (Version or vVersion)
if (-not $downloadSource -and -not $asset) {
    try {
        $releases = Invoke-RestMethod -Headers $apiHeaders -Uri "$base/releases?per_page=50"
        if ($releases) {
            $candidateTags = @($Version, "v$Version")
            $matchedRelease = $releases | Where-Object { $candidateTags -contains [string]$_.tag_name } | Select-Object -First 1
            if ($matchedRelease) {
                $asset = Find-AssetInRelease $matchedRelease $AssetName
            }

            # 3) Fallback to first release that has the expected installer asset
            if (-not $asset) {
                foreach ($rel in $releases) {
                    $asset = Find-AssetInRelease $rel $AssetName
                    if ($asset) {
                        break
                    }
                }
            }
        }
    } catch {
        # Continue to final failure below
    }
}

if (-not $downloadSource -and $asset) {
    $assetApiUrl = [string]$asset.url
    if ($assetApiUrl) {
        $downloadMode = 'release-asset-api'
        $downloadSource = $assetApiUrl
        $resolvedAssetName = [string]$asset.name
        if ($resolvedAssetName -and $resolvedAssetName -ne $AssetName) {
            Write-Host "Using release asset '$resolvedAssetName' (requested '$AssetName')."
        }
    }
}

if (-not $downloadSource) {
    try {
        $tree = Invoke-RestMethod -Headers $apiHeaders -Uri "$base/git/trees/main?recursive=1"
        if ($tree -and $tree.tree) {
            $candidate = $tree.tree |
                Where-Object {
                    $_.type -eq 'blob' -and [string]$_.path -match ("(^|/)" + [regex]::Escape($AssetName) + "$")
                } |
                Sort-Object { ([string]$_.path).Length } |
                Select-Object -First 1

            if ($candidate) {
                $path = [string]$candidate.path
                $encodedPath = [uri]::EscapeDataString($path)
                $downloadMode = 'contents-base64'
                $downloadSource = "$base/contents/$encodedPath`?ref=main"
                if ($path -ne $AssetName) {
                    Write-Host "Using repository file '$path' for '$AssetName'."
                }
            }
        }
    } catch {
        # Continue to final failure below
    }
}

if (-not $downloadSource) {
    throw "Asset '$AssetName' was not found via GitHub release assets or repository contents."
}

if ($ResolveOnly) {
    Write-Output $downloadSource
    exit 0
}

if (-not $OutputPath) {
    throw 'OutputPath is required unless -ResolveOnly is used.'
}

if ($downloadMode -eq 'release-asset-api') {
    $downloadHeaders = @{
        'User-Agent' = 'ikusa-logger'
        Accept = 'application/octet-stream'
    }
    Download-HttpFile -Uri $downloadSource -DestinationPath $OutputPath -Headers $downloadHeaders
} elseif ($downloadMode -eq 'contents-raw') {
    Download-HttpFile -Uri $downloadSource -DestinationPath $OutputPath -Headers $contentsRawHeaders
} elseif ($downloadMode -eq 'contents-base64') {
    $content = Invoke-RestMethod -Headers $apiHeaders -Uri $downloadSource
    if (-not $content -or -not $content.content) {
        throw "GitHub contents API returned empty data for '$AssetName'."
    }
    $raw = [string]$content.content
    $normalized = $raw.Replace("`r", '').Replace("`n", '')
    $bytes = [Convert]::FromBase64String($normalized)
    [System.IO.File]::WriteAllBytes($OutputPath, $bytes)
} else {
    throw 'Internal error: no download mode selected.'
}

if (-not (Test-Path -LiteralPath $OutputPath)) {
    throw "Downloaded file not found at '$OutputPath'."
}

Write-Output $OutputPath
exit 0
