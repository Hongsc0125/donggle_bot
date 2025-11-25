import discord
from discord.ext import commands, tasks
from discord import app_commands
import logging
import asyncio
from datetime import datetime, timedelta
import re
import traceback
from core.config import settings
from sqlalchemy import text


from db.session import SessionLocal
from core.utils import interaction_response, interaction_followup
from queries.alert_query import (
    get_alert_list, get_user_alerts, add_user_alert, 
    remove_user_alert, create_custom_alert,
    get_upcoming_alerts, check_alert_table_exists,
    check_deep_alert_user, remove_deep_alert_user,
    add_deep_alert_user, select_deep_alert_users
)
from queries.channel_query import select_alert_channel

logger = logging.getLogger(__name__)

# 알림 유형 표시 이름
ALERT_TYPE_NAMES = {
    'boss': '보스', 
    'barrier': '결계', 
    'mon': '월요일', 
    'tue': '화요일', 
    'wed': '수요일', 
    'thu': '목요일', 
    'fri': '금요일', 
    'sat': '토요일', 
    'sun': '일요일'
}

# 알림 유형 이모지
ALERT_TYPE_EMOJI = {
    'boss': '👹', 
    'barrier': '🛡️', 
    'mon': '🔵', 
    'tue': '🔴', 
    'wed': '🟤', 
    'thu': '🟢', 
    'fri': '🟡', 
    'sat': '🟣', 
    'sun': '⚪'
}

# 요일 매핑 수정
DAY_OF_WEEK = {
    0: 'mon',
    1: 'tue',
    2: 'wed',
    3: 'thu',
    4: 'fri',
    5: 'sat',
    6: 'sun'
}

# 한글->영어 변환용 매핑 수정
INTERVAL_MAPPING = {
    "매일": "day", 
    "매주": "week", 
    "week": "week"
}

DAY_MAPPING = {
    "월": "mon", 
    "화": "tue", 
    "수": "wed", 
    "목": "thu", 
    "금": "fri", 
    "토": "sat", 
    "일": "sun", 
    "mon": "mon", 
    "tue": "tue", 
    "wed": "wed", 
    "thu": "thu", 
    "fri": "fri", 
    "sat": "sat", 
    "sun": "sun"
}

class AlertView(discord.ui.View):
    def __init__(self, user_id, bot):
        super().__init__(timeout=300)  # 5분 타임아웃
        self.user_id = user_id
        
        # 각 컴포넌트를 특정 행에 배치
        boss_select = AlertSelect('boss', '보스 알림 🔔', user_id)
        boss_select.row = 0  # 첫 번째 행
        self.add_item(boss_select)

        barrier_select = AlertSelect('barrier', '결계 알림 🛡️', user_id)
        barrier_select.row = 1  # 두 번째 행
        self.add_item(barrier_select)

        day_select = DaySelect(user_id)
        day_select.row = 2  # 세 번째 행
        self.add_item(day_select)

        # 커스텀 알림 버튼 - 무제한 추가 가능
        custom_btn = CustomAlertButton()
        custom_btn.row = 3  # 네 번째 행
        self.add_item(custom_btn)
        
        # 심층 알림 관련 데이터 가져오기
        with SessionLocal() as db:
            # 사용자가 속한 길드 정보 가져오기
            guild_id = None
            for guild in bot.guilds:
                member = guild.get_member(int(user_id))
                if member:
                    guild_id = guild.id
                    break
            
            if guild_id:
                # 사용자의 권한 확인 - 멤버 객체를 통해 역할 가져오기
                member = bot.get_guild(guild_id).get_member(int(user_id))
                user_roles = [role.name for role in member.roles] if member else []
                
                # 모든 심층 채널 및 권한 그룹 정보 가져오기
                from queries.channel_query import select_deep_channels
                auth_groups = []
                
                deep_channels = select_deep_channels(db, guild_id)
                for _, auth in deep_channels:
                    if auth not in auth_groups:
                        auth_groups.append(auth)
                
                # 사용자가 권한을 가진 그룹만 필터링 (관리자도 자신의 역할명과 일치하는 그룹만)
                user_auth_groups = []
                for auth_group in auth_groups:
                    if auth_group in user_roles:
                        user_auth_groups.append(auth_group)
                
                # 버튼 추가 - 사용자가 권한을 가진 그룹에 대해서만
                for i, auth_group in enumerate(user_auth_groups[:5]):  # 최대 5개 그룹으로 제한
                    is_on = check_deep_alert_user(db, user_id, guild_id, auth_group)
                    deep_btn = DeepAlertToggleButton(is_on, auth_group)
                    deep_btn.row = 4  # 모든 심층 버튼을 마지막 행에 배치
                    self.add_item(deep_btn)

