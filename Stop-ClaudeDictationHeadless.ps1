$ErrorActionPreference = 'Stop'
$scriptPath = Join-Path $PSScriptRoot 'claude_headless\main.py'
$processes = @(Get-CimInstance Win32_Process | Where-Object { $_.Name -match '^python(?:w)?(?:\d+(?:\.\d+)*)?\.exe$' -and $_.CommandLine -and $_.CommandLine.Contains($scriptPath) -and $_.CommandLine -notmatch '--(check|diagnose)' })
if ($processes.Count -eq 0) { Write-Output 'Service non lancé.'; return }
$statusPath = Join-Path $PSScriptRoot 'claude_headless\status.json'
if (!(Test-Path -LiteralPath $statusPath)) { throw 'État du service inconnu : arrêt refusé. Vérifier Claude manuellement.' }
$status = Get-Content -LiteralPath $statusPath -Raw | ConvertFrom-Json
if ($processes.Count -ne 1 -or [int]$status.pid -ne $processes[0].ProcessId -or $status.state -ne 'idle') { throw "Arrêt refusé : état $($status.state). Terminer ou vérifier la dictée dans Claude avant de fermer le service." }
Stop-Process -Id $processes[0].ProcessId
Write-Output 'Service arrêté.'

