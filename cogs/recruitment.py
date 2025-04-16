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
                view = RecruitmentButtonView()
                # 이미 메시지가 있는지 확인
                last_message = None
                try:
                    async for message in channel.history(limit=50, oldest_first=False):
                        if (
                            message.author.id == self.bot.user.id and
                            message.components and
                            any(
                                any(
                                    hasattr(child, "custom_id") and child.custom_id == "recruitment_register"
                                    for child in (component.children if hasattr(component, "children") else [])
                                )
                                for component in message.components
                            )
                        ):
                            last_message = message
                            break
                except Exception as e:
                    logger.warning(f"채널 {channel_id} 메시지 조회 실패: {str(e)}")

                if last_message:
                    # last_message만 남기고 채널의 모든 메시지 삭제
                    try:
                        async for message in channel.history(limit=50, oldest_first=False):
                            if message.id != last_message.id:
                                try:
                                    await message.delete()
                                except Exception as e:
                                    logger.warning(f"메시지 삭제 실패: {str(e)}")
                        # 기존 메시지의 view만 갱신
                        await last_message.edit(view=view)
                    except Exception as e:
                        logger.warning(f"등록 채널 {channel_id} 버튼 갱신/정리 실패: {str(e)}")
                else:
                    # 모든 메시지 삭제 후 새 버튼 메시지 전송
                    try:
                        async for message in channel.history(limit=50, oldest_first=False):
                            try:
                                await message.delete()
                            except Exception as e:
                                logger.warning(f"메시지 삭제 실패: {str(e)}")
                        await channel.send(
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

