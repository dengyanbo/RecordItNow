<#
.SYNOPSIS
    Install RIN — Record It Now on Windows.

.DESCRIPTION
    End-to-end installer. By default it provisions Python, uv, FFmpeg,
    GitHub Copilot CLI, and all Python dependencies, then sets up a Start
    Menu shortcut. Use -FromExe to extract a pre-built standalone bundle
    instead.

    Designed to be run from the unpacked release zip:
        1. Right-click `install.ps1` -> Run with PowerShell, OR
        2. From PowerShell:  .\install.ps1 [flags]

.PARAMETER InstallDir
    Where to install RIN. Defaults to %LOCALAPPDATA%\Programs\RIN
    so the RIN install itself runs without admin rights. Note: if
    winget needs to install Python or FFmpeg system-wide it may
    surface a UAC prompt — that's a one-time elevation for the
    underlying installer, not for RIN.

.PARAMETER Prefetch
    Pre-download the ML model weights (~1 GB total) during install
    so the first analyze/search runs offline.

.PARAMETER Autostart
    Register RIN to launch automatically on Windows login.

.PARAMETER SkipDeps
    Skip Python / FFmpeg / Copilot CLI installation; assume they're
    already on PATH. Useful in CI or for advanced users.

.PARAMETER FromExe
    Install from a pre-built `RIN-v*-windows-exe.zip` instead of creating
    a Python virtual environment. The zip is discovered next to this script
    or in `..\dist\`.

.PARAMETER FromBundle
    Install from a pre-extracted PyInstaller bundle directory containing
    RIN.exe + _internal\. Used by the one-click Install.bat in the
    `RIN-v*-windows-installer.zip` asset to skip the redundant double-zip
    extraction step.

.PARAMETER Force
    Overwrite an existing installation without prompting.

.EXAMPLE
    .\install.ps1
    .\install.ps1 -Prefetch -Autostart
    .\install.ps1 -InstallDir "D:\Apps\RIN" -SkipDeps
    .\install.ps1 -FromBundle .\bundle -Force
#>
[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [string]$InstallDir = (Join-Path $env:LOCALAPPDATA 'Programs\RIN'),
    [switch]$Prefetch,
    [switch]$Autostart,
    [switch]$SkipDeps,
    [switch]$Force,
    [switch]$FromExe,
    [string]$FromBundle = ''
)

$ErrorActionPreference = 'Stop'
$ProgressPreference   = 'Continue'

# Pull version from the bundled source so install messages match the package.
function Get-RinVersion {
    # 1. Stamped version.txt next to install.ps1 (written by build_exe.ps1 for
    #    one-click installer zips).
    $stamp = Join-Path $PSScriptRoot 'version.txt'
    if (Test-Path $stamp) {
        $v = (Get-Content $stamp -Raw -ErrorAction SilentlyContinue).Trim()
        if ($v) { return $v }
    }
    # 2. Source checkout: read from src/rin/__init__.py.
    $initPath = Join-Path $PSScriptRoot '..\src\rin\__init__.py'
    if (-not (Test-Path $initPath)) {
        $initPath = Join-Path $PSScriptRoot 'src\rin\__init__.py'
    }
    if (Test-Path $initPath) {
        $line = (Select-String -Path $initPath -Pattern '__version__\s*=' -SimpleMatch:$false | Select-Object -First 1)
        if ($line) { return ($line.Line -replace '.*"([^"]+)".*', '$1') }
    }
    # 3. Last resort: parse the zip filename if one is nearby.
    foreach ($pattern in @(
        (Join-Path $PSScriptRoot 'RIN-v*-windows-installer.zip'),
        (Join-Path $PSScriptRoot 'RIN-v*-windows-exe.zip'),
        (Join-Path $PSScriptRoot '..\RIN-v*-windows-installer.zip'),
        (Join-Path $PSScriptRoot '..\RIN-v*-windows-exe.zip'),
        (Join-Path $PSScriptRoot '..\dist\RIN-v*-windows-installer.zip'),
        (Join-Path $PSScriptRoot '..\dist\RIN-v*-windows-exe.zip')
    )) {
        $zip = Get-ChildItem -Path $pattern -File -ErrorAction SilentlyContinue |
            Sort-Object LastWriteTime -Descending |
            Select-Object -First 1
        if ($zip -and $zip.BaseName -match '^RIN-v(.+)-windows-(installer|exe)$') {
            return $Matches[1]
        }
    }
    return '0.0.0'
}

function Write-Step    { param([string]$Msg) Write-Host ""; Write-Host ">>> $Msg" -ForegroundColor Cyan }
function Write-OK      { param([string]$Msg) Write-Host "    [OK] $Msg" -ForegroundColor Green }
function Write-Warn    { param([string]$Msg) Write-Host "    [!!] $Msg" -ForegroundColor Yellow }
function Fail          { param([string]$Msg) Write-Host "    [XX] $Msg" -ForegroundColor Red; exit 1 }

function Stop-RunningRin {
    <#
    .SYNOPSIS
        Detect any RIN.exe process whose binary lives under $InstallDir
        and shut it down cleanly, so the subsequent Remove-Item doesn't
        fail with a sharing-violation error.

    .PARAMETER InstallDir
        The directory whose RIN.exe instances should be terminated.

    .PARAMETER Force
        If set, skip the prompt and kill silently.
    #>
    param(
        [Parameter(Mandatory = $true)][string]$InstallDir,
        [switch]$Force
    )

    $running = @(Get-Process -Name RIN -ErrorAction SilentlyContinue | Where-Object {
        try { $_.Path -and $_.Path.StartsWith($InstallDir, [System.StringComparison]::OrdinalIgnoreCase) }
        catch { $false }
    })

    if (-not $running -or $running.Count -eq 0) { return }

    Write-Warn "RIN is currently running (PID $($running.Id -join ', ')) — must stop before overwrite."

    if (-not $Force) {
        $choice = Read-Host "    Stop the running RIN now? [Y/n]"
        if ($choice -match '^[Nn]') { Fail "Aborted: please quit RIN from the tray then re-run the installer." }
    }

    # Graceful close first
    foreach ($p in $running) {
        try { $null = $p.CloseMainWindow() } catch { }
    }

    # Wait up to 5 s for graceful exit
    $deadline = (Get-Date).AddSeconds(5)
    while ((Get-Date) -lt $deadline) {
        $still = @(Get-Process -Name RIN -ErrorAction SilentlyContinue | Where-Object {
            try { $_.Path -and $_.Path.StartsWith($InstallDir, [System.StringComparison]::OrdinalIgnoreCase) }
            catch { $false }
        })
        if (-not $still -or $still.Count -eq 0) {
            Write-OK "RIN closed gracefully."
            return
        }
        Start-Sleep -Milliseconds 250
    }

    # Force-kill fallback
    Write-Warn "Graceful close timed out — force-killing."
    foreach ($p in $running) {
        try { Stop-Process -Id $p.Id -Force -ErrorAction Stop } catch {
            Fail "Could not stop RIN (PID $($p.Id)): $($_.Exception.Message). Please quit it manually and re-run the installer."
        }
    }
    # Small grace period for the OS to release file handles
    Start-Sleep -Milliseconds 500
    Write-OK "RIN process terminated."
}

function Invoke-WithRetry {
    <#
    .SYNOPSIS
        Run a scriptblock up to 3 times with 1-2-4 second backoff.
        Used to give Windows time to release file handles after RIN
        exits.
    #>
    param(
        [Parameter(Mandatory = $true)][scriptblock]$Action,
        [int]$MaxAttempts = 3,
        [string]$Label = "operation"
    )

    $delay = 1
    for ($attempt = 1; $attempt -le $MaxAttempts; $attempt++) {
        try {
            & $Action
            return
        } catch {
            if ($attempt -eq $MaxAttempts) { throw }
            Write-Warn ("{0} failed (attempt {1}/{2}): {3} — retrying in {4}s..." -f $Label, $attempt, $MaxAttempts, $_.Exception.Message, $delay)
            Start-Sleep -Seconds $delay
            $delay *= 2
        }
    }
}

function Find-ExeBundleZip {
    foreach ($pattern in @(
        (Join-Path $PSScriptRoot 'RIN-v*-windows-exe.zip'),
        (Join-Path $PSScriptRoot '..\RIN-v*-windows-exe.zip'),
        (Join-Path $PSScriptRoot '..\dist\RIN-v*-windows-exe.zip')
    )) {
        $match = Get-ChildItem -Path $pattern -File -ErrorAction SilentlyContinue |
            Sort-Object LastWriteTime -Descending |
            Select-Object -First 1
        if ($match) {
            return $match.FullName
        }
    }
    return $null
}

function Test-Command {
    param([Parameter(Mandatory)][string]$Name)
    return [bool](Get-Command $Name -ErrorAction SilentlyContinue)
}

function Assert-Windows10Plus {
    $os = [Environment]::OSVersion.Version
    if ($os.Major -lt 10) {
        Fail "Windows 10 or newer required (detected $($os.ToString()))."
    }
    if ($PSVersionTable.PSVersion.Major -lt 5) {
        Fail "PowerShell 5.1 or newer required (detected $($PSVersionTable.PSVersion))."
    }
}

function Resolve-WingetPath {
    <#
    .SYNOPSIS
        Return the absolute path of a *runnable* winget.exe for the CURRENT
        user, or $null if winget is unavailable.

    .DESCRIPTION
        Default ``Get-Command winget`` resolution can return another user's
        App Execution Alias on multi-user machines, e.g.
        ``C:\Users\<other>\AppData\Local\Microsoft\WindowsApps\winget.exe``,
        which the current process cannot launch. The resulting error is
        cryptic: "The system cannot find the path specified".

        We probe the current user's WindowsApps folder first (the only
        path guaranteed to belong to the current process owner), then fall
        back to PATH resolution, and finally verify the candidate actually
        launches by invoking ``--version``.
    #>

    # 1. Current-user App Execution Alias (the per-user winget shim).
    $userWinget = Join-Path $env:LOCALAPPDATA 'Microsoft\WindowsApps\winget.exe'
    if (Test-Path -LiteralPath $userWinget) {
        try {
            & $userWinget --version 2>$null | Out-Null
            if ($LASTEXITCODE -eq 0) { return $userWinget }
        } catch { }
    }

    # 2. Fall back to PATH but VERIFY the resolved file is launchable —
    #    a stub belonging to a different user fails this probe.
    $cmd = Get-Command winget -ErrorAction SilentlyContinue
    if ($cmd -and $cmd.Source -and (Test-Path -LiteralPath $cmd.Source)) {
        try {
            & $cmd.Source --version 2>$null | Out-Null
            if ($LASTEXITCODE -eq 0) { return $cmd.Source }
        } catch { }
    }

    return $null
}

function Install-PackageViaWinget {
    param(
        [Parameter(Mandatory)][string]$Id,
        [Parameter(Mandatory)][string]$Friendly
    )
    $wingetPath = Resolve-WingetPath
    if (-not $wingetPath) {
        Write-Warn "winget not available for the current user; please install '$Friendly' manually."
        Write-Host "    Tip: open Microsoft Store and install 'App Installer' to get winget, then re-run Install.bat."
        return $false
    }
    Write-Host "    Installing $Friendly via winget ($wingetPath)..."
    & $wingetPath install --exact --id $Id `
        --accept-package-agreements --accept-source-agreements --silent | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Write-Warn "winget exited with code $LASTEXITCODE while installing $Friendly. Continuing."
        return $false
    }
    return $true
}

