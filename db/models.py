from sqlalchemy import Column, String, Integer, DateTime, ForeignKey
from sqlalchemy.orm import declarative_base, relationship
import datetime

Base = declarative_base()

class Guild(Base):
    __tablename__ = 'guilds'
    guild_id = Column(String, primary_key=True)        # 디스코드 길드 ID (문자열 PK)
    guild_name = Column(String)
    auth_expiration_dt = Column(DateTime)
    welcome_ch_id = Column(String)
    parents_thread_ch_id = Column(String)
    create_dt = Column(DateTime)
    update_dt = Column(DateTime)

    # relationship 예시: 해당 길드의 모집글들
    recruitments = relationship("Recruitment", back_populates="guild")

class Recruitment(Base):
    __tablename__ = 'recruitments'
    recru_id = Column(String, primary_key=True)        # 모집글 ID (UUID나 시퀀스 문자열)
    dungeon_id = Column(String, ForeignKey('dungeons.dungeon_id'))
    pair_id = Column(String, ForeignKey('pair_channels.pair_id'))
    list_message_id = Column(String)                   # 디스코드에 게시된 모집글 메시지 ID
    create_user_id = Column(String)                    # 모집글 작성자 (유저 ID)
    recru_discript = Column(String)                    # 모집 설명 (최대 3000자)
    max_person = Column(Integer)
    status_code = Column(Integer)                      # 모집 상태 (진행중=1, 완료=2 등)
    create_dt = Column(DateTime)
    update_dt = Column(DateTime)
    guild_id = Column(String, ForeignKey('guilds.guild_id'))

    # 관계 설정
    guild = relationship("Guild", back_populates="recruitments")
    participants = relationship("Participant", back_populates="recruitment")
    complete_info = relationship("RecruitComplete", uselist=False, back_populates="recruitment")

class Participant(Base):
    __tablename__ = 'participants'
    # 복합 PK를 위해 SQLAlchemy에서는 __table_args__ 사용 또는 각각 PK 후 UniqueConstraint 설정
    user_id = Column(String, primary_key=True)
    recru_id = Column(String, ForeignKey('recruitments.recru_id'), primary_key=True)
    create_dt = Column(DateTime, default=datetime.datetime.utcnow)
    update_dt = Column(DateTime, default=datetime.datetime.utcnow)

    # 관계 설정
    recruitment = relationship("Recruitment", back_populates="participants")

class RecruitComplete(Base):
    __tablename__ = 'recru_complete'
    complete_id = Column(String, primary_key=True)        # 완료 레코드 ID
    recru_id = Column(String, ForeignKey('recruitments.recru_id'))
    activate_time = Column(DateTime)
    complete_thread_ch_id = Column(String)                # 생성된 비밀 스레드 채널 ID
    voice_ch_id = Column(String)                          # 생성된 음성 채널 ID
    create_dt = Column(DateTime, default=datetime.datetime.utcnow)
    update_dt = Column(DateTime, default=datetime.datetime.utcnow)

    # 관계 설정
    recruitment = relationship("Recruitment", back_populates="complete_info")
