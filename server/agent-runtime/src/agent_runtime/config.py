"""
Configuration management for Agent Runtime.

Reads from environment variables with sensible defaults for local development.
"""

import os
from dataclasses import dataclass, field


@dataclass
class DatabaseConfig:
    host: str = "localhost"
    port: int = 5432
    user: str = "maim"
    password: str = "maim_dev"
    dbname: str = "multiagent"
    sslmode: str = "disable"

    @property
    def dsn(self) -> str:
        return (
            f"postgresql+asyncpg://{self.user}:{self.password}"
            f"@{self.host}:{self.port}/{self.dbname}"
        )


@dataclass
class RedisConfig:
    host: str = "localhost"
    port: int = 6379
    password: str = ""
    db: int = 0

    @property
    def url(self) -> str:
        if self.password:
            return f"redis://:{self.password}@{self.host}:{self.port}/{self.db}"
        return f"redis://{self.host}:{self.port}/{self.db}"


@dataclass
class LLMConfig:
    provider: str = "claude"
    model: str = "claude-sonnet-4-6"
    api_key: str = ""
    base_url: str = ""
    max_tokens: int = 4096
    temperature: float = 0.7


@dataclass
class Config:
    database: DatabaseConfig = field(default_factory=DatabaseConfig)
    redis: RedisConfig = field(default_factory=RedisConfig)
    llm: LLMConfig = field(default_factory=LLMConfig)
    log_level: str = "DEBUG"
    grpc_port: int = 50051
    default_memory_budget: dict = field(default_factory=lambda: {
        "core": 10000,
        "working": 20000,
        "buffer": 10000,
    })


def load() -> Config:
    return Config(
        database=DatabaseConfig(
            host=os.getenv("DB_HOST", "localhost"),
            port=int(os.getenv("DB_PORT", "5432")),
            user=os.getenv("DB_USER", "maim"),
            password=os.getenv("DB_PASSWORD", "maim_dev"),
            dbname=os.getenv("DB_NAME", "multiagent"),
        ),
        redis=RedisConfig(
            host=os.getenv("REDIS_HOST", "localhost"),
            port=int(os.getenv("REDIS_PORT", "6379")),
            password=os.getenv("REDIS_PASSWORD", ""),
        ),
        llm=LLMConfig(
            provider=os.getenv("LLM_PROVIDER", "claude"),
            model=os.getenv("LLM_MODEL", "claude-sonnet-4-6"),
            api_key=os.getenv("ANTHROPIC_API_KEY", ""),
            base_url=os.getenv("ANTHROPIC_BASE_URL", ""),
            max_tokens=int(os.getenv("LLM_MAX_TOKENS", "4096")),
            temperature=float(os.getenv("LLM_TEMPERATURE", "0.7")),
        ),
        log_level=os.getenv("LOG_LEVEL", "DEBUG"),
        grpc_port=int(os.getenv("GRPC_PORT", "50051")),
    )
