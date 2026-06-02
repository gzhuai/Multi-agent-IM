.PHONY: up down infra start-im start-gateway start-agent start-web \
        stop test lint clean dev status

# ============================================================
# Multi-agent-IM 开发命令
# ============================================================

# 启动所有基础设施 (PostgreSQL + Redis + MinIO)
infra:
	docker compose -f deploy/docker-compose.dev.yml up -d
	@echo "Waiting for services to be healthy..."
	@sleep 3
	@docker compose -f deploy/docker-compose.dev.yml ps

# 停止所有基础设施
down:
	docker compose -f deploy/docker-compose.dev.yml down

# 启动 IM Core 服务 (Go)
start-im:
	cd server/im-core && go run ./cmd/server/main.go

# 启动 API Gateway (Go)
start-gateway:
	cd server/api-gateway && go run ./cmd/server/main.go

# 启动 Agent Runtime (Python)
start-agent:
	cd server/agent-runtime && python -m agent_runtime.app

# 启动 Web 前端 (React)
start-web:
	cd client/web && npm run dev

# 一键启动所有服务 (需要多个终端)
dev: infra
	@echo "============================================"
	@echo "  基础设施已启动 (PostgreSQL, Redis, MinIO)"
	@echo "============================================"
	@echo ""
	@echo "  请在三个终端中分别运行:"
	@echo "    make start-im       # IM Core    :8080"
	@echo "    make start-gateway  # API Gateway :3000"
	@echo "    make start-agent    # Agent RT   :50051"
	@echo "    make start-web      # Web UI     :5173"
	@echo ""

# 停止所有服务
stop:
	@echo "Stopping all services..."
	docker compose -f deploy/docker-compose.dev.yml down

# ============================================================
# 测试
# ============================================================

test:
	bash scripts/test-all.sh

test-go:
	cd server/im-core && go test ./internal/... -race -count=1 -short
	cd server/api-gateway && go test ./internal/... -race -count=1 -short

test-python:
	cd server/agent-runtime && pytest src/ -x -q -m "not llm" --timeout=10

test-web:
	cd client/web && npx vitest run

# ============================================================
# 代码检查
# ============================================================

lint:
	cd server/im-core && go vet ./...
	cd server/api-gateway && go vet ./...
	cd server/agent-runtime && ruff check src/ tests/
	cd client/web && npx eslint src/

# ============================================================
# 工具
# ============================================================

# 初始化开发环境
setup:
	@echo "Installing Python dependencies..."
	cd server/agent-runtime && pip install -e ".[test]"
	@echo "Installing Node dependencies..."
	cd client/web && npm install
	@echo "Setup complete."

# 清理
clean:
	docker compose -f deploy/docker-compose.dev.yml down -v
	rm -rf server/im-core/coverage.out server/im-core/coverage.html
	rm -rf server/agent-runtime/htmlcov server/agent-runtime/.coverage
	rm -rf client/web/dist client/web/node_modules

# 状态查看
status:
	@echo "=== Docker Services ==="
	@docker compose -f deploy/docker-compose.dev.yml ps 2>/dev/null || echo "Not running"
	@echo ""
	@echo "=== Go Modules ==="
	@cd server/im-core && go version 2>/dev/null || echo "Go not found"
	@echo ""
	@echo "=== Python ==="
	@cd server/agent-runtime && python --version 2>/dev/null || echo "Python not found"
	@echo ""
	@echo "=== Node ==="
	@cd client/web && node --version 2>/dev/null || echo "Node not found"
