#!/usr/bin/env bash
#
# 安装 Git Hooks
#
# 用法: bash scripts/install-hooks.sh

set -euo pipefail
PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

# 创建 .githooks 目录
mkdir -p "$PROJECT_ROOT/.githooks"

# ============================================================
# pre-commit hook
# ============================================================
cat > "$PROJECT_ROOT/.githooks/pre-commit" << 'HOOK'
#!/usr/bin/env bash
#
# pre-commit: 提交前自动跑变更文件相关的测试
#
# 策略: 只跑变更涉及的服务测试，不跑全量

set -euo pipefail
PROJECT_ROOT="$(git rev-parse --show-toplevel)"

# 获取暂存区变更文件列表
changed=$(git diff --cached --name-only --diff-filter=ACM)

PASS=true

# Go 测试 (im-core)
if echo "$changed" | grep -q "^server/im-core/"; then
    echo "[pre-commit] Running im-core unit tests..."
    cd "$PROJECT_ROOT/server/im-core"
    if ! go test ./internal/... -short -count=1 -timeout 60s; then
        echo "ERROR: im-core tests failed. Commit aborted."
        PASS=false
    fi
fi

# Go 测试 (api-gateway)
if echo "$changed" | grep -q "^server/api-gateway/"; then
    echo "[pre-commit] Running api-gateway unit tests..."
    cd "$PROJECT_ROOT/server/api-gateway"
    if ! go test ./internal/... -short -count=1 -timeout 60s; then
        echo "ERROR: api-gateway tests failed. Commit aborted."
        PASS=false
    fi
fi

# Python 测试
if echo "$changed" | grep -q "^server/agent-runtime/src/"; then
    echo "[pre-commit] Running agent-runtime unit tests..."
    cd "$PROJECT_ROOT/server/agent-runtime"
    if ! pytest src/ -x -q -m "not llm" --timeout=10; then
        echo "ERROR: agent-runtime tests failed. Commit aborted."
        PASS=false
    fi
fi

if [ "$PASS" = true ]; then
    echo "[pre-commit] All relevant tests passed."
    exit 0
else
    exit 1
fi
HOOK

chmod +x "$PROJECT_ROOT/.githooks/pre-commit"

# 配置 git 使用 .githooks 目录
cd "$PROJECT_ROOT"
git config core.hooksPath .githooks

echo "Git hooks installed successfully."
echo "Hook directory: $(git rev-parse --show-toplevel)/.githooks"
