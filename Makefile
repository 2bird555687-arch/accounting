# ── AccCloud Makefile ─────────────────────────────────────────────────────────
# Usage: make <target>
# Requires: Docker, Docker Compose, Python 3.11+

.PHONY: help dev build deploy stop restart logs shell backup restore \
        init-db migrate test lint format clean

COMPOSE      := docker compose
APP_SERVICE  := app
IMAGE_NAME   := acccloud
PYTHON       := python

# ── Default: show help ────────────────────────────────────────────────────────
help:
	@echo ""
	@echo "  AccCloud — Available Commands"
	@echo "  ─────────────────────────────────────────────────────"
	@echo "  make dev        Start local dev server (no Docker)"
	@echo "  make build      Build Docker image"
	@echo "  make deploy     Build + start all services (production)"
	@echo "  make stop       Stop all containers"
	@echo "  make restart    Restart app container"
	@echo "  make logs       Follow all container logs"
	@echo "  make shell      Open shell inside app container"
	@echo "  make init-db    Initialize DB + seed starter COA data"
	@echo "  make migrate    Run Alembic migrations"
	@echo "  make backup     Trigger manual backup now"
	@echo "  make restore    Interactive restore from backup"
	@echo "  make test       Run test suite"
	@echo "  make lint       Run ruff linter"
	@echo "  make clean      Remove containers + dangling images"
	@echo ""

# ── Local development (no Docker) ────────────────────────────────────────────
dev:
	@echo "→ Starting dev server..."
	@test -f .env || (cp .env.example .env && echo "  Created .env from .env.example — edit before use")
	$(PYTHON) -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# ── Docker ────────────────────────────────────────────────────────────────────
build:
	@echo "→ Building Docker image..."
	$(COMPOSE) build --no-cache

deploy: _check-env build
	@echo "→ Starting all services..."
	$(COMPOSE) up -d
	@echo ""
	@echo "  Waiting for health check..."
	@sleep 5
	$(COMPOSE) ps
	@echo ""
	@echo "  AccCloud is running at http://localhost"
	@echo "  API docs: http://localhost/api/docs (dev only)"

_check-env:
	@test -f .env || (echo "ERROR: .env not found. Run: cp .env.example .env && nano .env" && exit 1)

stop:
	$(COMPOSE) down

restart:
	$(COMPOSE) restart $(APP_SERVICE)

logs:
	$(COMPOSE) logs -f

logs-app:
	$(COMPOSE) logs -f $(APP_SERVICE)

logs-nginx:
	$(COMPOSE) logs -f nginx

shell:
	$(COMPOSE) exec $(APP_SERVICE) bash

# ── Database ──────────────────────────────────────────────────────────────────
init-db:
	@echo "→ Initializing database..."
	@if $(COMPOSE) ps --services --filter "status=running" | grep -q $(APP_SERVICE); then \
		$(COMPOSE) exec $(APP_SERVICE) bash /app/scripts/init_db.sh; \
	else \
		bash scripts/init_db.sh; \
	fi

migrate:
	@echo "→ Running Alembic migrations..."
	@if $(COMPOSE) ps --services --filter "status=running" | grep -q $(APP_SERVICE); then \
		$(COMPOSE) exec $(APP_SERVICE) python -m alembic upgrade head; \
	else \
		$(PYTHON) -m alembic upgrade head; \
	fi

migrate-history:
	$(PYTHON) -m alembic history

# ── Backup ────────────────────────────────────────────────────────────────────
backup:
	@echo "→ Running backup..."
	$(COMPOSE) exec backup sh /backup.sh

restore:
	@bash scripts/restore.sh $(ARGS)

# ── Code quality ──────────────────────────────────────────────────────────────
test:
	$(PYTHON) -m pytest tests/ -v --tb=short

lint:
	$(PYTHON) -m ruff check app/ tests/

format:
	$(PYTHON) -m ruff format app/ tests/

typecheck:
	$(PYTHON) -m mypy app/ --ignore-missing-imports

# ── SSL setup with Certbot ────────────────────────────────────────────────────
ssl:
	@echo "→ Obtaining SSL certificate with Certbot..."
	@read -p "  Domain name: " DOMAIN; \
	$(COMPOSE) run --rm --entrypoint "" nginx \
		sh -c "apk add --no-cache certbot certbot-nginx && \
		       certbot certonly --nginx -d $$DOMAIN --non-interactive --agree-tos -m admin@$$DOMAIN"

# ── Cleanup ───────────────────────────────────────────────────────────────────
clean:
	$(COMPOSE) down --remove-orphans
	docker image prune -f
	docker volume prune -f --filter "label!=keep"

clean-all: clean
	docker rmi $(IMAGE_NAME):latest 2>/dev/null || true

# ── Show status ───────────────────────────────────────────────────────────────
status:
	$(COMPOSE) ps
	@echo ""
	@echo "→ Health check:"
	@curl -s http://localhost/api/v1/health | $(PYTHON) -m json.tool 2>/dev/null || echo "  (app not reachable)"
