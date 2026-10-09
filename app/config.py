from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    SECRET_KEY: str
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 10080  # 7 days

    DATABASE_URL: str = "sqlite:///./filmabend.db"

    TMDB_API_KEY: str = ""

    # Only needed on first start, when no admin exists yet. There is
    # deliberately no default password: a public default would be a known
    # credential on every fresh install.
    FIRST_ADMIN_USERNAME: str = "admin"
    FIRST_ADMIN_PASSWORD: str = ""

    # The bundled frontend is served from the same origin, so CORS is off
    # unless a separate frontend origin is configured explicitly.
    CORS_ORIGINS: list[str] = []

    # Proposals per person and round (admins are not limited).
    MAX_MOVIES_PER_USER: int = 3

    # Login/registration attempts per client IP within the window.
    AUTH_RATE_LIMIT: int = 10
    AUTH_RATE_WINDOW_SECONDS: int = 300

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


settings = Settings()
