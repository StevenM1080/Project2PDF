$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = Join-Path $root '.venv\Scripts\python.exe'

if (-not (Test-Path -LiteralPath $python)) {
    python -m venv (Join-Path $root '.venv')
}

& $python -m pip install --disable-pip-version-check -e "$root[dev]"
& $python -m PyInstaller `
    --noconfirm `
    --clean `
    --onefile `
    --windowed `
    --name Project2PDF `
    --collect-data project2pdf `
    (Join-Path $root 'run_project2pdf.py')

Write-Host "Built: $(Join-Path $root 'dist\Project2PDF.exe')"

