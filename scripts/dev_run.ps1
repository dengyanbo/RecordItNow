# Dev launcher — activates the venv and starts RIN with the system tray.
# Usage:  .\scripts\dev_run.ps1

$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$repo = Split-Path -Parent $here
$venvActivate = Join-Path $repo '.venv\Scripts\Activate.ps1'

if (-not (Test-Path $venvActivate)) {
    Write-Host "Creating venv with uv..."
    Push-Location $repo
    uv venv
    & $venvActivate
    uv pip install -e '.[all,dev]'
    Pop-Location
}

Push-Location $repo
& $venvActivate
python -m rin
Pop-Location
