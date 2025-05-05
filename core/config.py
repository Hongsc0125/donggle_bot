# app/core/config.py
import os
import logging
from datetime import datetime
from urllib.parse import quote_plus

from functools import lru_cache

import pytz
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)


class Settings(BaseSettings):
    DATABASE_URL: str
    DATABASE_NAME: str
    DB_PW: str
    DB_USER: str

    # 디코
    DISCORD_TOKEN: str
    APPLICATION_ID: str
    PUBLIC_KEY: str

    # openai
    OPENAI_API_KEY: str
    DEEPSEEK_API_KEY: str

    # ENV
    ENV: str

    # Pydantic v2 방식의 환경 설정
    model_config = SettingsConfigDict(
        env_file=os.path.join(os.path.dirname(__file__), ".env"),
        env_file_encoding='utf-8'
    )

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        encoded_user = quote_plus(self.DB_USER)
        encoded_pw = quote_plus(self.DB_PW)
        self.DATABASE_URL = f"postgresql://{encoded_user}:{encoded_pw}@{self.DATABASE_URL}/{self.DATABASE_NAME}"

    @property
    def CURRENT_DATETIME(self) -> str:
        kst = pytz.timezone('Asia/Seoul')
        return datetime.now(kst).isoformat()
    

@lru_cache()
def get_settings():
    return Settings()

get_settings.cache_clear()
settings = get_settings()
