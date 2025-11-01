# Makefile

.PHONY: check test format

# Full check - for CI or before push
check:
	uv run ruff check .
	uv run black --check .
	uv run mypy .
	uv run pytest -v

# Auto-formatting
format:
	uv run black .
	uv run ruff check . --fix

# Only tests
test:
	uv run pytest -v

# Local run
local_run:
	uv run uvicorn aide.main:app --host 0.0.0.0 --port 8001 --reload

# Docker run
run:
	docker compose up -d --build

stop:
	docker compose down
