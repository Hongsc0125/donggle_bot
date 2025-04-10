from discord.ext import commands
import discord
from discord import app_commands
from typing import List, Optional
from database.session import get_database
import logging
import traceback
import asyncio
from core.config import settings
import re

# 로깅 설정
logger = logging.getLogger('donggle_bot.auth')

# 서버와 직업 선택을 위한 상수
SERVERS = ["데이안", "아이라", "던컨", "알리사", "메이븐", "라사", "칼릭스"]
JOBS = [
    "전사", "대검전사", "검술사", 
    "궁수", "석궁사수", "장궁병", 
    "마법사", "화염술사", "빙결술사", 
    "힐러", "사제", "수도사", 
    "음유시인", "댄서", "악사"
]

class ServerSelect(discord.ui.Select):
    def __init__(self, parent_view):
        options = [discord.SelectOption(label=server, value=server) for server in SERVERS]
        super().__init__(placeholder="서버를 선택하세요", options=options, min_values=1, max_values=1)
        self.parent_view = parent_view
    
    async def callback(self, interaction: discord.Interaction):
        self.parent_view.server = self.values[0]
        self.parent_view.update_components()
        await interaction.response.edit_message(content=f"서버: {self.values[0]}\n직업을 선택해주세요.", view=self.parent_view)

class JobSelect(discord.ui.Select):
    def __init__(self, parent_view):
        options = [discord.SelectOption(label=job, value=job) for job in JOBS]
        super().__init__(placeholder="직업을 선택하세요", options=options, min_values=1, max_values=1)
        self.parent_view = parent_view
    
    async def callback(self, interaction: discord.Interaction):
        self.parent_view.job = self.values[0]
        self.parent_view.update_components()
        
        # 직업 선택 후 닉네임 입력 창 표시
        await interaction.response.edit_message(
            content=f"서버: {self.parent_view.server}\n직업: {self.values[0]}\n\n이제 닉네임을 입력해주세요.",
            view=self.parent_view
        )

class NicknameModal(discord.ui.Modal):
    def __init__(self, parent_view):
        super().__init__(title="닉네임 입력")
        self.parent_view = parent_view
        
        self.nickname = discord.ui.TextInput(
            label="닉네임",
            placeholder="게임 내 닉네임을 입력하세요",
            min_length=1,
            max_length=10
        )
        self.add_item(self.nickname)
    
    async def on_submit(self, interaction: discord.Interaction):
        self.parent_view.nickname = self.nickname.value
        await interaction.response.defer()
        await self.parent_view.apply_auth(interaction)

class NicknameButton(discord.ui.Button):
    def __init__(self, parent_view):
        super().__init__(label="닉네임 입력", style=discord.ButtonStyle.primary)
        self.parent_view = parent_view
    
    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_modal(NicknameModal(self.parent_view))

