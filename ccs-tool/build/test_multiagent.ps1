$ErrorActionPreference = 'Continue'
Set-Location (Split-Path $PSScriptRoot -Parent)
$testHome = Join-Path (Get-Location) '.agenttest'
if (Test-Path $testHome) { Remove-Item -Recurse -Force $testHome -ErrorAction SilentlyContinue }
New-Item -ItemType Directory -Force $testHome | Out-Null
$agentsJson = @'
{
  "mockclaude": {
    "aliases": ["mockclaude"],
    "new": ["{exe}", "--session-id", "{sid}", "--name", "{name}"],
    "new_flag": "--session-id",
    "resume": ["{exe}", "--resume", "{sid}"],
    "continue": ["{exe}", "--continue"],
    "id_regex": ["session id[: ]+([0-9a-fA-F-]{36})"]
  },
  "mockcodex": {
    "aliases": ["mockcodex"],
    "new": ["{exe}"],
    "resume": ["{exe}", "resume", "{sid}"],
    "continue": ["{exe}", "resume", "--last"],
    "id_regex": ["session id[: ]+([0-9a-fA-F-]{36})"]
  }
}
'@
Set-Content -Path (Join-Path $testHome 'agents.json') -Value $agentsJson -Encoding UTF8
$env:CCS_HOME = $testHome
$env:MOCK_LOG = Join-Path $testHome 'mock.log'
$env:PATH = (Join-Path (Get-Location) 'build\mock') + ';' + $env:PATH
Write-Host '--- new sessions ---'
python ccs.py daemon start
python ccs.py new a1 -- mockclaude
python ccs.py new b1 -- mockcodex
Start-Sleep -Seconds 2
Write-Host '--- ls ---'
python ccs.py ls --json
Write-Host '--- stop + restore ---'
python ccs.py daemon stop
Start-Sleep -Milliseconds 500
python ccs.py restore
Start-Sleep -Seconds 1
python ccs.py ls
Write-Host '--- mock launch log ---'
Get-Content $env:MOCK_LOG
python ccs.py daemon stop
