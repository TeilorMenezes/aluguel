$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $ProjectRoot

$PythonArgs = @()
$Python = $null
$PyLauncher = Get-Command "py.exe" -ErrorAction SilentlyContinue
if ($PyLauncher) {
    $Python = $PyLauncher.Source
    $PythonArgs = @("-3.11")
} else {
    $Candidates = @(
        (Join-Path $env:LOCALAPPDATA "Programs\Python\Python311\python.exe"),
        (Join-Path $env:LOCALAPPDATA "Programs\Python\Python312\python.exe"),
        (Join-Path $env:LOCALAPPDATA "Programs\Python\Python313\python.exe")
    )
    $Python = $Candidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
}

if (-not $Python) {
    Write-Host "Python 3.11 ou mais recente nao foi encontrado." -ForegroundColor Red
    Write-Host "Instale o Python e tente novamente."
    Read-Host "Pressione Enter para fechar"
    exit 1
}

& $Python @PythonArgs -c "import streamlit, playwright, yaml, bs4, requests, psutil" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "As dependencias do aplicativo ainda nao estao instaladas." -ForegroundColor Yellow
    Write-Host "Instalando agora; isso pode levar alguns minutos..."
    & $Python @PythonArgs -m pip install -r requirements.txt
    if ($LASTEXITCODE -ne 0) {
        Write-Host "A instalacao falhou. Verifique a conexao com a internet." -ForegroundColor Red
        Read-Host "Pressione Enter para fechar"
        exit 1
    }
}

Write-Host ""
Write-Host "Agente de Expansao iniciando em http://127.0.0.1:8502" -ForegroundColor Green
Write-Host "Mantenha esta janela aberta. Para encerrar, pressione Ctrl+C."
Write-Host ""

& $Python @PythonArgs -m streamlit run agente_expansao/app.py `
    --server.address=127.0.0.1 `
    --server.port=8502 `
    --server.headless=false `
    --browser.gatherUsageStats=false
