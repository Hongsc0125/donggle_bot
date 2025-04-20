from sqlalchemy import create_engine
import logging
from db.models import Base
from core.config import settings

logger = logging.getLogger(__name__)

def init_db():
    """
    데이터베이스 테이블을 초기화하는 함수
    """
    try:
        engine = create_engine(settings.DATABASE_URL)
        # 모든 테이블 생성
        Base.metadata.create_all(bind=engine)
        logger.info("Database tables created successfully")
        return True
    except Exception as e:
        logger.error(f"Failed to initialize database: {str(e)}")
        return False

if __name__ == "__main__":
    # 로깅 설정
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # 데이터베이스 초기화
    success = init_db()
    if success:
        print("Database initialized successfully")
    else:
        print("Database initialization failed")
