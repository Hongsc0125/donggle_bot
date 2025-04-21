import discord
from discord.ext import commands, tasks
from discord import app_commands
import logging
import asyncio
from datetime import datetime, timedelta
import re

from db.session import SessionLocal
from core.utils import interaction_response, interaction_followup
from queries.alert_query import (
    get_alert_list, get_user_alerts, add_user_alert, 
    remove_user_alert, create_custom_alert, check_user_alert,
    get_upcoming_alerts, check_alert_table_exists
)

logger = logging.getLogger(__name__)

# Alert type display names
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

# Alert type emoji
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

# Day of week mapping
DAY_OF_WEEK = {
    0: 'mon',
    1: 'tue',
    2: 'wed',
    3: 'thu',
    4: 'fri',
    5: 'sat',
    6: 'sun'
}

class AlertView(discord.ui.View):
    def __init__(self, user_id):
        super().__init__(timeout=300)  # 5 minute timeout
        self.user_id = user_id
        
        # Assign specific rows to each component
        boss_select = AlertSelect('boss', '보스 알림 🔔', user_id)
        boss_select.row = 0  # First row
        self.add_item(boss_select)
        
        barrier_select = AlertSelect('barrier', '결계 알림 🛡️', user_id)
        barrier_select.row = 1  # Second row
        self.add_item(barrier_select)
        
        day_select = DaySelect(user_id)
        day_select.row = 2  # Third row
        self.add_item(day_select)
        
        custom_btn = CustomAlertButton()
        custom_btn.row = 3  # Fourth row
        self.add_item(custom_btn)

