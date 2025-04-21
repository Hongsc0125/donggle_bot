from sqlalchemy.sql import text


INSERT_COMPLETE_RECRUITMENT = text("""
    INSERT INTO recru_complete (
        recru_id,
        complete_thread_ch_id
    ) VALUES (
        :recru_id,
        :complete_thread_ch_id
    ) RETURNING recru_id
""")
def insert_complete_recruitment(db, recru_id, complete_thread_ch_id):
    """모집 완료 정보 추가"""
    row = db.execute(INSERT_COMPLETE_RECRUITMENT, {
        'recru_id': str(recru_id),
        'complete_thread_ch_id': str(complete_thread_ch_id)
    }).fetchone()
    return row[0] if row else None

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

SELECT_COMPLETE_THREAD = text("""
    SELECT complete_thread_ch_id
    FROM recru_complete
    WHERE recru_id = :recru_id
""")
def select_complete_thread(db, recru_id):
    """recru_id로 완료된 스레드 채널 ID 조회"""
    row = db.execute(SELECT_COMPLETE_THREAD, {
        'recru_id': str(recru_id)
    }).fetchone()
    return row[0] if row else None