function Refresh-Path {
    # winget puts the new tool's path in HKCU/HKLM but the current session
    # doesn't see it until restarted. Re-read both registries.
    $machine = [Environment]::GetEnvironmentVariable('Path', 'Machine')
    $user    = [Environment]::GetEnvironmentVariable('Path', 'User')
    $env:Path = "$machine;$user"
}

function Find-PythonBin {
    foreach ($candidate in @('python', 'py')) {
        if (Test-Command $candidate) {
            $v = & $candidate --version 2>&1
            if ($v -match 'Python (\d+)\.(\d+)') {
                $maj = [int]$Matches[1]; $min = [int]$Matches[2]
                if ($maj -gt 3 -or ($maj -eq 3 -and $min -ge 11)) {
                    return $candidate
                }
            }
        }
    }
    return $null
}

# ----------------------------------------------------------------------
# 1. Sanity checks
# ----------------------------------------------------------------------

$Version = Get-RinVersion
Write-Host "============================================================"
Write-Host "  RIN — Record It Now  installer  (v$Version)"
Write-Host "============================================================"

Write-Step "Checking host"
Assert-Windows10Plus
Write-OK "Windows $($([Environment]::OSVersion.Version)), PowerShell $($PSVersionTable.PSVersion)"
if ($env:HTTPS_PROXY -or $env:HTTP_PROXY) {
    Write-OK "Honoring proxy: HTTPS_PROXY=$env:HTTPS_PROXY"
}

