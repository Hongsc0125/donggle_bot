from sqlalchemy import text


SELECT_RECRUITMENT_CHANNEL = text("""
    SELECT regist_ch_id
    FROM pair_channels
""")
def select_recruitment_channel(db):
    return db.execute(SELECT_RECRUITMENT_CHANNEL, {
    }).fetchall()


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


SELECT_DUNGEON_ID = text("""
    select dungeon_id
    from dungeons
    where dungeon_type_code = (SELECT value from com_code where discript=:dungeon_type_code and column_name ='dungeon_type_code')
    and dungeon_name_code = (SELECT value from com_code where discript=:dungeon_name_code and column_name ='dungeon_name_code')
    and dungeon_difficulty_code = (SELECT value from com_code where discript=:dungeon_difficulty_code and column_name ='dungeon_difficulty_code')
""")
def select_dungeon_id(db, dungeon_type_code, dungeon_name_code, dungeon_difficulty_code):
    row = db.execute(SELECT_DUNGEON_ID, {
        'dungeon_type_code': dungeon_type_code,
        'dungeon_name_code': dungeon_name_code,
        'dungeon_difficulty_code': dungeon_difficulty_code
    }).fetchone()
    return row[0] if row else None

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