from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # LLM
    llm_backend: str = "local"
    ollama_url: str = "http://localhost:11434"
    judge_model: str = "qwen2.5:7b"
    judge_max_tokens: int = 200
    embed_model: str = "all-MiniLM-L6-v2"
    groq_api_key: str = ""
    cascade_model: str = ""
    openai_api_key: str = ""

    # Storage
    database_url: str = "mysql+pymysql://ats:ats@localhost:3306/ats"
    redis_url: str = "redis://localhost:6379/0"
    storage_dir: str = "./storage"

    # API
    cors_origins: str = (
        "*"  # comma-separated list, e.g. "https://app.example.com,http://localhost:3000"
    )
    max_upload_mb: int = 10
    # Dev-only convenience: auto-create tables on startup instead of requiring `alembic upgrade
    # head` first. Set to false in any environment where Alembic manages the schema.
    auto_create_tables: bool = True

    @property
    def async_database_url(self) -> str:
        """Return async-compatible database URL."""
        url = self.database_url
        if url.startswith("mysql+pymysql://"):
            return url.replace("mysql+pymysql://", "mysql+aiomysql://", 1)
        if url.startswith("sqlite:///"):
            return url.replace("sqlite:///", "sqlite+aiosqlite:///", 1)
        return url

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


settings = Settings()
