from functools import lru_cache
from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    app_name: str = "WellCosting Pro"
    database_url: str = "sqlite:///./wellcosting.db"
    secret_key: str = "development-only-change-this-secret-before-deploying"
    access_token_minutes: int = 15
    refresh_token_days: int = 7
    secure_cookies: bool = False
    cors_origins: str = "http://localhost:5173"
    # First-run administrator bootstrap. Ask at startup when the database has no owner.
    bootstrap_admin_on_startup: bool = True
    # Optional unattended seeding for a first boot with no terminal. Leave blank to be asked.
    seed_org_slug: str = ""
    seed_org_name: str = ""
    seed_owner_name: str = ""
    seed_admin_email: str = ""
    seed_admin_password: str = ""

    @model_validator(mode="after")
    def validate_deployment(self):
        if not self.database_url.startswith("sqlite") and (self.secret_key.startswith("development-only") or len(self.secret_key) < 32):
            raise ValueError("Set a unique SECRET_KEY of at least 32 characters before using PostgreSQL")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
