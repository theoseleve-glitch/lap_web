.PHONY: dev test build deploy logs shell lint migrate db-backup db-restore frontend frontend-build frontend-deploy docker-up docker-down

# ── Backend ─────────────────────────────────────
dev:
	python telemetry_tool/main.py --serve

test:
	pytest telemetry_tool/tests/ -v

test-kart:
	pytest kart_envelope/tests/ -v

lint:
	python -m mypy telemetry_tool/web/ --ignore-missing-imports

migrate:
	alembic upgrade head

shell:
	python -c "from telemetry_tool.db.schema import *; import code; code.interact(local=locals())"

# ── Frontend ────────────────────────────────────
frontend:
	cd lap-website && npm run dev

frontend-build:
	cd lap-website && npm run build

frontend-deploy:
	cd lap-website && npm run cf:deploy

frontend-lint:
	cd lap-website && npm run lint

frontend-test:
	cd lap-website && npm test

# ── Docker ──────────────────────────────────────
docker-up:
	docker compose up -d

docker-down:
	docker compose down

docker-prod:
	docker compose -f docker-compose.prod.yml up -d

docker-logs:
	docker compose logs -f --tail=100

docker-build:
	docker compose build api

# ── Database ────────────────────────────────────
db-backup:
	docker compose exec postgres pg_dump -U telemetry telemetry > backup_$$(date +%Y%m%d_%H%M%S).sql

db-restore:
	@test -n "$(FILE)" || (echo "Usage: make db-restore FILE=backup.sql" && exit 1)
	docker compose exec -T postgres psql -U telemetry telemetry < $(FILE)

db-migrate-sqlite:
	python scripts/migrate_sqlite_to_pg.py

# ── Deploy (VPS) ────────────────────────────────
deploy:
	scp docker-compose.prod.yml Caddyfile Dockerfile root@46.225.227.24:/opt/lap-api/
	ssh root@46.225.227.24 "cd /opt/lap-api && docker compose -f docker-compose.prod.yml build api && docker compose -f docker-compose.prod.yml up -d api"

logs:
	ssh root@46.225.227.24 "cd /opt/lap-api && docker compose -f docker-compose.prod.yml logs -f --tail=100 api"

health:
	curl -s https://api.lap-coach.racing/healthz | python -m json.tool

# ── All ─────────────────────────────────────────
ci: lint test frontend-lint frontend-test frontend-build
	@echo "All CI checks passed"
