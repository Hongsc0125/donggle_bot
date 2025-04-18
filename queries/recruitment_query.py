from sqlalchemy import text

# 등록채널조회
SELECT_RECRUITMENT_CHANNEL = text("""
    SELECT regist_ch_id
    FROM pair_channels
""")
def select_recruitment_channel(db):
    return db.execute(SELECT_RECRUITMENT_CHANNEL, {
    }).fetchall()

# 던전리스트 조회
SELECT_DUNGEON = text("""
    select
    (select discript from com_code where value=dungeon_type_code and column_name ='dungeon_type_code') as dungeon_type
    , (select discript from com_code where value=dungeon_name_code and column_name ='dungeon_name_code') as dungeon_name
    , (select discript from com_code where value=dungeon_difficulty_code and column_name ='dungeon_difficulty_code') as dungeon_difficulty
    from dungeons
""")
def select_dungeon(db):
    return db.execute(SELECT_DUNGEON, {
    }).fetchall()

# 최대 인원 설정값 조회
SELECT_MAX_PERSON_SETTING = text("""
    SELECT value
    FROM com_code
    WHERE column_name = 'max_person_setting_code'
""")
def select_max_person_setting(db):
    row = db.execute(SELECT_MAX_PERSON_SETTING, {
    }).fetchone()
    return row[0] if row else None



# 던전ID 조회
SELECT_DUNGEON_ID = text("""
    select dungeon_id
    from dungeons
    where dungeon_type_code = (SELECT value from com_code where discript=:dungeon_type and column_name ='dungeon_type_code')
    and dungeon_name_code = (SELECT value from com_code where discript=:dungeon_name and column_name ='dungeon_name_code')
    and dungeon_difficulty_code = (SELECT value from com_code where discript=:dungeon_difficulty and column_name ='dungeon_difficulty_code')
""")
def select_dungeon_id(db, dungeon_type, dungeon_name, dungeon_difficulty):
    row = db.execute(SELECT_DUNGEON_ID, {
        'dungeon_type': dungeon_type,
        'dungeon_name': dungeon_name,
        'dungeon_difficulty': dungeon_difficulty
    }).fetchone()
    return row[0] if row else None

# 페어아이디 조회
SELECT_PAIR_CHANNEL_ID = text("""
    SELECT pair_id
    FROM pair_channels
    WHERE guild_id = :guild_id
    AND regist_ch_id = :regist_ch_id
""")
def select_pair_channel_id(db, guild_id, regist_ch_id):
    row = db.execute(SELECT_PAIR_CHANNEL_ID, {
        'guild_id': str(guild_id),
        'regist_ch_id': str(regist_ch_id)
    }).fetchone()
    return row[0] if row else None
    
# 모집등록
INSERT_RECRUITMENT = text("""
    INSERT INTO recruitments (
        dungeon_id
        , pair_id
        , create_user_id
        , recru_discript
        , max_person
        , status_code
        ) VALUES (
        :dungeon_id
        , :pair_id
        , :create_user_id
        , :recru_discript
        , :max_person
        , :status_code
        ) RETURNING recru_id
""")
def insert_recruitment(db, dungeon_id, pair_id, create_user_id, recru_discript, max_person, status_code):
    row = db.execute(INSERT_RECRUITMENT, {
        'dungeon_id': str(dungeon_id),
        'pair_id': str(pair_id),
        'create_user_id': create_user_id,
        'recru_discript': recru_discript,
        'max_person': int(max_person),
        'status_code': status_code
    }).fetchone()
    return row[0] if row else None


# 모집상태값 공통코드에서 조회
SELECT_COM_CODE_STATUS = text("""
    SELECT discript
    FROM com_code
    WHERE column_name = 'status_code'
    AND value = :status
""")
def select_com_code_status(db, status):
    row = db.execute(SELECT_COM_CODE_STATUS, {
        'status': status
    }).fetchone()
    return row[0] if row else None


# 등록한 공고 조회
SELECT_RECRUITMENT = text("""
    SELECT
        (select discript from com_code where value=C.dungeon_type_code and column_name ='dungeon_type_code') as dungeon_type
        , (select discript from com_code where value=C.dungeon_name_code and column_name ='dungeon_name_code') as dungeon_name
        , (select discript from com_code where value=C.dungeon_difficulty_code and column_name ='dungeon_difficulty_code') as dungeon_difficulty
        , (select discript from com_code where value=A.status_code and column_name ='status_code') as status
        , A.recru_discript
        , A.max_person
        , A.create_user_id
        , A.recru_id
        , B.list_ch_id
        , A.list_message_id
    FROM recruitments A
    JOIN pair_channels B
    ON A.pair_id = B.pair_id
    JOIN dungeons C
    ON A.dungeon_id = C.dungeon_id
    WHERE 1=1
    AND recru_id = :recru_id
""")
def select_recruitment(db, recru_id):
    row = db.execute(SELECT_RECRUITMENT, {
        'recru_id': str(recru_id)
    }).fetchone()
    # SQLAlchemy Row를 딕셔너리로 변환
    return {
        'dungeon_type': row[0],
        'dungeon_name': row[1],
        'dungeon_difficulty': row[2],
        'status': row[3],
        'recru_discript': row[4],
        'max_person': row[5],
        'create_user_id': row[6],
        'recru_id': row[7],
        'list_ch_id': row[8],
        'list_message_id': row[9]
    }


# 메시지ID 저장
UPDATE_RECRUITMENT_MESSAGE_ID = text("""
    UPDATE recruitments
    SET list_message_id = :message_id
    WHERE recru_id = :recru_id
""")
def update_recruitment_message_id(db, message_id, recru_id):
    row = db.execute(UPDATE_RECRUITMENT_MESSAGE_ID, {
        'message_id': str(message_id),
        'recru_id': str(recru_id)
    })
    return row.rowcount > 0

# 해당 모집의 참가자들 반환 List[str]
SELECT_PARTICIPANTS = text("""
    SELECT user_id
    FROM participants
    WHERE recru_id = :recru_id
""")
def select_participants(db, recru_id):
    rows = db.execute(SELECT_PARTICIPANTS, {
        'recru_id': str(recru_id)
    }).fetchall()
    return [row[0] for row in rows] 