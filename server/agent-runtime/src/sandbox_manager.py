"""
SandboxManager — Agent 操作沙箱管理 (v2)。

职责:
  1. 创建/销毁 Docker 沙箱容器
  2. 管理沙箱内的工作目录和文件隔离
  3. 执行命令（白名单 + 资源限制）
  4. 网络策略（默认禁止出站）

安全模型:
  - 每个 Agent 独享一个沙箱容器
  - Agent 的文件操作只在沙箱内生效
  - Shell 命令在沙箱内执行，资源受限
  - 敏感命令自动拦截
  - 沙箱使用超时自动销毁

使用方式:
  mgr = SandboxManager(docker_client)
  sandbox = await mgr.create(agent_id)
  result = await mgr.exec(sandbox.id, "go test ./...")
  await mgr.destroy(sandbox.id)
"""

from __future__ import annotations

import asyncio
import logging
import os
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


# ───────────────────────────────────────────────────────────────────
# 数据模型
# ───────────────────────────────────────────────────────────────────


class SandboxStatus(str, Enum):
    CREATING = "creating"
    READY = "ready"
    EXECUTING = "executing"
    ERROR = "error"
    DESTROYED = "destroyed"


@dataclass
class SandboxConfig:
    """沙箱配置。"""
    image: str = "ubuntu:22.04"       # Docker 镜像
    cpu_limit: str = "2.0"            # CPU 核数限制
    memory_limit: str = "2g"           # 内存限制
    disk_limit: str = "10g"            # 磁盘限制
    network_enabled: bool = False      # 默认禁止外网
    workspace_mount: str = ""          # 宿主机挂载到沙箱的路径
    max_runtime_s: int = 600           # 沙箱最大存活时间（10 分钟）
    command_timeout_s: int = 120       # 单次命令超时


@dataclass
class Sandbox:
    """沙箱实例。"""
    id: str
    agent_id: str
    container_id: str = ""
    status: SandboxStatus = SandboxStatus.CREATING
    config: SandboxConfig = field(default_factory=SandboxConfig)
    created_at: str = ""
    last_used_at: str = ""

    def __post_init__(self):
        now = datetime.now(timezone.utc).isoformat()
        if not self.created_at:
            self.created_at = now
        if not self.last_used_at:
            self.last_used_at = now


@dataclass
class ExecResult:
    """命令执行结果。"""
    exit_code: int
    stdout: str
    stderr: str
    duration_ms: float
    sandbox_id: str


# ───────────────────────────────────────────────────────────────────
# Docker 客户端接口（最小协议）
# ───────────────────────────────────────────────────────────────────


class DockerClient(Protocol):
    """Docker SDK 的最小协议。"""

    async def containers_run(
        self, image: str, command: list[str], **kwargs
    ) -> dict[str, Any]:
        """创建并运行容器。返回容器信息。"""
        ...

    async def containers_get(self, container_id: str) -> Any:
        """获取容器对象。"""
        ...

    async def exec_run(self, container_id: str, cmd: str, **kwargs) -> tuple[int, str]:
        """在容器中执行命令。返回 (exit_code, output)。"""
        ...

    async def exec_create(self, container_id: str, cmd: str, **kwargs) -> dict[str, Any]:
        """创建 exec 实例。"""
        ...

    async def exec_start(self, exec_id: str, **kwargs) -> str:
        """启动 exec 并获取输出。"""
        ...


# ───────────────────────────────────────────────────────────────────
# 命令安全策略
# ───────────────────────────────────────────────────────────────────

# 默认允许的开发工具
ALLOWED_COMMANDS = {
    "git", "go", "python", "python3", "node", "npm", "npx",
    "make", "cargo", "rustc", "javac", "java", "gcc", "g++",
    "cat", "head", "tail", "less", "grep", "find", "ls", "tree",
    "wc", "sort", "uniq", "cut", "awk", "sed", "diff", "patch",
    "echo", "printf", "test", "[", "mkdir", "cp", "mv",
    "curl", "wget",
    "docker", "kubectl",
    "psql", "mysql", "sqlite3",
}

# 始终禁止的命令（即使在前缀中匹配）
BLOCKED_PATTERNS = [
    "rm -rf /",
    "rm -rf ~",
    "rm -rf .",
    "mkfs.",
    "dd if=",
    "> /dev/sda",
    "> /dev/sdb",
    "chmod 777 /",
    "chown -R",
    "sudo ",
    "su ",
    "passwd",
    "shutdown",
    "reboot",
    "halt",
    ":(){ :|:& };:",     # fork bomb
    "curl.*|.*sh",        # curl-pipe-bash
]


