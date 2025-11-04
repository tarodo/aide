# Makefile

.PHONY: check test format

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
test:
	uv run pytest -v

# Local run
run:
	uv run uvicorn backend.main:app --host 0.0.0.0 --port 8001 --reload

# Docker run
up:
	docker compose up --build

stop:
	docker compose down
