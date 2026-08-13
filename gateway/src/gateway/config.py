from pydantic import AliasChoices, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        frozen=True,
        populate_by_name=True,
    )

    database_path: str = Field(
        default="agent_threads.db",
        validation_alias=AliasChoices("AGENT_THREAD_DB", "DATABASE_PATH"),
    )
    agent_model: str = "gpt-5.4-mini"
    agent_system_prompt: str = "You are a helpful assistant."
    openai_api_key: SecretStr | None = None
