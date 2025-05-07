from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from core.config import settings
import logging

logger = logging.getLogger(__name__)

# 데이터베이스 엔진 생성
engine = create_engine(
    settings.DATABASE_URL,
    pool_pre_ping=True,  # 연결 유효성 검사
    echo=True  # SQL 쿼리 로깅 비활성화 (필요시 True로 변경)
)

rank_engine = create_engine(
    settings.RANK_DATA_URL,
    pool_pre_ping=True,  # 연결 유효성 검사
    echo=True  # SQL 쿼리 로깅 비활성화 (필요시 True로 변경)
)

# 세션 팩토리 생성
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def get_db():
    """DB 세션을 반환하는 함수"""
    db = SessionLocal()
    try:
        yield db
    except Exception as e:
        logger.error(f"Database error: {e}")
        db.rollback()
        raise
    finally:
        db.close()

def get_rank_db():
    """랭크 데이터베이스 세션을 반환하는 함수"""
    db = sessionmaker(autocommit=False, autoflush=False, bind=rank_engine)()
    try:
        yield db
    except Exception as e:
        logger.error(f"Rank Database error: {e}")
        db.rollback()
        raise
    finally:
        db.close()