$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

python -m pip install -r requirements.txt
python -m PyInstaller --noconfirm --clean vrctool.spec

Write-Host ""
Write-Host "Build complete: dist\vrctool.exe"
