from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    gemini_api_key: str
    model_id: str = "gemini-2.5-flash"
    allowed_origins: str = "http://localhost:3000"

    model_config = {"env_file": ".env"}


settings = Settings()
