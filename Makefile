# Makefile

.PHONY: check test-local test-docker format run stop up alembic-gen

# Full check - for CI or before push
check:
	uv run ruff check .
	uv run black --check .
	uv run mypy .

# Auto-formatting
format:
	uv run black .
	uv run ruff check . --fix

# Only tests
test-local:
	uv run pytest -v

test-docker:
	docker compose run --rm test

# Local run
run:
	uv run uvicorn backend.main:app --host 0.0.0.0 --port 8001 --reload

# Docker run
up:
	docker compose up --build

stop:
	docker compose down

# Alembic migrations
alembic-gen:
	@if [ -n "$(MSG)" ]; then \
		docker compose run --rm app uv run alembic -c backend/alembic.ini revision --autogenerate -m "$(MSG)"; \
	else \
		MSG="$$(echo $(filter-out $@,$(MAKECMDGOALS)))"; \
		docker compose run --rm app uv run alembic -c backend/alembic.ini revision --autogenerate -m "$$MSG"; \
	fi
%:
	@:
