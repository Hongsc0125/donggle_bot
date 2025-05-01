from sqlalchemy import text

GET_PAIR_CHANNEL = text("""
    SELECT * FROM pair_channels
    WHERE guild_id = :guild_id
      AND regist_ch_id = :regist_ch_id
      AND list_ch_id = :list_ch_id
    LIMIT 1
""")
def get_pair_channel(db, guild_id, regist_ch_id, list_ch_id):
    return db.execute(GET_PAIR_CHANNEL, {
        "guild_id": str(guild_id),
        "regist_ch_id": str(regist_ch_id),
        "list_ch_id": str(list_ch_id)
    }).fetchone()


INSERT_PAIR_CHANNEL = text("""
    INSERT INTO pair_channels (
        guild_id,
        regist_ch_id,
        list_ch_id
    ) VALUES (
        :guild_id,
        :regist_ch_id,
        :list_ch_id
    ) RETURNING *
""")
def insert_pair_channel(db, guild_id, regist_ch_id, list_ch_id):
    return db.execute(INSERT_PAIR_CHANNEL, {
        "guild_id": str(guild_id),
        "regist_ch_id": str(regist_ch_id),
        "list_ch_id": str(list_ch_id)
    }).fetchone()


# Guild 인증 삽입/업데이트 (ON CONFLICT 사용)
INSERT_GUILD_AUTH = text("""
    INSERT INTO guilds (
        guild_id,
        guild_name,
        auth_expiration_dt
    ) VALUES (
        :guild_id,
        :guild_name,
        :auth_expiration_dt
    ) 
    ON CONFLICT (guild_id) 
    DO UPDATE SET 
        guild_name = :guild_name,
        auth_expiration_dt = :auth_expiration_dt,
        update_dt = now()
    RETURNING *
""")
def insert_guild_auth(db, guild_id, guild_name, expire_dt):
    return db.execute(INSERT_GUILD_AUTH, {
        "guild_id": str(guild_id),
        "guild_name": guild_name,
        "auth_expiration_dt": expire_dt
    }).fetchone()


SELECT_GUILD_AUTH = text("""
    SELECT COUNT(*) FROM guilds
    WHERE guild_id = :guild_id
      AND auth_expiration_dt > :auth_expiration_dt
""")
def select_guild_auth(db, guild_id, expire_dt):
    return db.execute(SELECT_GUILD_AUTH, {
        "guild_id": str(guild_id),
        "auth_expiration_dt": expire_dt
    }).fetchone()


# 슈퍼유저 조회
SELECT_SUPER_USER = text("""
    SELECT user_id
    FROM super_auth_user
""")
def select_super_user(db):
    row = db.execute(SELECT_SUPER_USER).fetchall()
    return [user[0] for user in row] if row else None



# 기존 UPDATE_DEEP_CHANNEL 제거 후 아래 코드로 대체
INSERT_DEEP_PAIR = text("""
    INSERT INTO deep_pair (
        deep_ch_id,
        deep_guild_auth,
        guild_id
    ) VALUES (
        :deep_ch_id,
        :deep_guild_auth,
        :guild_id
    ) ON CONFLICT (deep_ch_id, guild_id) 
    DO UPDATE SET 
        deep_guild_auth = :deep_guild_auth
    RETURNING deep_ch_id
""")
def insert_deep_pair(db, guild_id, deep_ch_id, deep_guild_auth):
    """심층 채널과 권한 매핑을 등록합니다."""
    result = db.execute(
        INSERT_DEEP_PAIR,
        {
            "guild_id": str(guild_id), 
            "deep_ch_id": str(deep_ch_id),
            "deep_guild_auth": str(deep_guild_auth)
        }
    )
    return result.rowcount > 0

# 심층 채널 조회 (수정: 모든 매핑 반환)
SELECT_DEEP_CHANNELS = text("""
    SELECT deep_ch_id, deep_guild_auth
    FROM deep_pair
    WHERE guild_id = :guild_id
""")
def select_deep_channels(db, guild_id):
    rows = db.execute(SELECT_DEEP_CHANNELS, {
        'guild_id': str(guild_id)
    }).fetchall()
    return [(row[0], row[1]) for row in rows] if rows else []

