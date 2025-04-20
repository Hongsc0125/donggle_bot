from sqlalchemy.sql import text


INSERT_COMPLETE_RECRUITMENT = text("""
    INSERT INTO recru_complete(
        recru_id
        , complete_thread_ch_id
    ) VALUES (
        :recru_id
        , :complete_thread_ch_id
    )
""")
def insert_complete_recruitment(db, recru_id, complete_thread_ch_id):
    row = db.execute(INSERT_COMPLETE_RECRUITMENT, {
        'recru_id': str(recru_id),
        'complete_thread_ch_id': str(complete_thread_ch_id)
    })
    return row.rowcount > 0

UPDATE_COMPLETE_RECRUITMENT = text("""
    UPDATE recru_complete
    SET voice_ch_id = :voice_ch_id
    , update_dt = now()
    WHERE recru_id = :recru_id
""")
def update_complete_recruitment(db, recru_id, voice_ch_id):
    row = db.execute(UPDATE_COMPLETE_RECRUITMENT, {
        'recru_id': str(recru_id),
        'voice_ch_id': str(voice_ch_id)
    })
    return row.rowcount > 0