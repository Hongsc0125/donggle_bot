import discord
from discord.ext import commands, tasks
import logging
from discord import app_commands
import asyncio
from datetime import datetime, timedelta

from db.session import SessionLocal
from core.utils import interaction_response, interaction_followup
from queries.channel_query import (
    select_deep_channels, select_deep_channel_by_auth, 
    select_deep_auth_by_channel
)
from queries.alert_query import (
    add_deep_alert_user, select_deep_alert_users_by_auth, 
    insert_deep_informant, check_recent_deep, 
    insert_deep_error, count_deep_error, 
    update_deep_error, check_user_deep_error, 
    update_deep_message_id, select_error_deep_ids, 
    select_all_deep_reports, select_user_deep_alerts, select_deep_alert_users_by_channel
)

logger = logging.getLogger(__name__)

class DeepLocationSelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(label="얼음협곡", value="얼음협곡", description="얼음협곡 심층 제보"),
            discord.SelectOption(label="여신의뜰", value="여신의뜰", description="여신의뜰 심층 제보")
        ]
        super().__init__(placeholder="심층 위치 선택", options=options)

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_modal(
            TimeInputModal(self.values[0], interaction.channel.id)
        )

class DeepButtonView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)  # 시간 제한 없는 영구 버튼
        self.add_item(DeepLocationSelect())

class DeepReportButton(discord.ui.Button):
    def __init__(self, deep_id=None):
        super().__init__(
            style=discord.ButtonStyle.danger,
            label="잘못된 정보 신고",
            emoji="⚠️"
        )
        self.deep_id = deep_id
    
    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_modal(DeepReportConfirmModal(self.deep_id))

class DeepReportConfirmModal(discord.ui.Modal, title="신고 확인"):
    def __init__(self, deep_id):
        super().__init__()
        self.deep_id = deep_id
        
        # 모달에 최소 하나의 TextInput 컴포넌트 추가
        self.reason = discord.ui.TextInput(
            label="신고 사유",
            placeholder="신고 사유를 입력해주세요 (선택사항)",
            required=False,
            max_length=100,
            style=discord.TextStyle.paragraph
        )
        self.add_item(self.reason)
    
    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        
        with SessionLocal() as db:
            try:
                # 이미 신고했는지 확인
                if check_user_deep_error(db, self.deep_id, interaction.user.id):
                    await interaction_followup(interaction, "이미 해당 정보를 신고하셨습니다.", ephemeral=True)
                    return
                
                # 신고 이유 가져오기
                reason = self.reason.value if self.reason.value.strip() else None
                
                # 신고 등록 (reason 포함)
                result = insert_deep_error(
                    db,
                    self.deep_id,
                    interaction.user.id,
                    interaction.user.display_name,
                    reason
                )
                
                if not result:
                    await interaction_followup(interaction, "신고 처리 중 오류가 발생했습니다.", ephemeral=True)
                    return
                
                # 신고 횟수 확인
                error_count = count_deep_error(db, self.deep_id)
                
                # 3번 이상 신고되면 is_error 업데이트 및 메시지 삭제
                if error_count >= 3:
                    update_result = update_deep_error(db, self.deep_id)
                    if update_result:
                        # 메시지 삭제
                        try:
                            await interaction.message.delete()
                            await interaction_followup(interaction, "신고가 누적되어 해당 정보가 삭제되었습니다.", ephemeral=True)
                        except Exception as e:
                            logger.error(f"메시지 삭제 중 오류: {str(e)}")
                            await interaction_followup(interaction, "신고가 누적되었으나 메시지 삭제에 실패했습니다.", ephemeral=True)
                    else:
                        await interaction_followup(interaction, "신고가 누적되었으나 상태 업데이트에 실패했습니다.", ephemeral=True)
                else:
                    await interaction_followup(interaction, f"신고가 접수되었습니다. (현재 {error_count}/3)", ephemeral=True)
                
                db.commit()
                
            except Exception as e:
                logger.error(f"심층 정보 신고 처리 중 오류: {str(e)}")
                await interaction_followup(interaction, "신고 처리 중 오류가 발생했습니다.", ephemeral=True)
                db.rollback()

