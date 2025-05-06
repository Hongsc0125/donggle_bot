# app/core/config.py
from pydantic_settings import BaseSettings
from datetime import datetime
import pytz
from urllib.parse import quote_plus
import logging

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

    # rankapiurl
    RANK_API_URL: str

    class Config:
        env_file = '.env'
        env_file_encoding = 'utf-8'

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        encoded_user = quote_plus(self.DB_USER)
        encoded_pw = quote_plus(self.DB_PW)
        self.DATABASE_URL = f"postgresql://{encoded_user}:{encoded_pw}@{self.DATABASE_URL}/{self.DATABASE_NAME}"

    @property
    def CURRENT_DATETIME(self) -> str:
        kst = pytz.timezone('Asia/Seoul')
        return datetime.now(kst).isoformat()

settings = Settings()