param([switch]$Check, [switch]$Diagnose)
$ErrorActionPreference = 'Stop'
$scriptPath = Join-Path $PSScriptRoot 'claude_headless\main.py'
if ($Check -or $Diagnose) {
    $python = (Get-Command python.exe -ErrorAction Stop).Source
    $option = if ($Diagnose) { '--diagnose' } else { '--check' }
    & $python $scriptPath $option
    exit $LASTEXITCODE
}
$python = (Get-Command pythonw.exe -ErrorAction Stop).Source
Start-Process -FilePath $python -ArgumentList ('"' + $scriptPath + '"') -WindowStyle Hidden
