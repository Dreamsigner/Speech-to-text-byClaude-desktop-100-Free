$ErrorActionPreference = 'Stop'
$tokens=$null; $errors=$null
$ast=[System.Management.Automation.Language.Parser]::ParseFile((Join-Path $PSScriptRoot 'uia_bridge.ps1'),[ref]$tokens,[ref]$errors)
if ($errors.Count) { throw 'Pont PowerShell invalide.' }
$switch=$ast.Find({param($node) $node -is [System.Management.Automation.Language.SwitchStatementAst]},$true)
$clause=@($switch.Clauses | Where-Object { $_.Item1.Extent.Text -eq "'await_text'" })
if ($clause.Count -ne 1) { throw 'Branche await_text introuvable.' }
$body=$clause[0].Item2.Extent.Text
# Shorten only the clock limits and polling interval; execute the production AST body.
$body=$body.Replace('AddSeconds(60)','AddSeconds(2)').Replace('Milliseconds 200','Milliseconds 10').Replace('TotalSeconds -ge 3','TotalSeconds -ge 0.15').Replace('TotalSeconds -ge 2','TotalSeconds -ge 0.1').Replace('$PSScriptRoot','$script:testRoot')
$run=[scriptblock]::Create("switch ('await_text') { 'await_text' $body }; return `$r")
$script:testRoot=Join-Path ([IO.Path]::GetTempPath()) ('dictation-test-'+[Guid]::NewGuid().ToString('N'))
[IO.Directory]::CreateDirectory($script:testRoot) | Out-Null
$script:window=@{Current=@{NativeWindowHandle=42}}
function Button($name) {
 if ($name -ne 'Dicter') { $script:verifyNext=$false; return $null }
 $script:verifyNext=$true; return 'idle'
}
function Value {
 if ($script:mode -eq 'drift') {
  if ($script:verifyNext -and -not $script:changed) { $script:changed=$true; return 'nouveau texte' }
  if ($script:changed) { return 'nouveau texte' }
  return 'ancien texte'
 }
 if ($script:mode -eq 'vanish') {
  if ($script:verifyNext -and -not $script:changed) { $script:changed=$true; return '' }
  if ($script:changed) { return '' }
  return 'texte sauvegarde'
 }
}
try {
 $script:mode='drift'; $script:changed=$false; $script:verifyNext=$false; $script:stopDispatched=$true
 $result=& $run
 if (-not $result.ok -or $result.text -cne 'nouveau texte' -or [IO.File]::ReadAllText($result.recovery) -cne 'nouveau texte') { throw 'Variation pendant vérification finale perdue.' }
 if (-not $script:changed) { throw 'Vérification finale non exercée.' }
 $script:mode='vanish'; $script:changed=$false; $script:verifyNext=$false; $script:stopDispatched=$true
 $result=& $run
 if ($result.ok -or -not $result.recovery -or [IO.File]::ReadAllText($result.recovery) -cne 'texte sauvegarde') { throw 'Candidat disparu sans récupération.' }
 Write-Host '2 tests de stabilisation réussis.'
} finally {
 $resolved=[IO.Path]::GetFullPath($script:testRoot)
 $tempBase=[IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd('\')+'\'
 if (-not $resolved.StartsWith($tempBase,[StringComparison]::OrdinalIgnoreCase) -or [IO.Path]::GetFileName($resolved) -notmatch '^dictation-test-[0-9a-f]{32}$') { throw 'Unexpected test cleanup path.' }
 Remove-Item -LiteralPath $resolved -Recurse -Force -ErrorAction SilentlyContinue
}