class AlertSelect(discord.ui.Select):
    def __init__(self, alert_type, placeholder, user_id):
        self.alert_type = alert_type
        self.user_id = user_id  # 인스턴스 변수로 user_id 저장
        
        with SessionLocal() as db:
            # 이 유형의 알림 가져오기
            alerts = get_alert_list(db, alert_type)
            
            # 전달된 user_id를 사용하여 사용자 선택 알림 가져오기
            user_alerts = get_user_alerts(db, self.user_id)
            user_alert_ids = [str(alert['alert_id']) for alert in user_alerts]  # Convert all to strings
            
            # 옵션 생성
            options = []
            for alert in alerts:
                alert_time = alert['alert_time'].strftime('%H:%M')
                emoji = ALERT_TYPE_EMOJI.get(alert_type, '🔔')
                option = discord.SelectOption(
                    label=f"{ALERT_TYPE_NAMES.get(alert_type, alert_type)} {alert_time}",
                    value=str(alert['alert_id']),  # Ensure value is a string
                    description=f"{alert['interval']}마다 {alert_time}에 알림",
                    emoji=emoji,
                    default=str(alert['alert_id']) in user_alert_ids  # Compare strings with strings
                )
                options.append(option)
        
        super().__init__(
            placeholder=placeholder,
            min_values=0,
            max_values=len(options) if options else 1,
            options=options if options else [discord.SelectOption(label="알림 없음", value="none", disabled=True)]
        )

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        
        with SessionLocal() as db:
            try:
                # 현재 사용자의 이 유형 알림 가져오기
                user_alerts = get_user_alerts(db, interaction.user.id)
                current_alert_ids = [str(alert['alert_id']) for alert in user_alerts 
                                    if alert['alert_type'] == self.alert_type]  # Convert to string
                
                # 추가할 알림과 제거할 알림 결정
                selected_alert_ids = [alert_id for alert_id in self.values]  # Keep as strings
                
                # 새 선택 추가
                for alert_id in selected_alert_ids:
                    if alert_id not in current_alert_ids:
                        add_user_alert(db, interaction.user.id, alert_id)
                
                # 선택 해제된 항목 제거
                for alert_id in current_alert_ids:
                    if alert_id not in selected_alert_ids:
                        remove_user_alert(db, interaction.user.id, alert_id)
                
                db.commit()
                
                await interaction_followup(interaction, f"{ALERT_TYPE_NAMES.get(self.alert_type, self.alert_type)} 알림 설정이 저장되었습니다!")
                
            except Exception as e:
                logger.error(f"알림 설정 처리 중 오류: {str(e)}")
                await interaction_followup(interaction, "알림 설정 중 오류가 발생했습니다.")
                db.rollback()

