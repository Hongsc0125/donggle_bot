from discord.ext import commands
from database.session import get_database
from views.recruitment_card import RecruitmentCard
from core.config import settings
import discord
from discord import app_commands
from typing import Union, Any

# AppCommandChannel 대신 사용할 타입 정의
class AppCommandChannel:
    id: str
    
    def __init__(self, id):
        self.id = id

# 도움말 명령어를 위한 도움말 데이터
HELP_DATA = {
    "모집": {
        "명령어": "/모집",
        "설명": "모집 등록 채널을 안내합니다. 실제 모집은 지정된 모집 등록 채널에서 진행됩니다.",
        "사용법": "/모집",
        "권한": "모든 사용자"
    },
    "모집채널설정": {
        "명령어": "/모집채널설정 [채널]",
        "설명": "모집 공고가 게시될 채널을 설정합니다. 채널을 지정하지 않으면 선택 메뉴가 표시됩니다.",
        "사용법": "/모집채널설정 또는 /모집채널설정 #채널명",
        "권한": "관리자"
    },
    "모집등록채널설정": {
        "명령어": "/모집등록채널설정 [채널]",
        "설명": "모집 등록 양식이 표시될 채널을 설정합니다. 채널을 지정하지 않으면 선택 메뉴가 표시됩니다.",
        "사용법": "/모집등록채널설정 또는 /모집등록채널설정 #채널명",
        "권한": "관리자"
    },
    "동글_도움말": {
        "명령어": "/동글_도움말",
        "설명": "동글봇의 명령어 목록과 사용법을 보여줍니다.",
        "사용법": "/동글_도움말",
        "권한": "모든 사용자"
    }
}

# 채널 설정을 위한 View 클래스 추가
class ChannelSetupView(discord.ui.View):
    def __init__(self, cog, setup_type):
        super().__init__(timeout=60)
        self.cog = cog
        self.setup_type = setup_type  # "announcement" 또는 "registration"
        
        # 채널 선택 메뉴 추가
        self.channel_select = discord.ui.ChannelSelect(
            placeholder="채널을 선택하세요",
            channel_types=[discord.ChannelType.text],
            min_values=1,
            max_values=1,
            row=0
        )
        self.channel_select.callback = self.channel_select_callback
        self.add_item(self.channel_select)
    
    async def channel_select_callback(self, interaction: discord.Interaction):
        """
        채널 선택 콜백 - 사용자가 선택한 채널을 처리합니다.
        채널 타입에 따라 적절한 채널 설정 함수를 호출합니다.
        """
        await interaction.response.defer(ephemeral=True)
        
        # 선택된 채널
        selected_channel = self.channel_select.values[0]
        
        # 채널 유형에 따라 설정 함수 호출
        if self.setup_type == "announcement":
            await self.cog.set_announcement_channel_internal(interaction, selected_channel)
        elif self.setup_type == "registration":
            await self.cog.set_registration_channel_internal(interaction, selected_channel)
        else:
            await interaction.followup.send("알 수 없는 채널 유형입니다.", ephemeral=True)

class PartyCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db = get_database()
        self.announcement_channel_id = None
        self.registration_channel_id = None
        self.registration_locked = False  # 모집 등록 잠금 상태 (5초간)
        self._load_settings_sync()

    def _load_settings_sync(self):
        """초기 설정을 동기적으로 로드합니다."""
        try:
            # 초기에는 채널 ID를 None으로 설정
            self.announcement_channel_id = None
            self.registration_channel_id = None
            # bot.py가 실행될 때 설정을 로드하기 위해 비동기적으로 설정을 로드하는 작업을 봇 루프에 추가
            self.bot.loop.create_task(self._load_settings_async())
        except Exception as e:
            print(f"설정 로드 중 오류 발생: {e}")

    async def _load_settings_async(self):
        """데이터베이스에서 채널 ID를 비동기적으로 로드합니다."""
        try:
            settings = await self.db["bot_settings"].find_one({"setting_type": "channels"})
            if settings:
                self.announcement_channel_id = settings.get("announcement_channel_id")
                self.registration_channel_id = settings.get("registration_channel_id")
                print(f"모집 공고 채널 ID를 로드했습니다: {self.announcement_channel_id}")
                print(f"모집 등록 채널 ID를 로드했습니다: {self.registration_channel_id}")
        except Exception as e:
            print(f"채널 ID 로드 중 오류 발생: {e}")

    @commands.Cog.listener()
    async def on_message(self, message):
        # 봇의 메시지는 무시
        if message.author.bot:
            return

        # 파티_모집 채널인지 확인
        if str(message.channel.id) == self.announcement_channel_id:
            await message.delete()
            return

        # 파티_모집_등록 채널인지 확인
        if str(message.channel.id) == self.registration_channel_id:
            await message.delete()
            return

    @app_commands.command(name="모집")
    async def recruit_party(self, interaction: discord.Interaction):
        """레거시 모집 명령어 - 더 이상 사용하지 않습니다."""
        await interaction.response.send_message("이제 모집 명령어는 사용하지 않습니다. 대신 모집 등록 채널에서 양식을 작성해주세요.")
    
    @app_commands.command(name="모집채널설정")
    @app_commands.checks.has_permissions(administrator=True)
    async def set_announcement_channel_cmd(self, interaction: discord.Interaction, channel: discord.TextChannel = None):
        """모집 공고가 게시될 채널을 설정합니다. 관리자만 사용 가능합니다."""
        if channel:
            # 직접 채널 인자가 제공된 경우
            await self.set_announcement_channel_internal(interaction, channel)
        else:
            # 채널 선택 UI 표시
            view = ChannelSetupView(self, "announcement")
            embed = discord.Embed(
                title="모집 공고 채널 설정",
                description="모집 공고가 게시될 채널을 선택해주세요.",
                color=discord.Color.blue()
            )
            await interaction.response.send_message(embed=embed, view=view)
    
    async def set_announcement_channel_internal(self, ctx, channel):
        """모집 공고 채널을 설정하는 내부 메서드"""
        is_interaction = isinstance(ctx, discord.Interaction)
        
        # 채널 객체 확인 및 변환
        if not isinstance(channel, discord.TextChannel):
            # ID를 사용하여 실제 채널 객체를 가져옴
            channel_id = getattr(channel, 'id', channel)
            try:
                if hasattr(ctx, 'guild'):
                    # Context나 Interaction인 경우
                    guild = ctx.guild
                else:
                    # 다른 경우에는 봇에서 guild를 찾음
                    guild = self.bot.get_guild(ctx.guild_id)
                
                real_channel = guild.get_channel(int(channel_id))
                if real_channel:
                    channel = real_channel
                else:
                    message = f"채널을 찾을 수 없습니다. ID: {channel_id}"
                    if is_interaction:
                        await ctx.followup.send(message, ephemeral=True)
                    else:
                        await ctx.send(message)
                    return
            except Exception as e:
                message = f"채널을 찾을 수 없습니다: {e}"
                if is_interaction:
                    await ctx.followup.send(message, ephemeral=True)
                else:
                    await ctx.send(message)
                return
        
        try:
            # 채널 권한 연동 설정
            await channel.edit(sync_permissions=True)
            
            # 데이터베이스에 설정 저장
            await self.db["bot_settings"].update_one(
                {"setting_type": "channels"},
                {"$set": {"announcement_channel_id": str(channel.id)}},
                upsert=True
            )
            
            # 채널 ID 저장
            self.announcement_channel_id = str(channel.id)
            
            message = f"모집 공고 채널이 {channel.mention}로 설정되었습니다."
            if is_interaction:
                await ctx.followup.send(message, ephemeral=True)
            else:
                await ctx.send(message)
        except Exception as e:
            print(f"모집 공고 채널 설정 중 오류 발생: {e}")
            message = "모집 공고 채널 설정 중 오류가 발생했습니다."
            if is_interaction:
                await ctx.followup.send(message, ephemeral=True)
            else:
                await ctx.send(message)

    @app_commands.command(name="모집등록채널설정")
    @app_commands.checks.has_permissions(administrator=True)
    async def set_registration_channel_cmd(self, interaction: discord.Interaction, channel: discord.TextChannel = None):
        """모집 등록 양식이 표시될 채널을 설정합니다. 관리자만 사용 가능합니다."""
        if channel:
            # 직접 채널 인자가 제공된 경우
            await self.set_registration_channel_internal(interaction, channel)
        else:
            # 채널 선택 UI 표시
            view = ChannelSetupView(self, "registration")
            embed = discord.Embed(
                title="모집 등록 채널 설정",
                description="모집 등록 양식이 표시될 채널을 선택해주세요.",
                color=discord.Color.blue()
            )
            await interaction.response.send_message(embed=embed, view=view)
    
    async def set_registration_channel_internal(self, ctx, channel):
        """모집 등록 채널을 설정하는 내부 메서드"""
        is_interaction = isinstance(ctx, discord.Interaction)
        
        # 채널 객체 확인 및 변환
        if not isinstance(channel, discord.TextChannel):
            # ID를 사용하여 실제 채널 객체를 가져옴
            channel_id = getattr(channel, 'id', channel)
            try:
                if hasattr(ctx, 'guild'):
                    # Context나 Interaction인 경우
                    guild = ctx.guild
                else:
                    # 다른 경우에는 봇에서 guild를 찾음
                    guild = self.bot.get_guild(ctx.guild_id)
                
                real_channel = guild.get_channel(int(channel_id))
                if real_channel:
                    channel = real_channel
                else:
                    message = f"채널을 찾을 수 없습니다. ID: {channel_id}"
                    if is_interaction:
                        await ctx.followup.send(message, ephemeral=True)
                    else:
                        await ctx.send(message)
                    return
            except Exception as e:
                message = f"채널을 찾을 수 없습니다: {e}"
                if is_interaction:
                    await ctx.followup.send(message, ephemeral=True)
                else:
                    await ctx.send(message)
                return
        
        try:
            # 채널 권한 연동 설정
            await channel.edit(sync_permissions=True)
            
            # 데이터베이스에 설정 저장
            await self.db["bot_settings"].update_one(
                {"setting_type": "channels"},
                {"$set": {"registration_channel_id": str(channel.id)}},
                upsert=True
            )
            
            # 채널 ID 저장
            self.registration_channel_id = str(channel.id)
            
            # 새 등록 양식 생성
            await self.create_registration_form(channel)
            
            # 설정 완료 메시지 전송
            message = f"모집 등록 채널이 {channel.mention}로 설정되었습니다."
            if is_interaction:
                await ctx.followup.send(message, ephemeral=True)
            else:
                await ctx.send(message)
        except Exception as e:
            print(f"등록 양식 설정 중 오류 발생: {e}")
            message = "등록 양식 설정 중 오류가 발생했습니다."
            if is_interaction:
                await ctx.followup.send(message, ephemeral=True)
            else:
                await ctx.send(message)

    async def create_registration_form(self, channel):
        """모집 등록 채널에 빈 양식을 생성합니다."""
        # 던전 목록 가져오기
        dungeons_cursor = self.db["dungeons"].find({})
        dungeons = [doc async for doc in dungeons_cursor]
        dungeons.sort(key=lambda d: (d["type"], d["name"], d["difficulty"]))
        
        # 등록 양식 생성
        view = RecruitmentCard(dungeons, self.db)
        embed = view.get_embed()
        embed.title = "파티 모집 등록 양식"
        
        # 등록 잠금 상태이면 안내 메시지 수정 및 버튼 비활성화
        if self.registration_locked:
            embed.description = "잠시 후 모집 등록이 가능합니다. 5초만 기다려주세요."
            # 모든 버튼과 선택 메뉴 비활성화
            for item in view.children:
                item.disabled = True
        else:
            embed.description = (
                "아래 순서대로 양식을 작성해주세요:\n\n"
                "1. **던전 유형** 선택: 일반/레이드/기타 중 선택\n"
                "2. **던전 종류** 선택: 선택한 유형에 맞는 던전 선택\n"
                "3. **난이도** 선택: 선택한 던전의 난이도 선택\n"
                "4. **모집 내용** 입력: 파티 모집에 대한 상세 내용 작성\n"
                "5. **최대 인원** 설정: 파티 모집 인원 수 설정\n\n"
                "모든 항목을 작성한 후 '모집 등록' 버튼을 클릭하세요."
            )
        
        # 양식 전송
        message = await channel.send(embed=embed, view=view)
        view.message = message  # persistent 메시지 저장
        self.registration_message = message
        
        return message
    
    # PartyCog의 모집 등록 후 이벤트를 처리하는 함수 (RecruitmentCard와 연동)
    async def post_recruitment_announcement(self, guild_id, recruitment_data, view):
        """모집 공고를 모집 공고 채널에 게시합니다."""
        if not self.announcement_channel_id:
            # 공고 채널이 설정되지 않았으면 종료
            return None
        
        try:
            # 채널 가져오기
            guild = self.bot.get_guild(int(guild_id))
            if not guild:
                return None
            
            channel = guild.get_channel(int(self.announcement_channel_id))
            if not channel:
                return None
            
            # 공고 임베드 생성 - 복제된 뷰 사용
            announcement_view = RecruitmentCard(view.dungeons, self.db)
            announcement_view.selected_type = view.selected_type
            announcement_view.selected_kind = view.selected_kind
            announcement_view.selected_diff = view.selected_diff
            announcement_view.recruitment_content = view.recruitment_content
            announcement_view.max_participants = view.max_participants
            announcement_view.status = view.status
            announcement_view.recruitment_id = view.recruitment_id
            announcement_view.participants = view.participants.copy()
            
            # 참가하기 버튼 추가
            join_button = discord.ui.Button(label="참가하기", style=discord.ButtonStyle.success, custom_id="btn_join", row=0)
            join_button.callback = announcement_view.btn_join_callback
            
            # 신청 취소 버튼 추가
            cancel_button = discord.ui.Button(label="신청 취소", style=discord.ButtonStyle.danger, custom_id="btn_cancel", row=0)
            cancel_button.callback = announcement_view.btn_cancel
            
            announcement_view.clear_items()  # 모든 기존 항목 제거
            announcement_view.add_item(join_button)  # 참가 버튼 추가
            announcement_view.add_item(cancel_button)  # 취소 버튼 추가
            
            embed = announcement_view.get_embed()
            embed.title = "파티 모집 공고"
            
            # 공고 메시지 전송
            announcement_message = await channel.send(embed=embed, view=announcement_view)
            announcement_view.message = announcement_message
            
            # 공고 메시지 ID 저장
            view.announcement_message_id = str(announcement_message.id)
            view.target_channel_id = self.announcement_channel_id
            announcement_view.announcement_message_id = str(announcement_message.id)
            announcement_view.target_channel_id = self.announcement_channel_id
            
            # DB에 공고 메시지 ID 업데이트
            await self.db["recruitments"].update_one(
                {"_id": view.recruitment_id},
                {"$set": {
                    "announcement_message_id": str(announcement_message.id),
                    "announcement_channel_id": self.announcement_channel_id
                }}
            )
            
            # 참고: 등록 양식 생성은 이제 recruitment_card.py에서 처리합니다.
            
            return announcement_message
            
        except Exception as e:
            print(f"모집 공고 게시 중 오류 발생: {e}")
            return None

    @app_commands.command(name="동글_도움말")
    async def help_command(self, interaction: discord.Interaction):
        """동글봇의 명령어 목록과 사용법을 보여줍니다."""
        embed = discord.Embed(
            title="🤖 동글봇 도움말",
            description="동글봇의 사용 가능한 명령어 목록입니다.",
            color=discord.Color.blue()
        )
        
        # 각 명령어별 설명 추가
        for cmd_name, cmd_info in HELP_DATA.items():
            value = f"**설명**: {cmd_info['설명']}\n**사용법**: {cmd_info['사용법']}\n**권한**: {cmd_info['권한']}"
            embed.add_field(name=f"/{cmd_name}", value=value, inline=False)
        
        # 모집 시스템 간단 설명 추가
        embed.add_field(
            name="📝 모집 시스템 사용법",
            value=(
                "1. 관리자가 `/모집채널설정`과 `/모집등록채널설정`으로 채널을 설정합니다.\n"
                "2. 사용자는 모집 등록 채널에서 양식을 작성하고 '모집 등록' 버튼을 클릭합니다.\n"
                "3. 등록된 모집은 모집 공고 채널에 자동으로 게시됩니다.\n"
                "4. 다른 사용자들은 모집 공고에서 '참가하기' 버튼을 클릭하여 참가할 수 있습니다.\n"
                "5. 인원이 다 차면 비공개 스레드가 자동으로 생성되고 참가자들이 초대됩니다."
            ),
            inline=False
        )
        
        # 슈퍼유저 명령어 설명 (힝트 사용자용)
        if interaction.user.name == "힝트" or interaction.user.display_name == "힝트":
            embed.add_field(
                name="🔑 슈퍼유저 기능 (힝트 전용)",
                value=(
                    "- 중복 참가 가능\n"
                    "- 인원 제한 무시 가능\n"
                    "- 모집 등록 시 값 자동 완성\n"
                    "- '스레드 생성' 버튼으로 즉시 스레드 생성 가능"
                ),
                inline=False
            )
        
        embed.set_footer(text="문제가 발생하거나 건의사항이 있으시면 관리자에게 문의해주세요.")
        
        await interaction.response.send_message(embed=embed, ephemeral=True)

async def setup(bot):
    await bot.add_cog(PartyCog(bot))
    bot_cog = bot.get_cog('PartyCog')
    if not bot_cog:
        print("PartyCog를 찾을 수 없습니다.")