# ----------------------------------------------------------------------
# 2. Pick install dir, ask about overwrite
# ----------------------------------------------------------------------

$InstallDir = [IO.Path]::GetFullPath($InstallDir)
Write-Step "Install location"
Write-Host "    Target: $InstallDir"
if (Test-Path $InstallDir) {
    if ($Force) {
        Write-Warn "Existing install detected, will overwrite (-Force)."
    } else {
        $choice = Read-Host "    A previous install was found. Overwrite? [y/N]"
        if ($choice -notmatch '^[Yy]') { Fail "Aborted by user." }
    }
    Stop-RunningRin -InstallDir $InstallDir -Force:$Force
    if ($PSCmdlet.ShouldProcess($InstallDir, 'remove existing install')) {
        Invoke-WithRetry -Label "Remove-Item $InstallDir" -Action {
            Remove-Item -Recurse -Force $InstallDir
        }
    }
}
if ($PSCmdlet.ShouldProcess($InstallDir, 'create install directory')) {
    New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
}

if ($FromBundle -or $FromExe) {
    Write-Step "Installing pre-built standalone bundle"
    if ($Prefetch) {
        Write-Warn "-Prefetch is ignored for pre-built exe installs. RIN will download models on first use."
    }

    if ($FromBundle) {
        $resolvedBundle = (Resolve-Path -LiteralPath $FromBundle -ErrorAction SilentlyContinue)
        if (-not $resolvedBundle) {
            Fail "Bundle directory not found: $FromBundle"
        }
        $bundleSrcExe = Join-Path $resolvedBundle.Path 'RIN.exe'
        if (-not (Test-Path $bundleSrcExe)) {
            Fail "Bundle directory $($resolvedBundle.Path) does not contain RIN.exe (expected $bundleSrcExe)."
        }
        Write-Host "    Source: $($resolvedBundle.Path)"
        if ($PSCmdlet.ShouldProcess($InstallDir, 'copy pre-built bundle')) {
            $robocopyLog = Join-Path $env:TEMP 'rin-install-robocopy.log'
            & robocopy $resolvedBundle.Path $InstallDir /E /NFL /NDL /NJH /NJS /NP /R:1 /W:1 /LOG:$robocopyLog | Out-Null
            # robocopy returns 0..7 on success; >=8 is an error
            $rc = $LASTEXITCODE
            $global:LASTEXITCODE = 0
            if ($rc -ge 8) {
                if (Test-Path $robocopyLog) { Get-Content $robocopyLog -Tail 50 | ForEach-Object { Write-Host "    $_" } }
                Fail "robocopy failed with exit code $rc"
            }
        }
    } else {
        $exeZip = Find-ExeBundleZip
        if (-not $exeZip) {
            Fail "Cannot find RIN-v*-windows-exe.zip next to install.ps1 or under ..\dist\."
        }
        Write-Host "    Bundle: $exeZip"
        if ($PSCmdlet.ShouldProcess($InstallDir, 'extract pre-built exe bundle')) {
            Expand-Archive -Path $exeZip -DestinationPath $InstallDir -Force
        }
    }

    $exePath = Join-Path $InstallDir 'RIN.exe'
    if (-not (Test-Path $exePath)) {
        Fail "Install copy succeeded but $exePath was not found."
    }
    Write-OK "Standalone bundle installed at $InstallDir"

    # FFmpeg auto-install for true one-click. Skipped under -SkipDeps.
    if (-not $SkipDeps) {
        Write-Step "Ensuring FFmpeg (required for MP4 recording)"
        if (-not (Test-Command 'ffmpeg')) {
            Install-PackageViaWinget -Id 'Gyan.FFmpeg' -Friendly 'FFmpeg' | Out-Null
            Refresh-Path
        }
        if (Test-Command 'ffmpeg') {
            Write-OK "FFmpeg OK: $((& ffmpeg -version 2>&1 | Select-Object -First 1))"
        } else {
            Write-Warn "FFmpeg not on PATH. Video recording will fail until installed."
            Write-Host "    Install manually: winget install Gyan.FFmpeg"
        }
    } else {
        Write-Warn "FFmpeg auto-install skipped (-SkipDeps). Video recording requires ffmpeg on PATH."
    }
    Write-Warn "The default LLM provider expects GitHub Copilot CLI; you can switch to OpenAI/Azure in Settings."

    Write-Step "Start Menu shortcut"
    $startMenu = Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs\RIN.lnk'
    if ($PSCmdlet.ShouldProcess($startMenu, 'create shortcut')) {
        try {
            $shell = New-Object -ComObject WScript.Shell
            $lnk = $shell.CreateShortcut($startMenu)
            $lnk.TargetPath = $exePath
            $lnk.WorkingDirectory = $InstallDir
            $lnk.IconLocation = $exePath
            $lnk.Description  = 'RIN — Record It Now'
            $lnk.Save()
            Write-OK "Shortcut: $startMenu"
        } catch {
            Write-Warn "Failed to create Start Menu shortcut: $_"
        }
    }

    if ($Autostart) {
        Write-Step "Registering autostart on login"
        $runKey = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run'
        if (-not (Test-Path $runKey)) {
            New-Item -Path $runKey -Force | Out-Null
        }
        Set-ItemProperty -Path $runKey -Name 'RIN' -Value ('"{0}"' -f $exePath)
        Write-OK "Autostart enabled (will start RIN.exe with Windows)."
    }

    Write-Step "Installation complete!"
    Write-Host ""
    Write-Host "  Launch RIN:"
    Write-Host "    - From Start Menu: type 'RIN' and press Enter"
    Write-Host "    - From CLI:        & '$exePath'"
    Write-Host ""
    Write-Host "  Data directory:  $(Join-Path $env:LOCALAPPDATA 'RIN')"
    Write-Host "  Uninstall:       Remove $InstallDir and $(Join-Path $env:LOCALAPPDATA 'RIN')"
    Write-Host ""
    Write-Host "  Quick check:"
    Write-Host "    & '$exePath' --smoke"
    Write-Host ""
    return
}