class DaySelect(discord.ui.Select):
    def __init__(self, user_id=None):  # 기본값이 None인 user_id 매개변수 추가
        self.user_id = user_id  # user_id 저장
        options = []
        days = [
            ('mon', '월요일', '🔵'),
            ('tue', '화요일', '🔴'),
            ('wed', '수요일', '🟤'),
            ('thu', '목요일', '🟢'),
            ('fri', '금요일', '🟡'),
            ('sat', '토요일', '🟣'),
            ('sun', '일요일', '⚪')
        ]
        
        for day_code, day_name, emoji in days:
            option = discord.SelectOption(
                label=day_name,
                value=day_code,
                emoji=emoji
            )
            options.append(option)
        
        # user_id가 제공된 경우 현재 선택 항목 미리 선택
        if user_id:
            with SessionLocal() as db:
                user_alerts = get_user_alerts(db, user_id)
                selected_days = [alert['alert_type'] for alert in user_alerts 
                               if alert['alert_type'] in ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun']]
                
                # 사용자 선택에 따라 기본 상태 업데이트
                for option in options:
                    option.default = option.value in selected_days
        
        super().__init__(
            placeholder="요일 알림 📅",
            min_values=0,
            max_values=len(options),
            options=options
        )
    
    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        
        with SessionLocal() as db:
            try:
                selected_days = self.values
                
                # 요일 알림 가져오기
                day_alerts = []
                for day in ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun']:
                    day_alerts.extend(get_alert_list(db, day))
                
                # 사용자가 선택한 요일 알림 가져오기
                user_alerts = get_user_alerts(db, interaction.user.id)
                current_day_alert_ids = [str(alert['alert_id']) for alert in user_alerts 
                                        if alert['alert_type'] in ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun']]
                
                # 각 요일 알림 처리
                for alert in day_alerts:
                    alert_id_str = str(alert['alert_id'])  # Convert to string
                    if alert['alert_type'] in selected_days and alert_id_str not in current_day_alert_ids:
                        # 이 요일 알림 추가
                        add_user_alert(db, interaction.user.id, alert_id_str)
                    elif alert['alert_type'] not in selected_days and alert_id_str in current_day_alert_ids:
                        # 이 요일 알림 제거
                        remove_user_alert(db, interaction.user.id, alert_id_str)
                
                db.commit()
                
                day_names = [ALERT_TYPE_NAMES.get(day, day) for day in selected_days]
                await interaction_followup(interaction, f"요일 알림이 설정되었습니다: {', '.join(day_names) if day_names else '없음'}")
                
            except Exception as e:
                logger.error(f"요일 알림 설정 처리 중 오류: {str(e)}")
                await interaction_followup(interaction, "알림 설정 중 오류가 발생했습니다.")
                db.rollback()

class CustomAlertButton(discord.ui.Button):
    def __init__(self):
        super().__init__(
            style=discord.ButtonStyle.primary,
            label="커스텀 알림 추가",
            emoji="➕",
            row=4
        )
    
    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_modal(CustomAlertModal())

class CustomAlertModal(discord.ui.Modal, title="커스텀 알림 등록"):
    alert_time = discord.ui.TextInput(
        label="알림 시간 (HH:MM 형식)",
        placeholder="예: 08:30",
        required=True,
        min_length=5,
        max_length=5
    )
    
    interval = discord.ui.TextInput(
        label="반복 주기",
        placeholder="매일, 매주 중 하나",
        required=True,
        default="매일"
    )
    
    day_of_week = discord.ui.TextInput(
        label="요일 (주기가 매주인 경우만 입력)",
        placeholder="월, 화, 수, 목, 금, 토, 일 중 하나",
        required=False
    )
    
    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        # 시간 형식 검증
        time_pattern = re.compile(r'^([0-1][0-9]|2[0-3]):([0-5][0-9])$')
        if not time_pattern.match(self.alert_time.value):
            await interaction_followup(interaction, "❌ 시간 형식이 올바르지 않습니다. HH:MM 형식으로 입력해주세요.")
            return
        
        # 주기 한글->영어 변환
        interval_input = self.interval.value.strip()
        interval = INTERVAL_MAPPING.get(interval_input)
        if not interval:
            await interaction_followup(interaction, "❌ 반복 주기는 '매일' 또는 '매주'로 입력해주세요.")
            return
        
        # 알림 타입 설정
        alert_type = 'custom'
        
        # 주간 알림의 경우 요일 검증 및 알림 타입 업데이트
        if interval == 'week':
            # 요일 한글->영어 변환
            day_input = self.day_of_week.value.strip() if self.day_of_week.value else ''
            day = DAY_MAPPING.get(day_input)
            
            if not day:
                await interaction_followup(interaction, "❌ 주간 알림의 경우 요일을 '월', '화', '수', '목', '금', '토', '일' 중 선택해주세요.")
                return
            
            # 주간 알림의 경우 알림 타입을 "custom_[day]"로 설정
            alert_type = f"custom_{day}"
        
        with SessionLocal() as db:
            try:
                # 적절한 알림 타입으로 커스텀 알림 생성
                alert_id = create_custom_alert(db, self.alert_time.value, interval, alert_type)
                
                if not alert_id:
                    await interaction_followup(interaction, "❌ 커스텀 알림 생성에 실패했습니다.")
                    return
                
                # 사용자에게 할당
                add_user_alert(db, interaction.user.id, alert_id)
                
                db.commit()
                
                # 적절한 성공 메시지 생성
                interval_display = "매일" if interval == "day" else "매주"
                day_text = ""
                if interval == 'week':
                    day_name = ALERT_TYPE_NAMES.get(day, day)
                    day_text = f" ({day_name})"
                
                await interaction_followup(interaction, f"✅ 커스텀 알림이 등록되었습니다: {interval_display}{day_text} {self.alert_time.value}")
                
            except Exception as e:
                logger.error(f"커스텀 알림 등록 중 오류: {str(e)}")
                await interaction_followup(interaction, "❌ 커스텀 알림 등록 중 오류가 발생했습니다.")
                db.rollback()

class CustomAlertDeleteButton(discord.ui.Button):
    def __init__(self, alert_id):
        super().__init__(
            style=discord.ButtonStyle.danger,
            emoji="🗑️",
            custom_id=f"delete_custom_alert_{alert_id}"
        )
        self.alert_id = alert_id
    
    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        
        with SessionLocal() as db:
            try:
                # 사용자가 해당 알림을 등록했는지 확인
                user_alerts = get_user_alerts(db, interaction.user.id)
                alert_ids = [alert['alert_id'] for alert in user_alerts]
                
                if self.alert_id not in alert_ids:
                    await interaction_followup(interaction, "❌ 해당 알림을 찾을 수 없습니다.")
                    return
                
                # 사용자-알림 연결 삭제
                remove_user_alert(db, interaction.user.id, self.alert_id)
                
                # 해당 알림을 사용하는 다른 사용자가 있는지 확인
                from sqlalchemy import text
                check_query = text("SELECT COUNT(*) FROM alert_user WHERE alert_id = :alert_id")
                result = db.execute(check_query, {"alert_id": self.alert_id}).fetchone()
                
                # 다른 사용자가 없으면 알림 자체도 삭제
                if result[0] == 0:
                    from queries.alert_query import delete_custom_alert
                    delete_custom_alert(db, self.alert_id)
                
                db.commit()
                
                # 삭제 성공 메시지 표시
                await interaction_followup(interaction, "✅ 커스텀 알림이 삭제되었습니다.")
                
                # 메시지 삭제 시도 - 현재 메시지를 완전히 삭제
                try:
                    await interaction.message.delete()
                except:
                    pass
                
                # 새로운 상호작용으로 새 명령어 실행하도록 안내
                await interaction_followup(interaction, "알림 설정이 변경되었습니다. 메시지를 닫고 `/알림설정` 명령어 또는 버튼을 다시클릭하여 설정 화면을 열어주세요.")
                
            except Exception as e:
                logger.error(f"커스텀 알림 삭제 중 오류: {str(e)}")
                await interaction_followup(interaction, "❌ 알림 삭제 중 오류가 발생했습니다.")
                db.rollback()

class CustomAlertView(discord.ui.View):
    def __init__(self, custom_alerts, parent_cog):
        super().__init__(timeout=180)
        self.parent_cog = parent_cog
        
        if not custom_alerts:
            # 커스텀 알림이 없는 경우 안내 메시지만 표시
            return
        
        # 각 커스텀 알림에 대한 삭제 버튼 추가
        for i, alert in enumerate(custom_alerts):
            delete_btn = CustomAlertDeleteButton(alert['alert_id'])
            delete_btn.row = i // 2  # 한 줄에 2개씩 표시
            self.add_item(delete_btn)

class AlertRegisterButton(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)  # 시간 제한 없는 영구 버튼
    
    @discord.ui.button(label="알림등록", style=discord.ButtonStyle.primary, custom_id="alert_register")
    async def register_alert(self, interaction: discord.Interaction, button: discord.ui.Button):
        """알림등록 버튼 처리"""
        alert_cog = interaction.client.get_cog("AlertCog")
        if (alert_cog):
            await alert_cog.show_alert_settings(interaction)

# 심층 알림 토글 버튼 클래스 수정
class DeepAlertToggleButton(discord.ui.Button):
    def __init__(self, is_on=False, auth_group=None):
        super().__init__(
            style=discord.ButtonStyle.success if is_on else discord.ButtonStyle.secondary,
            label=f"심층 알림 ON ({auth_group})" if is_on else f"심층 알림 OFF ({auth_group})",
            emoji="🧊" if is_on else "🔕",
            row=3
        )
        self.is_on = is_on
        self.auth_group = auth_group
    
    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        
        with SessionLocal() as db:
            try:
                # 현재 상태 확인
                user_id = interaction.user.id
                guild_id = interaction.guild.id
                auth_group = self.auth_group
                
                if self.is_on:
                    # 알림 제거 - 권한별로 제거
                    result = remove_deep_alert_user(db, user_id, guild_id, auth_group)
                    if result:
                        self.is_on = False
                        self.style = discord.ButtonStyle.secondary
                        self.label = f"심층 알림 OFF ({auth_group})"
                        self.emoji = "🔕"
                        message = f"{auth_group} 심층 알림이 비활성화되었습니다."
                    else:
                        message = f"{auth_group} 심층 알림 비활성화에 실패했습니다."
                else:
                    # 해당 권한 그룹과 연결된 채널 ID 조회
                    from queries.channel_query import select_deep_channel_by_auth
                    deep_ch_id = select_deep_channel_by_auth(db, guild_id, auth_group)
                    
                    if not deep_ch_id:
                        message = f"{auth_group} 채널 정보를 찾을 수 없습니다. 관리자에게 문의하세요."
                    else:
                        # 알림 추가 - 권한별로 추가 (상호작용 채널이 아닌 권한 그룹의 채널 사용)
                        result = add_deep_alert_user(db, user_id, guild_id, interaction.user.display_name, deep_ch_id)
                        if result:
                            self.is_on = True
                            self.style = discord.ButtonStyle.success
                            self.label = f"심층 알림 ON ({auth_group})"
                            self.emoji = "🧊"
                            message = f"{auth_group} 심층 알림이 활성화되었습니다. 심층 제보가 있을 때 DM으로 알림을 받습니다."
                        else:
                            message = f"{auth_group} 심층 알림 활성화에 실패했습니다."
                
                db.commit()
                await interaction_followup(interaction, message)
                
                # 뷰 업데이트
                try:
                    await interaction.message.edit(view=self.view)
                except discord.errors.NotFound:
                    logger.warning("메시지를 찾을 수 없습니다. 알림 토글 버튼을 다시 생성해야 합니다.")
                    await interaction_followup(interaction, "알림 설정이 변경되었습니다. 등록 양식 메시지를 닫고 `알림등록` 버튼을 다시 눌러 상태를 갱신해주세요.")
                except Exception as e:
                    logger.error(f"메시지 업데이트 중 오류: {e}")
                
            except Exception as e:
                logger.error(f"심층 알림 토글 중 오류: {str(e)}")
                await interaction_followup(interaction, "설정 변경 중 오류가 발생했습니다.")
                db.rollback()

class AlertCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # self.check_alerts.start()
        self.last_sent_alerts = {}
        logger.info("AlertCog 초기화 완료")
    
    def cog_unload(self):
        # self.check_alerts.cancel()
        pass
    
    @commands.Cog.listener()
    async def on_ready(self):
        """봇이 준비되면 알림 채널 초기화"""
        logger.info("알림 시스템 초기화 중...")
        
        try:
            # 알림 테이블이 존재하는지 확인
            with SessionLocal() as db:
                table_exists = check_alert_table_exists(db)
                if not table_exists:
                    logger.error("알림 테이블 없음.")
                    return
            
            # 모든 길드의 알림 채널 초기화
            for guild in self.bot.guilds:
                with SessionLocal() as db:
                    try:
                        alert_channel_id = select_alert_channel(db, guild.id)
                        if alert_channel_id:
                            await self.initialize_alert_channel(alert_channel_id)
                            logger.info(f"길드 {guild.id} 알림 채널 {alert_channel_id} 초기화 완료")
                        else:
                            logger.info(f"길드 {guild.id}에 설정된 알림 채널이 없습니다")
                    except Exception as e:
                        logger.error(f"길드 {guild.id}의 알림 채널 초기화 중 오류: {e}")
            
            logger.info("알림 시스템 초기화 완료")
        except Exception as e:
            logger.error(f"알림 시스템 초기화 중 오류: {e}")
            logger.error(traceback.format_exc())
    
    async def initialize_alert_channel(self, channel_id):
        """알림 채널 초기화 - 버튼 메시지 설정"""
        channel = self.bot.get_channel(int(channel_id))
        if not channel:
            logger.warning(f"알림 채널 {channel_id}를 찾을 수 없습니다.")
            return
        
        logger.info(f"알림 채널 {channel_id} 초기화 시작")
        view = AlertRegisterButton()

        instruction_embed = discord.Embed(
            title="**알림 등록 버튼을 눌러주세요!**",
            description="버튼이 동작을 안한다면 명령어를 입력해주세요.\n\n" +
            "> **알림 설정 명령어** \n" +
            "> `/알림설정`\n\n" +
            "> **사용법**\n" +
            "> 아래 버튼을 클릭하거나 `/알림설정` 명령어를 입력해서 알림을 설정하세요.",
            color=discord.Color.blue()
        )

        # 기존 버튼이 있는지 확인
        last_message = None
        try:
            async for message in channel.history(limit=5, oldest_first=False):
                if (
                    message.author.id == self.bot.user.id and
                    message.components and
                    any(
                        any(
                            hasattr(child, "custom_id") and child.custom_id == "alert_register"
                            for child in (component.children if hasattr(component, "children") else [])
                        )
                        for component in message.components
                    )
                ):
                    last_message = message
                    break
        except Exception as e:
            logger.warning(f"채널 {channel_id} 메시지 조회 실패: {str(e)}")

        # 기존 버튼이 있으면 업데이트, 없으면 새로 생성
        if last_message:
            try:
                await last_message.edit(embed=instruction_embed, view=view)
                logger.info(f"알림 채널 {channel_id} 기존 버튼 메시지 업데이트 완료")
            except Exception as e:
                logger.warning(f"알림 채널 {channel_id} 버튼 갱신 실패: {str(e)}")
        else:
            try:
                await channel.send(embed=instruction_embed, view=view)
                logger.info(f"알림 채널 {channel_id} 새 버튼 메시지 생성 완료")
            except Exception as e:
                logger.warning(f"알림 채널 {channel_id}에 버튼 메시지 전송 실패: {str(e)}")
    
    async def show_alert_settings(self, interaction: discord.Interaction):
        """알림 설정 UI를 표시"""
        logger.info(f"알림설정 UI 표시: 사용자 {interaction.user.id}")
        try:
            
            if not interaction.response.is_done():
                await interaction.response.defer(ephemeral=True)

            # 이미 응답된 상호작용인지 확인
            if interaction.response.is_done():
                logger.info("이미 응답된 상호작용입니다. followup 메시지를 사용합니다.")
                send_method = interaction.followup.send
            else:
                logger.info("새 상호작용 응답을 전송합니다.")
                send_method = interaction.response.send_message
            
            # 알림 테이블 존재 확인
            with SessionLocal() as db:
                table_exists = check_alert_table_exists(db)
                if not table_exists:
                    logger.error("알림 테이블이 존재하지 않습니다!")
                    await interaction_response(interaction, 
                                             "알림 시스템 테이블이 존재하지 않습니다. 관리자에게 문의하세요.", 
                                             ephemeral=True)
                    return
                
                # 심층 알림 상태 확인
                is_deep_alert_on = check_deep_alert_user(db, interaction.user.id, interaction.guild.id, None)
            
            # 알림 설정 임베드 생성
            embed = discord.Embed(
                title="⏰ 알림 설정",
                description="원하는 알림을 선택하세요. 알림은 DM으로 발송됩니다.\n\n" +
                           "커스텀 알림 설정 시:\n" +
                           "• 주기: '매일' 또는 '매주'\n" + 
                           "• 주기가 '매주'인 경우 요일을 월~일 중에서 선택하세요.",
                color=discord.Color.blue()
            )
            
            # 사용자의 현재 알림 가져오기
            with SessionLocal() as db:
                try:
                    user_alerts = get_user_alerts(db, interaction.user.id)
                    logger.info(f"사용자 알림 조회 성공: {len(user_alerts)}개 알림")
                except Exception as e:
                    logger.error(f"사용자 알림 조회 중 오류: {str(e)}")
                    await interaction_response(interaction, 
                                             f"알림 정보 조회 중 오류가 발생했습니다: {str(e)}", 
                                             ephemeral=True)
                    return
            
            # 유형별로 알림 그룹화
            boss_alerts = [a for a in user_alerts if a['alert_type'] == 'boss']
            barrier_alerts = [a for a in user_alerts if a['alert_type'] == 'barrier']
            day_alerts = [a for a in user_alerts if a['alert_type'] in ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun']]
            custom_alerts = [a for a in user_alerts if a['alert_type'] == 'custom' or a['alert_type'].startswith('custom_')]
            
            # 각 알림 유형에 대한 필드 추가
            if boss_alerts:
                boss_times = ", ".join([a['alert_time'].strftime('%H:%M') for a in boss_alerts])
                embed.add_field(name="👹 보스 알림", value=boss_times, inline=False)
            
            if barrier_alerts:
                barrier_times = ", ".join([a['alert_time'].strftime('%H:%M') for a in barrier_alerts])
                embed.add_field(name="🛡️ 결계 알림", value=barrier_times, inline=False)
            
            if day_alerts:
                day_values = {}
                for a in day_alerts:
                    day_type = a['alert_type']
                    day_values[day_type] = day_values.get(day_type, []) + [a['alert_time'].strftime('%H:%M')]
                
                day_text = "\n".join([f"{ALERT_TYPE_EMOJI.get(day)} {ALERT_TYPE_NAMES.get(day)}: {', '.join(times)}"
                                    for day, times in day_values.items()])
                embed.add_field(name="📅 요일 알림", value=day_text, inline=False)
            
            # 커스텀 알림 섹션
            if custom_alerts:
                custom_times = []
                for a in custom_alerts:
                    time_str = a['alert_time'].strftime('%H:%M')
                    if a['alert_type'].startswith('custom_'):
                        # custom_[day] 형식에서 day 코드 추출
                        day_code = a['alert_type'][7:]  # "custom_" 접두사 제거
                        day_name = ALERT_TYPE_NAMES.get(day_code, day_code)
                        custom_times.append(f"{time_str} (매주 {day_name})")
                    else:
                        interval_display = "매일" if a['interval'] == "day" else "매주"
                        custom_times.append(f"{time_str} ({interval_display})")
                
                # 커스텀 알림 정보 표시
                embed.add_field(
                    name="➕ 커스텀 알림",
                    value=", ".join(custom_times) + f"\n\n아래 버튼으로 커스텀 알림을 관리할 수 있습니다.\n(현재 {len(custom_alerts)}개 등록됨)",
                    inline=False
                )
            
            # 심층 알림 상태 표시
            embed.add_field(
                name="🧊 심층 알림",
                value="활성화됨" if is_deep_alert_on else "비활성화됨",
                inline=False
            )
            
            if not any([boss_alerts, barrier_alerts, day_alerts, custom_alerts]):
                embed.add_field(name="알림 없음", value="아래 버튼과 선택 메뉴를 사용하여 알림을 설정하세요.", inline=False)
            
            embed.set_footer(text="알림은 설정 시간 5분 전과 정각에 발송됩니다.")
            
            # 기본 알림 선택용 뷰 생성
            view = AlertView(interaction.user.id, self.bot)
            
            # 커스텀 알림 삭제 버튼 추가
            for i, alert in enumerate(custom_alerts):
                delete_btn = CustomAlertDeleteButton(alert['alert_id'])
                # 알림 정보 표시
                if alert['alert_type'].startswith('custom_'):
                    day_code = alert['alert_type'][7:]
                    day_name = ALERT_TYPE_NAMES.get(day_code, day_code)
                    time_display = f"{alert['alert_time'].strftime('%H:%M')} (매주 {day_name})"
                else:
                    interval_display = "매일" if alert['interval'] == "day" else "매주"
                    time_display = f"{alert['alert_time'].strftime('%H:%M')} ({interval_display})"

                delete_btn.label = f"삭제: {time_display}"
                delete_btn.row = 4 + (i // 5)  # 한 줄에 다섯 개씩 배치
                view.add_item(delete_btn)
            
            # 메시지 전송 (적절한 메서드 사용)
            await send_method(embed=embed, view=view, ephemeral=True)
            logger.info("알림설정 UI 전송 완료")
            
        except discord.errors.InteractionResponded:
            logger.warning("이미 응답된 상호작용입니다. 새 명령어를 실행하도록 유도합니다.")
        except Exception as e:
            logger.error(f"알림 설정 UI 표시 중 오류: {str(e)}")
            logger.error(traceback.format_exc())
            if not interaction.response.is_done():
                await interaction_response(interaction, "알림 설정 처리 중 오류가 발생했습니다.", ephemeral=True)
            else:
                await interaction_followup(interaction, "알림 설정 처리 중 오류가 발생했습니다.")
    
    @app_commands.command(name="알림설정", description="보스, 결계, 요일 알림을 설정합니다")
    async def alert_settings(self, interaction: discord.Interaction):
        """알림 설정 명령어"""
        logger.info(f"알림설정 명령어 호출: 사용자 {interaction.user.id}")
        
        # 지정된 알림 채널인지 확인
        with SessionLocal() as db:
            alert_channel_id = select_alert_channel(db, interaction.guild.id)
            if alert_channel_id and str(interaction.channel_id) != str(alert_channel_id):
                channel = interaction.guild.get_channel(int(alert_channel_id))
                if channel:
                    await interaction_response(interaction, 
                                             f"이 명령어는 {channel.mention} 채널에서만 사용할 수 있습니다.", 
                                             ephemeral=True)
                    return
        
        # 알림 설정 UI 표시
        await self.show_alert_settings(interaction)

    # @tasks.loop(minutes=1)
    # async def check_alerts(self):
    #     """매분마다 알림을 확인합니다"""
    #     try:
    #         now = datetime.now()
    #         current_time = now.strftime('%H:%M:00')
            
    #         # 5분 후 경고 알림 시간 계산
    #         warning_time = (now + timedelta(minutes=5)).strftime('%H:%M:00')
            
    #         # 현재 요일 확인
    #         day_of_week = DAY_OF_WEEK[now.weekday()]
            
    #         with SessionLocal() as db:
    #             # 정각 알림 확인
    #             exact_time_key = f"{current_time}-exact"
    #             if exact_time_key not in self.last_sent_alerts or self.last_sent_alerts[exact_time_key] < now.date():
    #                 await self.send_alerts(db, current_time, day_of_week, is_warning=False)
    #                 self.last_sent_alerts[exact_time_key] = now.date()
                
    #             # 5분 전 경고 알림 확인
    #             warning_key = f"{warning_time}-warning"
    #             if warning_key not in self.last_sent_alerts or self.last_sent_alerts[warning_key] < now.date():
    #                 await self.send_alerts(db, warning_time, day_of_week, is_warning=True)
    #                 self.last_sent_alerts[warning_key] = now.date()
        
    #     except Exception as e:
    #         logger.error(f"알림 체크 중 오류: {str(e)}")
    
    # @check_alerts.before_loop
    # async def before_check_alerts(self):
    #     """알림 루프를 시작하기 전에 봇이 준비될 때까지 대기"""
    #     await self.bot.wait_until_ready()
    
    # async def send_alerts(self, db, alert_time, day_of_week, is_warning=False):
    #     """사용자에게 알림 전송"""
    #     try:
    #         # 현재 시간에 대한 알림 가져오기
    #         alerts = get_upcoming_alerts(db, alert_time, day_of_week)
            
    #         if not alerts:
    #             return
            
    #         # 사용자별로 알림 그룹화
    #         user_alerts = {}
    #         for alert in alerts:
    #             user_id = alert['user_id']
    #             if not user_alerts.get(user_id):
    #                 user_alerts[user_id] = []
    #             user_alerts[user_id].append(alert)

    #         # 개발 환경에서는 알림을 봇 운영자에게만 전송
    #         if settings.ENV == "development":
    #             BOT_OPERATOR_ID = "307620267067179019"
                
    #             # 운영자 ID가 있는 경우에만 유지, 다른 사용자는 필터링
    #             filtered_alerts = {}
    #             if BOT_OPERATOR_ID in user_alerts:
    #                 filtered_alerts[BOT_OPERATOR_ID] = user_alerts[BOT_OPERATOR_ID]
                
    #             user_alerts = filtered_alerts
    #             logger.info(f"개발 환경: 봇 운영자만 알림 받음 ({len(user_alerts)} 명)")
            
    #         # 사용자에게 DM 전송
    #         for user_id, user_alert_list in user_alerts.items():
    #             try:
    #                 user = await self.bot.fetch_user(int(user_id))
    #                 if not user or user.bot:
    #                     continue
                    
    #                 # 알림용 임베드 생성
    #                 embed = discord.Embed(
    #                     title="⏰ 알림" if not is_warning else "⚠️ 5분 전 알림",
    #                     description=f"{'알림 시간입니다!' if not is_warning else '5분 후 설정한 알림이 있습니다!'}",
    #                     color=discord.Color.red() if not is_warning else discord.Color.gold(),
    #                     timestamp=datetime.now()
    #                 )
                    
    #                 # 유형별로 알림 그룹화
    #                 alert_types = {}
    #                 for alert in user_alert_list:
    #                     alert_type = alert['alert_type']
    #                     if not alert_types.get(alert_type):
    #                         alert_types[alert_type] = []
    #                     alert_types[alert_type].append(alert)
                    
    #                 # 각 알림 유형에 대한 필드 추가
    #                 for alert_type, alerts_of_type in alert_types.items():
    #                     # 이미 처리된 알림 건너뛰기
    #                     if is_warning and self.was_alert_sent(alerts_of_type[0], user_id):
    #                         continue
                            
    #                     type_name = ALERT_TYPE_NAMES.get(alert_type, alert_type)
    #                     emoji = ALERT_TYPE_EMOJI.get(alert_type, '🔔')
    #                     times = [alert['alert_time'].strftime('%H:%M') for alert in alerts_of_type]
    #                     embed.add_field(
    #                         name=f"{emoji} {type_name} 알림",
    #                         value=f"시간: {', '.join(times)}",
    #                         inline=False
    #                     )
                    
    #                 if len(embed.fields) > 0:
    #                     try:
    #                         await user.send(embed=embed)
    #                         logger.info(f"알림 전송 완료: {user.name} ({user_id})")
    #                     except discord.Forbidden:
    #                         logger.warning(f"사용자 {user.name} ({user_id})에게 DM을 보낼 수 없습니다.")
    #                     except Exception as e:
    #                         logger.error(f"알림 전송 중 오류: {str(e)}")
                
    #             except Exception as e:
    #                 logger.error(f"사용자 {user_id}에게 알림 전송 중 오류: {str(e)}")
        
    #     except Exception as e:
    #         logger.error(f"알림 전송 중 오류: {str(e)}")
    
    # def was_alert_sent(self, alert, user_id):
    #     """특정 알림이 오늘 이미 전송되었는지 확인"""
    #     alert_id = alert['alert_id']
    #     alert_key = f"{alert_id}-{user_id}"
    #     return alert_key in self.last_sent_alerts and self.last_sent_alerts[alert_key] == datetime.now().date()

# Cog 등록
async def setup(bot):
    await bot.add_cog(AlertCog(bot))
