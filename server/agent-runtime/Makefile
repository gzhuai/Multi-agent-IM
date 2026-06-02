.PHONY: install test test-unit test-integration test-llm cover lint

install:
	pip install -e ".[test]"

# 快速单元测试 (跳过 LLM)
test-unit:
	pytest src/ -x -q -m "not llm" --timeout=10

# 集成测试
test-integration:
	pytest tests/ -x -q -m integration --timeout=30

# LLM 相关测试
test-llm:
	pytest src/ tests/ -x -q -m llm --timeout=60

# 全量测试
test:
	pytest src/ tests/ -x -q --timeout=30

# 覆盖率报告
cover:
	pytest src/ --cov=src --cov-report=html --cov-report=term --cov-fail-under=75
	@echo "Coverage report: htmlcov/index.html"

# 代码检查
lint:
	ruff check src/ tests/