# ----------------------------------------------------------------------
# 3. External tools
# ----------------------------------------------------------------------

if ($SkipDeps) {
    Write-Step "Dependency check (skipped via -SkipDeps)"
} else {
    Write-Step "Ensuring Python 3.11+"
    $py = Find-PythonBin
    if (-not $py) {
        Install-PackageViaWinget -Id 'Python.Python.3.12' -Friendly 'Python 3.12' | Out-Null
        Refresh-Path
        $py = Find-PythonBin
    }
    if (-not $py) { Fail "Python install failed. Install Python 3.11+ manually and re-run with -SkipDeps." }
    Write-OK "Python OK: $py ($(& $py --version 2>&1))"

    Write-Step "Ensuring FFmpeg"
    if (-not (Test-Command 'ffmpeg')) {
        Install-PackageViaWinget -Id 'Gyan.FFmpeg' -Friendly 'FFmpeg' | Out-Null
        Refresh-Path
    }
    if (Test-Command 'ffmpeg') {
        Write-OK "FFmpeg OK: $((& ffmpeg -version 2>&1 | Select-Object -First 1))"
    } else {
        Write-Warn "FFmpeg not on PATH. Video recording will fail until installed."
        Write-Host "    Install manually: winget install Gyan.FFmpeg"
    }

    Write-Step "Ensuring GitHub Copilot CLI"
    if (-not (Test-Command 'copilot')) {
        Write-Warn "Copilot CLI not found."
        Write-Host "    The default LLM provider uses it. Install via:"
        Write-Host "      https://docs.github.com/copilot/how-tos/copilot-cli"
        Write-Host "    Then run:  copilot login"
        Write-Host "    You can also switch to OpenAI/Azure in RIN -> Settings -> Analysis."
    } else {
        Write-OK "Copilot CLI OK: $((& copilot --version 2>&1))"
    }
}

