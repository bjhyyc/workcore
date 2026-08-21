$ErrorActionPreference = 'Stop'

$workspaceRoot = [IO.Path]::GetFullPath('C:\Users\86135\Documents\workcore')
$downloadsRoot = [IO.Path]::GetFullPath('C:\Users\86135\Downloads')
$localAppDataRoot = [IO.Path]::GetFullPath('C:\Users\86135\AppData\Local')
$codexTempRoot = [IO.Path]::GetFullPath('C:\Users\86135\.codex\.tmp')
$archiveRoot = [IO.Path]::GetFullPath('D:\workcore_archive\2026-07-25_c_drive_cleanup_round2')

function Assert-WithinRoot {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Root,
        [Parameter(Mandatory = $true)][string]$Label
    )

    $fullPath = [IO.Path]::GetFullPath($Path)
    $fullRoot = [IO.Path]::GetFullPath($Root)
    if (-not $fullPath.StartsWith($fullRoot, [StringComparison]::OrdinalIgnoreCase)) {
        throw "$Label escaped its permitted root: $fullPath"
    }
    return $fullPath
}

function Measure-Path {
    param([Parameter(Mandatory = $true)][string]$Path)

    $item = Get-Item -LiteralPath $Path -Force
    if ($item.PSIsContainer) {
        return Get-ChildItem -LiteralPath $Path -Force -Recurse -File |
            Measure-Object -Property Length -Sum
    }
    return $item | Measure-Object -Property Length -Sum
}

function Move-VerifiedItem {
    param(
        [Parameter(Mandatory = $true)][string]$Source,
        [Parameter(Mandatory = $true)][string]$AllowedSourceRoot,
        [Parameter(Mandatory = $true)][string]$Destination
    )

    $sourceFull = Assert-WithinRoot -Path $Source -Root $AllowedSourceRoot -Label 'Source'
    $destinationFull = Assert-WithinRoot -Path $Destination -Root $archiveRoot -Label 'Destination'

    if (-not (Test-Path -LiteralPath $sourceFull)) {
        return $null
    }
    if (Test-Path -LiteralPath $destinationFull) {
        throw "Destination already exists: $destinationFull"
    }

    $before = Measure-Path -Path $sourceFull
    New-Item -ItemType Directory -Path (Split-Path -Parent $destinationFull) -Force | Out-Null
    Move-Item -LiteralPath $sourceFull -Destination $destinationFull
    $after = Measure-Path -Path $destinationFull

    if ($before.Count -ne $after.Count -or $before.Sum -ne $after.Sum) {
        throw "Verification failed for $sourceFull"
    }

    return [pscustomobject]@{
        Source = $sourceFull
        Destination = $destinationFull
        Files = $after.Count
        Bytes = $after.Sum
    }
}

$results = [System.Collections.Generic.List[object]]::new()
New-Item -ItemType Directory -Path $archiveRoot -Force | Out-Null

# Preserve downloaded installers and compressed packages on D while freeing C.
$downloadExtensions = @('.exe', '.msi', '.msix', '.apk', '.zip', '.7z', '.rar', '.iso')
$downloadDestination = Join-Path $archiveRoot 'downloaded_installers_and_archives'
$downloadItems = Get-ChildItem -LiteralPath $downloadsRoot -Force -File |
    Where-Object { $downloadExtensions -contains $_.Extension.ToLowerInvariant() }
foreach ($item in $downloadItems) {
    $moved = Move-VerifiedItem `
        -Source $item.FullName `
        -AllowedSourceRoot $downloadsRoot `
        -Destination (Join-Path $downloadDestination $item.Name)
    if ($null -ne $moved) {
        $results.Add($moved)
    }
}

# npm's download cache is reproducible. Move it without installing or deleting packages.
$npmCache = Join-Path $localAppDataRoot 'npm-cache'
$npmDestination = Join-Path $archiveRoot 'regenerable_caches\npm-cache'
if (-not (Test-Path -LiteralPath $npmDestination)) {
    $movedNpm = Move-VerifiedItem `
        -Source $npmCache `
        -AllowedSourceRoot $localAppDataRoot `
        -Destination $npmDestination
    if ($null -ne $movedNpm) {
        $results.Add($movedNpm)
    }
}

# Codex temporary directories are intentionally left in place while Codex is running.
# Even older entries can be protected or reopened by the active desktop process.

