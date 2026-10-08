# Creates a "Moje inwestycje" shortcut on the Windows desktop that starts the app in its own window, without a console.
# Run from anywhere after installing the package into .venv:
#   powershell -ExecutionPolicy Bypass -File scripts\create_desktop_shortcut.ps1
param(
    [string]$Destination = [Environment]::GetFolderPath("Desktop")
)

$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
$target = Join-Path $repo ".venv\Scripts\financial-app-gui.exe"
if (-not (Test-Path $target)) {
    throw "Missing $target. Install the app first: .venv\Scripts\python.exe -m pip install -e "".[dev]"""
}

$link = Join-Path $Destination "Moje inwestycje.lnk"
$shortcut = (New-Object -ComObject WScript.Shell).CreateShortcut($link)
$shortcut.TargetPath = $target
$shortcut.WorkingDirectory = $repo
$shortcut.Description = "Moje inwestycje - portfel inwestycyjny"
$shortcut.Save()
Write-Output "Created $link"
