param([string]$Python = "python")
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
if (-not (Test-Path .venv\Scripts\python.exe)) {
    & $Python -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw "Python 3.12+ is required; use -Python with its full path." }
}
& .\.venv\Scripts\python.exe -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw "Dependency installation failed." }
Write-Host "Ready. Drag a VR180 JPG or folder onto convert.cmd, or see README.md."
