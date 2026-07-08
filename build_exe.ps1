$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

python -m pip install -r requirements.txt

if (Test-Path ".\logo.png") {
  New-Item -ItemType Directory -Force -Path ".\build" | Out-Null
  @'
from pathlib import Path
from PIL import Image

source = Path("logo.png")
target = Path("build/logo.ico")

image = Image.open(source).convert("RGBA")
image.save(
    target,
    format="ICO",
    sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
)
print(f"Icon generated: {target}")
'@ | python -
} else {
  Write-Warning "logo.png not found, exe will use the default icon."
}

python -m PyInstaller --noconfirm --clean vrctool.spec

Write-Host ""
Write-Host "Build complete: dist\vrctool.exe"
