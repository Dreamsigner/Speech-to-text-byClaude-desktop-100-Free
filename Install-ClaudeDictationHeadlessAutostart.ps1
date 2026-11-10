param([switch]$Check)
$ErrorActionPreference = 'Stop'
$name = 'CodexClaudeDictationHeadless'
$path = '\'
$script = Join-Path $PSScriptRoot 'claude_headless\main.py'
$python = (Get-Command pythonw.exe -CommandType Application -ErrorAction Stop | Select-Object -First 1).Source
if (-not (Test-Path -LiteralPath $script -PathType Leaf)) { throw "Service introuvable : $script" }
$user = [Security.Principal.WindowsIdentity]::GetCurrent().Name
$sid = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
foreach ($old in @('CodexLocalDictation','CodexClaudeDictation')) {
    $task = Get-ScheduledTask -TaskPath $path -TaskName $old -ErrorAction SilentlyContinue
    if ($task -and $task.State -ne 'Disabled') { throw "Tâche concurrente active : $old. Aucune modification effectuée." }
}
foreach ($runPath in @('HKCU:\Software\Microsoft\Windows\CurrentVersion\Run','HKLM:\Software\Microsoft\Windows\CurrentVersion\Run','HKLM:\Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Run')) {
    foreach ($old in @('CodexLocalDictation','CodexClaudeDictation','CodexClaudeDictationHeadless')) {
        $entry = Get-ItemProperty -LiteralPath $runPath -Name $old -ErrorAction SilentlyContinue
        if ($null -ne $entry) { throw "Entrée Run concurrente présente : $old ($runPath). Aucune modification effectuée." }
    }
}
$existing = Get-ScheduledTask -TaskPath $path -TaskName $name -ErrorAction SilentlyContinue
if ($existing) {
    [xml]$xml = Export-ScheduledTask -TaskPath $path -TaskName $name
    $ns = [Xml.XmlNamespaceManager]::new($xml.NameTable); $ns.AddNamespace('t','http://schemas.microsoft.com/windows/2004/02/mit/task')
    function Nodes($query) { @($xml.SelectNodes($query,$ns)) }
    function Text($query) { $node=$xml.SelectSingleNode($query,$ns); if ($node) { $node.InnerText } else { '' } }
    $action = @(Nodes '/t:Task/t:Actions/*'); $trigger = @(Nodes '/t:Task/t:Triggers/*')
    $principal = Text '/t:Task/t:Principals/t:Principal/t:UserId'
    try { $principalSid = ([Security.Principal.NTAccount]$principal).Translate([Security.Principal.SecurityIdentifier]).Value } catch { $principalSid = $principal }
    $triggerUser = Text '/t:Task/t:Triggers/t:LogonTrigger/t:UserId'
    try { $triggerSid = ([Security.Principal.NTAccount]$triggerUser).Translate([Security.Principal.SecurityIdentifier]).Value } catch { $triggerSid = $triggerUser }
    $runLevel = Text '/t:Task/t:Principals/t:Principal/t:RunLevel'
    $valid = $existing.State -ne 'Disabled' -and $action.Count -eq 1 -and $action[0].LocalName -eq 'Exec' -and
        (Text '/t:Task/t:Actions/t:Exec/t:Command') -ieq $python -and (Text '/t:Task/t:Actions/t:Exec/t:Arguments') -ceq ('"' + $script + '"') -and
        (Text '/t:Task/t:Actions/t:Exec/t:WorkingDirectory') -ieq $PSScriptRoot -and $trigger.Count -eq 1 -and $trigger[0].LocalName -eq 'LogonTrigger' -and
        $triggerSid -eq $sid -and (Text '/t:Task/t:Triggers/t:LogonTrigger/t:Delay') -eq 'PT15S' -and $principalSid -eq $sid -and
        (Text '/t:Task/t:Principals/t:Principal/t:LogonType') -eq 'InteractiveToken' -and ($runLevel -eq '' -or $runLevel -eq 'LeastPrivilege') -and
        (Text '/t:Task/t:Settings/t:MultipleInstancesPolicy') -eq 'IgnoreNew' -and (Text '/t:Task/t:Settings/t:DisallowStartIfOnBatteries') -eq 'false' -and
        (Text '/t:Task/t:Settings/t:StopIfGoingOnBatteries') -eq 'false' -and (Text '/t:Task/t:Settings/t:ExecutionTimeLimit') -eq 'PT0S'
    if (-not $valid) { throw "La tâche $name existe avec une configuration différente ; elle est conservée. Aucune modification effectuée." }
    Write-Output "La tâche $name est déjà conforme et activée."; exit 0
}
if ($Check) { Write-Output "Aucun conflit connu ; la tâche $name peut être créée pour $user."; exit 0 }
$action = New-ScheduledTaskAction -Execute $python -Argument ('"' + $script + '"') -WorkingDirectory $PSScriptRoot
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $user; $trigger.Delay = 'PT15S'
$principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Seconds 0) -MultipleInstances IgnoreNew
# Register without -Force: a concurrent creation must never be overwritten.
Register-ScheduledTask -TaskPath $path -TaskName $name -Action $action -Trigger $trigger -Principal $principal -Settings $settings | Out-Null
Write-Output "Tâche $name installée pour $user : ouverture de session + 15 secondes."