class AuthView(discord.ui.View):
    def __init__(self, cog):
        super().__init__(timeout=None)  # 10분 타임아웃
        self.cog = cog
        self.server = None
        self.job = None
        self.nickname = None
        
        # 초기 상태로 서버 선택만 표시
        self.server_select = ServerSelect(self)
        self.add_item(self.server_select)
    
    def update_components(self):
        # 모든 기존 컴포넌트 제거
        self.clear_items()
        
        # 서버 선택 완료 상태
        if self.server and not self.job:
            self.job_select = JobSelect(self)
            self.add_item(self.job_select)
        
        # 직업 선택 완료 상태
        elif self.server and self.job and not self.nickname:
            self.nickname_button = NicknameButton(self)
            self.add_item(self.nickname_button)
    
    async def apply_auth(self, interaction: discord.Interaction):
        try:
            user = interaction.user
            guild = interaction.guild
            
            # 닉네임 형식 설정
            new_nickname = f"[{self.server}][{self.job}]{self.nickname}"
            
            # 닉네임 변경
            try:
                await user.edit(nick=new_nickname)
                logger.info(f"사용자 {user.id} 닉네임 변경: {new_nickname}")
            except discord.Forbidden:
                logger.error(f"사용자 {user.id} 닉네임 변경 권한 없음")
                await interaction.followup.send("닉네임 변경 권한이 없습니다. 서버 관리자에게 문의해주세요.", ephemeral=True)
                return
            
            # 서버와 직업에 따른 역할 할당
            await self.assign_role(interaction)
            
            # 사용자 정보 DB에 저장
            await self.save_user_data(interaction)
            
            await interaction.followup.send(f"권한 설정이 완료되었습니다!\n서버: {self.server}\n직업: {self.job}\n닉네임: {self.nickname}", ephemeral=True)
            
        except Exception as e:
            logger.error(f"권한 적용 중 오류 발생: {e}")
            logger.error(traceback.format_exc())
            await interaction.followup.send("권한 설정 중 오류가 발생했습니다. 나중에 다시 시도하거나 관리자에게 문의해주세요.", ephemeral=True)
    
    async def assign_role(self, interaction: discord.Interaction):
        """서버와 직업에 따라 적절한 역할 부여"""
        guild = interaction.guild
        user = interaction.user
        
        # 서버 역할 찾기
        server_role = discord.utils.get(guild.roles, name=self.server)
        if not server_role:
            # 역할이 없으면 생성
            try:
                server_role = await guild.create_role(name=self.server, reason="자동 역할 생성")
                logger.info(f"서버 역할 생성: {self.server}")
            except discord.Forbidden:
                logger.error(f"역할 생성 권한 없음: {self.server}")
        
        # 직업 역할 찾기
        job_role = discord.utils.get(guild.roles, name=self.job)
        if not job_role:
            # 역할이 없으면 생성
            try:
                job_role = await guild.create_role(name=self.job, reason="자동 역할 생성")
                logger.info(f"직업 역할 생성: {self.job}")
            except discord.Forbidden:
                logger.error(f"역할 생성 권한 없음: {self.job}")
        
        # 인증 완료 역할 찾기
        auth_role = discord.utils.get(guild.roles, name="인증완료")
        if not auth_role:
            try:
                auth_role = await guild.create_role(name="인증완료", reason="자동 역할 생성")
                logger.info("인증완료 역할 생성")
            except discord.Forbidden:
                logger.error("역할 생성 권한 없음: 인증완료")
        
        # 역할 부여
        try:
            roles_to_add = []
            if server_role:
                roles_to_add.append(server_role)
            if job_role:
                roles_to_add.append(job_role)
            if auth_role:
                roles_to_add.append(auth_role)
            
            # 역할 할당
            for role in roles_to_add:
                if role not in user.roles:
                    await user.add_roles(role, reason="자동 권한 설정")
            
            logger.info(f"사용자 {user.id}에게 역할 부여: {[r.name for r in roles_to_add]}")
        except discord.Forbidden:
            logger.error(f"역할 부여 권한 없음: {user.id}")
    
    async def save_user_data(self, interaction: discord.Interaction):
        """사용자 정보를 데이터베이스에 저장"""
        try:
            db = get_database()
            user = interaction.user
            guild = interaction.guild
            
            user_data = {
                "user_id": str(user.id),
                "guild_id": str(guild.id),
                "server": self.server,
                "job": self.job,
                "nickname": self.nickname,
                "full_nickname": f"[{self.server}][{self.job}]{self.nickname}",
                "updated_at": settings.CURRENT_DATETIME
            }
            
            # 사용자 정보 저장/업데이트
            await db["user_auth"].update_one(
                {"user_id": str(user.id), "guild_id": str(guild.id)},
                {"$set": user_data},
                upsert=True
            )
            
            logger.info(f"사용자 {user.id} 권한 정보 저장 완료")
        except Exception as e:
            logger.error(f"사용자 정보 저장 중 오류 발생: {e}")
            logger.error(traceback.format_exc())

class AuthCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db = get_database()
        self.welcome_channels = {}  # 서버별 환영 채널 저장
        self._load_settings()
    
    def _load_settings(self):
        """초기 설정을 로드합니다."""
        try:
            # 비동기적으로 설정을 로드하는 작업을 봇 루프에 추가
            self.bot.loop.create_task(self._load_settings_async())
        except Exception as e:
            logger.error(f"설정 로드 중 오류 발생: {e}")
            logger.error(traceback.format_exc())
    
    async def _load_settings_async(self):
        """채널 설정을 비동기적으로 로드합니다."""
        try:
            # 봇이 준비될 때까지 대기
            await self.bot.wait_until_ready()
            
            # 모든 서버의 설정 정보 가져오기
            all_settings = await self.db["settings"].find({}).to_list(length=None)
            
            # 환영 채널 ID 로드
            for settings in all_settings:
                if "guild_id" not in settings:
                    continue
                
                guild_id = settings["guild_id"]
                
                if "welcome_channel_id" in settings:
                    self.welcome_channels[guild_id] = settings["welcome_channel_id"]
            
            logger.info(f"환영 채널 ID를 로드했습니다: {self.welcome_channels}")
        except Exception as e:
            logger.error(f"환영 채널 ID 로드 중 오류 발생: {e}")
            logger.error(traceback.format_exc())
    
    @commands.Cog.listener()
    async def on_ready(self):
        """봇이 준비되면 호출되는 이벤트"""
        try:
            # 명령어 동기화 시도
            await self.bot.tree.sync()
            logger.info("AuthCog: 명령어 트리가 성공적으로 동기화되었습니다.")
        except Exception as e:
            logger.error(f"AuthCog: 명령어 트리 동기화 중 오류 발생: {e}")
            logger.error(traceback.format_exc())
    
    @app_commands.command(name="명령어동기화", description="봇의 모든 슬래시 명령어를 동기화합니다.")
    @app_commands.checks.has_permissions(administrator=True)
    async def sync_commands(self, interaction: discord.Interaction):
        """명령어를 강제로 동기화하는 명령어"""
        try:
            await interaction.response.defer(ephemeral=True)
            await self.bot.tree.sync()
            await interaction.followup.send("모든 명령어가 성공적으로 동기화되었습니다.", ephemeral=True)
            logger.info(f"관리자 {interaction.user.id}가 명령어 동기화를 실행했습니다.")
        except Exception as e:
            logger.error(f"명령어 동기화 중 오류 발생: {e}")
            logger.error(traceback.format_exc())
            await interaction.followup.send("명령어 동기화 중 오류가 발생했습니다.", ephemeral=True)
    
    @commands.Cog.listener()
    async def on_member_join(self, member):
        """새 멤버가 서버에 들어왔을 때 환영 메시지 전송"""
        try:
            guild_id = str(member.guild.id)
            
            # 환영 채널이 설정되어 있으면 환영 메시지 전송
            if guild_id in self.welcome_channels:
                channel_id = self.welcome_channels[guild_id]
                channel = member.guild.get_channel(int(channel_id))
                
                if channel:
                    # 채널의 기본 메시지 자동 생성 기능 비활성화
                    await channel.edit(slowmode_delay=1)  # 1초 슬로우모드 설정
                    
                    embed = discord.Embed(
                        title="서버에 오신 것을 환영합니다!",
                        description=(
                            f"{member.mention}님, 서버 이용을 위해 다음 권한을 설정해주세요:\n\n"
                            "1. **서버 권한** - 서버 내 활동을 위한 기본 권한\n"
                            "2. **직업 권한** - 파티 모집 시 필요한 직업 정보\n"
                            "3. **닉네임 권한** - 서버 내 표시될 닉네임\n\n"
                            "권한 설정 방법:\n"
                            "1. `/권한` 명령어를 사용하여 권한 설정 메뉴를 열어주세요\n"
                            "2. 각 항목별로 필요한 정보를 입력해주세요\n"
                            "3. 모든 권한이 설정되면 서버의 모든 기능을 이용할 수 있습니다"
                        ),
                        color=discord.Color.blue()
                    )
                    
                    await channel.send(content=member.mention, embed=embed)
                    logger.info(f"사용자 {member.id}에게 환영 메시지 전송")
        except Exception as e:
            logger.error(f"환영 메시지 전송 중 오류 발생: {e}")
            logger.error(traceback.format_exc())
    
    @app_commands.command(name="환영채널설정", description="새 사용자를 환영하는 채널을 설정합니다.")
    @app_commands.checks.has_permissions(administrator=True)
    async def set_welcome_channel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        """환영 채널을 설정하는 명령어"""
        try:
            guild_id = str(interaction.guild.id)
            channel_id = str(channel.id)
            
            # DB에 저장
            await self.db["settings"].update_one(
                {"guild_id": guild_id},
                {"$set": {"welcome_channel_id": channel_id}},
                upsert=True
            )
            
            # 캐시 업데이트
            self.welcome_channels[guild_id] = channel_id
            
            await interaction.response.send_message(f"환영 채널이 {channel.mention}으로 설정되었습니다.", ephemeral=True)
            logger.info(f"서버 {guild_id}의 환영 채널 설정: {channel_id}")
        except Exception as e:
            logger.error(f"환영 채널 설정 중 오류 발생: {e}")
            logger.error(traceback.format_exc())
            await interaction.response.send_message("환영 채널 설정 중 오류가 발생했습니다.", ephemeral=True)
    
    @app_commands.command(name="권한", description="서버, 직업, 닉네임을 설정하여 적절한 권한을 받습니다.")
    async def auth(self, interaction: discord.Interaction):
        """서버, 직업, 닉네임 설정 명령어"""
        try:
            # 이미 인증이 완료된 사용자인지 확인
            user = interaction.user
            auth_role = discord.utils.get(interaction.guild.roles, name="인증완료")
            
            if auth_role and auth_role in user.roles:
                # 재인증 여부 확인
                await interaction.response.send_message(
                    "이미 인증이 완료되었습니다. 다시 설정하시겠습니까?",
                    view=ReauthConfirmView(self),
                    ephemeral=True
                )
                return
            
            # 인증 프로세스 시작
            view = AuthView(self)
            await interaction.response.send_message(
                "서버를 선택해주세요.",
                view=view,
                ephemeral=True
            )
            logger.info(f"사용자 {user.id} 권한 설정 시작")
        except Exception as e:
            logger.error(f"권한 명령어 실행 중 오류 발생: {e}")
            logger.error(traceback.format_exc())
            await interaction.response.send_message("명령어 실행 중 오류가 발생했습니다.", ephemeral=True)
    
    @app_commands.command(name="test", description="테스트 명령어입니다.")
    async def test_command(self, interaction: discord.Interaction):
        """테스트 용도의 명령어"""
        await interaction.response.send_message("테스트 명령어가 작동합니다!", ephemeral=True)
        logger.info(f"사용자 {interaction.user.id}가 테스트 명령어를 실행했습니다.")
    
    @app_commands.command(name="닉네임확인", description="특정 사용자의 서버, 직업, 닉네임 정보를 확인합니다.")
    @app_commands.checks.has_permissions(administrator=True)
    async def check_nickname(self, interaction: discord.Interaction, 사용자: discord.Member):
        """관리자용 사용자 정보 확인 명령어"""
        try:
            # 닉네임에서 정보 추출
            nickname = 사용자.nick or 사용자.name
            match = re.match(r'\[(.*?)\]\[(.*?)\](.*)', nickname)
            
            if match:
                server, job, ingame_nickname = match.groups()
                
                embed = discord.Embed(
                    title="사용자 정보",
                    description=f"사용자: {사용자.mention}",
                    color=discord.Color.blue()
                )
                
                embed.add_field(name="서버", value=server, inline=True)
                embed.add_field(name="직업", value=job, inline=True)
                embed.add_field(name="닉네임", value=ingame_nickname, inline=True)
                
                await interaction.response.send_message(embed=embed, ephemeral=True)
            else:
                await interaction.response.send_message("이 사용자는 인증된 닉네임 형식이 아닙니다.", ephemeral=True)
        except Exception as e:
            logger.error(f"닉네임 확인 중 오류 발생: {e}")
            logger.error(traceback.format_exc())
            await interaction.response.send_message("명령어 실행 중 오류가 발생했습니다.", ephemeral=True)

class ReauthConfirmView(discord.ui.View):
    def __init__(self, cog):
        super().__init__(timeout=None)  # 1분 타임아웃
        self.cog = cog
    
    @discord.ui.button(label="네", style=discord.ButtonStyle.primary)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = AuthView(self.cog)
        await interaction.response.edit_message(content="서버를 선택해주세요.", view=view)
    
    @discord.ui.button(label="아니오", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(content="인증 설정이 취소되었습니다.", view=None)

async def setup(bot):
    await bot.add_cog(AuthCog(bot)) 