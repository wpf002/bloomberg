.PHONY: up down logs preflight smoke

preflight:
	@./scripts/check_docker.sh

up: preflight
	docker compose up --build

down:
	docker compose down

logs:
	docker compose logs -f --tail=200

smoke:
	uv run --python 3.11 --with-requirements backend/requirements.txt python scripts/smoke.py
