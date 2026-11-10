param([switch]$Check)
$ErrorActionPreference = 'Stop'
$name = 'CodexClaudeDictationHeadless'
$task = Get-ScheduledTask -TaskPath '\' -TaskName $name -ErrorAction SilentlyContinue
if (-not $task) { Write-Output "Tâche $name absente ; aucune modification."; exit 0 }
[xml]$xml = Export-ScheduledTask -TaskPath '\' -TaskName $name
$ns = [Xml.XmlNamespaceManager]::new($xml.NameTable); $ns.AddNamespace('t','http://schemas.microsoft.com/windows/2004/02/mit/task')
$actions = @($xml.SelectNodes('/t:Task/t:Actions/*',$ns))
$command = $xml.SelectSingleNode('/t:Task/t:Actions/t:Exec/t:Command',$ns)
$arguments = $xml.SelectSingleNode('/t:Task/t:Actions/t:Exec/t:Arguments',$ns)
$script = Join-Path $PSScriptRoot 'claude_headless\main.py'
if ($actions.Count -ne 1 -or $actions[0].LocalName -ne 'Exec' -or -not $command -or
    [IO.Path]::GetFileName($command.InnerText) -ine 'pythonw.exe' -or -not $arguments -or $arguments.InnerText -cne ('"' + $script + '"')) {
    throw "La tâche $name ne lance pas ce service ; elle est conservée."
}
if ($task.State -eq 'Disabled') { Write-Output "Tâche $name déjà désactivée."; exit 0 }
if ($Check) { Write-Output "Tâche $name activée ; elle peut être désactivée sans arrêter le service."; exit 0 }
Disable-ScheduledTask -TaskPath '\' -TaskName $name | Out-Null
Write-Output "Tâche $name désactivée. Le service actuellement lancé continue de fonctionner."
