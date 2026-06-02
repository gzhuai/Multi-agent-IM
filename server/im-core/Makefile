.PHONY: test test-unit test-integration test-race cover lint

# 快速单元测试
test-unit:
	go test ./internal/... -short -count=1 -timeout 120s

# 含竞态检测
test-race:
	go test ./internal/... -race -count=1 -short -timeout 120s

# 集成测试 (需要 PostgreSQL + Redis)
test-integration:
	go test ./test/... -tags=integration -count=1 -timeout 300s

# 全量测试
test: test-race test-integration

# 覆盖率报告
cover:
	go test ./... -coverprofile=coverage.out
	go tool cover -html=coverage.out -o coverage.html
	@echo "Coverage report: coverage.html"

# 代码检查
lint:
	go vet ./...
