$ErrorActionPreference = 'Stop'

$repoOwner = 'KarmaPanda'
$repoName = 'ikusa_logger'
$base = "https://api.github.com/repos/$repoOwner/$repoName"

$headers = @{
    'User-Agent' = 'ikusa-logger'
    Accept = 'application/vnd.github+json'
}

function Normalize-Version([string]$value) {
    if (-not $value) {
        return ''
    }

    $trimmed = $value.Trim()
    if (-not $trimmed) {
        return ''
    }

    $withoutQuotes = $trimmed -replace '^["'']+|["'']+$', ''
    return ($withoutQuotes -replace '^[vV]', '').ToLowerInvariant()
}

function Try-ApiTag([string]$url, [scriptblock]$selector) {
    try {
        $response = Invoke-RestMethod -Headers $headers -Uri $url
        $value = & $selector $response
        if ($value) {
            return Normalize-Version ([string]$value)
        }
    } catch {
        return $null
    }
    return $null
}

function Try-ManifestVersion {
    try {
        $manifestPath = [uri]::EscapeDataString('version/version-manifest.json')
        $url = "$base/contents/$manifestPath`?ref=main"
        $content = Invoke-RestMethod -Headers $headers -Uri $url
        if (-not $content -or -not $content.content) {
            return $null
        }

        $raw = [string]$content.content
        $normalized = $raw.Replace("`r", '').Replace("`n", '')
        $bytes = [Convert]::FromBase64String($normalized)
        $json = [System.Text.Encoding]::UTF8.GetString($bytes) | ConvertFrom-Json
        if ($json -and $json.version) {
            return Normalize-Version ([string]$json.version)
        }
    } catch {
        return $null
    }

    return $null
}

$tag = Try-ManifestVersion
if (-not $tag) {
    $tag = Try-ApiTag "$base/releases/latest" { param($r) $r.tag_name }
}
if (-not $tag) {
    $tag = Try-ApiTag "$base/releases?per_page=20" {
        param($r)
        if ($r -and $r.Count -gt 0) {
            foreach ($release in $r) {
                if ($release.tag_name) {
                    return $release.tag_name
                }
            }
        }
        return $null
    }
}
if (-not $tag) {
    $tag = Try-ApiTag "$base/tags?per_page=20" {
        param($r)
        if ($r -and $r.Count -gt 0 -and $r[0].name) {
            return $r[0].name
        }
        return $null
    }
}

if (-not $tag) {
    try {
        $remote = "https://github.com/$repoOwner/$repoName.git"
        $lines = & git ls-remote --tags $remote 2>$null
        if ($LASTEXITCODE -eq 0 -and $lines) {
            $tagNames = @()
            foreach ($line in $lines) {
                if ($line -match 'refs/tags/(.+)$') {
                    $name = $Matches[1]
                    if ($name.EndsWith('^{}')) {
                        $name = $name.Substring(0, $name.Length - 3)
                    }
                    $normalizedName = Normalize-Version $name
                    if ($normalizedName) {
                        $tagNames += $normalizedName
                    }
                }
            }

            $tagNames = $tagNames | Select-Object -Unique
            if ($tagNames.Count -gt 0) {
                $parsed = @()
                foreach ($name in $tagNames) {
                    $norm = Normalize-Version $name
                    $version = $null
                    if ([version]::TryParse($norm, [ref]$version)) {
                        $parsed += [PSCustomObject]@{ name = $name; ver = $version }
                    }
                }

                if ($parsed.Count -gt 0) {
                    $tag = ($parsed | Sort-Object ver -Descending | Select-Object -First 1).name
                } else {
                    $tag = ($tagNames | Sort-Object -Descending | Select-Object -First 1)
                }
            }
        }
    } catch {
        # Ignore and fail below
    }
}

if (-not $tag) {
    exit 1
}

Write-Output (Normalize-Version $tag)
exit 0
