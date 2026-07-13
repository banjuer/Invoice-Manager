#!/usr/bin/env bash
set -euo pipefail

# ================================================
#  Invoice Manager - One-Click Docker Deployment
# ================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log()   { echo -e "${GREEN}[✓]${NC} $1"; }
warn()  { echo -e "${YELLOW}[!]${NC} $1"; }
error() { echo -e "${RED}[✗]${NC} $1"; }
info()  { echo -e "${BLUE}[i]${NC} $1"; }

# ---------- Pre-flight checks ----------
check_prerequisites() {
  if ! command -v docker &>/dev/null; then
    error "Docker is not installed. Please install Docker first."
    error "Download: https://docs.docker.com/get-docker/"
    exit 1
  fi

  if ! docker compose version &>/dev/null; then
    error "Docker Compose (v2) is not available. Please upgrade Docker."
    exit 1
  fi

  log "Docker $(docker --version | cut -d' ' -f3 | tr -d ',') + Compose v2 detected"
}

# ---------- Prepare .env ----------
prepare_env() {
  if [ -f ".env" ]; then
    warn ".env already exists, skipping creation"
    return
  fi

  if [ -f ".env.example" ]; then
    cp .env.example .env
    log "Created .env from .env.example"
    warn "Please edit .env to configure LLM provider and set strong passwords!"
  else
    # Generate fallback .env
    cat > .env <<'EOF'
POSTGRES_USER=postgres
POSTGRES_PASSWORD=ChangeMe123!
POSTGRES_DB=invoice_db
DATABASE_URL=postgresql+asyncpg://postgres:ChangeMe123!@db:5432/invoice_db
DEBUG=false
EOF
    log "Created default .env"
    warn "Using default passwords. Edit .env for production!"
  fi

  # Copy docker-compose template if not exists
  if [ ! -f "docker-compose.yml" ]; then
    if [ -f "docker-compose.yml.example" ]; then
      cp docker-compose.yml.example docker-compose.yml
      log "Created docker-compose.yml from .example"
    fi
  fi
}

# ---------- Start services ----------
start_services() {
  # Ensure uploads directory exists for Docker bind mount
  mkdir -p uploads

  info "Building and starting services..."
  docker compose up -d --build

  info "Waiting for services to be ready..."
  local max_wait=60
  local elapsed=0
  while [ $elapsed -lt $max_wait ]; do
    if curl -s -o /dev/null -w "%{http_code}" http://localhost:18080/api/invoices?page=1\&page_size=1 2>/dev/null | grep -q "200"; then
      log "Backend is healthy"
      break
    fi
    sleep 2
    elapsed=$((elapsed + 2))
    info "Waiting... (${elapsed}s)"
  done

  if [ $elapsed -ge $max_wait ]; then
    warn "Backend health check timed out. Check logs: docker compose logs backend"
  fi
}

# ---------- Print info ----------
print_info() {
  echo ""
  echo -e "${GREEN}================================================${NC}"
  echo -e "${GREEN}   Invoice Manager Deployed Successfully!${NC}"
  echo -e "${GREEN}================================================${NC}"
  echo ""
  echo -e "  Frontend:  ${BLUE}http://localhost:15173${NC}"
  echo -e "  Backend:   ${BLUE}http://localhost:18080${NC}"
  echo -e "  API Docs:  ${BLUE}http://localhost:18080/docs${NC}"
  echo ""
  echo -e "  Uploaded files: ${YELLOW}$SCRIPT_DIR/uploads/${NC}"
  echo -e "  PostgreSQL data: ${YELLOW}$(docker volume inspect invoice-manager_postgres_data --format '{{.Mountpoint}}' 2>/dev/null || echo '<docker volume>')${NC}"
  echo ""
  echo "  Commands:"
  echo "    查看日志:  docker compose logs -f"
  echo "    停止服务:  docker compose down"
  echo "    重启服务:  docker compose restart"
  echo ""
}

# ---------- Main ----------
main() {
  echo -e "${BLUE}"
  echo "╔══════════════════════════════════════════╗"
  echo "║   Invoice Manager - One-Click Deploy    ║"
  echo "╚══════════════════════════════════════════╝"
  echo -e "${NC}"

  check_prerequisites
  prepare_env
  start_services
  print_info
}

main "$@"