# 특정 권한과 연결된 심층 채널 조회
SELECT_DEEP_CHANNEL_BY_AUTH = text("""
    SELECT deep_ch_id
    FROM deep_pair
    WHERE guild_id = :guild_id
    AND deep_guild_auth = :deep_guild_auth
""")
def select_deep_channel_by_auth(db, guild_id, deep_guild_auth):
    row = db.execute(SELECT_DEEP_CHANNEL_BY_AUTH, {
        'guild_id': str(guild_id),
        'deep_guild_auth': str(deep_guild_auth)
    }).fetchone()
    return row[0] if row and row[0] else None

# 심층 채널에 매핑된 권한 조회
SELECT_DEEP_AUTH_BY_CHANNEL = text("""
    SELECT deep_guild_auth
    FROM deep_pair
    WHERE guild_id = :guild_id
    AND deep_ch_id = :deep_ch_id
""")
def select_deep_auth_by_channel(db, guild_id, deep_ch_id):
    row = db.execute(SELECT_DEEP_AUTH_BY_CHANNEL, {
        'guild_id': str(guild_id),
        'deep_ch_id': str(deep_ch_id)
    }).fetchone()
    return row[0] if row and row[0] else None

# 특정 권한과 연결된 심층 채널 목록 조회
SELECT_DEEP_CHANNELS_BY_AUTH = text("""
    SELECT deep_ch_id
    FROM deep_pair
    WHERE guild_id = :guild_id
    AND deep_guild_auth = :deep_guild_auth
""")
def select_deep_channels_by_auth(db, guild_id, deep_guild_auth):
    rows = db.execute(SELECT_DEEP_CHANNELS_BY_AUTH, {
        'guild_id': str(guild_id),
        'deep_guild_auth': str(deep_guild_auth)
    }).fetchall()
    return [row[0] for row in rows] if rows else []

# 기존 SELECT_DEEP_CHANNEL 유지 (하위 호환성)
# 심층 채널 조회
SELECT_DEEP_CHANNEL = text("""
    SELECT deep_ch_id
    FROM guilds
    WHERE guild_id = :guild_id
""")
def select_deep_channel(db, guild_id):
    row = db.execute(SELECT_DEEP_CHANNEL, {
        'guild_id': str(guild_id)
    }).fetchone()
    return row[0] if row and row[0] else None

# 비밀스레드 부모채널 설정
UPDATE_THREAD_CHANNEL = text("""
    UPDATE guilds
    SET parents_thread_ch_id = :channel_id
    , update_dt = now()
    WHERE guild_id = :guild_id
""")
def update_thread_channel(db, guild_id, channel_id):
    row = db.execute(UPDATE_THREAD_CHANNEL, {
        'guild_id': str(guild_id),
        'channel_id': str(channel_id)
    })
    return row.rowcount > 0

# 음성채널 부모채널 설정
UPDATE_VOICE_CHANNEL = text("""
    UPDATE guilds
    SET parents_voice_ch_id = :channel_id
    , update_dt = now()
    WHERE guild_id = :guild_id
""")
def update_voice_channel(db, guild_id, channel_id):
    row = db.execute(UPDATE_VOICE_CHANNEL, {
        'guild_id': str(guild_id),
        'channel_id': str(channel_id)
    })
    return row.rowcount > 0

# 길드의 음성채널 부모채널 ID 조회
SELECT_VOICE_CHANNEL = text("""
    SELECT parents_voice_ch_id
    FROM guilds
    WHERE guild_id = :guild_id
""")
def select_voice_channel(db, guild_id):
    row = db.execute(SELECT_VOICE_CHANNEL, {
        'guild_id': str(guild_id)
    }).fetchone()
    return row[0] if row and row[0] else None

