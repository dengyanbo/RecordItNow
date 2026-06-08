<#
.SYNOPSIS
    Build a RIN release zip suitable for upload to GitHub Releases.

.DESCRIPTION
    Author-side packaging script:
      1. Runs ruff + pytest. Aborts on failure unless -SkipChecks.
      2. Reads __version__ from src/rin/__init__.py.
      3. Stages a minimal source tree in build/release/RIN-v{version}/.
      4. Zips it as dist/RIN-v{version}-windows.zip.
      5. Prints the gh CLI command to publish the release.

.EXAMPLE
    .\scripts\build_release.ps1
    .\scripts\build_release.ps1 -SkipChecks
#>
[CmdletBinding()]
param(
    [switch]$SkipChecks
)

$ErrorActionPreference = 'Stop'

$repoRoot = (Resolve-Path "$PSScriptRoot\..").Path
Push-Location $repoRoot
try {
    # ------------------------------------------------------------------
    # 1. Pre-flight checks
    # ------------------------------------------------------------------
    if (-not $SkipChecks) {
        Write-Host ">>> ruff check" -ForegroundColor Cyan
        & ruff check src tests scripts
        if ($LASTEXITCODE -ne 0) { throw "ruff failed; fix issues or pass -SkipChecks" }

        Write-Host ">>> pytest" -ForegroundColor Cyan
        & pytest -q
        if ($LASTEXITCODE -ne 0) { throw "pytest failed; fix issues or pass -SkipChecks" }
    } else {
        Write-Host ">>> Skipping ruff + pytest (-SkipChecks)" -ForegroundColor Yellow
    }

    # ------------------------------------------------------------------
    # 2. Read version
    # ------------------------------------------------------------------
    $initLine = Select-String -Path 'src\rin\__init__.py' -Pattern '__version__\s*=' | Select-Object -First 1
    if (-not $initLine) { throw "Cannot find __version__ in src/rin/__init__.py" }
    if ($initLine.Line -notmatch '"([^"]+)"') { throw "Cannot parse version from: $($initLine.Line)" }
    $version = $Matches[1]
    Write-Host ">>> Version: $version" -ForegroundColor Cyan

    # ------------------------------------------------------------------
    # 3. Stage files
    # ------------------------------------------------------------------
    $stage   = "build\release\RIN-v$version"
    $distDir = 'dist'
    if (Test-Path $stage)   { Remove-Item -Recurse -Force $stage }
    if (-not (Test-Path $distDir)) { New-Item -ItemType Directory -Path $distDir | Out-Null }
    New-Item -ItemType Directory -Force -Path $stage | Out-Null

    Write-Host ">>> Staging source tree at $stage"

    # Source tree — copy then prune __pycache__.
    Copy-Item -Recurse -Force 'src' (Join-Path $stage 'src')
    Get-ChildItem -Recurse -Force -Path (Join-Path $stage 'src') -Filter '__pycache__' |
        Remove-Item -Recurse -Force -ErrorAction SilentlyContinue

    # Scripts users need: installer + prefetch + dev launcher.
    $scriptDst = Join-Path $stage 'scripts'
    New-Item -ItemType Directory -Force -Path $scriptDst | Out-Null
    foreach ($s in @('install.ps1', 'prefetch_models.py', 'dev_run.ps1')) {
        $src = Join-Path 'scripts' $s
        if (Test-Path $src) { Copy-Item -Force $src $scriptDst }
    }

    # Top-level docs + project metadata.
    foreach ($f in @('pyproject.toml', 'README.md', 'README.zh-CN.md', 'LICENSE', 'NOTICE')) {
        if (Test-Path $f) { Copy-Item -Force $f $stage }
    }

    # ------------------------------------------------------------------
    # 4. Zip
    # ------------------------------------------------------------------
    $zipName = "RIN-v$version-windows.zip"
    $zipPath = Join-Path $distDir $zipName
    if (Test-Path $zipPath) { Remove-Item -Force $zipPath }
    Write-Host ">>> Creating $zipPath"
    Compress-Archive -Path (Join-Path $stage '*') -DestinationPath $zipPath -CompressionLevel Optimal

    $sizeKB = [int]((Get-Item $zipPath).Length / 1024)
    Write-Host ">>> Built $zipPath ($sizeKB KB)" -ForegroundColor Green
    if ($sizeKB -gt 20480) {
        Write-Host "!!! Warning: release zip > 20 MB. Investigate what crept in." -ForegroundColor Yellow
    }

    # ------------------------------------------------------------------
    # 5. Print publish hint
    # ------------------------------------------------------------------
    Write-Host ""
    Write-Host "============================================================"
    Write-Host "  Next: publish to GitHub Releases"
    Write-Host "============================================================"
    Write-Host ""
    Write-Host "  git tag -a v$version -m 'RIN v$version'"
    Write-Host "  git push origin v$version"
    Write-Host "  gh release create v$version $zipPath \"
    Write-Host "    --title 'RIN v$version' --notes-file CHANGELOG.md"
    Write-Host ""
} finally {
    Pop-Location
}
