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
    judge_max_tokens: int = 300
    embed_model: str = "all-MiniLM-L6-v2"
    # Hard caps for prompt inputs (see CLAUDE.md) — raise with care, LLM context/cost tradeoff.
    resume_max_chars: int = 6000
    jd_max_chars: int = 4000
    parse_resume_max_tokens: int = 512
    parse_jd_max_tokens: int = 2048
    groq_api_key: str = ""
    cascade_model: str = "openai/gpt-oss-20b"
    # Retry/backoff for transient Groq failures (timeouts, 429s). Exponential:
    # groq_retry_backoff_base ** attempt seconds between tries.
    groq_max_retries: int = 3
    groq_retry_backoff_base: float = 2.0
    # Client-side throttle so we never trip Groq's rate limit in the first place.
    # Free tier is ~30 req/min for llama-3.3-70b-versatile — kept under that by default.
    # Raise this in .env once you're on a paid Groq plan.
    groq_requests_per_minute: int = 28
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"
    openai_embed_model: str = "text-embedding-3-small"
    cerebras_api_key: str = ""
    cerebras_model: str = "gemma-4-31b"
    # Retry/backoff for transient Cerebras failures (timeouts, 429s). Exponential:
    # cerebras_retry_backoff_base ** attempt seconds between tries.
    cerebras_max_retries: int = 3
    cerebras_retry_backoff_base: float = 2.0
    # Client-side throttle so we never trip Cerebras' rate limit in the first place.
    # Raise this in .env once you're on a paid Cerebras plan.
    cerebras_requests_per_minute: int = 28

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
    # Upstash Redis (optional — takes priority over redis_url when set)
    upstash_redis_rest_url: str = ""
    upstash_redis_rest_token: str = ""

    # Billing — deliberately manual for MVP (no card data, no webhooks, no payment
    # provider account on this app): a user requests credits, pays via an external
    # link the operator sets up, and the operator grants credits by hand once they've
    # confirmed the payment themselves. See app/api/billing.py.
    signup_free_credits: int = 3  # trial credits granted on signup, no payment needed
    payment_link_url: str = ""  # e.g. a Stripe Payment Link / PayPal.me URL, operator's choice
    admin_api_key: str = ""  # shared secret for POST /billing/admin/grant-credits; unset = disabled
    # Shown alongside a pending credit request so the user has somewhere to follow up
    # besides waiting — e.g. "support@example.com" or a Slack/Discord invite link.
    support_contact: str = ""

    @staticmethod
    def _is_real(value: str) -> bool:
        """False for unset or still-a-placeholder values like `https://<name>.upstash.io`.
        Without this, a half-filled .env builds a valid-looking URL pointing at a host
        that doesn't exist, and the queue fails at runtime instead of falling back."""
        return bool(value) and "<" not in value

    @property
    def effective_redis_url(self) -> str:
        """Return Upstash rediss:// URL when REST credentials are provided, else redis_url."""
        if self._is_real(self.upstash_redis_rest_url) and self._is_real(
            self.upstash_redis_rest_token
        ):
            # REST URL is https://<host>.upstash.io — strip scheme to get hostname
            host = (
                self.upstash_redis_rest_url.removeprefix("https://")
                .removeprefix("http://")
                .rstrip("/")
            )
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

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


settings = Settings()
