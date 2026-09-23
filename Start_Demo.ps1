$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
& docker info --format '{{.ServerVersion}}'
if ($LASTEXITCODE -ne 0) { throw 'Please start Docker Desktop (Linux engine) first.' }
& docker image inspect vcme-storymem:transition-v27 *> $null
if ($LASTEXITCODE -ne 0) {
    $image = Join-Path $PSScriptRoot 'runtime\vcme-storymem.tar'
    if (-not (Test-Path -LiteralPath $image)) { throw 'Missing runtime image archive.' }
    & docker load --input $image
    if ($LASTEXITCODE -ne 0) { throw 'Runtime image import failed.' }
}
$env:PYTHONDONTWRITEBYTECODE='1'
Write-Host 'Open http://127.0.0.1:7860 in a browser. Ctrl+C stops the UI.'
& python -u app/server.py