# Relocate the reproducible WorkCore virtual environment and retain its original path via Junction.
$venvSource = Join-Path $workspaceRoot '.venv'
$venvDestination = Join-Path $archiveRoot 'active_relocated\workcore\.venv'
$venvItem = Get-Item -LiteralPath $venvSource -Force
if ($venvItem.LinkType -eq 'Junction') {
    if (($venvItem.Target -join ';') -ne $venvDestination) {
        throw "Unexpected existing .venv Junction target: $($venvItem.Target -join ';')"
    }
} else {
    $workspacePython = Get-Process -Name python, pythonw -ErrorAction SilentlyContinue |
        Where-Object {
            $_.Path -and
            ([IO.Path]::GetFullPath($_.Path)).StartsWith(
                [IO.Path]::GetFullPath($venvSource),
                [StringComparison]::OrdinalIgnoreCase
            )
        }
    if ($workspacePython) {
        throw 'A Python process is currently running from the WorkCore .venv.'
    }

    $movedVenv = Move-VerifiedItem `
        -Source $venvSource `
        -AllowedSourceRoot $workspaceRoot `
        -Destination $venvDestination
    if ($null -ne $movedVenv) {
        $results.Add($movedVenv)
    }

    $junction = New-Item -ItemType Junction -Path $venvSource -Target $venvDestination
    if ($junction.LinkType -ne 'Junction' -or ($junction.Target -join ';') -ne $venvDestination) {
        throw 'Failed to verify the WorkCore .venv Junction.'
    }
}

# Archive superseded WorkCore renders, state files, and validation output.
$v11Root = Join-Path $workspaceRoot 'design\e6_final_exterior\v11_v8_blender_exterior_restart_20260721'
$historicalCandidates = [System.Collections.Generic.List[string]]::new()
foreach ($relativeRoot in @('blender\states', 'renders\preview', 'renders\final', 'qa')) {
    $candidateRoot = Join-Path $v11Root $relativeRoot
    if (Test-Path -LiteralPath $candidateRoot) {
        Get-ChildItem -LiteralPath $candidateRoot -Force -Directory |
            Where-Object { $_.Name -match '^r(0[1-9]|1[0-3])$' } |
            ForEach-Object { $historicalCandidates.Add($_.FullName) }
    }
}

foreach ($path in @(
    (Join-Path $workspaceRoot 'design\e6_final_exterior\step_anchored_v2\class_a_cad\.validation_work'),
    (Join-Path $workspaceRoot 'design\e6_final_exterior\.v8_material_visual_preflight'),
    (Join-Path $workspaceRoot 'design\e6_final_exterior\.v8_final_visual_review_20260719'),
    (Join-Path $workspaceRoot 'design\e6_final_exterior\v8_patent_drawings_and_disclosure_figures_20260720\qa\.headless_profile'),
    (Join-Path $v11Root 'interactive\r14_threejs_review\.vinext'),
    (Join-Path $v11Root 'interactive\r14_threejs_review\.wrangler'),
    (Join-Path $workspaceRoot 'build\workcore_e2_review.html'),
    (Join-Path $workspaceRoot 'build\workcore_e3_review.html'),
    (Join-Path $workspaceRoot 'build\workcore_e4_review_offline_v2.html')
)) {
    if (Test-Path -LiteralPath $path) {
        $historicalCandidates.Add($path)
    }
}

foreach ($path in $historicalCandidates) {
    $sourceFull = Assert-WithinRoot -Path $path -Root $workspaceRoot -Label 'Historical source'
    $relative = $sourceFull.Substring($workspaceRoot.Length).TrimStart('\')
    $movedHistorical = Move-VerifiedItem `
        -Source $sourceFull `
        -AllowedSourceRoot $workspaceRoot `
        -Destination (Join-Path $archiveRoot "workcore_historical\$relative")
    if ($null -ne $movedHistorical) {
        $results.Add($movedHistorical)
    }
}

$summary = [pscustomobject]@{
    ArchiveRoot = $archiveRoot
    MovedItems = $results.Count
    MovedFiles = ($results | Measure-Object -Property Files -Sum).Sum
    MovedBytes = ($results | Measure-Object -Property Bytes -Sum).Sum
    CFreeGiB = [math]::Round((Get-PSDrive C).Free / 1GB, 3)
    DFreeGiB = [math]::Round((Get-PSDrive D).Free / 1GB, 3)
    Results = $results
}

$summary | ConvertTo-Json -Depth 5
