# scripts/setup.ps1
# Configura o ambiente virtual e instala todas as dependencias
# Uso: .\scripts\setup.ps1

$root = Split-Path $PSScriptRoot -Parent

Write-Host "--- Configurando Ambiente para PDF Extractor API ---" -ForegroundColor Cyan

# 1. Criar o venv se nao existir
if (-not (Test-Path "$root\venv")) {
    Write-Host "Criando ambiente virtual..." -ForegroundColor Yellow
    python -m venv "$root\venv"
} else {
    Write-Host "Ambiente virtual ja existe." -ForegroundColor Green
}

# 2. Instalar dependencias
Write-Host "Instalando dependencias..." -ForegroundColor Yellow
& "$root\venv\Scripts\python.exe" -m pip install --upgrade pip
& "$root\venv\Scripts\pip.exe" install -r "$root\requirements.txt"

Write-Host ""
Write-Host "--- Configuracao Concluida! ---" -ForegroundColor Green
Write-Host "Para iniciar a API:  .\scripts\run.ps1" -ForegroundColor Cyan
Write-Host "Para desenvolvimento: .\scripts\run.ps1 -Reload" -ForegroundColor Cyan
Write-Host "Documentacao:        http://localhost:8000/docs" -ForegroundColor Green