class AlertSelect(discord.ui.Select):
    def __init__(self, alert_type, placeholder, user_id):
        self.alert_type = alert_type
        self.user_id = user_id  # Store user_id as an instance variable
        
        with SessionLocal() as db:
            # Get alerts of this type
            alerts = get_alert_list(db, alert_type)
            
            # Get user's selected alerts using the passed user_id
            user_alerts = get_user_alerts(db, self.user_id)
            user_alert_ids = [alert['alert_id'] for alert in user_alerts]
            
            # Create options
            options = []
            for alert in alerts:
                alert_time = alert['alert_time'].strftime('%H:%M')
                emoji = ALERT_TYPE_EMOJI.get(alert_type, '🔔')
                option = discord.SelectOption(
                    label=f"{ALERT_TYPE_NAMES.get(alert_type, alert_type)} {alert_time}",
                    value=alert['alert_id'],
                    description=f"{alert['interval']}마다 {alert_time}에 알림",
                    emoji=emoji,
                    default=alert['alert_id'] in user_alert_ids
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
                # Get current user alerts of this type
                user_alerts = get_user_alerts(db, interaction.user.id)
                current_alert_ids = [alert['alert_id'] for alert in user_alerts 
                                    if alert['alert_type'] == self.alert_type]
                
                # Determine which alerts to add and which to remove
                selected_alert_ids = self.values
                
                # Add new selections
                for alert_id in selected_alert_ids:
                    if alert_id not in current_alert_ids:
                        add_user_alert(db, interaction.user.id, alert_id)
                
                # Remove deselected
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
    def __init__(self, user_id=None):  # Add user_id parameter with default None
        self.user_id = user_id  # Store the user_id
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
        
        # If user_id is provided, pre-select current choices
        if user_id:
            with SessionLocal() as db:
                user_alerts = get_user_alerts(db, user_id)
                selected_days = [alert['alert_type'] for alert in user_alerts 
                               if alert['alert_type'] in ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun']]
                
                # Update default state based on user's selections
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
                
                # Get day alerts
                day_alerts = []
                for day in ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun']:
                    day_alerts.extend(get_alert_list(db, day))
                
                # Get user's selected day alerts
                user_alerts = get_user_alerts(db, interaction.user.id)
                current_day_alert_ids = [alert['alert_id'] for alert in user_alerts 
                                        if alert['alert_type'] in ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun']]
                
                # Process each day alert
                for alert in day_alerts:
                    if alert['alert_type'] in selected_days and alert['alert_id'] not in current_day_alert_ids:
                        # Add this day alert
                        add_user_alert(db, interaction.user.id, alert['alert_id'])
                    elif alert['alert_type'] not in selected_days and alert['alert_id'] in current_day_alert_ids:
                        # Remove this day alert
                        remove_user_alert(db, interaction.user.id, alert['alert_id'])
                
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
            row=3
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
        placeholder="day(매일), week(매주)",
        required=True,
        default="day"
    )
    
    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        
        # Validate time format
        time_pattern = re.compile(r'^([0-1][0-9]|2[0-3]):([0-5][0-9])$')
        if not time_pattern.match(self.alert_time.value):
            await interaction_followup(interaction, "❌ 시간 형식이 올바르지 않습니다. HH:MM 형식으로 입력해주세요.")
            return
        
        # Validate interval
        interval = self.interval.value.lower()
        if interval not in ['day', 'week']:
            await interaction_followup(interaction, "❌ 반복 주기는 'day' 또는 'week'으로 입력해주세요.")
            return
        
        with SessionLocal() as db:
            try:
                # Create custom alert
                alert_id = create_custom_alert(db, self.alert_time.value, interval)
                
                if not alert_id:
                    await interaction_followup(interaction, "❌ 커스텀 알림 생성에 실패했습니다.")
                    return
                
                # Assign to user
                add_user_alert(db, interaction.user.id, alert_id)
                
                db.commit()
                
                await interaction_followup(interaction, f"✅ 커스텀 알림이 등록되었습니다: 매{interval} {self.alert_time.value}")
                
            except Exception as e:
                logger.error(f"커스텀 알림 등록 중 오류: {str(e)}")
                await interaction_followup(interaction, "❌ 커스텀 알림 등록 중 오류가 발생했습니다.")
                db.rollback()

class AlertCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.check_alerts.start()
        self.last_sent_alerts = {}  # Track last sent alerts to avoid duplicates
        logger.info("AlertCog initialized successfully")
    
    def cog_unload(self):
        self.check_alerts.cancel()
    
    @app_commands.command(name="알림설정", description="보스, 결계, 요일 알림을 설정합니다")
    async def alert_settings(self, interaction: discord.Interaction):
        """알림 설정 명령어"""
        logger.info(f"알림설정 명령어 호출: 사용자 {interaction.user.id}")
        try:
            logger.info(f"알림설정 명령어 시작: 사용자 {interaction.user.id}")
            
            # Check if alert table exists
            with SessionLocal() as db:
                table_exists = check_alert_table_exists(db)
                if not table_exists:
                    logger.error("Alert table does not exist!")
                    await interaction_response(interaction, 
                                              "알림 시스템 테이블이 존재하지 않습니다. 관리자에게 문의하세요.", 
                                              ephemeral=True)
                    return
                    
            # Create embed with current alert settings
            embed = discord.Embed(
                title="⏰ 알림 설정",
                description="원하는 알림을 선택하세요. 알림은 DM으로 발송됩니다.",
                color=discord.Color.blue()
            )
            
            # Get user's current alerts
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
            
            # Group alerts by type
            boss_alerts = [a for a in user_alerts if a['alert_type'] == 'boss']
            barrier_alerts = [a for a in user_alerts if a['alert_type'] == 'barrier']
            day_alerts = [a for a in user_alerts if a['alert_type'] in ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun']]
            custom_alerts = [a for a in user_alerts if a['alert_type'] == 'custom']
            
            # Add fields for each alert type
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
            
            if custom_alerts:
                custom_times = ", ".join([f"{a['alert_time'].strftime('%H:%M')} ({a['interval']})" for a in custom_alerts])
                embed.add_field(name="➕ 커스텀 알림", value=custom_times, inline=False)
            
            if not any([boss_alerts, barrier_alerts, day_alerts, custom_alerts]):
                embed.add_field(name="알림 없음", value="아래 버튼과 선택 메뉴를 사용하여 알림을 설정하세요.", inline=False)
            
            embed.set_footer(text="알림은 설정 시간 5분 전과 정각에 발송됩니다.")
            
            # Create view with select menus
            try:
                view = AlertView(interaction.user.id)
                logger.info("알림 뷰 생성 성공")
            except Exception as e:
                logger.error(f"알림 뷰 생성 중 오류: {str(e)}")
                import traceback
                logger.error(f"Traceback: {traceback.format_exc()}")
                await interaction_response(interaction, 
                                         f"알림 설정 UI 생성 중 오류가 발생했습니다. 관리자에게 문의하세요.", 
                                         ephemeral=True)
                return
            
            await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
            logger.info("알림설정 UI 전송 완료")
            
        except Exception as e:
            logger.error(f"알림 설정 명령어 처리 중 오류: {str(e)}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            await interaction_response(interaction, "명령어 처리 중 오류가 발생했습니다.", ephemeral=True)
    
    @tasks.loop(minutes=1)
    async def check_alerts(self):
        """Check for alerts every minute"""
        try:
            now = datetime.now()
            current_time = now.strftime('%H:%M:00')
            
            # Get time for 5-minute warnings
            warning_time = (now + timedelta(minutes=5)).strftime('%H:%M:00')
            
            # Get current day of week
            day_of_week = DAY_OF_WEEK[now.weekday()]
            
            with SessionLocal() as db:
                # Check for exact time alerts
                exact_time_key = f"{current_time}-exact"
                if exact_time_key not in self.last_sent_alerts or self.last_sent_alerts[exact_time_key] < now.date():
                    await self.send_alerts(db, current_time, day_of_week, is_warning=False)
                    self.last_sent_alerts[exact_time_key] = now.date()
                
                # Check for 5-minute warning alerts
                warning_key = f"{warning_time}-warning"
                if warning_key not in self.last_sent_alerts or self.last_sent_alerts[warning_key] < now.date():
                    await self.send_alerts(db, warning_time, day_of_week, is_warning=True)
                    self.last_sent_alerts[warning_key] = now.date()
        
        except Exception as e:
            logger.error(f"알림 체크 중 오류: {str(e)}")
    
    @check_alerts.before_loop
    async def before_check_alerts(self):
        """Wait until the bot is ready before starting the alert loop"""
        await self.bot.wait_until_ready()
    
    async def send_alerts(self, db, alert_time, day_of_week, is_warning=False):
        """Send alerts to users"""
        try:
            # Get alerts for the current time
            alerts = get_upcoming_alerts(db, alert_time, day_of_week)
            
            if not alerts:
                return
            
            # Group alerts by user
            user_alerts = {}
            for alert in alerts:
                user_id = alert['user_id']
                if user_id not in user_alerts:
                    user_alerts[user_id] = []
                user_alerts[user_id].append(alert)
            
            # Send DMs to users
            for user_id, user_alert_list in user_alerts.items():
                try:
                    user = await self.bot.fetch_user(int(user_id))
                    if not user or user.bot:
                        continue
                    
                    # Create embed for the alerts
                    embed = discord.Embed(
                        title="⏰ 알림" if not is_warning else "⚠️ 5분 전 알림",
                        description=f"{'알림 시간입니다!' if not is_warning else '5분 후 설정한 알림이 있습니다!'}",
                        color=discord.Color.red() if not is_warning else discord.Color.gold(),
                        timestamp=datetime.now()
                    )
                    
                    # Group alerts by type
                    alert_types = {}
                    for alert in user_alert_list:
                        alert_type = alert['alert_type']
                        if alert_type not in alert_types:
                            alert_types[alert_type] = []
                        alert_types[alert_type].append(alert)
                    
                    # Add fields for each alert type
                    for alert_type, alerts_of_type in alert_types.items():
                        # Skip already processed alerts
                        if is_warning and self.was_alert_sent(alerts_of_type[0], user_id):
                            continue
                            
                        type_name = ALERT_TYPE_NAMES.get(alert_type, alert_type)
                        emoji = ALERT_TYPE_EMOJI.get(alert_type, '🔔')
                        times = [alert['alert_time'].strftime('%H:%M') for alert in alerts_of_type]
                        embed.add_field(
                            name=f"{emoji} {type_name} 알림",
                            value=f"시간: {', '.join(times)}",
                            inline=False
                        )
                    
                    if len(embed.fields) > 0:
                        try:
                            await user.send(embed=embed)
                            logger.info(f"알림 전송 완료: {user.name} ({user_id})")
                        except discord.Forbidden:
                            logger.warning(f"사용자 {user.name} ({user_id})에게 DM을 보낼 수 없습니다.")
                        except Exception as e:
                            logger.error(f"알림 전송 중 오류: {str(e)}")
                
                except Exception as e:
                    logger.error(f"사용자 {user_id}에게 알림 전송 중 오류: {str(e)}")
        
        except Exception as e:
            logger.error(f"알림 전송 중 오류: {str(e)}")
    
    def was_alert_sent(self, alert, user_id):
        """Check if a specific alert was already sent today"""
        alert_id = alert['alert_id']
        alert_key = f"{alert_id}-{user_id}"
        return alert_key in self.last_sent_alerts and self.last_sent_alerts[alert_key] == datetime.now().date()

# Register the cog
async def setup(bot):
    await bot.add_cog(AlertCog(bot))