class DeepReportView(discord.ui.View):
    def __init__(self, deep_id):
        # 시간 제한 없는 영구 버튼으로 변경
        super().__init__(timeout=None)
        self.add_item(DeepReportButton(deep_id))

class TimeInputModal(discord.ui.Modal, title="심층 제보"):
    def __init__(self, location, channel_id):
        super().__init__()
        self.location = location
        self.channel_id = channel_id
        
        self.time_input = discord.ui.TextInput(
            label=f"{location} 남은 시간(분)",
            placeholder="예: 30",
            required=True,
            min_length=1,
            max_length=3
        )
        self.add_item(self.time_input)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            # 입력 검증
            remaining_minutes = int(self.time_input.value)
            if (remaining_minutes <= 0 or remaining_minutes > 999):
                await interaction_response(interaction, "남은 시간은 1~999 사이의 숫자로 입력해주세요.", ephemeral=True)
                return
                
            # 제보 정보 생성
            location = self.location
            
            # 중복 등록 검사 개선
            with SessionLocal() as db:
                recent_deep = check_recent_deep(db, location, interaction.guild.id, remaining_minutes, interaction.channel.id)
                if recent_deep:
                    # 남은 시간 계산
                    time_left = int(recent_deep["remaining_minutes"])
                    await interaction_response(interaction, f"이미 {location}에 대한 정보가 등록되어 있습니다. {time_left}분 후에 다시 시도해주세요.", ephemeral=True)
                    return
                
                # 채널에 매핑된 권한 가져오기
                deep_guild_auth = select_deep_auth_by_channel(db, interaction.guild.id, self.channel_id)
                if not deep_guild_auth:
                    await interaction_response(interaction, "채널에 권한 매핑이 설정되어 있지 않습니다.", ephemeral=True)
                    return
            
            # 제보자 정보 저장 (remaining_minutes, deep_ch_id 추가)
            with SessionLocal() as db:
                try:
                    # informant_deep_user 테이블에 제보자 정보 저장
                    result = insert_deep_informant(
                        db,
                        interaction.user.id,
                        interaction.user.display_name, 
                        interaction.guild.id,
                        interaction.guild.name,
                        location,  # 여신의뜰 or 얼음협곡
                        remaining_minutes,  # 남은 시간 저장
                        self.channel_id  # 채널 ID 저장
                    )
                    
                    if result:
                        deep_id = result
                        db.commit()
                        logger.info(f"심층 제보자 정보 저장 성공: {interaction.user.display_name}, {location}, 채널: {self.channel_id}")
                    else:
                        logger.warning(f"심층 제보자 정보 저장 실패: {interaction.user.display_name}, {location}")
                        await interaction_response(interaction, "심층 제보 등록에 실패했습니다.", ephemeral=True)
                        return
                except Exception as e:
                    logger.error(f"심층 제보자 정보 저장 중 오류: {str(e)}")
                    db.rollback()
                    await interaction_response(interaction, "제보 처리 중 오류가 발생했습니다.", ephemeral=True)
                    return
            
            # 제보 임베드 생성
            embed = discord.Embed(
                title="심층 제보",
                description=f"**<@{interaction.user.id}>님이 심층을 제보했습니다.**",
                color=discord.Color.dark_purple()
            ).set_thumbnail(url="https://harmari.duckdns.org/static/심층구멍.png")
            embed.add_field(name="위치", value=location, inline=True)
            embed.add_field(name="남은 시간", value=f"{remaining_minutes}분", inline=True)
            embed.add_field(name="권한 그룹", value=deep_guild_auth, inline=True)
            embed.set_footer(text=f"제보자: {interaction.user.display_name} | ID: {deep_id}")
            
            # 채널에 메시지 전송 (신고 버튼 포함)
            view = DeepReportView(deep_id)
            channel_message = await interaction.channel.send(
                content=f"────────────────────────────────\n",
                embed=embed, 
                view=view
            )
            
            # 메시지 ID 저장
            with SessionLocal() as db:
                update_deep_message_id(db, deep_id, channel_message.id)
                db.commit()
            
            # 원본 대화상자 응답
            await interaction.response.defer(ephemeral=True)
            
            # 원본 메시지 (임베드와 select box) 삭제 시도
            try:
                # 원래 상호작용이 발생한 메시지의 ID 저장
                original_message_id = interaction.message.id
                
                # 채널에서 해당 메시지 찾기
                channel = interaction.channel
                original_message = await channel.fetch_message(original_message_id)
                
                # 메시지 삭제
                await original_message.delete()
                logger.info(f"원본 심층 정보 메시지 삭제 성공 (ID: {original_message_id})")
            except Exception as delete_error:
                # 메시지 삭제 실패 시 로그만 남기고 계속 진행
                logger.warning(f"원본 메시지 삭제 실패: {str(delete_error)}")
            
            # DM 전송 처리 - 권한 그룹별 알림 전송
            await self.send_notifications(interaction, location, remaining_minutes, deep_guild_auth, deep_id)
            
            # 버튼 메시지 초기화
            await asyncio.sleep(1)  # 약간의 지연을 주어 UI 갱신 안정화
            cog = interaction.client.get_cog("DeepCog")
            if cog:
                await cog.initialize_deep_button(interaction.channel.id, deep_guild_auth)
                
        except ValueError:
            await interaction_response(interaction, "남은 시간은 숫자로 입력해주세요.", ephemeral=True)
        except Exception as e:
            logger.error(f"심층 제보 처리 중 오류: {str(e)}")
            await interaction_response(interaction, "제보 처리 중 오류가 발생했습니다.", ephemeral=True)

    async def send_notifications(self, interaction, location, remaining_minutes, deep_guild_auth, deep_id):
        with SessionLocal() as db:
            try:
                # 권한 그룹에 맞는 알림 사용자 조회 (모든 등록된 사용자)
                from queries.alert_query import select_deep_alert_users_by_auth_group
                potential_users = select_deep_alert_users_by_auth_group(db, interaction.guild.id, deep_guild_auth)
                
                # 실제 알림을 받을 최종 사용자 목록
                valid_users = []
                
                # 각 사용자에 대해 Discord 역할 확인
                for user_data in potential_users:
                    try:
                        user_id = int(user_data['user_id'])
                        member = await interaction.guild.fetch_member(user_id)
                        
                        # 사용자가 길드에 존재하고, 권한 그룹 이름과 일치하는 역할을 가지고 있는지 확인
                        if member:
                            for role in member.roles:
                                if role.name.lower() == deep_guild_auth.lower():
                                    valid_users.append(user_data)
                                    logger.info(f"User {member.display_name} has matching role '{deep_guild_auth}' and will receive alerts")
                                    break
                    except Exception as user_error:
                        logger.error(f"사용자 {user_data['user_id']} 역할 확인 중 오류: {str(user_error)}")
                
                logger.info(f"{len(valid_users)}/{len(potential_users)} 사용자가 '{deep_guild_auth}' 역할을 가지고 있어 알림을 받습니다.")
                
                # 알림 내용 생성 및 전송
                embed = discord.Embed(
                    title="심층 발견 알림",
                    description=f"**<@{interaction.user.id}>님이 심층을 제보했습니다.**",
                    color=discord.Color.dark_purple()
                )
                embed.add_field(name="위치", value=location, inline=True)
                embed.add_field(name="남은 시간", value=f"{remaining_minutes}분", inline=True)
                embed.add_field(name="권한 그룹", value=deep_guild_auth, inline=True)
                embed.add_field(name="제보 채널", value=f"<#{interaction.channel.id}>", inline=False)
                embed.set_footer(text=f"서버: {interaction.guild.name} | ID: {deep_id}")
                
                # 확인된 사용자에게 DM 전송
                sent_count = 0
                for user_data in valid_users:
                    try:
                        user = await interaction.client.fetch_user(int(user_data['user_id']))
                        if user and not user.bot:
                            await user.send(embed=embed)
                            sent_count += 1
                    except Exception as user_error:
                        logger.warning(f"사용자 {user_data['user_id']}에게 DM 전송 실패: {str(user_error)}")
                
                if sent_count > 0:
                    logger.info(f"{sent_count}명의 사용자에게 심층 알림을 전송했습니다. (권한 그룹: {deep_guild_auth})")
                else:
                    logger.info(f"알림을 전송할 사용자가 없습니다. (권한 그룹: {deep_guild_auth})")
                    
            except Exception as e:
                logger.error(f"심층 알림 전송 중 오류: {str(e)}")
                logger.error(traceback.format_exc())

