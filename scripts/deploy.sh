#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_DIR"

echo "=== Multi-agent-IM Production Deploy ==="

# Check .env
if [ ! -f ".env" ]; then
  echo "ERROR: .env file not found. Copy .env.example and configure."
  exit 1
fi

# Build frontend
echo "[1/4] Building frontend..."
cd client/web
npm install --silent
npm run build
cd "$PROJECT_DIR"

# Build Go services
echo "[2/4] Building Go services..."
cd server/im-core && go build -o im-core ./cmd/server/main.go && cd "$PROJECT_DIR"
cd server/api-gateway && go build -o api-gateway ./cmd/server/main.go && cd "$PROJECT_DIR"

# Start services
echo "[3/4] Starting services..."
docker compose -f deploy/docker-compose.prod.yml up -d --build

# Wait for health
echo "[4/4] Waiting for health checks..."
for i in $(seq 1 30); do
  if curl -sf http://localhost:3000/health > /dev/null 2>&1; then
    echo "API Gateway healthy"
    break
  fi
  sleep 2
done

echo "=== Deploy complete ==="
echo "  Web:       http://localhost"
echo "  API:       http://localhost:3000"
echo "  MinIO:     http://localhost:9001"
