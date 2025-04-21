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


INSERT_GUILD_AUTH = text("""
    INSERT INTO guilds (
        guild_id,
        guild_name,
        auth_expiration_dt
    ) VALUES (
        :guild_id,
        :guild_name,
        :auth_expiration_dt
    ) RETURNING *
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