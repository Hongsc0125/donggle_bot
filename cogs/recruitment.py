import discord
from discord.ext import commands
from discord import app_commands
import logging

from db.session import SessionLocal
from queries.channel_query import get_pair_channel, insert_pair_channel, insert_guild_auth, select_guild_auth
from queries.recruitment_query import select_recruitment_channel

logger = logging.getLogger(__name__)

class RecruitmentCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_ready(self):
        # 봇이 준비되면 등록 채널에 버튼 메시지 전송
        db = SessionLocal()
        # 등록된 모든 등록채널 조회
        regist_channel_ids = select_recruitment_channel(db)
        db.close()
        for row in regist_channel_ids:
            channel_id = int(row[0])
            channel = self.bot.get_channel(channel_id)
            if channel:
                # 이미 메시지가 있는지 확인하지 않고 항상 보냄 (중복 방지 필요시 추가 구현)
                view = RecruitmentButtonView()
                try:
                    await channel.send(
                        content="파티 모집 등록을 원하시면 아래 버튼을 눌러주세요.",
                        view=view
                    )
                except Exception as e:
                    logger.warning(f"등록 채널 {channel_id}에 버튼 메시지 전송 실패: {str(e)}")

class RecruitmentButtonView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="파티 모집 등록", style=discord.ButtonStyle.primary, custom_id="recruitment_register")
    async def register_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("파티 모집 등록 기능은 준비 중입니다.", ephemeral=True)

# Cog를 등록하는 설정 함수
async def setup(bot):
    await bot.add_cog(RecruitmentCog(bot))