class SecurityPolicy:

    @staticmethod
    def is_allowed(command: str) -> tuple[bool, str]:
        """检查命令是否被允许。返回 (allowed, reason)。"""
        # 检查禁止模式
        for pattern in BLOCKED_PATTERNS:
            import re
            if re.search(pattern, command, re.IGNORECASE):
                return False, f"Blocked by security policy: matches dangerous pattern"

        # 提取命令名（第一个词）
        cmd_name = command.strip().split()[0] if command.strip() else ""
        # 处理路径形式 (/usr/bin/git → git)
        cmd_name = os.path.basename(cmd_name)

        if cmd_name in ALLOWED_COMMANDS:
            return True, "ok"
        elif cmd_name == "":
            return False, "empty command"
        else:
            return False, (
                f"Command '{cmd_name}' is not in the allowed list. "
                f"Allowed: {sorted(ALLOWED_COMMANDS)}"
            )


# ───────────────────────────────────────────────────────────────────
# SandboxManager
# ───────────────────────────────────────────────────────────────────


class SandboxManager:
    """
    Agent 沙箱管理器。

    支持两种模式:
      1. Docker 模式 (生产): 真实容器隔离
      2. Local 模式 (开发): 本地子进程，不隔离（仅用于开发调试）
    """

    def __init__(
        self,
        docker_client: DockerClient | None = None,
        mode: str = "local",  # "docker" | "local"
        config: SandboxConfig | None = None,
    ):
        self.docker = docker_client
        self.mode = mode if docker_client else "local"
        self.config = config or SandboxConfig()
        self._sandboxes: dict[str, Sandbox] = {}
        self._cleanup_tasks: dict[str, asyncio.Task] = {}

        logger.info(
            "SandboxManager initialized: mode=%s image=%s",
            self.mode, self.config.image,
        )

    # ── 沙箱生命周期 ──────────────────────────────────────────────

    async def create(self, agent_id: str, config: SandboxConfig | None = None) -> Sandbox:
        """为 Agent 创建沙箱。"""
        cfg = config or self.config
        sandbox_id = f"sandbox-{agent_id[:8]}-{uuid.uuid4().hex[:8]}"

        sandbox = Sandbox(
            id=sandbox_id,
            agent_id=agent_id,
            config=cfg,
        )

        if self.mode == "docker" and self.docker:
            try:
                container = await self.docker.containers_run(
                    image=cfg.image,
                    command=["sleep", str(cfg.max_runtime_s)],
                    detach=True,
                    remove=True,
                    cpu_quota=int(float(cfg.cpu_limit) * 100000),
                    mem_limit=cfg.memory_limit,
                    network_mode="none" if not cfg.network_enabled else "bridge",
                )
                sandbox.container_id = container.get("id", "")
                logger.info(
                    "Docker sandbox created: %s container=%s",
                    sandbox_id, sandbox.container_id,
                )
            except Exception as e:
                sandbox.status = SandboxStatus.ERROR
                logger.error("Failed to create Docker sandbox: %s", e)
                raise

        sandbox.status = SandboxStatus.READY
        self._sandboxes[sandbox_id] = sandbox

        # 设置超时自动销毁
        loop = asyncio.get_event_loop()
        self._cleanup_tasks[sandbox_id] = loop.create_task(
            self._auto_destroy(sandbox_id, cfg.max_runtime_s)
        )

        return sandbox

    async def destroy(self, sandbox_id: str) -> None:
        """销毁沙箱。"""
        sandbox = self._sandboxes.pop(sandbox_id, None)
        if sandbox is None:
            return

        # 取消自动销毁任务
        task = self._cleanup_tasks.pop(sandbox_id, None)
        if task:
            task.cancel()

        if sandbox.container_id and self.docker and self.mode == "docker":
            try:
                container = await self.docker.containers_get(sandbox.container_id)
                await container.kill()
            except Exception as e:
                logger.warning("Failed to kill container %s: %s", sandbox.container_id, e)

        sandbox.status = SandboxStatus.DESTROYED
        logger.info("Sandbox destroyed: %s", sandbox_id)

    async def _auto_destroy(self, sandbox_id: str, delay_s: int) -> None:
        """延迟自动销毁沙箱。"""
        await asyncio.sleep(delay_s)
        sandbox = self._sandboxes.get(sandbox_id)
        if sandbox and sandbox.status != SandboxStatus.DESTROYED:
            logger.info("Auto-destroying sandbox %s (timeout)", sandbox_id)
            await self.destroy(sandbox_id)

    # ── 命令执行 ──────────────────────────────────────────────────

    async def exec(
        self,
        sandbox_id: str,
        command: str,
        cwd: str = "/workspace",
        timeout_s: float | None = None,
        env: dict[str, str] | None = None,
    ) -> ExecResult:
        """在沙箱内执行命令。"""
        sandbox = self._sandboxes.get(sandbox_id)
        if sandbox is None:
            return ExecResult(-1, "", "Sandbox not found", 0, sandbox_id)

        # 安全检查
        allowed, reason = SecurityPolicy.is_allowed(command)
        if not allowed:
            logger.warning("Blocked command in sandbox %s: %s → %s", sandbox_id, command, reason)
            return ExecResult(-1, "", f"Security: {reason}", 0, sandbox_id)

        timeout = timeout_s or sandbox.config.command_timeout_s
        sandbox.status = SandboxStatus.EXECUTING
        sandbox.last_used_at = datetime.now(timezone.utc).isoformat()

        t0 = asyncio.get_event_loop().time()

        try:
            if self.mode == "docker" and self.docker:
                full_cmd = f"cd {cwd} 2>/dev/null || true; {command}"
                result = await asyncio.wait_for(
                    self.docker.exec_run(sandbox.container_id, full_cmd),
                    timeout=timeout,
                )
                exit_code, output = result if isinstance(result, tuple) else (-1, str(result))
                stdout = output
                stderr = ""
            else:
                # Local mode — subprocess
                proc = await asyncio.create_subprocess_shell(
                    command,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=cwd,
                    env={**os.environ, **(env or {})},
                )
                stdout_bytes, stderr_bytes = await asyncio.wait_for(
                    proc.communicate(), timeout=timeout
                )
                exit_code = proc.returncode or 0
                stdout = stdout_bytes.decode("utf-8", errors="replace")
                stderr = stderr_bytes.decode("utf-8", errors="replace")

        except asyncio.TimeoutError:
            exit_code = -1
            stdout = ""
            stderr = f"Command timed out after {timeout}s"
        except Exception as e:
            exit_code = -1
            stdout = ""
            stderr = str(e)
        finally:
            sandbox.status = SandboxStatus.READY

        elapsed = (asyncio.get_event_loop().time() - t0) * 1000

        return ExecResult(
            exit_code=exit_code,
            stdout=stdout,
            stderr=stderr,
            duration_ms=elapsed,
            sandbox_id=sandbox_id,
        )

    # ── 文件操作 ──────────────────────────────────────────────────

    async def read_file(self, sandbox_id: str, path: str, max_bytes: int = 1_000_000) -> str:
        """读取沙箱内的文件。"""
        result = await self.exec(sandbox_id, f"cat {path}")
        if result.exit_code != 0:
            raise FileNotFoundError(f"Cannot read {path}: {result.stderr}")
        return result.stdout[:max_bytes]

    async def write_file(self, sandbox_id: str, path: str, content: str) -> ExecResult:
        """写入文件到沙箱。需要审批。"""
        # 使用 base64 避免特殊字符问题
        import base64
        encoded = base64.b64encode(content.encode()).decode()
        cmd = f"echo {encoded} | base64 -d > {path}"
        return await self.exec(sandbox_id, cmd)

    async def list_files(self, sandbox_id: str, directory: str = "/workspace") -> list[str]:
        """列出沙箱内的文件。"""
        result = await self.exec(sandbox_id, f"find {directory} -type f -maxdepth 5 2>/dev/null")
        if result.exit_code != 0 and not result.stdout:
            return []
        return [f.strip() for f in result.stdout.split("\n") if f.strip()]

    # ── 状态查询 ──────────────────────────────────────────────────

    def get_sandbox(self, sandbox_id: str) -> Sandbox | None:
        return self._sandboxes.get(sandbox_id)

    def get_agent_sandbox(self, agent_id: str) -> Sandbox | None:
        for s in self._sandboxes.values():
            if s.agent_id == agent_id:
                return s
        return None

    async def cleanup_all(self) -> None:
        """清理所有沙箱。"""
        ids = list(self._sandboxes.keys())
        for sid in ids:
            await self.destroy(sid)
        logger.info("All sandboxes cleaned up (%d)", len(ids))
