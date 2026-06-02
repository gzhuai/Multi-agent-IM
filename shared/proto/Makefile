.PHONY: generate lint clean

# 使用 buf 生成 Go 和 Python 代码
generate:
	buf generate

# Lint proto 文件
lint:
	buf lint

# 清理生成的代码
clean:
	rm -rf ../gen/*
	rm -rf ../../server/agent-runtime/src/generated/*