# ----------------------------------------------------------------------
# 4. Stage source
# ----------------------------------------------------------------------

Write-Step "Staging source tree"
$srcSrc = Join-Path $PSScriptRoot '..\src'
if (-not (Test-Path $srcSrc)) { $srcSrc = Join-Path $PSScriptRoot 'src' }
if (-not (Test-Path $srcSrc)) { Fail "Cannot find src\ next to install.ps1." }

$ppSrc = Join-Path $PSScriptRoot '..\pyproject.toml'
if (-not (Test-Path $ppSrc)) { $ppSrc = Join-Path $PSScriptRoot 'pyproject.toml' }
if (-not (Test-Path $ppSrc)) { Fail "Cannot find pyproject.toml." }

if ($PSCmdlet.ShouldProcess($InstallDir, 'copy source')) {
    Copy-Item -Recurse -Force $srcSrc (Join-Path $InstallDir 'src')
    Copy-Item -Force $ppSrc (Join-Path $InstallDir 'pyproject.toml')
    foreach ($name in @('README.md', 'README.zh-CN.md', 'LICENSE', 'NOTICE')) {
        $p = Join-Path $PSScriptRoot "..\$name"
        if (-not (Test-Path $p)) { $p = Join-Path $PSScriptRoot $name }
        if (Test-Path $p) { Copy-Item -Force $p $InstallDir }
    }
    $scriptsDst = Join-Path $InstallDir 'scripts'
    New-Item -ItemType Directory -Force -Path $scriptsDst | Out-Null
    Copy-Item -Force $PSScriptRoot\prefetch_models.py $scriptsDst -ErrorAction SilentlyContinue
}
Write-OK "Source staged at $InstallDir"

