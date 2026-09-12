from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field
from pathlib import Path


class Settings(BaseSettings):
    """
    Основные переменные окружения
    """
    BASE_DIR: str = f'{Path(__file__).resolve().parent}/'

    ANTHROPIC_TOKEN: str = Field(description='Токен Claude API')
    TELEGRAM_TOKEN: str = Field(description='Токен Telegram API')
    IDIOMS_SCHEDULE_TIME: int = Field(description='Время отправки идиом (часы)')

    CH_HOST: str = Field(description='Хост ClickHouse')
    CH_PSW: str = Field(description='Пароль ClickHouse')

    VOYAGE_TOKEN: str = Field(description='Токен VoyageAI API')

    RATE_LIMIT_MAX_REQUESTS: int = Field(description='Максимум запросов за окно')
    RATE_LIMIT_WINDOW_SECONDS: int = Field(description='Ширина окна в секундах')

    REDIS_HOST: str = Field(description='Хост Redis')
    REDIS_PSW: str = Field(description='Пароль Redis')

    model_config = SettingsConfigDict(env_file='.env', env_file_encoding='utf-8')


settings = Settings()
