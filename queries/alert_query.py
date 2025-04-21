from sqlalchemy import text


#  alert_type = boss, barrier, mon, tue, wed, thu, fri, sat, sun / custom
#  interval = day, week, month
ALERT_lIST = text("""
    SELECT interval, alert_type, alert_time
    FROM alerts
    WHERE 1=1
      AND alert_type = :alert_type
""")
def get_alert_list(db, guild_id, alert_type):
    list = db.execute(ALERT_lIST, {
        "guild_id": str(guild_id),
        "alert_type": alert_type
    }).fetchall()
    return[{
        'interval': row[0],
        'alert_type': row[1],
        'alert_time': row[2]
    } for row in list]