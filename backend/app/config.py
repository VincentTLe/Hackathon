import os
from pathlib import Path

from pydantic_settings import BaseSettings


def _default_db_path() -> str:
    if os.path.isdir("/data"):
        return "/data/bridge.db"
    return "bridge.db"


class Settings(BaseSettings):
    gemini_api_key: str
    model_id: str = "gemini-2.5-flash"
    allowed_origins: str = "http://localhost:3000"
    allowed_origin_regex: str = (
        r"https://.*\.vercel\.app"
        r"|http://localhost(:\d+)?"
        r"|http://127\.0\.0\.1(:\d+)?"
    )
    app_base_url: str = "http://localhost:3000"
    database_path: str = _default_db_path()

    model_config = {"env_file": ".env", "extra": "ignore"}

    @property
    def resolved_database_path(self) -> Path:
        path = Path(self.database_path)
        if not path.is_absolute():
            path = Path(__file__).resolve().parent.parent / path
        return path


settings = Settings()
