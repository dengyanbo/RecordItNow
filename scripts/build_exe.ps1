<#
.SYNOPSIS
    Build a standalone PyInstaller onedir bundle for RIN.

.DESCRIPTION
    Author-side packaging script:
      1. Runs ruff + pytest. Aborts on failure unless -SkipChecks.
      2. Reads __version__ from src/rin/__init__.py.
      3. Runs pyinstaller scripts\RIN.spec --clean --noconfirm.
      4. Zips the resulting onedir bundle as dist\RIN-v{version}-windows-exe.zip.
      5. Prints the gh CLI command to publish the asset.

.EXAMPLE
    .\scripts\build_exe.ps1
    .\scripts\build_exe.ps1 -SkipChecks
#>
[CmdletBinding()]
param(
    [switch]$SkipChecks
)

$ErrorActionPreference = 'Stop'

function Resolve-PyInstallerOutputDir {
    foreach ($candidate in @('build\exe\RIN', 'dist\RIN')) {
        if (Test-Path $candidate) {
            return (Resolve-Path $candidate).Path
        }
    }
    throw "Cannot find PyInstaller output directory (expected build\\exe\\RIN or dist\\RIN)."
}

function Invoke-PyInstallerBuild {
    $localPyInstaller = Join-Path $repoRoot '.venv\Scripts\pyinstaller.exe'
    if (Test-Path $localPyInstaller) {
        & $localPyInstaller 'scripts\RIN.spec' --clean --noconfirm
        return
    }
    $pyinstaller = Get-Command 'pyinstaller' -ErrorAction SilentlyContinue
    if ($pyinstaller) {
        & $pyinstaller.Source 'scripts\RIN.spec' --clean --noconfirm
        return
    }
    throw 'PyInstaller not found. Install dev deps with uv pip install -e ".[all,dev]".'
}

$repoRoot = (Resolve-Path "$PSScriptRoot\..").Path
Push-Location $repoRoot
try {
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

    $initLine = Select-String -Path 'src\rin\__init__.py' -Pattern '__version__\s*=' | Select-Object -First 1
    if (-not $initLine) { throw "Cannot find __version__ in src/rin/__init__.py" }
    if ($initLine.Line -notmatch '"([^"]+)"') { throw "Cannot parse version from: $($initLine.Line)" }
    $version = $Matches[1]
    Write-Host ">>> Version: $version" -ForegroundColor Cyan

    $distDir = 'dist'
    if (-not (Test-Path $distDir)) { New-Item -ItemType Directory -Path $distDir | Out-Null }
    $zipPath = Join-Path $distDir "RIN-v$version-windows-exe.zip"
    if (Test-Path $zipPath) { Remove-Item -Force $zipPath }

    Write-Host ">>> pyinstaller scripts\RIN.spec --clean --noconfirm" -ForegroundColor Cyan
    Invoke-PyInstallerBuild
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed with exit code $LASTEXITCODE" }

    $bundleDir = Resolve-PyInstallerOutputDir
    Write-Host ">>> Zipping $bundleDir -> $zipPath" -ForegroundColor Cyan
    Compress-Archive -Path (Join-Path $bundleDir '*') -DestinationPath $zipPath -CompressionLevel Optimal

    $sizeMB = [math]::Round((Get-Item $zipPath).Length / 1MB, 1)
    Write-Host ">>> Built $zipPath ($sizeMB MB)" -ForegroundColor Green
    if ($sizeMB -gt 1024) {
        Write-Host "!!! Warning: exe zip > 1 GB. Check Torch / Whisper payload size." -ForegroundColor Yellow
    }

    Write-Host ""
    Write-Host "============================================================"
    Write-Host "  Next: publish the standalone exe bundle"
    Write-Host "============================================================"
    Write-Host ""
    Write-Host "  gh release upload v$version $zipPath --clobber"
    Write-Host ""
} finally {
    Pop-Location
}
