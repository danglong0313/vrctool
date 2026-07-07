$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

python -m pip install -r requirements.txt
python -m PyInstaller --noconfirm --clean VRCOSC.spec

Write-Host ""
Write-Host "Build complete: dist\VRCOSC.exe"
