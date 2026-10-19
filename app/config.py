from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / ".env", extra="ignore")

    bot_token: str = ""
    anthropic_api_key: str = ""
    base_url: str = "http://localhost:8000"
    admin_ids: str = ""
    rahmat_url: str = ""
    price: int = 25000
    max_edits: int = 10
    database_url: str = "sqlite+aiosqlite:///tayyorla.db"
    host: str = "0.0.0.0"
    port: int = 8000

    # Premium sifat uchun eng kuchli Opus modeli
    ai_model: str = "claude-opus-5-5"

    @property
    def admins(self) -> set[int]:
        return {int(x) for x in self.admin_ids.replace(" ", "").split(",") if x}


settings = Settings()
MEDIA_DIR = ROOT / "media"
MEDIA_DIR.mkdir(exist_ok=True)
