[Console]::InputEncoding=[Text.UTF8Encoding]::new($false)
[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false)
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
$A=[Windows.Automation.AutomationElement]; $T=[Windows.Automation.TreeScope]; $C=[Windows.Automation.ControlType]
$script:started=$false
. (Join-Path $PSScriptRoot 'stop_control.ps1')
. (Join-Path $PSScriptRoot 'identity_control.ps1')
function Connect-App($launch, $windowOnly=$false) {
 $p=@(Get-Process Claude -ErrorAction SilentlyContinue | Where-Object MainWindowHandle -NE 0 | Select-Object -First 1)
 if ($p.Count -eq 0 -and $launch) {
  $app=Get-StartApps | Where-Object Name -eq 'Claude' | Select-Object -First 1
  if (!$app) { throw 'Claude Desktop introuvable.' }; Start-Process "shell:AppsFolder\$($app.AppID)" | Out-Null
  $until=[DateTime]::UtcNow.AddSeconds(25)
  do { Start-Sleep -Milliseconds 250; $p=@(Get-Process Claude -ErrorAction SilentlyContinue | Where-Object MainWindowHandle -NE 0 | Select-Object -First 1) } while ($p.Count -eq 0 -and [DateTime]::UtcNow -lt $until)
 }
 if (!$p.Count) { throw 'Fenêtre Claude introuvable.' }
 $script:window=$A::FromHandle($p[0].MainWindowHandle)
 if (-not $windowOnly) { Refresh-Editor }
}
function Refresh-Editor {
 $cond=[Windows.Automation.PropertyCondition]::new($A::ControlTypeProperty,$C::Edit)
 $editors=@($script:window.FindAll($T::Descendants,$cond) | Where-Object { $v=$null; $_.TryGetCurrentPattern([Windows.Automation.ValuePattern]::Pattern,[ref]$v) })
 if ($editors.Count -ne 1) { throw "Zone Claude ambiguë : $($editors.Count)" }; $script:editor=$editors[0]
}
function Buttons($name) {
 $matches=[Collections.Generic.List[Windows.Automation.AutomationElement]]::new()
 $walker=[Windows.Automation.TreeWalker]::ControlViewWalker
 $stack=[Collections.Generic.Stack[Windows.Automation.AutomationElement]]::new(); $stack.Push($script:window)
 while ($stack.Count -gt 0) {
  $node=$stack.Pop()
  if ($node.Current.ControlType -eq $C::Button -and $node.Current.Name -eq $name) { $matches.Add($node) }
  $child=$walker.GetFirstChild($node)
  while ($null -ne $child) { $stack.Push($child); $child=$walker.GetNextSibling($child) }
 }
 return $matches.ToArray()
}
function Button($name) { return @(Buttons $name) | Select-Object -First 1 }
function Value { Refresh-Editor; $script:editor.GetCurrentPattern([Windows.Automation.ValuePattern]::Pattern).Current.Value }
function Invoke-UI($name) { $b=Button $name; if (!$b -or !$b.Current.IsEnabled) { throw "Bouton indisponible : $name" }; $b.GetCurrentPattern([Windows.Automation.InvokePattern]::Pattern).Invoke() }
while ($null -ne ($line=[Console]::ReadLine())) {
 try {
  $q=$line|ConvertFrom-Json
  switch ($q.op) {
   'capture_target' {
    $script:targetElement=$null; $script:targetRange=$null; $script:targetId=$null; $script:targetPid=$null
    try {
     $script:targetElement=$A::FocusedElement
     if ($null -ne $script:targetElement) {
      $script:targetId=$script:targetElement.GetRuntimeId(); $script:targetPid=$script:targetElement.Current.ProcessId
      $pattern=$null
      if ($script:targetElement.TryGetCurrentPattern([Windows.Automation.TextPattern]::Pattern,[ref]$pattern)) {
       $selection=$pattern.GetSelection(); if ($selection.Count -eq 1) { $script:targetRange=$selection[0].Clone() }
      }
     }
    } catch { $script:targetElement=$null; $script:targetRange=$null }
    $r=@{ok=$true;captured=($null -ne $script:targetElement);caret=($null -ne $script:targetRange)}
   }
   'restore_target' {
    $verified=$false
    if ($null -ne $script:targetElement -and $null -ne $script:targetId) {
     $script:targetElement.SetFocus(); if ($null -ne $script:targetRange) { $script:targetRange.Select() }
     $focused=$A::FocusedElement
     if ($null -ne $focused -and $focused.Current.ProcessId -eq $script:targetPid) {
      $verified=Test-TargetIdentity $script:targetPid $focused.Current.ProcessId $script:targetId ($focused.GetRuntimeId()) ($null -ne $script:targetRange)
     }
    }
    $r=@{ok=$true;verified=$verified}
   }
   'ensure' { Connect-App $true $true; $r=@{ok=$true;hwnd=$script:window.Current.NativeWindowHandle} }
   'ping' { $r=@{ok=$true} }
   'diagnose' { Connect-App $false; $r=@{ok=$true;connected=$true;draft_nonempty=(-not [string]::IsNullOrWhiteSpace([string](Value)));recording=($null -ne (Button 'Terminer la dictée'));dictation_button=($null -ne (Button 'Dicter'))} }
   'read_walk' {
    Connect-App $false
    $walker=[Windows.Automation.TreeWalker]::ControlViewWalker; $stack=[Collections.Generic.Stack[Windows.Automation.AutomationElement]]::new(); $stack.Push($script:window); $items=@()
    while ($stack.Count -gt 0) {
     $node=$stack.Pop()
     if ($node.Current.ControlType -eq $C::Edit) { $pat=$null; if ($node.TryGetCurrentPattern([Windows.Automation.ValuePattern]::Pattern,[ref]$pat)) { $items+=@{name=$node.Current.Name;value=$pat.Current.Value} } }
     $child=$walker.GetFirstChild($node)
     while ($null -ne $child) { $stack.Push($child); $child=$walker.GetNextSibling($child) }
    }
    $r=@{ok=$true;editors=$items}
   }
   'read' { Connect-App $false; $r=@{ok=$true;text=(Value);hwnd=$script:window.Current.NativeWindowHandle;recording=($null -ne (Button 'Terminer la dictée'))} }
   'focus_editor' { Connect-App $false; $script:editor.SetFocus(); $r=@{ok=$true;hwnd=$script:window.Current.NativeWindowHandle} }
   'clear_saved' {
    if ((Value) -cne $q.text) { throw 'Texte Claude modifié avant extraction.' }
    $pattern=$script:editor.GetCurrentPattern([Windows.Automation.ValuePattern]::Pattern)
    try { $pattern.SetValue('') } catch { }
    $until=[DateTime]::UtcNow.AddMilliseconds(700)
    do { Start-Sleep -Milliseconds 100; $current=[string](Value) } while (-not [string]::IsNullOrWhiteSpace($current) -and [DateTime]::UtcNow -lt $until)
    if (-not [string]::IsNullOrWhiteSpace($current) -and $current -cne $q.text) { throw 'Texte Claude modifié pendant extraction.' }
    $r=@{ok=$true;empty=[string]::IsNullOrWhiteSpace($current)}
   }
   'verify_empty' { $r=@{ok=$true;empty=([string]::IsNullOrWhiteSpace([string](Value)))} }
   'adopt_recording' { Connect-App $false; if ($null -eq (Button 'Terminer la dictée')) { throw 'Dictée active non confirmée.' }; $script:started=$true; $r=@{ok=$true} }
   'cancel' { Connect-App $false; if ($null -ne (Button 'Annuler la dictée')) { Invoke-UI 'Annuler la dictée' }; $script:started=$false; $r=@{ok=$true} }
   'start' {
    Connect-App $true
    if (-not [string]::IsNullOrWhiteSpace([string](Value))) { throw 'Brouillon Claude non vide, conservé.' }
    if ($null -ne (Button 'Terminer la dictée')) { throw 'Une dictée est déjà en cours.' }
    $script:stopDispatched=$false
    Invoke-UI 'Dicter'; $until=[DateTime]::UtcNow.AddSeconds(10); $found=$false
    do { Start-Sleep -Milliseconds 100; if ($null -ne (Button 'Terminer la dictée')) { $found=$true; break } } while ([DateTime]::UtcNow -lt $until)
    if (!$found) { throw 'Démarrage non confirmé.' }; $script:started=$true; $r=@{ok=$true}
   }
   'dispatch_stop' {
    if (!$script:started) { throw 'Aucune dictée confirmée.' }
    $originalHwnd=$script:window.Current.NativeWindowHandle
    Invoke-StopWhenReady $originalHwnd 10
    $script:started=$false; $script:stopDispatched=$true; $r=@{ok=$true}
   }
   'rearm_check' {
    Connect-App $false
    if ($script:window.Current.NativeWindowHandle -ne $q.hwnd) { throw 'Fenêtre Claude différente ; récupération manuelle nécessaire.' }
    $recording=$null -ne (Button 'Terminer la dictée'); $idle=$null -ne (Button 'Dicter'); $draft=[string](Value)
    $path=$null
    if (-not [string]::IsNullOrWhiteSpace($draft)) {
     $dir=Join-Path $PSScriptRoot 'recovery'; [IO.Directory]::CreateDirectory($dir)|Out-Null
     $path=Join-Path $dir ('dictation-'+[Guid]::NewGuid().ToString('N')+'.txt'); [IO.File]::WriteAllText($path,$draft,[Text.UTF8Encoding]::new($false))
    }
    $r=@{ok=$true;safe=((-not $recording) -and $idle -and [string]::IsNullOrWhiteSpace($draft));recovery=$path}
   }
   'await_text' {
    if (!$script:stopDispatched) { throw 'Arrêt non déclenché.' }
    $until=[DateTime]::UtcNow.AddSeconds(60); $last=$null; $since=$null; $done=$false; $idleSince=$null; $path=$null
    $dir=Join-Path $PSScriptRoot 'recovery'; [IO.Directory]::CreateDirectory($dir)|Out-Null
    do {
     Start-Sleep -Milliseconds 200; $recording=$null -ne (Button 'Terminer la dictée'); $value=[string](Value)
     if ($recording) { $last=$null; $since=$null; $idleSince=$null; continue }
     if ([string]::IsNullOrWhiteSpace($value)) {
      if ($null -ne (Button 'Dicter')) {
       if ($null -eq $idleSince) { $idleSince=[DateTime]::UtcNow }
       elseif (([DateTime]::UtcNow-$idleSince).TotalSeconds -ge 3) { break }
      }
      $last=$null; $since=$null; continue
     }
     $idleSince=$null
     if ($value -cne $last) {
      $last=$value; $since=[DateTime]::UtcNow
      $path=Join-Path $dir ('dictation-'+[Guid]::NewGuid().ToString('N')+'.txt'); [IO.File]::WriteAllText($path,$value,[Text.UTF8Encoding]::new($false))
      continue
     }
     if ($null -ne (Button 'Dicter') -and ([DateTime]::UtcNow-$since).TotalSeconds -ge 2) {
      $verify=[string](Value)
      if ($verify -cne $value) {
       if (-not [string]::IsNullOrWhiteSpace($verify)) {
        $path=Join-Path $dir ('dictation-'+[Guid]::NewGuid().ToString('N')+'.txt'); [IO.File]::WriteAllText($path,$verify,[Text.UTF8Encoding]::new($false))
       }
       $last=$null; continue
      }
      $done=$true; break
     }
    } while ([DateTime]::UtcNow -lt $until)
    if (!$done -and $null -ne $idleSince -and [string]::IsNullOrWhiteSpace($value) -and !$path) { $script:stopDispatched=$false; $r=@{ok=$true;empty=$true}; break }
    if (!$done) { $r=@{ok=$false;error='Fin ou transcription non confirmée ; récupération nécessaire.';recovery=$path}; break }
    $script:stopDispatched=$false
    $r=@{ok=$true;text=$value;recovery=$path;hwnd=$script:window.Current.NativeWindowHandle}
   }
   default { throw 'Commande inconnue.' }
  }
 } catch { $message=$_.Exception.Message; $r=@{ok=$false;error=$message}; if ($message.StartsWith('STOP_NOT_INVOKED:')) { $r.code='stop_not_invoked' } }
 [Console]::WriteLine(($r|ConvertTo-Json -Compress -Depth 5))
}