# ----------------------------------------------------------------------
# 5. Virtualenv via uv (much faster than venv + pip)
# ----------------------------------------------------------------------

Write-Step "Creating virtual environment"
$py = if ($SkipDeps) { 'python' } else { Find-PythonBin }
if (-not $py) { Fail "Python not found." }

if (-not (Test-Command 'uv')) {
    Write-Host "    Installing uv..."
    & $py -m pip install --user --upgrade uv | Out-Null
    Refresh-Path
}

Push-Location $InstallDir
try {
    Write-Host "    uv venv ..."
    & uv venv | Out-Null
    $venvPy = Join-Path $InstallDir '.venv\Scripts\python.exe'
    if (-not (Test-Path $venvPy)) { Fail "uv venv did not produce $venvPy" }
    # Pin uv to the venv we just created. Without this, an outer VIRTUAL_ENV
    # (e.g. the maintainer's dev venv) would silently win.
    $prevVenv = $env:VIRTUAL_ENV
    $env:VIRTUAL_ENV = Join-Path $InstallDir '.venv'
    try {
        Write-Host "    uv pip install --python `"$venvPy`" -e .[all] ..."
        & uv pip install --python $venvPy -e ".[all]" | Out-Null
        if ($LASTEXITCODE -ne 0) { Fail "pip install failed." }
    } finally {
        if ($null -eq $prevVenv) { Remove-Item env:VIRTUAL_ENV -ErrorAction SilentlyContinue }
        else { $env:VIRTUAL_ENV = $prevVenv }
    }
    Write-OK "Virtual environment ready at $InstallDir\.venv"
} finally {
    Pop-Location
}

# ----------------------------------------------------------------------
# 6. Optional: prefetch ML models
# ----------------------------------------------------------------------

if ($Prefetch) {
    Write-Step "Pre-downloading ML models (~1 GB, takes a few minutes)"
    $venvPy = Join-Path $InstallDir '.venv\Scripts\python.exe'
    $prefetchScript = Join-Path $InstallDir 'scripts\prefetch_models.py'
    if (Test-Path $prefetchScript) {
        & $venvPy $prefetchScript
        if ($LASTEXITCODE -ne 0) {
            Write-Warn "Prefetch finished with some failures. RIN will retry on first use."
        } else {
            Write-OK "Models cached at %LOCALAPPDATA%\RIN\models"
        }
    } else {
        Write-Warn "prefetch_models.py missing; skipping."
    }
} else {
    Write-Step "Skipping model prefetch (use -Prefetch to download now)"
}

# ----------------------------------------------------------------------
# 7. Start Menu shortcut
# ----------------------------------------------------------------------

Write-Step "Start Menu shortcut"
$startMenu = Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs\RIN.lnk'
$venvPyW   = Join-Path $InstallDir '.venv\Scripts\pythonw.exe'
if ($PSCmdlet.ShouldProcess($startMenu, 'create shortcut')) {
    try {
        $shell = New-Object -ComObject WScript.Shell
        $lnk = $shell.CreateShortcut($startMenu)
        $lnk.TargetPath = $venvPyW
        $lnk.Arguments  = '-m rin'
        $lnk.WorkingDirectory = $InstallDir
        $lnk.IconLocation = $venvPyW
        $lnk.Description  = 'RIN — Record It Now'
        $lnk.Save()
        Write-OK "Shortcut: $startMenu"
    } catch {
        Write-Warn "Failed to create Start Menu shortcut: $_"
    }
}

# ----------------------------------------------------------------------
# 8. Optional: autostart on login
# ----------------------------------------------------------------------

if ($Autostart) {
    Write-Step "Registering autostart on login"
    $venvPy = Join-Path $InstallDir '.venv\Scripts\python.exe'
    $cmd = "& '$venvPy' -c 'from rin.utils.autostart import enable, default_command; enable(default_command())'"
    Invoke-Expression $cmd | Out-Null
    Write-OK "Autostart enabled (will start with Windows)."
}

# ----------------------------------------------------------------------
# 9. Done!
# ----------------------------------------------------------------------

Write-Step "Installation complete!"
Write-Host ""
Write-Host "  Launch RIN:"
Write-Host "    - From Start Menu: type 'RIN' and press Enter"
Write-Host "    - From CLI:        & '$venvPyW' -m rin"
Write-Host ""
Write-Host "  Data directory:  $(Join-Path $env:LOCALAPPDATA 'RIN')"
Write-Host "  Uninstall:       Remove $InstallDir and $(Join-Path $env:LOCALAPPDATA 'RIN')"
Write-Host ""
Write-Host "  Quick check:"
Write-Host "    & '$(Join-Path $InstallDir '.venv\Scripts\python.exe')' -m rin --smoke"
Write-Host ""