# 길드의 음성채널 부모채널 ID 목록 조회
SELECT_VOICE_CHANNELS = text("""
    SELECT parents_voice_ch_id
    FROM guilds_voice_ch
    WHERE guild_id = :guild_id
""")
def select_voice_channels(db, guild_id):
    """음성채널 ID 목록 조회"""
    import logging
    logger = logging.getLogger(__name__)
    
    # logger.info(f"음성채널 ID 목록 조회: 길드 ID {guild_id}")
    try:
        rows = db.execute(SELECT_VOICE_CHANNELS, {
            'guild_id': str(guild_id)
        }).fetchall()
        result = [row[0] for row in rows] if rows else []
        # logger.info(f"음성채널 ID 목록 조회 결과: {result}")
        return result
    except Exception as e:
        logger.error(f"음성채널 ID 목록 조회 중 오류: {e}")
        return []

# 음성채널 추가
INSERT_VOICE_CHANNEL = text("""
    INSERT INTO guilds_voice_ch (
        guild_id,
        parents_voice_ch_id
    ) VALUES (
        :guild_id,
        :parents_voice_ch_id
    )
    ON CONFLICT (guild_id, parents_voice_ch_id) 
    DO NOTHING
    RETURNING parents_voice_ch_id
""")
def insert_voice_channel(db, guild_id, channel_id):
    """음성채널을 새 테이블에 추가"""
    result = db.execute(INSERT_VOICE_CHANNEL, {
        'guild_id': str(guild_id),
        'parents_voice_ch_id': str(channel_id)
    })
    return result.rowcount > 0

# 음성채널 삭제
DELETE_VOICE_CHANNEL = text("""
    DELETE FROM guilds_voice_ch
    WHERE guild_id = :guild_id
    AND parents_voice_ch_id = :parents_voice_ch_id
    RETURNING parents_voice_ch_id
""")
def delete_voice_channel(db, guild_id, channel_id):
    """음성채널을 테이블에서 제거"""
    result = db.execute(DELETE_VOICE_CHANNEL, {
        'guild_id': str(guild_id),
        'parents_voice_ch_id': str(channel_id)
    })
    return result.rowcount > 0

# 하위 호환성을 위한 기존 메서드 유지
def select_voice_channel(db, guild_id):
    """하위 호환성 - 음성채널 목록을 단일 채널처럼 반환"""
    channels = select_voice_channels(db, guild_id)
    return channels[0] if channels else None

# 알림 채널 설정
UPDATE_ALERT_CHANNEL = text("""
    UPDATE guilds
    SET alert_ch_id = :channel_id
    , update_dt = now()
    WHERE guild_id = :guild_id
""")
def update_alert_channel(db, guild_id, channel_id):
    row = db.execute(UPDATE_ALERT_CHANNEL, {
        'guild_id': str(guild_id),
        'channel_id': str(channel_id)
    })
    return row.rowcount > 0

# 알림 채널 조회
SELECT_ALERT_CHANNEL = text("""
    SELECT alert_ch_id
    FROM guilds
    WHERE guild_id = :guild_id
""")
def select_alert_channel(db, guild_id):
    row = db.execute(SELECT_ALERT_CHANNEL, {
        'guild_id': str(guild_id)
    }).fetchone()
    return row[0] if row and row[0] else None


INSERT_CHATBOT_CHANNEL = text('''
    INSERT INTO guilds (
        guild_id, 
        chatbot_ch_id
    ) VALUES (
        :guild_id, 
        :chatbot_ch_id
    ) ON CONFLICT (guild_id) 
    DO UPDATE SET 
        chatbot_ch_id = :chatbot_ch_id,
        update_dt = now()
    RETURNING chatbot_ch_id
''')

def insert_chatbot_channel(db, guild_id, chatbot_ch_id):
    """챗봇 채널 설정"""
    return db.execute(INSERT_CHATBOT_CHANNEL, {
        "guild_id": str(guild_id),
        "chatbot_ch_id": str(chatbot_ch_id)
    }).fetchone()

# 챗봇 채널 조회 쿼리
SELECT_CHATBOT_CHANNEL = text('''
    SELECT chatbot_ch_id FROM guilds
    WHERE guild_id = :guild_id
''')

def select_chatbot_channel(db, guild_id):
    """특정 길드의 챗봇 채널 조회"""
    result = db.execute(SELECT_CHATBOT_CHANNEL, {
        "guild_id": str(guild_id)
    }).fetchone()
    return result[0] if result else None