class DeepAlertView(discord.ui.View):
    def __init__(self, guild_id, channel_id, user_id, deep_guild_auth, timeout=180):
        super().__init__(timeout=timeout)
        self.guild_id = guild_id
        self.channel_id = channel_id
        self.user_id = user_id
        self.deep_guild_auth = deep_guild_auth
        
        # 알림 상태 확인
        with SessionLocal() as db:
            is_subscribed = check_deep_alert_user(db, user_id, guild_id, deep_guild_auth)
        
        # 버튼 상태 설정
        self.add_item(
            discord.ui.Button(
                style=discord.ButtonStyle.success if is_subscribed else discord.ButtonStyle.secondary,
                label=f"심층 알림 {deep_guild_auth} {'ON' if is_subscribed else 'OFF'}",
                emoji="🧊" if is_subscribed else "🔕",
                custom_id=f"deep_alert_toggle_{deep_guild_auth}"
            )
        )
    
    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        # 다른 사용자가 버튼을 클릭하는 것을 방지
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("이 버튼은 명령어를 사용한 사용자만 클릭할 수 있습니다.", ephemeral=True)
            return False
        return True
    
    @discord.ui.button(label="닫기", style=discord.ButtonStyle.danger, row=1)
    async def close_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.message.delete()
        await interaction.response.send_message("심층 알림 설정 메뉴가 닫혔습니다.", ephemeral=True)

class DeepCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.manage_deep_channel.start()  # 심층 채널 관리 작업 시작

    def cog_unload(self):
        """Cog가 언로드될 때 실행됩니다."""
        self.manage_deep_channel.cancel()  # 작업 취소

    @commands.Cog.listener()
    async def on_ready(self):
        """봇이 준비되면 초기화"""
        logger.info("심층 제보 시스템 초기화 중...")
        
        try:
            success_count = 0
            failed_count = 0
            
            # 모든 길드의 심층 채널 초기화
            for guild in self.bot.guilds:
                with SessionLocal() as db:
                    try:
                        # 모든 심층 채널 및 권한 매핑 조회
                        channel_auth_pairs = select_deep_channels(db, guild.id)
                        
                        for channel_id, auth in channel_auth_pairs:
                            try:
                                await self.initialize_deep_button(channel_id, auth)
                                success_count += 1
                                logger.info(f"길드 {guild.id} 심층 채널 {channel_id} 초기화 완료 (권한: {auth})")
                            except Exception as e:
                                failed_count += 1
                                logger.error(f"심층 채널 {channel_id} 초기화 중 오류: {e}")
                                
                        if not channel_auth_pairs:
                            logger.info(f"길드 {guild.id}에 설정된 심층 채널이 없습니다")
                    except Exception as e:
                        logger.error(f"길드 {guild.id}의 심층 채널 초기화 중 오류: {e}")
            
            logger.info(f"심층 제보 시스템 초기화 완료 (성공: {success_count}, 실패: {failed_count})")
        except Exception as e:
            logger.error(f"심층 제보 시스템 초기화 중 오류: {e}")

    @tasks.loop(minutes=2)
    async def manage_deep_channel(self):
        """2분마다 심층 제보 채널의 메시지를 관리합니다."""
        logger.info("심층 제보 채널 관리 시작...")
        
        success_count = 0
        failed_count = 0
        
        # 각 길드별로 처리
        for guild in self.bot.guilds:
            try:
                with SessionLocal() as db:
                    # 모든 심층 채널 및 권한 매핑 조회
                    channel_auth_pairs = select_deep_channels(db, guild.id)
                    
                    if not channel_auth_pairs:
                        continue
                    
                    # 각 채널별로 처리
                    for channel_id, auth in channel_auth_pairs:
                        try:
                            await self.clean_deep_channel(db, guild.id, channel_id, auth)
                            success_count += 1
                        except Exception as e:
                            failed_count += 1
                            logger.error(f"심층 채널 {channel_id} 정리 중 오류: {e}")
            except Exception as e:
                failed_count += 1
                logger.error(f"길드 {guild.id}의 심층 채널 관리 중 오류: {e}")
        
        logger.info(f"심층 제보 채널 관리 완료 (성공: {success_count}, 실패: {failed_count})")

    @manage_deep_channel.before_loop
    async def before_manage_deep_channel(self):
        """심층 채널 관리를 시작하기 전에 봇이 준비될 때까지 대기"""
        await self.bot.wait_until_ready()

    async def clean_deep_channel(self, db, guild_id, channel_id, auth=None):
        """심층 제보 채널의 메시지를 정리하고 갱신합니다."""
        channel = self.bot.get_channel(int(channel_id))
        if not channel:
            logger.warning(f"심층 채널 {channel_id}를 찾을 수 없습니다.")
            return
        
        logger.info(f"심층 채널 {channel_id} 정리 시작 (권한: {auth})")
        
        # 메시지 모음
        select_messages = []  # 선택 메시지 (임베드+셀렉트)
        deep_report_messages = {}  # 심층 제보 메시지 {deep_id: message}
        total_messages = 0
        processed_messages = 0
        
        try:
            # 채널 내 메시지 조회 (최근 100개)
            async for message in channel.history(limit=100):
                total_messages += 1
                if message.author.id != self.bot.user.id:
                    continue
                
                processed_messages += 1
                
                # 메시지 분류 - 메시지 유형 정확하게 구분
                try:
                    if (
                        message.embeds and 
                        len(message.embeds) > 0 and 
                        message.embeds[0].title and
                        "📢 심층 정보를 공유해 주세요!" in message.embeds[0].title and
                        message.components and 
                        len(message.components) > 0
                    ):
                        # 심층 제보 선택 메시지
                        select_messages.append(message)
                        logger.debug(f"선택 메시지 발견: {message.id}")
                    elif (
                        message.embeds and
                        len(message.embeds) > 0 and
                        message.embeds[0].title and
                        "심층 제보" in message.embeds[0].title and
                        message.embeds[0].footer and
                        message.embeds[0].footer.text and
                        "ID:" in message.embeds[0].footer.text
                    ):
                        # 심층 제보 메시지
                        try:
                            footer_text = message.embeds[0].footer.text
                            deep_id_part = footer_text.split("ID:")[1].strip() if "ID:" in footer_text else None
                            if deep_id_part:
                                # Use the deep_id as a string instead of converting to integer
                                deep_id = deep_id_part  # Remove the int() conversion
                                deep_report_messages[deep_id] = message
                                logger.debug(f"제보 메시지 발견: deep_id {deep_id}, message_id {message.id}")
                        except (IndexError) as e:  # Removed ValueError since we're not converting to int
                            logger.warning(f"메시지 {message.id}의 footer 파싱 중 오류: {e}")
                except Exception as msg_e:
                    logger.warning(f"메시지 {message.id} 분류 중 오류: {msg_e}")
            
            logger.info(f"채널 {channel_id}에서 총 {total_messages}개 메시지 중 {processed_messages}개 처리됨 "
                        f"(선택 메시지: {len(select_messages)}, 제보 메시지: {len(deep_report_messages)})")
            
            # 1. 오류로 표시된 메시지 및 만료된 메시지 삭제
            now = datetime.now()
            all_reports = select_all_deep_reports(db, guild_id, channel_id)
            
            # 삭제할 deep_id 목록
            deep_ids_to_delete = []
            valid_deep_ids = set()
            
            for report in all_reports:
                deep_id = report["deep_id"]
                try:
                    # 오류로 표시된 메시지 또는 만료된 메시지
                    if (
                        report["is_error"] == 'Y' or
                        (report["create_dt"] + timedelta(minutes=int(report["remaining_minutes"])) < now)
                    ):
                        deep_ids_to_delete.append(deep_id)
                    else:
                        valid_deep_ids.add(deep_id)
                except Exception as e:
                    logger.warning(f"심층 제보 {deep_id} 상태 확인 중 오류: {e}")
            
            # 메시지 삭제
            deleted_count = 0
            for deep_id in deep_ids_to_delete:
                if deep_id in deep_report_messages:
                    try:
                        await deep_report_messages[deep_id].delete()
                        deleted_count += 1
                        logger.info(f"메시지 삭제 완료: deep_id {deep_id}")
                    except Exception as e:
                        logger.warning(f"메시지 deep_id {deep_id} 삭제 실패: {e}")
            
            logger.info(f"오류/만료된 메시지 {deleted_count}개 삭제 완료")
            
            # 2. 선택 메시지 정리 (마지막 하나만 남기고 삭제)
            if len(select_messages) > 0:
                # 시간순 정렬 (최신순)
                select_messages.sort(key=lambda m: m.created_at, reverse=True)
                
                # 첫 번째를 제외한 모든 메시지 삭제
                removed_count = 0
                for msg in select_messages[1:]:
                    try:
                        await msg.delete()
                        removed_count += 1
                        logger.info(f"오래된 선택 메시지 삭제: {msg.id}")
                    except Exception as e:
                        logger.warning(f"선택 메시지 {msg.id} 삭제 실패: {e}")
                
                logger.info(f"오래된 선택 메시지 {removed_count}개 삭제 완료")
                
                # 가장 최근 메시지 갱신
                try:
                    view = DeepButtonView()
                    await select_messages[0].edit(embed=select_messages[0].embeds[0], view=view)
                    logger.info(f"선택 메시지 {select_messages[0].id} 갱신 완료")
                except Exception as e:
                    logger.warning(f"선택 메시지 갱신 실패: {e}, 새로 생성합니다")
                    # 실패 시 새로 생성 시도
                    await self.initialize_deep_button(channel_id, auth)
            else:
                # 선택 메시지가 없으면 새로 생성
                logger.info(f"선택 메시지가 없어 새로 생성합니다")
                await self.initialize_deep_button(channel_id, auth)
            
            # 3. 남은 제보 메시지의 컴포넌트 갱신
            updated_count = 0
            for deep_id in valid_deep_ids:
                if deep_id in deep_report_messages:
                    try:
                        # 기존 메시지 내용 유지하면서 버튼만 갱신
                        message = deep_report_messages[deep_id]
                        view = DeepReportView(deep_id)
                        await message.edit(content=message.content, embed=message.embeds[0], view=view)
                        updated_count += 1
                        logger.debug(f"제보 메시지 {deep_id}의 컴포넌트 갱신 완료")
                    except Exception as e:
                        logger.warning(f"제보 메시지 {deep_id} 컴포넌트 갱신 실패: {e}")
            
            logger.info(f"유효한 제보 메시지 {updated_count}개 컴포넌트 갱신 완료")
            
            # 4. DB에 없는 불필요한 메시지 정리
            orphaned_count = 0
            for deep_id in deep_report_messages:
                if deep_id not in valid_deep_ids and deep_id not in deep_ids_to_delete:
                    try:
                        await deep_report_messages[deep_id].delete()
                        orphaned_count += 1
                        logger.info(f"불필요한 메시지 삭제: deep_id {deep_id}")
                    except Exception as e:
                        logger.warning(f"불필요한 메시지 삭제 실패: deep_id {deep_id}, 오류: {e}")
            
            logger.info(f"불필요한 메시지 {orphaned_count}개 삭제 완료")
            
            logger.info(f"심층 채널 {channel_id} 정리 완료")
            
        except Exception as e:
            logger.error(f"심층 채널 정리 중 오류: {e}")
            logger.error(f"오류 세부 정보: {str(e)}")
            # 오류가 발생해도 채널 초기화는 시도
            try:
                await self.initialize_deep_button(channel_id, auth)
                logger.info(f"오류 발생 후 심층 채널 {channel_id} 초기화 완료")
            except Exception as init_e:
                logger.error(f"오류 발생 후 심층 채널 {channel_id} 초기화 실패: {init_e}")

    async def initialize_deep_button(self, channel_id, auth=None):
        """심층 제보 버튼 초기화"""
        channel = self.bot.get_channel(int(channel_id))
        if not channel:
            logger.warning(f"심층 채널 {channel_id}를 찾을 수 없습니다.")
            return
        
        logger.info(f"심층 채널 {channel_id} 초기화 시작 (권한: {auth})")
        
        class DeepChannelSelect(discord.ui.Select):
            def __init__(self, parent_cog, channel_id):
                self.parent_cog = parent_cog
                self.channel_id = channel_id
                options = [
                    discord.SelectOption(label="얼음협곡", value="얼음협곡", description="얼음협곡 심층 제보"),
                    discord.SelectOption(label="여신의뜰", value="여신의뜰", description="여신의뜰 심층 제보")
                ]
                super().__init__(placeholder="심층 위치 선택", options=options)
            
            async def callback(self, interaction: discord.Interaction):
                await interaction.response.send_modal(
                    TimeInputModal(self.values[0], self.channel_id)
                )
        
        class DeepChannelView(discord.ui.View):
            def __init__(self, parent_cog, channel_id):
                super().__init__(timeout=None)  # 시간 제한 없는 영구 버튼
                self.add_item(DeepChannelSelect(parent_cog, channel_id))
        
        view = DeepChannelView(self, channel_id)
        auth_text = f" - {auth}" if auth else ""

        instruction_embed = discord.Embed(
                title=f"🧊 **심층 정보를 공유해 주세요!** 🧊{auth_text}",
                description=(
                    "### 📝 심층 제보 방법\n"
                    "> 1. 아래 선택 메뉴에서 심층 **위치**를 선택하세요\n"
                    "> 2. 심층 소멸까지 **남은 시간(분)**을 입력하세요\n\n"
                    "### ⚠️ 주의사항\n"
                    "> • 이미 등록된 위치는 시간이 지날 때까지 중복 제보가 불가능합니다\n"
                    "> • 3회 이상 신고가 누적되면 제보 정보가 자동 삭제됩니다\n"
                    "> • 허위 제보 시 서버 이용에 제한을 받을 수 있습니다\n\n"
                    "### 💡 알림 설정\n"
                    f"> 이 채널에서 `/심층알림{auth_text}` 명령어를 입력하면 이 권한의 심층 제보 DM 알림을 설정할 수 있습니다"
                ),
            color=discord.Color.dark_purple()
        ).set_thumbnail(url="https://harmari.duckdns.org/static/심층구멍.png")
        
        # 기존 버튼 메시지 찾기 및 업데이트
        existing_message = None
        try:
            async for message in channel.history(limit=30, oldest_first=False):
                if (
                    message.author.id == self.bot.user.id and 
                    message.embeds and 
                    len(message.embeds) > 0 and 
                    message.embeds[0].title and
                    "심층 정보를 공유해 주세요!" in message.embeds[0].title and
                    # 권한 그룹 일치 확인
                    ((auth and auth_text in message.embeds[0].title) or 
                     (not auth and " - " not in message.embeds[0].title))
                ):
                    existing_message = message
                    break
        except Exception as e:
            logger.warning(f"채널 {channel_id} 메시지 검색 중 오류: {str(e)}")

        # 기존 메시지 갱신 또는 새로 생성
        try:
            if existing_message:
                await existing_message.edit(embed=instruction_embed, view=view)
                logger.info(f"심층 채널 {channel_id}의 기존 버튼 메시지 갱신 완료 (ID: {existing_message.id})")
            else:
                new_message = await channel.send(embed=instruction_embed, view=view)
                logger.info(f"심층 채널 {channel_id}에 새 버튼 메시지 생성 완료 (ID: {new_message.id})")
        except Exception as e:
            logger.error(f"심층 채널 {channel_id} 버튼 메시지 생성/갱신 실패: {str(e)}")

    # @app_commands.command(name="심층알림", description="특정 채널의 심층 알림을 설정합니다")
    # async def manage_deep_alert(self, interaction: discord.Interaction):
    #     """심층 알림 관리 명령어"""
    #     await interaction.response.defer(ephemeral=True)
        
    #     with SessionLocal() as db:
    #         try:
    #             guild_id = interaction.guild.id
    #             channel_id = interaction.channel.id
    #             user_id = interaction.user.id
                
    #             # 현재 채널에 연결된 권한 그룹 확인
    #             deep_guild_auth = select_deep_auth_by_channel(db, guild_id, channel_id)
                
    #             if not deep_guild_auth:
    #                 await interaction_followup(interaction, "이 채널은 심층 제보 채널로 설정되어 있지 않습니다.", ephemeral=True)
    #                 return
                
    #             # 현재 상태 확인 (채널 기준)
    #             is_subscribed = check_deep_alert_user_by_channel(db, user_id, guild_id, channel_id)
                
    #             # 알림 활성화/비활성화
    #             if is_subscribed:
    #                 result = remove_deep_alert_user_by_channel(db, user_id, guild_id, channel_id)
    #                 msg = f"❌ '{deep_guild_auth}' 권한 그룹의 심층 알림이 비활성화되었습니다."
    #             else:
    #                 result = add_deep_alert_user(db, user_id, guild_id, interaction.user.display_name, channel_id)
    #                 msg = f"✅ '{deep_guild_auth}' 권한 그룹의 심층 알림이 활성화되었습니다. 해당 권한의 심층 제보가 있을 때 DM으로 알림을 받습니다."
                
    #             if result:
    #                 db.commit()
    #                 await interaction_followup(interaction, msg, ephemeral=True)
    #             else:
    #                 await interaction_followup(interaction, "❌ 심층 알림 설정에 실패했습니다.", ephemeral=True)
                    
    #         except Exception as e:
    #             logger.error(f"심층 알림 설정 중 오류: {str(e)}")
    #             db.rollback()
    #             await interaction_followup(interaction, f"❌ 심층 알림 설정 중 오류가 발생했습니다: {str(e)}", ephemeral=True)

    # @app_commands.command(name="심층알림목록", description="현재 활성화된 심층 알림 목록을 확인합니다")
    # async def list_deep_alerts(self, interaction: discord.Interaction):
    #     """심층 알림 목록 조회 명령어"""
    #     await interaction.response.defer(ephemeral=True)
        
    #     with SessionLocal() as db:
    #         try:
    #             user_id = interaction.user.id
    #             guild_id = interaction.guild.id
                
    #             # 사용자가 알림을 설정한 채널 목록 조회
    #             alert_channels = select_user_deep_alert_channels(db, user_id, guild_id)
                
    #             if not alert_channels:
    #                 await interaction_followup(interaction, "❌ 활성화된 심층 알림이 없습니다.", ephemeral=True)
    #                 return
                
    #             # 알림 목록 표시
    #             embed = discord.Embed(
    #                 title="🧊 활성화된 심층 알림 목록",
    #                 description="아래 권한 그룹의 심층 제보가 있을 때 DM으로 알림을 받습니다.",
    #                 color=discord.Color.dark_purple()
    #             )
                
    #             for ch_id in alert_channels:
    #                 # 채널에 연결된 권한 그룹 조회
    #                 auth = select_deep_auth_by_channel(db, guild_id, ch_id)
    #                 channel = self.bot.get_channel(int(ch_id))
    #                 channel_text = f"<#{ch_id}>" if channel else "채널 찾을 수 없음"
                    
    #                 embed.add_field(
    #                     name=f"🔔 {auth if auth else '알 수 없는 그룹'}",
    #                     value=f"채널: {channel_text}\n비활성화: 해당 채널에서 `/심층알림` 명령어 사용",
    #                     inline=False
    #                 )
                
    #             await interaction_followup(interaction, embed=embed, ephemeral=True)
                
    #         except Exception as e:
    #             logger.error(f"심층 알림 목록 조회 중 오류: {str(e)}")
    #             await interaction_followup(interaction, f"❌ 심층 알림 목록 조회 중 오류가 발생했습니다: {str(e)}", ephemeral=True)

# Cog 등록
async def setup(bot):
    await bot.add_cog(DeepCog(bot))
