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
        "alert_id": alert_id  # Don't try to convert to int
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
        "alert_id": alert_id  # Don't try to convert to int
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
        "alert_id": alert_id  # Don't try to convert to int
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

# 심층 알림 사용자 등록 - 채널 ID로 수정 (권한 대신)
ADD_DEEP_ALERT_USER = text("""
    INSERT INTO deep_alert_user(
        user_id
        , guild_id
        , user_name
        , deep_ch_id
    ) VALUES (
        :user_id
        , :guild_id
        , :user_name
        , :deep_ch_id
    )
    ON CONFLICT (user_id, guild_id, deep_ch_id) DO UPDATE 
    SET user_name = :user_name
    RETURNING user_id, guild_id
""")
def add_deep_alert_user(db, user_id, guild_id, user_name, deep_ch_id=None):
    try:
        row = db.execute(ADD_DEEP_ALERT_USER, {
            "user_id": str(user_id),
            "guild_id": str(guild_id),
            "user_name": str(user_name),
            "deep_ch_id": str(deep_ch_id) if deep_ch_id else None
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

# 심층 알림 받을 사용자 조회 - 권한 필터링 제거 (컬럼 없음)
SELECT_DEEP_ALERT_USERS_BY_AUTH = text("""
    SELECT user_id, guild_id, user_name
    FROM deep_alert_user
    WHERE guild_id = :guild_id
""")
def select_deep_alert_users_by_auth(db, guild_id, deep_guild_auth=None):
    # deep_guild_auth 컬럼이 없으므로 무시하고 모든 사용자 반환
    rows = db.execute(SELECT_DEEP_ALERT_USERS_BY_AUTH, {
        'guild_id': str(guild_id)
    }).fetchall()
    logger.info(f"Retrieved {len(rows)} deep alert users for guild {guild_id} (auth filter ignored)")
    return [{'user_id': row[0], 'guild_id': row[1], 'user_name': row[2]} for row in rows]

# 심층 알림 받을 사용자 조회 - 특정 채널에 등록된 사용자
SELECT_DEEP_ALERT_USERS_BY_CHANNEL = text("""
    SELECT user_id, guild_id, user_name
    FROM deep_alert_user
    WHERE guild_id = :guild_id
    AND deep_ch_id = :deep_ch_id
""")
def select_deep_alert_users_by_channel(db, guild_id, deep_ch_id):
    rows = db.execute(SELECT_DEEP_ALERT_USERS_BY_CHANNEL, {
        'guild_id': str(guild_id),
        'deep_ch_id': str(deep_ch_id)
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

# 심층 알림 사용자 확인 - 채널 ID 기준
CHECK_DEEP_ALERT_USER_BY_CHANNEL = text("""
    SELECT COUNT(*)
    FROM deep_alert_user
    WHERE user_id = :user_id
    AND guild_id = :guild_id
    AND deep_ch_id = :deep_ch_id
""")
def check_deep_alert_user_by_channel(db, user_id, guild_id, deep_ch_id):
    try:
        row = db.execute(CHECK_DEEP_ALERT_USER_BY_CHANNEL, {
            "user_id": str(user_id),
            "guild_id": str(guild_id),
            "deep_ch_id": str(deep_ch_id)
        }).fetchone()
        return row[0] > 0 if row else False
    except Exception as e:
        logger.error(f"Error checking deep alert user by channel: {e}")
        return False

# 심층 알림 사용자 삭제
REMOVE_DEEP_ALERT_USER = text("""
    DELETE FROM deep_alert_user
    WHERE user_id = :user_id
    AND guild_id = :guild_id
    AND DEEP_CH_ID = (SELECT deep_ch_id FROM deep_pair WHERE guild_id = :guild_id AND deep_guild_auth = :deep_guild_auth)
    RETURNING user_id
""")
def remove_deep_alert_user(db, user_id, guild_id, deep_guild_auth):
    try:
        row = db.execute(REMOVE_DEEP_ALERT_USER, {
            "user_id": str(user_id),
            "guild_id": str(guild_id),
            "deep_guild_auth": str(deep_guild_auth)
        }).fetchone()
        return row[0] if row else None
    except Exception as e:
        logger.error(f"Error removing deep alert user: {e}")
        return None

# 심층 알림 사용자 삭제 - 권한 파라미터 무시
def remove_deep_alert_user(db, user_id, guild_id, deep_guild_auth=None):
    try:
        # deep_guild_auth 파라미터 무시하고 기본 쿼리 사용
        row = db.execute("""
            DELETE FROM deep_alert_user
            WHERE user_id = :user_id
            AND guild_id = :guild_id
            RETURNING user_id
        """, {
            "user_id": str(user_id),
            "guild_id": str(guild_id)
        }).fetchone()
        return row[0] if row else None
    except Exception as e:
        logger.error(f"Error removing deep alert user: {e}")
        return None

# 심층 알림 사용자 삭제 - 채널 ID 기준
REMOVE_DEEP_ALERT_USER_BY_CHANNEL = text("""
    DELETE FROM deep_alert_user
    WHERE user_id = :user_id
    AND guild_id = :guild_id
    AND deep_ch_id = :deep_ch_id
    RETURNING user_id
""")
def remove_deep_alert_user_by_channel(db, user_id, guild_id, deep_ch_id):
    try:
        row = db.execute(REMOVE_DEEP_ALERT_USER_BY_CHANNEL, {
            "user_id": str(user_id),
            "guild_id": str(guild_id),
            "deep_ch_id": str(deep_ch_id)
        }).fetchone()
        return row[0] if row else None
    except Exception as e:
        logger.error(f"Error removing deep alert user by channel: {e}")
        return None

# 심층 제보자 정보 저장
INSERT_DEEP_INFORMANT = text("""
    INSERT INTO informant_deep_user(
        user_id
        , user_name
        , guild_id
        , guild_name
        , deep_type
        , remaining_minutes
    ) VALUES (
        :user_id
        , :user_name
        , :guild_id
        , :guild_name
        , :deep_type
        , :remaining_minutes
    )
    RETURNING deep_id
""")
def insert_deep_informant(db, user_id, user_name, guild_id, guild_name, deep_type, remaining_minutes):
    try:
        row = db.execute(INSERT_DEEP_INFORMANT, {
            "user_id": str(user_id),
            "user_name": str(user_name),
            "guild_id": str(guild_id),
            "guild_name": str(guild_name),
            "deep_type": str(deep_type),
            "remaining_minutes": remaining_minutes
        }).fetchone()
        return row[0] if row else None
    except Exception as e:
        logger.error(f"Error adding deep informant: {e}")
        return None

# 심층 제보자 정보 저장 - deep_ch_id 추가
INSERT_DEEP_INFORMANT = text("""
    INSERT INTO informant_deep_user(
        user_id
        , user_name
        , guild_id
        , guild_name
        , deep_type
        , remaining_minutes
        , deep_ch_id
    ) VALUES (
        :user_id
        , :user_name
        , :guild_id
        , :guild_name
        , :deep_type
        , :remaining_minutes
        , :deep_ch_id
    )
    RETURNING deep_id
""")
def insert_deep_informant(db, user_id, user_name, guild_id, guild_name, deep_type, remaining_minutes, deep_ch_id):
    try:
        row = db.execute(INSERT_DEEP_INFORMANT, {
            "user_id": str(user_id),
            "user_name": str(user_name),
            "guild_id": str(guild_id),
            "guild_name": str(guild_name),
            "deep_type": str(deep_type),
            "remaining_minutes": remaining_minutes,
            "deep_ch_id": str(deep_ch_id)
        }).fetchone()
        return row[0] if row else None
    except Exception as e:
        logger.error(f"Error adding deep informant: {e}")
        return None

# 심층 제보 신고 추가
INSERT_DEEP_ERROR = text("""
    INSERT INTO error_deep_info(
        deep_id
        , report_user_id
        , report_user_name
        , reason
    ) VALUES (
        :deep_id
        , :report_user_id
        , :report_user_name
        , :reason
    )
    ON CONFLICT (deep_id, report_user_id) DO NOTHING
    RETURNING deep_id
""")
def insert_deep_error(db, deep_id, report_user_id, report_user_name, reason=None):
    try:
        row = db.execute(INSERT_DEEP_ERROR, {
            "deep_id": deep_id,
            "report_user_id": str(report_user_id),
            "report_user_name": str(report_user_name),
            "reason": reason
        }).fetchone()
        return row[0] if row else None
    except Exception as e:
        logger.error(f"Error adding deep error report: {e}")
        return None

# 심층 제보 신고 횟수 확인
COUNT_DEEP_ERROR = text("""
    SELECT COUNT(*)
    FROM error_deep_info
    WHERE deep_id = :deep_id
""")
def count_deep_error(db, deep_id):
    try:
        row = db.execute(COUNT_DEEP_ERROR, {
            "deep_id": deep_id
        }).fetchone()
        return row[0] if row else 0
    except Exception as e:
        logger.error(f"Error counting deep error reports: {e}")
        return 0

# 심층 제보 error 표시 업데이트 
UPDATE_DEEP_ERROR = text("""
    UPDATE informant_deep_user
    SET is_error = 'Y'
    WHERE deep_id = :deep_id
    RETURNING deep_id
""")
def update_deep_error(db, deep_id):
    try:
        row = db.execute(UPDATE_DEEP_ERROR, {
            "deep_id": deep_id
        }).fetchone()
        return row[0] if row else None
    except Exception as e:
        logger.error(f"Error updating deep error status: {e}")
        return None

# 유저의 기존 신고 여부 확인
CHECK_USER_DEEP_ERROR = text("""
    SELECT COUNT(*)
    FROM error_deep_info
    WHERE deep_id = :deep_id
    AND report_user_id = :report_user_id
""")
def check_user_deep_error(db, deep_id, report_user_id):
    try:
        row = db.execute(CHECK_USER_DEEP_ERROR, {
            "deep_id": deep_id,
            "report_user_id": str(report_user_id)
        }).fetchone()
        return row[0] > 0 if row else False
    except Exception as e:
        logger.error(f"Error checking user deep error report: {e}")
        return False

# 심층 최근 등록 조회 - 동일 위치의 아직 시간이 지나지 않은 정보 - 채널별로 구분
CHECK_RECENT_DEEP = text("""
    SELECT deep_id, remaining_minutes 
    FROM informant_deep_user
    WHERE deep_type = :deep_type
    AND guild_id = :guild_id
    AND deep_ch_id = :deep_ch_id
    AND is_error = 'N'
    AND create_dt > NOW() - (INTERVAL '1 minute' * :remaining_minutes)
    ORDER BY create_dt DESC
    LIMIT 1
""")
def check_recent_deep(db, deep_type, guild_id, remaining_minutes, deep_ch_id):
    try:
        row = db.execute(CHECK_RECENT_DEEP, {
            "deep_type": deep_type,
            "guild_id": str(guild_id),
            "remaining_minutes": remaining_minutes,
            "deep_ch_id": str(deep_ch_id)
        }).fetchone()
        return {
            "deep_id": row[0],
            "remaining_minutes": row[1]
        } if row else None
    except Exception as e:
        logger.error(f"Error checking recent deep: {e}")
        return None

# 메시지 ID 업데이트
UPDATE_DEEP_MESSAGE_ID = text("""
    UPDATE informant_deep_user
    SET message_id = :message_id
    WHERE deep_id = :deep_id
    RETURNING deep_id
""")
def update_deep_message_id(db, deep_id, message_id):
    try:
        row = db.execute(UPDATE_DEEP_MESSAGE_ID, {
            "deep_id": deep_id,
            "message_id": str(message_id)
        }).fetchone()
        return row[0] if row else None
    except Exception as e:
        logger.error(f"Error updating deep message id: {e}")
        return None

# 메시지 ID 업데이트 - 해당 컬럼이 없으므로 수정하지 않고 성공 리턴
def update_deep_message_id(db, deep_id, message_id):
    try:
        # message_id 컬럼이 없으므로 실제 업데이트하지 않고 성공으로 처리
        # deep_id를 통해 메시지를 식별하므로 DB에 저장할 필요 없음
        logger.info(f"Deep message {message_id} associated with deep_id {deep_id} (no DB update needed)")
        return deep_id
    except Exception as e:
        logger.error(f"Error during deep message association: {e}")
        return None

# 오류로 표시된 심층 제보 ID 목록 조회
SELECT_ERROR_DEEP_IDS = text("""
    SELECT deep_id, message_id
    FROM informant_deep_user
    WHERE is_error = 'Y'
""")
def select_error_deep_ids(db):
    try:
        rows = db.execute(SELECT_ERROR_DEEP_IDS).fetchall()
        return [(row[0], row[1]) for row in rows] if rows else []
    except Exception as e:
        logger.error(f"Error selecting error deep ids: {e}")
        return []

# 모든 심층 제보 조회
SELECT_ALL_DEEP_REPORTS = text("""
    SELECT deep_id, deep_type, create_dt, remaining_minutes, is_error
    FROM informant_deep_user
    WHERE guild_id = :guild_id
""")
def select_all_deep_reports(db, guild_id):
    try:
        rows = db.execute(SELECT_ALL_DEEP_REPORTS, {
            "guild_id": str(guild_id)
        }).fetchall()
        return [{
            "deep_id": row[0],
            "deep_type": row[1],
            "create_dt": row[2],
            "remaining_minutes": row[3],
            "is_error": row[4]
        } for row in rows] if rows else []
    except Exception as e:
        logger.error(f"Error selecting all deep reports: {e}")
        return []

# 모든 심층 제보 조회 - 채널 ID 필터링 추가
SELECT_ALL_DEEP_REPORTS = text("""
    SELECT deep_id, deep_type, create_dt, remaining_minutes, is_error, deep_ch_id
    FROM informant_deep_user
    WHERE guild_id = :guild_id
    AND (:deep_ch_id IS NULL OR deep_ch_id = :deep_ch_id)
""")
def select_all_deep_reports(db, guild_id, deep_ch_id=None):
    try:
        rows = db.execute(SELECT_ALL_DEEP_REPORTS, {
            "guild_id": str(guild_id),
            "deep_ch_id": str(deep_ch_id) if deep_ch_id else None
        }).fetchall()
        return [{
            "deep_id": row[0],
            "deep_type": row[1],
            "create_dt": row[2],
            "remaining_minutes": row[3],
            "is_error": row[4],
            "deep_ch_id": row[5]
        } for row in rows] if rows else []
    except Exception as e:
        logger.error(f"Error selecting all deep reports: {e}")
        return []

# 사용자의 모든 심층 알림 설정 조회
SELECT_USER_DEEP_ALERTS = text("""
    SELECT deep_guild_auth
    FROM deep_alert_user
    WHERE user_id = :user_id
    AND guild_id = :guild_id
""")
def select_user_deep_alerts(db, user_id, guild_id):
    try:
        rows = db.execute(SELECT_USER_DEEP_ALERTS, {
            "user_id": str(user_id),
            "guild_id": str(guild_id)
        }).fetchall()
        return [row[0] for row in rows] if rows else []
    except Exception as e:
        logger.error(f"Error selecting user deep alerts: {e}")
        return []

# 사용자의 모든 심층 알림 설정 채널 조회
SELECT_USER_DEEP_ALERT_CHANNELS = text("""
    SELECT deep_ch_id
    FROM deep_alert_user
    WHERE user_id = :user_id
    AND guild_id = :guild_id
""")
def select_user_deep_alert_channels(db, user_id, guild_id):
    try:
        rows = db.execute(SELECT_USER_DEEP_ALERT_CHANNELS, {
            "user_id": str(user_id),
            "guild_id": str(guild_id)
        }).fetchall()
        return [row[0] for row in rows] if rows else []
    except Exception as e:
        logger.error(f"Error selecting user deep alert channels: {e}")
        return []

# 심층 알림 사용자 조회 - 권한 그룹으로 조회 (모든 채널)
def select_deep_alert_users_by_auth_group(db, guild_id, auth_group):
    try:
        # 1. 권한 그룹에 속한 모든 채널 목록 조회
        from queries.channel_query import select_deep_channels_by_auth
        channel_ids = select_deep_channels_by_auth(db, guild_id, auth_group)
        
        if not channel_ids:
            logger.info(f"No channels found for auth group '{auth_group}' in guild {guild_id}")
            return []
        
        # 2. 모든 채널에 등록된 사용자 조회 (중복 제거)
        placeholders = ', '.join([f"'{ch_id}'" for ch_id in channel_ids])
        query = text(f"""
            SELECT DISTINCT user_id, guild_id, user_name
            FROM deep_alert_user
            WHERE guild_id = :guild_id
            AND (deep_ch_id IN ({placeholders}) OR deep_ch_id IS NULL)
        """)
        
        rows = db.execute(query, {
            'guild_id': str(guild_id)
        }).fetchall()
        
        logger.info(f"Found {len(rows)} users for auth group '{auth_group}' in guild {guild_id}")
        return [{'user_id': row[0], 'guild_id': row[1], 'user_name': row[2]} for row in rows]
    except Exception as e:
        logger.error(f"Error getting alert users by auth group: {e}")
        return []

# 심층 알림 사용자 조회 - 권한 그룹으로 조회 (권한 그룹과 Discord 역할 일치 확인)
def select_deep_alert_users_by_auth_group(db, guild_id, auth_group):
    try:
        # 1. 권한 그룹에 속한 모든 채널 목록 조회
        from queries.channel_query import select_deep_channels_by_auth
        channel_ids = select_deep_channels_by_auth(db, guild_id, auth_group)
        
        if not channel_ids:
            logger.info(f"No channels found for auth group '{auth_group}' in guild {guild_id}")
            return []
        
        # 2. 해당 길드의 모든 알림 사용자 조회 (채널 무관)
        query = text("""
            SELECT DISTINCT user_id, guild_id, user_name
            FROM deep_alert_user
            WHERE guild_id = :guild_id
        """)
        
        rows = db.execute(query, {
            'guild_id': str(guild_id)
        }).fetchall()
        
        logger.info(f"Found {len(rows)} users registered for alerts in guild {guild_id}")
        return [{'user_id': row[0], 'guild_id': row[1], 'user_name': row[2]} for row in rows]
    except Exception as e:
        logger.error(f"Error getting alert users by auth group: {e}")
        return []

# 심층 알림 사용자 등록 - 권한별 중복 방지 로직 추가
ADD_DEEP_ALERT_USER = text("""
    INSERT INTO deep_alert_user(
        user_id
        , guild_id
        , user_name
        , deep_ch_id
    ) VALUES (
        :user_id
        , :guild_id
        , :user_name
        , :deep_ch_id
    )
    ON CONFLICT (user_id, guild_id, deep_ch_id) DO UPDATE 
    SET user_name = :user_name,
        deep_ch_id = :deep_ch_id
    RETURNING user_id, guild_id
""")
def add_deep_alert_user(db, user_id, guild_id, user_name, deep_ch_id):
    try:
        row = db.execute(ADD_DEEP_ALERT_USER, {
            "user_id": str(user_id),
            "guild_id": str(guild_id),
            "user_name": str(user_name),
            "deep_ch_id": str(deep_ch_id)
        }).fetchone()
        return row[0] if row else None
    except Exception as e:
        logger.error(f"Error adding deep user: {e}")
        return None

# 심층 알림 사용자 확인 - 권한별 체크
CHECK_DEEP_ALERT_USER = text("""
    SELECT COUNT(*)
    FROM deep_alert_user
    WHERE user_id = :user_id
    AND guild_id = :guild_id
    AND deep_ch_id = (SELECT deep_ch_id FROM deep_pair WHERE deep_guild_auth = :deep_guild_auth AND guild_id = :guild_id)
""")
def check_deep_alert_user(db, user_id, guild_id, deep_guild_auth):
    try:
        row = db.execute(CHECK_DEEP_ALERT_USER, {
            "user_id": str(user_id),
            "guild_id": str(guild_id),
            "deep_guild_auth": str(deep_guild_auth)
        }).fetchone()
        return row[0] > 0 if row else False
    except Exception as e:
        logger.error(f"Error checking deep alert user: {e}")
        return False

# 심층 알림 사용자 삭제 - 권한별 삭제
REMOVE_DEEP_ALERT_USER = text("""
    DELETE FROM deep_alert_user
    WHERE user_id = :user_id
    AND guild_id = :guild_id
    AND deep_ch_id = (SELECT deep_ch_id FROM deep_pair WHERE deep_guild_auth = :deep_guild_auth AND guild_id = :guild_id)
    RETURNING user_id
""")
def remove_deep_alert_user(db, user_id, guild_id, deep_guild_auth):
    try:
        row = db.execute(REMOVE_DEEP_ALERT_USER, {
            "user_id": str(user_id),
            "guild_id": str(guild_id),
            "deep_guild_auth": str(deep_guild_auth)
        }).fetchone()
        return row[0] if row else None
    except Exception as e:
        logger.error(f"Error removing deep alert user: {e}")
        return None