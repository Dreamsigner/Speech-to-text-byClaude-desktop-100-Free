function Write-StopDiagnostic($state, $hwnd, $attempt) {
 try {
  $path=Join-Path $PSScriptRoot 'stop-events.jsonl'
  if ((Test-Path -LiteralPath $path) -and (Get-Item -LiteralPath $path).Length -gt 65536) { [IO.File]::WriteAllText($path,'') }
  $entry=@{time=[DateTime]::UtcNow.ToString('o');state=$state;hwnd=$hwnd;attempt=$attempt}|ConvertTo-Json -Compress
  [IO.File]::AppendAllText($path,$entry+[Environment]::NewLine,[Text.UTF8Encoding]::new($false))
 } catch { }
}
function Select-StopCandidate($candidates) {
 $visible=@($candidates | Where-Object { !$_.Current.IsOffscreen })
 $active=@($visible | Where-Object { $_.Current.IsEnabled })
 if ($active.Count -gt 1) { throw 'Plusieurs boutons de fin actifs ; invocation impossible.' }
 if ($active.Count -eq 1) { return $active[0] }
 return $null
}
function Invoke-StopWhenReady($originalHwnd, $timeoutSeconds) {
 $until=[DateTime]::UtcNow.AddSeconds($timeoutSeconds); $reason='absent'; $hwnd=$originalHwnd; $attempt=0; $previous=$null
 do {
  $attempt++
  try {
   Connect-App $false $true
   $hwnd=$script:window.Current.NativeWindowHandle
   if ($hwnd -ne $originalHwnd) { $reason='fenêtre modifiée'; $button=$null }
   else {
    $candidates=@(Buttons 'Terminer la dictée')
    $visible=@($candidates | Where-Object { !$_.Current.IsOffscreen })
    $enabled=@($visible | Where-Object { $_.Current.IsEnabled })
    Write-StopDiagnostic ("candidates=$($candidates.Count),visible=$($visible.Count),enabled=$($enabled.Count)") $hwnd $attempt
    if ($enabled.Count -gt 1) { throw 'Plusieurs boutons de fin actifs ; invocation impossible.' }
    $button=Select-StopCandidate $candidates
    if ($null -eq $button) { if ($visible.Count) { $reason='désactivé' } else { $reason='absent' } }
   }
  } catch { $reason='fenêtre indisponible ou boutons ambigus'; $button=$null }
  if ($null -eq $button -and $reason -ne $previous) { Write-StopDiagnostic $reason $hwnd $attempt; $previous=$reason }
  if ($null -ne $button) {
   Write-StopDiagnostic 'invoke_attempted' $hwnd $attempt
   # Once Invoke is attempted its effect is uncertain on error: never retry here.
   $button.GetCurrentPattern([Windows.Automation.InvokePattern]::Pattern).Invoke()
   Write-StopDiagnostic 'invoke_returned' $hwnd $attempt
   return
  }
  if ([DateTime]::UtcNow -lt $until) { Start-Sleep -Milliseconds 150 }
 } while ([DateTime]::UtcNow -lt $until)
 Write-StopDiagnostic 'timeout_not_invoked' $hwnd $attempt
 throw "STOP_NOT_INVOKED: bouton Terminer la dictée $reason ; fenêtre $hwnd"
}
