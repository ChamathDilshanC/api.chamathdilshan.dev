"""Application settings. All secrets come from the environment, never from code."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # --- Application ---
    APP_ENV: str = "development"
    APP_DEBUG: bool = False
    PUBLIC_SITE_URL: str = "http://localhost:3000"
    NEXT_APP_URL: str = "http://localhost:3000"
    ALLOWED_ORIGINS: str = "http://localhost:3000"

    # --- Database ---
    DATABASE_URL: str = ""
    SUPABASE_URL: str = ""
    SUPABASE_ANON_KEY: str = ""
    SUPABASE_SERVICE_ROLE_KEY: str = ""

    # --- Storage ---
    MEDIA_STORAGE_BUCKET: str = "media"

    # --- GitHub OAuth (owner-only admin) ---
    GITHUB_CLIENT_ID: str = ""
    GITHUB_CLIENT_SECRET: str = ""
    GITHUB_OWNER_ID: str = ""
    GITHUB_OWNER_USERNAME: str = "ChamathDilshanC"
    GITHUB_OAUTH_REDIRECT_URI: str = ""

    # --- Sessions ---
    SESSION_SECRET: str = ""
    SESSION_COOKIE_NAME: str = "pf_session"
    SESSION_MAX_AGE: int = 86_400

    # --- Caching (CACHING.md §17) ---
    REDIS_URL: str = "redis://localhost:6379/0"
    CACHE_NAMESPACE: str = "pf:v1"
    CACHE_DEFAULT_TTL: int = 3_600
    CACHE_ENABLED: bool = True
    CACHE_REVALIDATE_SECRET: str = ""
    CDN_PURGE_URL: str = ""
    CDN_PURGE_TOKEN: str = ""

    # --- Observability ---
    LOG_LEVEL: str = "info"
    SENTRY_DSN: str = ""

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.ALLOWED_ORIGINS.split(",") if o.strip()]

    @property
    def is_production(self) -> bool:
        return self.APP_ENV == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
