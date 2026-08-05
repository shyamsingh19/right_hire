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

    # Upstash Redis (optional — takes priority over redis_url when set)
    upstash_redis_rest_url: str = ""
    upstash_redis_rest_token: str = ""

    @property
    def effective_redis_url(self) -> str:
        """Return Upstash rediss:// URL when REST credentials are provided, else redis_url."""
        if self.upstash_redis_rest_url and self.upstash_redis_rest_token:
            # REST URL is https://<host>.upstash.io — strip scheme to get hostname
            host = self.upstash_redis_rest_url.removeprefix("https://").removeprefix("http://").rstrip("/")
            return f"rediss://default:{self.upstash_redis_rest_token}@{host}:6379"
        return self.redis_url

    @property
    def async_database_url(self) -> str:
        """Return async-compatible database URL."""
        url = self.database_url
        if url.startswith("mysql+pymysql://"):
            return url.replace("mysql+pymysql://", "mysql+aiomysql://", 1)
        if url.startswith("sqlite:///"):
            return url.replace("sqlite:///", "sqlite+aiosqlite:///", 1)
        return url


settings = Settings()
