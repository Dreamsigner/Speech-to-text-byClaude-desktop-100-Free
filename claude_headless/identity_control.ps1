function Test-TargetIdentity($expectedPid, $actualPid, $expectedId, $actualId, $hasSelection) {
 if (!$hasSelection -or $expectedPid -ne $actualPid -or $null -eq $expectedId -or $null -eq $actualId -or $expectedId.Count -eq 0 -or $actualId.Count -eq 0) { return $false }
 return [Windows.Automation.Automation]::Compare([int[]]$expectedId,[int[]]$actualId)
}
