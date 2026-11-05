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
    # postgresql+asyncpg://… in production (Supabase), sqlite+aiosqlite://… locally.
    DATABASE_URL: str = "sqlite+aiosqlite:///./dev.db"
    DATABASE_ECHO: bool = False

    # --- Admin identity (SECURITY.md §4–§5) ---
    # The one Google account allowed into the admin panel.
    ADMIN_EMAIL: str = ""
    # Optional: the immutable Google account id ("sub"). When set it must match
    # too, so a recycled or renamed address can never pass.
    ADMIN_GOOGLE_SUB: str = ""

    # --- Google OAuth ---
    GOOGLE_CLIENT_ID: str = ""
    GOOGLE_CLIENT_SECRET: str = ""
    GOOGLE_OAUTH_REDIRECT_URI: str = "http://localhost:8000/api/auth/google/callback"

    # --- Email verification code (Resend) ---
    RESEND_API_KEY: str = ""
    RESEND_FROM: str = "chamathdilshan.dev <auth@chamathdilshan.dev>"
    OTP_TTL_SECONDS: int = 600
    OTP_MAX_ATTEMPTS: int = 5
    OTP_MAX_SENDS: int = 4
    OTP_RESEND_COOLDOWN_SECONDS: int = 30

    # --- Sessions ---
    SESSION_SECRET: str = ""
    SESSION_COOKIE_NAME: str = "pf_session"
    SESSION_MAX_AGE: int = 86_400
    # Defaults to True outside development; http://localhost needs False.
    SESSION_COOKIE_SECURE: bool | None = None

    # --- Media (Cloudinary) ---
    CLOUDINARY_CLOUD_NAME: str = ""
    CLOUDINARY_API_KEY: str = ""
    CLOUDINARY_API_SECRET: str = ""
    CLOUDINARY_FOLDER: str = "chamathdilshan.dev"
    # Must match the account's signature algorithm (Settings → Security).
    CLOUDINARY_SIGNATURE_ALGORITHM: str = "sha1"

    # --- Caching (CACHING.md §17) ---
    REDIS_URL: str = "redis://localhost:6379/0"
    CACHE_NAMESPACE: str = "pf:v1"
    CACHE_DEFAULT_TTL: int = 3_600
    CACHE_ENABLED: bool = True
    CACHE_REVALIDATE_SECRET: str = ""
    CDN_PURGE_URL: str = ""
    CDN_PURGE_TOKEN: str = ""

    # --- Rate limiting (SECURITY.md §20) ---
    RATE_LIMIT_AUTH_PER_MINUTE: int = 10

    # --- Observability ---
    LOG_LEVEL: str = "info"
    SENTRY_DSN: str = ""

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip().rstrip("/") for o in self.ALLOWED_ORIGINS.split(",") if o.strip()]

    @property
    def is_production(self) -> bool:
        return self.APP_ENV == "production"

    @property
    def is_development(self) -> bool:
        return self.APP_ENV == "development"

    @property
    def cookie_secure(self) -> bool:
        if self.SESSION_COOKIE_SECURE is not None:
            return self.SESSION_COOKIE_SECURE
        return not self.is_development and self.APP_ENV != "test"

    @property
    def admin_email(self) -> str:
        return self.ADMIN_EMAIL.strip().lower()

    @property
    def google_configured(self) -> bool:
        return bool(self.GOOGLE_CLIENT_ID and self.GOOGLE_CLIENT_SECRET and self.admin_email)

    @property
    def cloudinary_configured(self) -> bool:
        return bool(
            self.CLOUDINARY_CLOUD_NAME and self.CLOUDINARY_API_KEY and self.CLOUDINARY_API_SECRET
        )

    @property
    def admin_url(self) -> str:
        return f"{self.NEXT_APP_URL.rstrip('/')}/ChamathDilshanC"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
