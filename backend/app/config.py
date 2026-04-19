from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    gemini_api_key: str
    model_id: str = "gemini-2.5-flash"
    allowed_origins: str = "http://localhost:3000"
    allowed_origin_regex: str = (
        r"https://.*\.vercel\.app"
        r"|http://localhost(:\d+)?"
        r"|http://127\.0\.0\.1(:\d+)?"
    )

    model_config = {"env_file": ".env"}


settings = Settings()
