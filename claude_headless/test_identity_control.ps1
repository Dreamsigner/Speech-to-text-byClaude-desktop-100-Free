$ErrorActionPreference='Stop'
Add-Type -AssemblyName UIAutomationClient
. (Join-Path $PSScriptRoot 'identity_control.ps1')
if (!(Test-TargetIdentity 42 42 @(1,2,3) @(1,2,3) $true)) { throw 'Identical target was rejected.' }
if (Test-TargetIdentity 42 42 @(1,2,3) @(1,2,4) $true) { throw 'Different runtime ID was accepted.' }
if (Test-TargetIdentity 42 43 @(1,2,3) @(1,2,3) $true) { throw 'Different process was accepted.' }
if (Test-TargetIdentity 42 42 @(1,2,3) @(1,2,3) $false) { throw 'Missing selection was accepted.' }
if (Test-TargetIdentity 42 42 @() @() $true) { throw 'Empty runtime ID was accepted.' }
Write-Output 'Target identity tests passed.'
