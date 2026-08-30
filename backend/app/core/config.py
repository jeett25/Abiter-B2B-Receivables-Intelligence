from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str
    seed: int = 42
    razorpay_key_id: str | None = None
    razorpay_key_secret: str | None = None
    llm_api_key: str | None = None


settings = Settings()
