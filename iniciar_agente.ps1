$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -LiteralPath $ProjectRoot

& (Join-Path $ProjectRoot "agente_expansao\iniciar_agente.ps1")
exit $LASTEXITCODE
