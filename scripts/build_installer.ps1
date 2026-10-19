# Builds the Windows installer dist\KAPITA-<version>-setup.exe: PyInstaller freezes the app into dist\KAPITA,
# then Inno Setup 6 packs that folder. Needs the build extra and Inno Setup (winget install JRSoftware.InnoSetup):
#   .venv\Scripts\python.exe -m pip install -e ".[dev,build]"
#   powershell -ExecutionPolicy Bypass -File scripts\build_installer.ps1
param(
    [string]$Iscc = ""
)

$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
$python = Join-Path $repo ".venv\Scripts\python.exe"

$version = & $python -c "import financial_app; print(financial_app.__version__)"
if ($LASTEXITCODE -ne 0) { throw "Cannot read the app version; is the package installed into .venv?" }

& $python -m PyInstaller --noconfirm --clean `
    --distpath (Join-Path $repo "dist") --workpath (Join-Path $repo "build\pyinstaller") `
    (Join-Path $repo "packaging\kapita.spec")
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }

if (-not $Iscc) {
    $found = Get-Command ISCC.exe -ErrorAction SilentlyContinue
    $candidates = @(
        $(if ($found) { $found.Source }),
        (Join-Path $env:LOCALAPPDATA "Programs\Inno Setup 6\ISCC.exe"),
        (Join-Path ${env:ProgramFiles(x86)} "Inno Setup 6\ISCC.exe"),
        (Join-Path $env:ProgramFiles "Inno Setup 6\ISCC.exe")
    )
    $Iscc = $candidates | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1
    if (-not $Iscc) { throw "Inno Setup 6 not found; install it or pass -Iscc <path to ISCC.exe>" }
}

& $Iscc "/DAppVersion=$version" (Join-Path $repo "packaging\kapita.iss")
if ($LASTEXITCODE -ne 0) { throw "Inno Setup failed" }
Write-Output "Built dist\KAPITA-$version-setup.exe"
