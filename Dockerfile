# === Builder ===
FROM python:3.13.9-slim AS base
WORKDIR /app
ENV PATH="/app/.venv/bin:$PATH"
RUN pip install --no-cache-dir uv

COPY pyproject.toml uv.lock ./
COPY schemas/ schemas/
RUN uv sync --locked --no-install-project --all-groups

# === Dev ===
FROM base AS dev
RUN uv sync --locked --all-groups
COPY . .
EXPOSE 8000
CMD ["uv", "run", "uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]