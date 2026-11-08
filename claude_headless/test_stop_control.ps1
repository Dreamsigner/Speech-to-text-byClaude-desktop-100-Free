$ErrorActionPreference='Stop'
Add-Type -AssemblyName UIAutomationClient
. (Join-Path $PSScriptRoot 'stop_control.ps1')
function Write-StopDiagnostic($state, $hwnd, $attempt) { }
class FakePattern {
 static [int]$Calls=0
 static [bool]$Fail=$false
 [void] Invoke() { [FakePattern]::Calls++; if ([FakePattern]::Fail) { throw 'invoke uncertain' } }
}
class FakeButton {
 [object]$Current
 FakeButton([bool]$enabled) { $this.Current=@{IsEnabled=$enabled; IsOffscreen=$false} }
 [object] GetCurrentPattern($ignored) { return [FakePattern]::new() }
}
$script:window=@{Current=@{NativeWindowHandle=123}}
$script:steps=0
function Connect-App($launch,$windowOnly) { }
function Buttons($name) { if ($name -cne 'Terminer la dictée') { throw "Unexpected button name: $name" }; $script:steps++; if ($script:steps -eq 1) { return $null }; if ($script:steps -eq 2) { return [FakeButton]::new($false) }; return [FakeButton]::new($true) }
Invoke-StopWhenReady 123 2
if ([FakePattern]::Calls -ne 1 -or $script:steps -ne 3) { throw 'Expected one invocation after unavailable controls.' }
[FakePattern]::Calls=0; [FakePattern]::Fail=$true; $script:steps=2
try { Invoke-StopWhenReady 123 2; throw 'Expected error' } catch { if ($_.Exception.Message -ne 'invoke uncertain') { throw } }
if ([FakePattern]::Calls -ne 1) { throw 'An uncertain invocation must never be repeated.' }
[FakePattern]::Calls=0; [FakePattern]::Fail=$false
try { Invoke-StopWhenReady 456 0; throw 'Expected error' } catch { if (!$_.Exception.Message.StartsWith('STOP_NOT_INVOKED:')) { throw } }
if ([FakePattern]::Calls -ne 0) { throw 'Changed window must not be invoked.' }
$hidden=[FakeButton]::new($true); $hidden.Current.IsOffscreen=$true
$disabled=[FakeButton]::new($false); $active=[FakeButton]::new($true)
if ((Select-StopCandidate @($hidden,$disabled,$active)) -ne $active) { throw 'Expected unique visible enabled control.' }
try { Select-StopCandidate @($active,[FakeButton]::new($true)); throw 'Expected ambiguity error' } catch { if (!$_.Exception.Message.StartsWith('Plusieurs boutons')) { throw } }
Write-Output 'Stop control tests passed.' 
