# scripts/run.ps1
# Roda a API FastAPI usando o venv local
# Uso: .\scripts\run.ps1
#      .\scripts\run.ps1 --reload   (hot-reload para desenvolvimento)

param(
    [switch]$Reload,
    [int]$Port = 8000,
    [string]$Host = "0.0.0.0"
)

$root = Split-Path $PSScriptRoot -Parent

if (-not (Test-Path "$root\venv")) {
    Write-Host "Ambiente nao configurado. Rode .\scripts\setup.ps1 primeiro." -ForegroundColor Red
    exit 1
}

$uvicorn = "$root\venv\Scripts\uvicorn.exe"
if (-not (Test-Path $uvicorn)) {
    Write-Host "uvicorn nao encontrado. Rode .\scripts\setup.ps1 primeiro." -ForegroundColor Red
    exit 1
}

$args = @("app.main:app", "--host", $Host, "--port", $Port)
if ($Reload) { $args += "--reload" }

Write-Host "Iniciando API em http://${Host}:${Port}" -ForegroundColor Cyan
Write-Host "Documentacao: http://localhost:${Port}/docs" -ForegroundColor Green
Write-Host ""

Set-Location $root
& $uvicorn @args
