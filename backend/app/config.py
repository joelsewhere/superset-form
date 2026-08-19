"""Application settings. Everything sensitive comes from the environment."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/frontflow"

    # Comma-separated list of allowed browser origins.
    cors_origins: str = "http://localhost:5173"

    # Superset, reached over the compose network.
    superset_url: str = "http://superset:8088"
    superset_admin_username: str = "admin"
    superset_admin_password: str = "admin"

    # The UUID from the dashboard's "Embed dashboard" dialog — NOT the numeric
    # dashboard id. Using the numeric id yields a silently blank iframe.
    superset_dashboard_embed_uuid: str = ""

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
