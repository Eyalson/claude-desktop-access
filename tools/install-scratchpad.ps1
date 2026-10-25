# Copies the add-on's app module into NVDA's Developer Scratchpad folder.
# Run: powershell -NoProfile -ExecutionPolicy Bypass -File install-scratchpad.ps1
# Then in NVDA press NVDA+Ctrl+F3 to reload plugins.
$source = Join-Path (Split-Path $PSScriptRoot -Parent) 'addon\appModules\claude.py'
$target = Join-Path $env:APPDATA 'nvda\scratchpad\appModules'
New-Item -ItemType Directory -Force $target | Out-Null
Copy-Item -LiteralPath $source -Destination $target -Force
Write-Output ('Copied to ' + (Join-Path $target 'claude.py'))
