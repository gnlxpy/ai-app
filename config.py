from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field


class Settings(BaseSettings):
    """
    Основные переменные окружения
    """
    ANTHROPIC_TOKEN: str = Field(description='Токен Claude API')
    TELEGRAM_TOKEN: str = Field(description='Токен Telegram API')
    CHROMA_PATH: str = Field(description='Местополежение данных БД')
    IDIOMS_COLLECTION: str = Field(description='Название коллекции в БД')
    IDIOMS_SCHEDULE_TIME: int = Field(description='Время отправки идиом (часы)')

    model_config = SettingsConfigDict(env_file='.env', env_file_encoding='utf-8')


settings = Settings()
