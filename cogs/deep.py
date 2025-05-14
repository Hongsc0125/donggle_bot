import discord
from discord.ext import commands, tasks
import logging
from discord import app_commands
import asyncio
from datetime import datetime, timedelta
import traceback  # traceback 모듈 추가

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
                
                # 관리자 권한 확인 - 관리자면 즉시 오제보 처리
                is_admin = interaction.user.guild_permissions.administrator
                
                # 관리자가 신고하면 즉시 오제보 처리, 아니면 신고 횟수 확인
                if is_admin:
                    logger.info(f"관리자 {interaction.user.display_name}({interaction.user.id})의 즉시 오제보 처리: {self.deep_id}")
                    update_result = update_deep_error(db, self.deep_id)
                    if update_result:
                        try:
                            # 메시지 내용 갱신을 위해 DeepCog 참조
                            deep_cog = interaction.client.get_cog("DeepCog")
                            if (deep_cog and hasattr(deep_cog, "mark_error_message")):
                                await deep_cog.mark_error_message(interaction.message, self.deep_id)
                                await interaction_followup(interaction, "관리자 권한으로 즉시 오제보 처리되었습니다.", ephemeral=True)
                            else:
                                await interaction_followup(interaction, "오제보 처리는 되었으나 메시지 상태 변경에 실패했습니다.", ephemeral=True)
                        except Exception as e:
                            logger.error(f"메시지 상태 변경 중 오류: {str(e)}")
                            await interaction_followup(interaction, "오제보 처리는 되었으나 메시지 상태 변경에 실패했습니다.", ephemeral=True)
                    else:
                        await interaction_followup(interaction, "오제보 처리에 실패했습니다.", ephemeral=True)
                else:
                    # 일반 사용자는 기존 로직대로 신고 횟수 확인
                    error_count = count_deep_error(db, self.deep_id)
                    
                    # 3번 이상 신고되면 is_error 업데이트하고 메시지는 삭제하지 않고 표시만 변경
                    if error_count >= 3:
                        update_result = update_deep_error(db, self.deep_id)
                        if update_result:
                            # 메시지 삭제 대신 오제보 표시로 변경
                            try:
                                # 메시지 내용 갱신을 위해 DeepCog 참조
                                deep_cog = interaction.client.get_cog("DeepCog")
                                if deep_cog and hasattr(deep_cog, "mark_error_message"):
                                    await deep_cog.mark_error_message(interaction.message, self.deep_id)
                                    await interaction_followup(interaction, "신고가 누적되어 해당 정보가 오제보로 표시되었습니다.", ephemeral=True)
                                else:
                                    # DeepCog를 찾을 수 없거나 메서드가 없는 경우
                                    await interaction_followup(interaction, "신고가 누적되었으나 메시지 상태 변경에 실패했습니다.", ephemeral=True)
                            except Exception as e:
                                logger.error(f"메시지 상태 변경 중 오류: {str(e)}")
                                await interaction_followup(interaction, "신고가 누적되었으나 메시지 상태 변경에 실패했습니다.", ephemeral=True)
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

        self.comment_input = discord.ui.TextInput(
            label="상세내용 (선택사항)",
            placeholder="추가 정보를 입력하세요 (예: 2개요, 3개요 등등)",
            required=False,
            max_length=100,
            style=discord.TextStyle.paragraph
        )
        self.add_item(self.comment_input)

    async def on_submit(self, interaction: discord.Interaction):
        # 즉시 응답 지연 처리 - 3초 제한을 피하기 위해 가장 먼저 호출
        await interaction.response.defer(ephemeral=True)
        
        try:
            # 입력 검증
            remaining_minutes = int(self.time_input.value)
            if (remaining_minutes <= 0 or remaining_minutes > 999):
                await interaction.followup.send("남은 시간은 1~999 사이의 숫자로 입력해주세요.", ephemeral=True)
                return
            
            comment = self.comment_input.value if self.comment_input.value.strip() else None
                
            # 제보 정보 생성
            location = self.location
            
            # 중복 등록 검사 개선
            with SessionLocal() as db:
                try:
                    # 중복 등록 검사 개선
                    recent_deep = check_recent_deep(db, location, interaction.guild.id, remaining_minutes, interaction.channel.id)
                    if (recent_deep):
                        # 남은 시간 계산
                        time_left = int(recent_deep["remaining_minutes"])
                        await interaction.followup.send(f"이미 {location}에 대한 정보가 등록되어 있습니다. {time_left}분 후에 다시 시도해주세요.", ephemeral=True)
                        return
                    
                    # 채널에 매핑된 권한 가져오기
                    deep_guild_auth = select_deep_auth_by_channel(db, interaction.guild.id, self.channel_id)
                    if not deep_guild_auth:
                        await interaction.followup.send("채널에 권한 매핑이 설정되어 있지 않습니다.", ephemeral=True)
                        return
                    
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
                        await interaction.followup.send("심층 제보 등록에 실패했습니다.", ephemeral=True)
                        return
                except Exception as e:
                    logger.error(f"심층 제보자 정보 저장 중 오류: {str(e)}")
                    db.rollback()
                    await interaction.followup.send("제보 처리 중 오류가 발생했습니다.", ephemeral=True)
                    return
            
            # 제보 임베드 생성
            embed = discord.Embed(
                title="심층 제보",
                description=f"**<@{interaction.user.id}>님이 심층을 제보했습니다.**",
                color=discord.Color.dark_purple(),
                timestamp=datetime.now()  # 현재 시간을 타임스탬프로 추가
            ).set_thumbnail(url="https://harmari.duckdns.org/static/심층구멍.png")
            embed.add_field(name="위치", value=location, inline=True)
            embed.add_field(name="남은 시간", value=f"{remaining_minutes}분", inline=True)
            embed.add_field(name="권한 그룹", value=deep_guild_auth, inline=True)
            if comment:
                embed.add_field(name="상세내용", value=comment, inline=False)
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
            await self.send_notifications(interaction, location, remaining_minutes, deep_guild_auth, deep_id, comment)
            
            # 성공 메시지 전송
            await interaction.followup.send("심층 제보가 성공적으로 등록되었습니다.", ephemeral=True)
            
            # 버튼 메시지 초기화
            await asyncio.sleep(1)  # 약간의 지연을 주어 UI 갱신 안정화
            cog = interaction.client.get_cog("DeepCog")
            if (cog):
                await cog.initialize_deep_button(interaction.channel.id, deep_guild_auth)
                
        except ValueError:
            await interaction.followup.send("남은 시간은 숫자로 입력해주세요.", ephemeral=True)
        except Exception as e:
            logger.error(f"심층 제보 처리 중 오류: {str(e)}")
            logger.error(traceback.format_exc())  # 상세 오류 로그 추가
            await interaction.followup.send("제보 처리 중 오류가 발생했습니다.", ephemeral=True)

    async def send_notifications(self, interaction, location, remaining_minutes, deep_guild_auth, deep_id, comment=None):
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
                if comment:
                    embed.add_field(name="코멘트", value=comment, inline=False)
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
            # 초기화 코드 실행 전 약간의 지연 추가 (서버 연결 안정화 대기)
            await asyncio.sleep(5)
            
            success_count = 0
            failed_count = 0
            
            # 모든 길드의 심층 채널 초기화
            for guild in self.bot.guilds:
                logger.info(f"길드 {guild.id} ({guild.name})의 심층 채널 초기화 시작")
                with SessionLocal() as db:
                    try:
                        # 모든 심층 채널 및 권한 매핑 조회
                        channel_auth_pairs = select_deep_channels(db, guild.id)
                        logger.info(f"길드 {guild.id}에서 {len(channel_auth_pairs)}개의 심층 채널 발견")
                        
                        if not channel_auth_pairs:
                            logger.info(f"길드 {guild.id}에 설정된 심층 채널이 없습니다.")
                            continue
                            
                        for channel_id, auth in channel_auth_pairs:
                            try:
                                logger.info(f"심층 채널 {channel_id} 초기화 시도 (권한: {auth})")
                                # 채널 Select 상호작용만 갱신
                                channel = self.bot.get_channel(int(channel_id))
                                if not channel:
                                    logger.warning(f"심층 채널 {channel_id}를 찾을 수 없습니다. 건너뜁니다.")
                                    failed_count += 1
                                    continue
                                    
                                result = await self.initialize_deep_button(channel_id, auth)
                                if result:
                                    success_count += 1
                                    logger.info(f"심층 채널 {channel_id} 초기화 성공 (권한: {auth})")
                                else:
                                    failed_count += 1
                                    logger.error(f"심층 채널 {channel_id} 초기화 실패 (권한: {auth})")
                            except Exception as e:
                                failed_count += 1
                                logger.error(f"심층 채널 {channel_id} 초기화 중 오류: {e}")
                                logger.error(traceback.format_exc())
                    except Exception as e:
                        logger.error(f"길드 {guild.id}의 심층 채널 초기화 중 오류: {e}")
                        logger.error(traceback.format_exc())  # 상세 오류 정보 기록
            
            logger.info(f"심층 제보 시스템 초기화 완료 (성공: {success_count}, 실패: {failed_count})")
        except Exception as e:
            logger.error(f"심층 제보 시스템 초기화 중 오류: {e}")
            logger.error(traceback.format_exc())  # 상세 오류 정보 기록
            
    async def initialize_deep_button(self, channel_id, auth=None):
        """심층 제보 채널의 Select 상호작용 버튼을 초기화합니다."""
        channel = self.bot.get_channel(int(channel_id))
        if not channel:
            logger.warning(f"심층 채널 {channel_id}를 찾을 수 없습니다.")
            return False
        
        logger.info(f"심층 채널 {channel_id} Select 상호작용 초기화 시작 (권한: {auth})")
        
        # 기존 Select 버튼이 있는 메시지 찾기
        select_message = None
        try:
            logger.debug(f"채널 {channel_id}에서 기존 Select 메시지 검색 중...")
            async for message in channel.history(limit=5):
                if (message.author.id == self.bot.user.id and 
                    message.components and 
                    any("심층 위치 선택" in str(comp) for comp in message.components)):
                    select_message = message
                    logger.debug(f"기존 Select 메시지 발견: {message.id}")
                    break
        except discord.HTTPException as e:
            logger.error(f"채널 {channel_id} 메시지 조회 실패: {e}")
            return False
        except Exception as e:
            logger.error(f"채널 {channel_id} 메시지 조회 중 알 수 없는 오류: {e}")
            logger.error(traceback.format_exc())
            return False
            
        # 버튼 뷰 생성
        view = DeepButtonView()
        
        # 새로운 포맷의 임베드 생성
        embed = discord.Embed(
            title=f"🧊 심층 정보를 공유해 주세요! 🧊 - {auth if auth else ''}",
            description="📝 **심층 제보 방법**\n"
                       "아래 선택 메뉴에서 심층 위치를 선택하세요\n"
                       "심층 소멸까지 남은 시간(분)을 입력하세요\n\n"
                       "⚠️ **주의사항**\n"
                       "• 이미 등록된 위치는 시간이 지날 때까지 중복 제보가 불가능합니다\n"
                       "• 3회 이상 신고가 누적되면 제보 정보가 자동 삭제됩니다\n"
                       "• 허위 제보 시 서버 이용에 제한을 받을 수 있습니다\n"
                       "• 잘못 작성 하셨거나, 제보가 이상하면 채팅채널에서 `@힝트시` 를 호출해서 말씀해주세요.",
            color=discord.Color.dark_purple()
        ).set_thumbnail(url="https://harmari.duckdns.org/static/심층구멍.png")
        
        embed.set_footer(text=f"마지막 업데이트: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        
        # 기존 Select 메시지가 있으면 업데이트, 없으면 새로 생성
        try:
            if select_message:
                logger.info(f"심층 채널 {channel_id}의 기존 Select 메시지 업데이트 시도 (메시지 ID: {select_message.id})")
                await select_message.edit(content="", embed=embed, view=view)
                logger.info(f"심층 채널 {channel_id} Select 메시지 업데이트 완료")
            else:
                logger.info(f"심층 채널 {channel_id}에 새 Select 메시지 생성 시도")
                await channel.send(embed=embed, view=view)
                logger.info(f"심층 채널 {channel_id} 새 Select 메시지 생성 완료")
            return True
        except discord.Forbidden as e:
            logger.error(f"심층 채널 {channel_id} 메시지 생성/업데이트 권한 부족: {e}")
            return False
        except discord.HTTPException as e:
            logger.error(f"심층 채널 {channel_id} 메시지 생성/업데이트 HTTP 오류: {e}")
            return False
        except Exception as e:
            logger.error(f"심층 채널 {channel_id} 메시지 생성/업데이트 실패: {e}")
            logger.error(traceback.format_exc())
            return False

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
                        logger.info(f"길드 {guild.id}에 설정된 심층 채널이 없습니다.")
                        continue
                    
                    # 각 채널별로 처리
                    for channel_id, auth in channel_auth_pairs:
                        try:
                            # 채널 메시지 관리 (삭제하지 않고 상태에 따라 처리)
                            await self.clean_deep_channel(db, guild.id, channel_id, auth)
                            success_count += 1
                        except Exception as e:
                            failed_count += 1
                            logger.error(f"심층 채널 {channel_id} 관리 중 오류: {e}")
                            logger.error(traceback.format_exc())
            except Exception as e:
                failed_count += 1
                logger.error(f"길드 {guild.id}의 심층 채널 관리 중 오류: {e}")
                logger.error(traceback.format_exc())
        
        logger.info(f"심층 제보 채널 관리 완료 (성공: {success_count}, 실패: {failed_count})")

    @manage_deep_channel.before_loop
    async def before_manage_deep_channel(self):
        """심층 채널 관리를 시작하기 전에 봇이 준비될 때까지 대기"""
        await self.bot.wait_until_ready()

    async def clean_deep_channel(self, db, guild_id, channel_id, auth=None):
        """심층 제보 채널의 메시지를 상태에 따라 관리합니다."""
        channel = self.bot.get_channel(int(channel_id))
        if not channel:
            logger.warning(f"심층 채널 {channel_id}를 찾을 수 없습니다.")
            return
        
        logger.info(f"심층 채널 {channel_id} 메시지 관리 시작 (권한: {auth})")
        
        # 메시지 분류용 변수
        select_messages = []  # 선택 메시지 (임베드+셀렉트)
        deep_report_messages = {}  # 심층 제보 메시지 {deep_id: message}
        total_messages = 0
        processed_messages = 0
        
        try:
            # 채널 내 메시지 조회 (최근 100개)
            async for message in channel.history(limit=5):
                total_messages += 1
                if message.author.id != self.bot.user.id:
                    continue
                
                processed_messages += 1
                
                # 메시지 분류 - 메시지 유형 정확하게 구분
                try:
                    # Select 메시지 식별 (드롭다운 선택 컴포넌트가 있는 메시지)
                    if message.components and any("심층 위치 선택" in str(comp) for comp in message.components):
                        select_messages.append(message)
                        continue
                    
                    # 심층 제보 메시지 식별 (footer에 ID가 있는 임베드)
                    if message.embeds and len(message.embeds) > 0:
                        embed = message.embeds[0]
                        if embed.footer and embed.footer.text and "ID:" in embed.footer.text:
                            try:
                                # Footer 형식: "제보자: USERNAME | ID: DEEP_ID"
                                deep_id_str = embed.footer.text.split("ID:")[-1].strip()
                                # 숫자로 변환하지 않고 문자열 그대로 사용
                                deep_report_messages[deep_id_str] = message
                                logger.debug(f"심층 제보 메시지 발견: ID {deep_id_str}, 메시지 ID {message.id}")
                            except (ValueError, IndexError) as e:
                                logger.warning(f"ID 파싱 실패: '{embed.footer.text}' - {e}")
                except Exception as msg_e:
                    logger.error(f"메시지 분류 중 오류: {msg_e}")
                    logger.error(traceback.format_exc())
            
            logger.info(f"채널 {channel_id}에서 총 {total_messages}개 메시지 중 {processed_messages}개 처리됨 "
                        f"(선택 메시지: {len(select_messages)}, 제보 메시지: {len(deep_report_messages)})")
            
            # 제보 메시지들의 ID 목록
            found_deep_ids = list(deep_report_messages.keys())
            if found_deep_ids:
                logger.info(f"발견된 제보 메시지 ID: {', '.join(found_deep_ids[:5])}{'...' if len(found_deep_ids) > 5 else ''}")
            
            # 1. 제보 메시지 상태에 따라 분류
            now = datetime.now()
            logger.info(f"현재 시간: {now.strftime('%Y-%m-%d %H:%M:%S')}")
            all_reports = select_all_deep_reports(db, guild_id, channel_id)
            
            if not all_reports:
                logger.info(f"채널 {channel_id}에 저장된 심층 제보가 없습니다.")
                return
            
            # DB에 저장된 모든 deep_id 목록
            db_deep_ids = [str(report["deep_id"]) for report in all_reports]
            logger.info(f"DB에 저장된 제보 ID: {', '.join(db_deep_ids[:5])}{'...' if len(db_deep_ids) > 5 else ''}")
            
            # 제보 상태별 분류
            error_deep_ids = set()  # 오제보로 표시된 메시지
            expired_deep_ids = set()  # 시간이 만료된 메시지
            valid_deep_ids = set()  # 유효한 메시지
            
            for report in all_reports:
                deep_id = str(report["deep_id"])  # 문자열로 변환하여 비교
                create_time = report["create_dt"]
                remaining_minutes = report["remaining_minutes"]
                is_error = report["is_error"] == 'Y'
                
                # 오제보 여부 확인
                if is_error:
                    error_deep_ids.add(deep_id)
                    continue
                
                # 만료 여부 확인 (생성 시간 + 남은 시간 < 현재 시간)
                expiration_time = create_time + timedelta(minutes=remaining_minutes)
                
                # 디버깅을 위한 로그 추가
                logger.debug(f"심층 제보 ID {deep_id}: 생성시간 {create_time.strftime('%Y-%m-%d %H:%M:%S')}, " +
                            f"남은시간 {remaining_minutes}분, 만료시간 {expiration_time.strftime('%Y-%m-%d %H:%M:%S')}")
                
                if expiration_time < now:
                    expired_deep_ids.add(deep_id)
                    logger.info(f"만료된 심층 제보 감지: ID {deep_id} (만료시각: {expiration_time.strftime('%Y-%m-%d %H:%M:%S')})")
                    continue
                
                # 유효한 메시지
                valid_deep_ids.add(deep_id)
            
            logger.info(f"채널 {channel_id} 메시지 상태 분류: 오제보 {len(error_deep_ids)}개, " + 
                        f"만료됨 {len(expired_deep_ids)}개, 유효함 {len(valid_deep_ids)}개")
            
            # 2. 각 메시지 상태에 따라 처리 - 유효한 메시지만 업데이트
            updated_count = 0
            for deep_id_str, message in deep_report_messages.items():
                try:
                    # DB에 해당 deep_id가 없는 경우 건너뛰기
                    if deep_id_str not in db_deep_ids:
                        logger.warning(f"채널 메시지 {message.id} (Deep ID: {deep_id_str})에 해당하는 DB 레코드가 없습니다. 건너뜁니다.")
                        continue

                    action_taken = False
                    if deep_id_str in error_deep_ids:
                        logger.debug(f"오류 메시지 {deep_id_str} 처리 시도.")
                        if await self.mark_error_message(message, deep_id_str):
                            action_taken = True
                    elif deep_id_str in expired_deep_ids:
                        logger.debug(f"만료 메시지 {deep_id_str} 처리 시도.")
                        if await self.mark_expired_message(message, deep_id_str):
                            action_taken = True
                    elif deep_id_str in valid_deep_ids:
                        logger.debug(f"유효 메시지 {deep_id_str} 처리 시도.")
                        if await self.refresh_valid_message(message, deep_id_str):
                            action_taken = True
                    else:
                        logger.warning(f"메시지 {deep_id_str} (ID: {message.id})는 DB에 있지만 상태가 불분명합니다.")
                    
                    if action_taken:
                        updated_count += 1

                except discord.NotFound:
                    logger.warning(f"메시지 {deep_id_str} (ID: {message.id})를 찾을 수 없어 처리할 수 없습니다.")
                except Exception as e:
                    logger.error(f"메시지 {deep_id_str} (ID: {message.id}) 처리 중 오류: {e}")
                    logger.error(traceback.format_exc())
            
            logger.info(f"채널 {channel_id}에서 총 {updated_count}개 메시지 상태 업데이트 시도/완료")
            
            # 3. Select 메시지 처리 - 반드시 채널의 가장 마지막에 위치하도록 관리
            try:
                # 현재 채널의 가장 최근 메시지 확인
                last_message = None
                async for msg in channel.history(limit=1):
                    last_message = msg
                    break
                
                # 양식 메시지가 채널의 마지막 메시지가 아니거나 없는 경우
                needs_new_select = False
                
                if not select_messages:
                    # 양식 메시지가 없는 경우 신규 생성 필요
                    needs_new_select = True
                    logger.info(f"양식 메시지가 없어 새로 생성합니다.")
                elif last_message and select_messages[0].id != last_message.id:
                    # 양식 메시지가 마지막 메시지가 아닌 경우 기존 메시지 삭제 후 신규 생성
                    needs_new_select = True
                    logger.info(f"양식 메시지가 마지막 메시지가 아니어서 재생성합니다.")
                
                # 신규 양식 메시지 생성이 필요한 경우
                if needs_new_select:
                    # 기존 양식 메시지 모두 삭제
                    for old_select in select_messages:
                        try:
                            await old_select.delete()
                            logger.info(f"기존 양식 메시지 삭제: {old_select.id}")
                        except Exception as del_err:
                            logger.error(f"양식 메시지 삭제 중 오류: {del_err}")
                    
                    # 새 양식 메시지 생성
                    await self.initialize_deep_button(channel_id, auth)
                else:
                    # 중복된 양식 메시지만 삭제 (첫 번째 메시지 유지)
                    if len(select_messages) > 1:
                        for old_message in select_messages[1:]:
                            try:
                                await old_message.delete()
                            except Exception as e:
                                logger.error(f"Select 메시지 삭제 중 오류: {e}")
            
            except Exception as e:
                logger.error(f"Select 메시지 처리 중 오류: {e}")
        
        except Exception as e:
            logger.error(f"심층 채널 {channel_id} 메시지 관리 중 오류: {e}")
            logger.error(traceback.format_exc())

    def _clean_status_indicators(self, title):
        """상태 표시자를 제목에서 제거하는 헬퍼 함수"""
        if not title:
            return "심층 제보"  # 기본 제목 설정
            
        # 모든 상태 표시자 제거
        cleaned_title = title
        status_indicators = ["[진행중] ", "⏰ [만료] ", "❌ [오제보] "]
        for indicator in status_indicators:
            cleaned_title = cleaned_title.replace(indicator, "")
            
        return cleaned_title

    async def mark_error_message(self, message, deep_id):
        """오제보 메시지 표시"""
        try:
            # 원본 임베드 복제
            embed = message.embeds[0]
            
            # 제목에서 모든 상태 표시자 제거 후 오제보 표시 추가
            original_title = embed.title
            # 이미 오제보 상태면 스킵
            if "❌ [오제보]" in original_title:
                logger.info(f"메시지 {deep_id} (ID: {message.id})는 이미 오제보 상태로 표시되어 있습니다. 스킵합니다.")
                return True # 이미 올바른 상태이므로 성공으로 처리

            cleaned_title = self._clean_status_indicators(original_title)
            embed.title = f"❌ [오제보] {cleaned_title}"
            embed.color = discord.Color.red()
            
            logger.info(f"오제보 메시지 {deep_id} 제목 변경: '{original_title}' → '{embed.title}'")
            
            # 버튼 비활성화 - 신고 버튼이 있는 뷰 생성
            view = DeepReportView(deep_id)
            for item in view.children:
                item.disabled = True
                item.label = "신고 처리 완료"
            
            # 메시지 업데이트
            await message.edit(embed=embed, view=view)
            logger.info(f"오제보 메시지 {deep_id} 표시 완료")
            return True
        except Exception as e:
            logger.error(f"오제보 메시지 {deep_id} 표시 중 오류: {e}")
            return False

    async def mark_expired_message(self, message, deep_id):
        """만료된 메시지 표시"""
        try:
            # 원본 임베드 존재 여부 확인
            if not message.embeds or len(message.embeds) == 0:
                logger.error(f"만료된 메시지 {deep_id}에 임베드가 없습니다.")
                return False
                
            # 원본 임베드 복제
            embed = message.embeds[0]
            
            # 제목에서 모든 상태 표시자 제거 후 만료 표시 추가
            original_title = embed.title
            # 이미 만료 상태면 스킵
            if "⏰ [만료]" in original_title:
                logger.info(f"메시지 {deep_id} (ID: {message.id})는 이미 만료 상태로 표시되어 있습니다. 스킵합니다.")
                return True # 이미 올바른 상태이므로 성공으로 처리

            cleaned_title = self._clean_status_indicators(original_title)
            embed.title = f"⏰ [만료] {cleaned_title}"
            embed.color = discord.Color.greyple()
            
            logger.info(f"만료된 메시지 {deep_id} 제목 변경: '{original_title}' → '{embed.title}'")
            
            # 버튼 비활성화 - 신고 버튼이 있는 뷰 생성
            view = DeepReportView(deep_id)
            for item in view.children:
                if isinstance(item, discord.ui.Button): # 버튼인지 확인 (안전장치)
                    item.disabled = True
                    item.label = "만료됨" # "만료됨"으로 버튼 레이블 변경
            
            # 메시지 업데이트 전 로깅
            logger.info(f"메시지 {deep_id} (ID: {message.id}) 업데이트 시도 중...")
            
            # 메시지 업데이트
            try:
                await message.edit(embed=embed, view=view)
                logger.info(f"만료 메시지 {deep_id} 표시 완료 (메시지 ID: {message.id})")
                return True
            except discord.NotFound:
                logger.error(f"만료된 메시지 {deep_id}를 찾을 수 없습니다 (메시지 ID: {message.id})")
                return False
            except discord.HTTPException as http_error:
                logger.error(f"만료된 메시지 {deep_id} 업데이트 중 HTTP 오류: {http_error} (메시지 ID: {message.id})")
                return False
        except Exception as e:
            logger.error(f"만료 메시지 {deep_id} 표시 중 오류: {e}")
            logger.error(traceback.format_exc())
            return False

    async def refresh_valid_message(self, message, deep_id):
        """유효한 메시지 상호작용 갱신"""
        try:
            # 원본 임베드 복제
            embed = message.embeds[0]
            
            # 제목에서 모든 상태 표시자 제거 후 진행중 표시 추가
            original_title = embed.title
            
            # 이미 유효한 진행중 상태이고, 오류/만료 상태가 아니면 스킵
            is_already_valid_display = "[진행중]" in original_title
            is_error_or_expired_display = "⏰ [만료]" in original_title or "❌ [오제보]" in original_title

            if is_already_valid_display and not is_error_or_expired_display:
                logger.info(f"메시지 {deep_id} (ID: {message.id})는 이미 유효한 진행중 상태입니다. 스킵합니다.")
                return True # 이미 올바른 상태이므로 성공으로 처리

            cleaned_title = self._clean_status_indicators(original_title)
            embed.title = f"[진행중] {cleaned_title}"
            embed.color = discord.Color.dark_purple() # 원래 유효한 메시지의 색상으로 설정
            
            # 로그 추가
            logger.info(f"유효 메시지 {deep_id} 제목 변경: '{original_title}' → '{embed.title}'")
            
            # 버튼 갱신 - 신고 버튼이 있는 뷰 생성
            view = DeepReportView(deep_id)
            
            # 메시지 업데이트
            await message.edit(embed=embed, view=view)
            logger.info(f"유효 메시지 {deep_id} 상호작용 갱신 완료")
            return True
        except Exception as e:
            logger.error(f"유효 메시지 {deep_id} 상호작용 갱신 중 오류: {e}")
            return False

# Cog 등록
async def setup(bot):
    await bot.add_cog(DeepCog(bot))
