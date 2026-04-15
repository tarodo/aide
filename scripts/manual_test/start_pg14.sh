#!/usr/bin/env bash
# Start PG14 target DB on port 5434 for crawler manual testing.
set -euo pipefail

NAME="aide-crawler-target-pg14"
PORT=5434

if docker ps -a --format '{{.Names}}' | grep -q "^${NAME}$"; then
  echo "Container ${NAME} already exists; restarting."
  docker start "${NAME}" >/dev/null
else
  docker run -d \
    --name "${NAME}" \
    -e POSTGRES_USER=crawler \
    -e POSTGRES_PASSWORD=crawler \
    -e POSTGRES_DB=target \
    -p ${PORT}:5432 \
    postgres:14 >/dev/null
fi

echo "Waiting for PG to accept connections..."
for _ in {1..30}; do
  if docker exec "${NAME}" pg_isready -U crawler -d target >/dev/null 2>&1; then
    echo "PG14 ready on localhost:${PORT} (user=crawler pw=crawler db=target)"
    exit 0
  fi
  sleep 1
done
echo "PG did not become ready in time" >&2
exit 1
