<#
.SYNOPSIS
    Build a one-click installer zip for RIN (PyInstaller bundle + Install.bat).

.DESCRIPTION
    Author-side packaging script:
      1. Runs ruff + pytest. Aborts on failure unless -SkipChecks.
      2. Reads __version__ from src/rin/__init__.py.
      3. Runs pyinstaller scripts\RIN.spec --clean --noconfirm.
      4. Stages a release layout in build\installer\:
             Install.bat
             install.ps1
             prefetch_models.py
             README-INSTALL.txt
             bundle\RIN.exe + _internal\...
      5. Zips the staged layout as dist\RIN-v{version}-windows-installer.zip
         so end users get one download, extract, double-click Install.bat.
      6. Prints the gh CLI command to publish the asset.

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
    $zipPath = Join-Path $distDir "RIN-v$version-windows-installer.zip"
    if (Test-Path $zipPath) { Remove-Item -Force $zipPath }

    Write-Host ">>> pyinstaller scripts\RIN.spec --clean --noconfirm" -ForegroundColor Cyan
    Invoke-PyInstallerBuild
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed with exit code $LASTEXITCODE" }

    $bundleDir = Resolve-PyInstallerOutputDir

    # ------------------------------------------------------------------
    # Stage the installer layout: Install.bat + install.ps1 + bundle\
    # ------------------------------------------------------------------
    $installerStage = Join-Path $repoRoot 'build\installer'
    if (Test-Path $installerStage) { Remove-Item -Recurse -Force $installerStage }
    New-Item -ItemType Directory -Force -Path $installerStage | Out-Null

    Write-Host ">>> Staging installer layout at $installerStage" -ForegroundColor Cyan

    # Copy installer scripts. install.ps1 + Install.bat + README are the
    # only thing the end user touches directly.
    foreach ($f in @('Install.bat', 'install.ps1', 'README-INSTALL.txt', 'prefetch_models.py')) {
        $src = Join-Path $repoRoot "scripts\$f"
        if (-not (Test-Path $src)) {
            throw "Missing required installer file: $src"
        }
        Copy-Item -Force $src $installerStage
    }

    # Sanity-check install.ps1 has UTF-8 BOM. Windows PowerShell 5.1
    # (the Explorer "Run with PowerShell" default) cannot parse it
    # otherwise — em-dashes get mis-decoded under CP1252.
    $ipBytes = [IO.File]::ReadAllBytes((Join-Path $installerStage 'install.ps1'))
    $ipBom = ($ipBytes.Length -ge 3 -and $ipBytes[0] -eq 0xEF -and $ipBytes[1] -eq 0xBB -and $ipBytes[2] -eq 0xBF)
    if (-not $ipBom) {
        throw "install.ps1 in stage is missing UTF-8 BOM; PS 5.1 users will fail. Add BOM to scripts\install.ps1 before re-running."
    }

    # Stamp the version so install.ps1's banner shows the right number when
    # installing from the bundle (no src/__init__.py available at install time).
    $versionStamp = Join-Path $installerStage 'version.txt'
    Set-Content -Path $versionStamp -Value $version -NoNewline -Encoding ASCII

    # Copy PyInstaller bundle into bundle\ subdir
    $stageBundle = Join-Path $installerStage 'bundle'
    Copy-Item -Recurse -Force $bundleDir $stageBundle
    if (-not (Test-Path (Join-Path $stageBundle 'RIN.exe'))) {
        throw "After copy, bundle\RIN.exe not found at $stageBundle"
    }

    # ------------------------------------------------------------------
    # Zip. Use System.IO.Compression directly to avoid Compress-Archive
    # quirks (PS 5.1 has been observed to silently skip subdirectories
    # when given a wildcard pattern).
    # ------------------------------------------------------------------
    Write-Host ">>> Zipping $installerStage -> $zipPath" -ForegroundColor Cyan
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    [System.IO.Compression.ZipFile]::CreateFromDirectory(
        $installerStage, $zipPath,
        [System.IO.Compression.CompressionLevel]::Optimal,
        $false  # includeBaseDirectory=$false -> contents at zip root
    )

    $sizeMB = [math]::Round((Get-Item $zipPath).Length / 1MB, 1)
    Write-Host ">>> Built $zipPath ($sizeMB MB)" -ForegroundColor Green
    if ($sizeMB -gt 1024) {
        Write-Host "!!! Warning: installer zip > 1 GB. Check Torch / Whisper payload size." -ForegroundColor Yellow
    }

    Write-Host ""
    Write-Host "============================================================"
    Write-Host "  Next: publish the one-click installer"
    Write-Host "============================================================"
    Write-Host ""
    Write-Host "  gh release upload v$version $zipPath --clobber"
    Write-Host ""
    Write-Host "  End-user flow after upload:"
    Write-Host "    1. Download RIN-v$version-windows-installer.zip"
    Write-Host "    2. Right-click -> Extract All"
    Write-Host "    3. Double-click Install.bat"
    Write-Host ""
} finally {
    Pop-Location
}
