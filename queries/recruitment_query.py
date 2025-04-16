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