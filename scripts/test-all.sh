#!/usr/bin/env bash
#
# test-all.sh — 运行全项目测试套件
#
# 用法:
#   bash scripts/test-all.sh              # 快速测试 (跳过 LLM 调用)
#   bash scripts/test-all.sh --include-llm # 包含 LLM 调用测试
#   bash scripts/test-all.sh --coverage    # 生成覆盖率报告
#   bash scripts/test-all.sh --integration # 仅集成测试
#
# 退出码: 0 = 全部通过, 非0 = 有失败

set -euo pipefail
PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
INCLUDE_LLM=false
COVERAGE=false
INTEGRATION_ONLY=false
FAILED=0

# 颜色输出
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

print_section() {
    echo ""
    echo -e "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${YELLOW}  $1${NC}"
    echo -e "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
}

print_pass() { echo -e "  ${GREEN}✓ PASS${NC}  $1"; }
print_fail() { echo -e "  ${RED}✗ FAIL${NC}  $1"; }

# 解析参数
for arg in "$@"; do
    case $arg in
        --include-llm) INCLUDE_LLM=true ;;
        --coverage)    COVERAGE=true ;;
        --integration) INTEGRATION_ONLY=true ;;
    esac
done

# ============================================================
# Go 单元测试 (im-core)
# ============================================================
if [ "$INTEGRATION_ONLY" = false ]; then
    print_section "Go 单元测试 · im-core"
    cd "$PROJECT_ROOT/server/im-core"
    if go test ./internal/... -race -count=1 -short -timeout 120s; then
        print_pass "im-core 单元测试全部通过"
    else
        print_fail "im-core 单元测试存在失败"
        FAILED=1
    fi

    # ============================================================
    # Go 单元测试 (api-gateway)
    # ============================================================
    print_section "Go 单元测试 · api-gateway"
    cd "$PROJECT_ROOT/server/api-gateway"
    if go test ./internal/... -race -count=1 -short -timeout 120s; then
        print_pass "api-gateway 单元测试全部通过"
    else
        print_fail "api-gateway 单元测试存在失败"
        FAILED=1
    fi

    # ============================================================
    # Python 单元测试
    # ============================================================
    print_section "Python 单元测试 · agent-runtime"
    cd "$PROJECT_ROOT/server/agent-runtime"

    PYTEST_ARGS="-x -q --timeout=10"
    if [ "$INCLUDE_LLM" = false ]; then
        PYTEST_ARGS="$PYTEST_ARGS -m 'not llm'"
    fi
    if [ "$COVERAGE" = true ]; then
        PYTEST_ARGS="$PYTEST_ARGS --cov=src --cov-report=html --cov-report=term"
    fi

    if pytest src/ $PYTEST_ARGS; then
        print_pass "agent-runtime 单元测试全部通过"
    else
        print_fail "agent-runtime 单元测试存在失败"
        FAILED=1
    fi
fi

# ============================================================
# 集成测试
# ============================================================
print_section "集成测试"

# Go 集成测试
cd "$PROJECT_ROOT/server/im-core"
if go test ./test/... -tags=integration -count=1 -timeout 300s 2>/dev/null; then
    print_pass "im-core 集成测试通过"
else
    print_fail "im-core 集成测试失败 (确认 PostgreSQL 和 Redis 已启动)"
    FAILED=1
fi

# Python 集成测试
cd "$PROJECT_ROOT/server/agent-runtime"
if pytest tests/ -x -q -m integration --timeout=30 2>/dev/null; then
    print_pass "agent-runtime 集成测试通过"
else
    print_fail "agent-runtime 集成测试失败 (确认测试依赖已启动)"
    FAILED=1
fi

# ============================================================
# 结果汇总
# ============================================================
echo ""
if [ "$FAILED" -eq 0 ]; then
    echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${GREEN}  全部测试通过 ✓${NC}"
    echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
else
    echo -e "${RED}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${RED}  存在测试失败 ✗  请检查上方输出${NC}"
    echo -e "${RED}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
fi

exit $FAILED
