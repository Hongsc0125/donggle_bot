from sqlalchemy import text
import logging

logger = logging.getLogger(__name__)

# 알림 테이블이 존재하는지 확인
CHECK_ALERT_TABLE = text("""
    SELECT EXISTS (
        SELECT FROM information_schema.tables 
        WHERE table_name = 'alert'
    )
""")
def check_alert_table_exists(db):
    try:
        row = db.execute(CHECK_ALERT_TABLE).fetchone()
        return row[0] if row else False
    except Exception as e:
        logger.error(f"Error checking alert table: {e}")
        return False

# alert_type = boss, barrier, mon, tue, wed, thu, fri, sat, sun / custom
# interval = day, week, month
ALERT_LIST = text("""
    SELECT alert_id, interval, alert_type, alert_time
    FROM alert  
    WHERE alert_type = :alert_type
    ORDER BY alert_time
""")
def get_alert_list(db, alert_type):
    try:
        list = db.execute(ALERT_LIST, {
            "alert_type": alert_type
        }).fetchall()
        return [{
            'alert_id': row[0],
            'interval': row[1],
            'alert_type': row[2],
            'alert_time': row[3]
        } for row in list]
    except Exception as e:
        logger.error(f"Error getting alert list: {e}")
        return []

# 모든 알림 카테고리별로 가져오기(커스텀 제외)
GET_ALL_alert = text("""
    SELECT alert_id, interval, alert_type, alert_time
    FROM alert
    WHERE alert_type != 'custom'
    ORDER BY alert_type, alert_time
""")
def get_all_alerts(db):
    list = db.execute(GET_ALL_alert).fetchall()
    return [{
        'alert_id': row[0],
        'interval': row[1],
        'alert_type': row[2],
        'alert_time': row[3]
    } for row in list]


# Get alert by type (boss, barrier, days)
GET_alert_BY_TYPE = text("""
    SELECT alert_id, interval, alert_type, alert_time
    FROM alert
    WHERE alert_type IN ('boss', 'barrier', 'mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun')
    ORDER BY alert_type, alert_time
""")
def get_alert_by_type(db):
    list = db.execute(GET_alert_BY_TYPE).fetchall()
    return [{
        'alert_id': row[0],
        'interval': row[1],
        'alert_type': row[2],
        'alert_time': row[3]
    } for row in list]


# Get user's selected alert
GET_USER_alert = text("""
    SELECT a.alert_id, a.interval, a.alert_type, a.alert_time
    FROM alert a
    JOIN alert_user au ON a.alert_id = au.alert_id
    WHERE au.user_id = :user_id
    ORDER BY a.alert_type, a.alert_time
""")
def get_user_alerts(db, user_id):
    list = db.execute(GET_USER_alert, {
        "user_id": str(user_id)
    }).fetchall()
    return [{
        'alert_id': row[0],
        'interval': row[1],
        'alert_type': row[2],
        'alert_time': row[3]
    } for row in list]


# Check if a user has subscribed to an alert
CHECK_USER_ALERT = text("""
    SELECT COUNT(*)
    FROM alert_user
    WHERE user_id = :user_id
    AND alert_id = :alert_id
""")
def check_user_alert(db, user_id, alert_id):
    row = db.execute(CHECK_USER_ALERT, {
        "user_id": str(user_id),
        "alert_id": alert_id
    }).fetchone()
    return row[0] > 0


# Add user alert
ADD_USER_ALERT = text("""
    INSERT INTO alert_user (user_id, alert_id)
    VALUES (:user_id, :alert_id)
    ON CONFLICT (user_id, alert_id) DO NOTHING
""")
def add_user_alert(db, user_id, alert_id):
    result = db.execute(ADD_USER_ALERT, {
        "user_id": str(user_id),
        "alert_id": alert_id
    })
    return result.rowcount > 0


# Remove user alert
REMOVE_USER_ALERT = text("""
    DELETE FROM alert_user
    WHERE user_id = :user_id
    AND alert_id = :alert_id
""")
def remove_user_alert(db, user_id, alert_id):
    result = db.execute(REMOVE_USER_ALERT, {
        "user_id": str(user_id),
        "alert_id": alert_id
    })
    return result.rowcount > 0


# Create custom alert
CREATE_CUSTOM_ALERT = text("""
    INSERT INTO alert (alert_type, alert_time, interval)
    VALUES (:alert_type, :alert_time, :interval)
    RETURNING alert_id
""")
def create_custom_alert(db, alert_time, interval='day', alert_type='custom'):
    row = db.execute(CREATE_CUSTOM_ALERT, {
        "alert_time": alert_time,
        "interval": interval,
        "alert_type": alert_type
    }).fetchone()
    return row[0] if row else None


