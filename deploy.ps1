# ================================================
#  Invoice Manager - One-Click Docker Deployment
#  (Windows PowerShell)
# ================================================

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

function Write-Step($msg) { Write-Host "[✓] $msg" -ForegroundColor Green }
function Write-Warn($msg) { Write-Host "[!] $msg" -ForegroundColor Yellow }
function Write-Error($msg) { Write-Host "[✗] $msg" -ForegroundColor Red }
function Write-Info($msg)  { Write-Host "[i] $msg" -ForegroundColor Blue }

# ---------- Pre-flight checks ----------
function Check-Prerequisites {
    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
        Write-Error "Docker is not installed. Please install Docker Desktop first."
        Write-Error "Download: https://docs.docker.com/desktop/install/windows-install/"
        exit 1
    }

    $composeVersion = docker compose version 2>$null
    if (-not $composeVersion) {
        Write-Error "Docker Compose (v2) is not available. Please upgrade Docker Desktop."
        exit 1
    }

    Write-Step "Docker Compose v2 detected"
}

# ---------- Prepare .env ----------
function Prepare-Env {
    if (Test-Path ".env") {
        Write-Warn ".env already exists, skipping creation"
        return
    }

    if (Test-Path ".env.example") {
        Copy-Item ".env.example" ".env"
        Write-Step "Created .env from .env.example"
        Write-Warn "Please edit .env to configure LLM provider and set strong passwords!"
    } else {
        @"
POSTGRES_USER=postgres
POSTGRES_PASSWORD=ChangeMe123!
POSTGRES_DB=invoice_db
DATABASE_URL=postgresql+asyncpg://postgres:ChangeMe123!@db:5432/invoice_db
DEBUG=false
"@ | Out-File -FilePath ".env" -Encoding utf8

        Write-Step "Created default .env"
        Write-Warn "Using default passwords. Edit .env for production!"
    }

    # Copy docker-compose template if not exists
    if (-not (Test-Path "docker-compose.yml")) {
        if (Test-Path "docker-compose.yml.example") {
            Copy-Item "docker-compose.yml.example" "docker-compose.yml"
            Write-Step "Created docker-compose.yml from .example"
        }
    }
}

# ---------- Start services ----------
function Start-Services {
    # Ensure uploads directory exists for Docker bind mount
    New-Item -ItemType Directory -Force -Path "uploads" | Out-Null

    Write-Info "Building and starting services..."
    docker compose up -d --build

    Write-Info "Waiting for backend to be ready..."
    $maxWait = 90
    $elapsed = 0
    while ($elapsed -lt $maxWait) {
        try {
            $response = Invoke-WebRequest -Uri "http://localhost:18080/api/invoices?page=1&page_size=1" -UseBasicParsing -TimeoutSec 3
            if ($response.StatusCode -eq 200) {
                Write-Step "Backend is healthy"
                break
            }
        } catch {
            # Still starting
        }
        Start-Sleep -Seconds 3
        $elapsed += 3
        if ($elapsed % 9 -eq 0) {
            Write-Info "Waiting... (${elapsed}s)"
        }
    }

    if ($elapsed -ge $maxWait) {
        Write-Warn "Backend health check timed out. Check logs: docker compose logs backend"
    }
}

# ---------- Print info ----------
function Print-Info {
    Write-Host ""
    Write-Host "================================================" -ForegroundColor Green
    Write-Host "   Invoice Manager Deployed Successfully!" -ForegroundColor Green
    Write-Host "================================================" -ForegroundColor Green
    Write-Host ""
    Write-Host "  Frontend:  http://localhost:15173" -ForegroundColor Blue
    Write-Host "  Backend:   http://localhost:18080" -ForegroundColor Blue
    Write-Host "  API Docs:  http://localhost:18080/docs" -ForegroundColor Blue
    Write-Host ""
    Write-Host "  Uploaded files: $PSScriptRoot\uploads\" -ForegroundColor Yellow
    Write-Host "  PostgreSQL data: stored in Docker volume 'postgres_data'"
    Write-Host ""
    Write-Host "  Commands:"
    Write-Host "    查看日志:  docker compose logs -f"
    Write-Host "    停止服务:  docker compose down"
    Write-Host "    重启服务:  docker compose restart"
    Write-Host ""
}

# ---------- Main ----------
function Main {
    Write-Host ""
    Write-Host "╔══════════════════════════════════════════╗" -ForegroundColor Blue
    Write-Host "║   Invoice Manager - One-Click Deploy    ║" -ForegroundColor Blue
    Write-Host "╚══════════════════════════════════════════╝" -ForegroundColor Blue
    Write-Host ""

    Check-Prerequisites
    Prepare-Env
    Start-Services
    Print-Info
}

Main
