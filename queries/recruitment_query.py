from sqlalchemy import text

SELECT_RECRUITMENT_CHANNEL = text("""
    SELECT regist_ch_id
    FROM pair_channels
""")
def select_recruitment_channel(db):
    return db.execute(SELECT_RECRUITMENT_CHANNEL, {
    }).fetchall()