# Delete custom alert
DELETE_CUSTOM_ALERT = text("""
    DELETE FROM alert
    WHERE alert_id = :alert_id
    AND (alert_type = 'custom' OR alert_type LIKE 'custom_%')
    RETURNING alert_id
""")
def delete_custom_alert(db, alert_id):
    try:
        row = db.execute(DELETE_CUSTOM_ALERT, {
            "alert_id": alert_id
        }).fetchone()
        return row[0] if row else None
    except Exception as e:
        logger.error(f"Error deleting custom alert: {e}")
        return None


# Get alert by time (for notification sending)
GET_alert_BY_TIME = text("""
    SELECT a.alert_id, a.alert_type, a.alert_time, a.interval, au.user_id
    FROM alert a
    JOIN alert_user au ON a.alert_id = au.alert_id
    WHERE a.alert_time = :alert_time
    AND (
        (a.interval = 'day') OR
        (a.interval = 'week' AND a.alert_type = :day_of_week)
    )
""")
def get_alert_by_time(db, alert_time, day_of_week):
    list = db.execute(GET_alert_BY_TIME, {
        "alert_time": alert_time,
        "day_of_week": day_of_week
    }).fetchall()
    return [{
        'alert_id': row[0],
        'alert_type': row[1],
        'alert_time': row[2],
        'interval': row[3],
        'user_id': row[4]
    } for row in list]


# Get upcoming alert (for 5 minute warning)
GET_UPCOMING_alert = text("""
    SELECT a.alert_id, a.alert_type, a.alert_time, a.interval, au.user_id
    FROM alert a
    JOIN alert_user au ON a.alert_id = au.alert_id
    WHERE 
        CASE 
            WHEN a.interval = 'day' THEN true
            WHEN a.interval = 'week' AND a.alert_type = :day_of_week THEN true
            WHEN a.interval = 'week' AND a.alert_type = 'custom_' || :day_of_week THEN true
            ELSE false
        END
    AND a.alert_time = :alert_time
""")
def get_upcoming_alerts(db, alert_time, day_of_week):
    list = db.execute(GET_UPCOMING_alert, {
        "alert_time": alert_time,
        "day_of_week": day_of_week
    }).fetchall()
    return [{
        'alert_id': row[0],
        'alert_type': row[1],
        'alert_time': row[2],
        'interval': row[3],
        'user_id': row[4]
    } for row in list]

ADD_DEEP_ALERT_USER = text("""
    INSERT INTO deep_alert_user(
        user_id
        , guild_id
        , user_name
    ) VALUES (
        :user_id
        , :guild_id
        , :user_name
    ) RETURNING user_id, guild_id
""")
def add_deep_alert_user(db, user_id, guild_id, user_name):
    try:
        row = db.execute(ADD_DEEP_ALERT_USER, {
            "user_id": str(user_id),
            "guild_id": str(guild_id),
            "user_name": str(user_name)
        }).fetchone()
        return row[0] if row else None
    except Exception as e:
        logger.error(f"Error adding deep user: {e}")
        return None

# 심층 알림 받을 사용자 조회
SELECT_DEEP_ALERT_USERS = text("""
    SELECT user_id, guild_id, user_name
    FROM deep_alert_user
    WHERE guild_id = :guild_id
""")
def select_deep_alert_users(db, guild_id):
    rows = db.execute(SELECT_DEEP_ALERT_USERS, {
        'guild_id': str(guild_id)
    }).fetchall()
    return [{'user_id': row[0], 'guild_id': row[1], 'user_name': row[2]} for row in rows]

# 심층 알림 사용자 확인
CHECK_DEEP_ALERT_USER = text("""
    SELECT COUNT(*)
    FROM deep_alert_user
    WHERE user_id = :user_id
    AND guild_id = :guild_id
""")
def check_deep_alert_user(db, user_id, guild_id):
    try:
        row = db.execute(CHECK_DEEP_ALERT_USER, {
            "user_id": str(user_id),
            "guild_id": str(guild_id)
        }).fetchone()
        return row[0] > 0 if row else False
    except Exception as e:
        logger.error(f"Error checking deep alert user: {e}")
        return False

# 심층 알림 사용자 삭제
REMOVE_DEEP_ALERT_USER = text("""
    DELETE FROM deep_alert_user
    WHERE user_id = :user_id
    AND guild_id = :guild_id
    RETURNING user_id
""")
def remove_deep_alert_user(db, user_id, guild_id):
    try:
        row = db.execute(REMOVE_DEEP_ALERT_USER, {
            "user_id": str(user_id),
            "guild_id": str(guild_id)
        }).fetchone()
        return row[0] if row else None
    except Exception as e:
        logger.error(f"Error removing deep alert user: {e}")
        return None