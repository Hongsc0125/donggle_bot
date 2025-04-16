import discord
from discord.ext import commands
from discord import app_commands
import logging
from datetime import datetime

from db.session import SessionLocal
from queries.channel_query import get_pair_channel, insert_pair_channel, insert_guild_auth, select_guild_auth

logger = logging.getLogger(__name__)

class ChannelCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="채널설정", description="등록, 리스트 채널을 설정하고 연결합니다.")
    @app_commands.describe(
        등록채널="등록채널을 선택",
        리스트채널="파티모집 리스트가 나올 채널을 선택"
    )
    async def pair_channels(
            self,
            interaction: discord.Interaction,
            등록채널: discord.TextChannel,
            리스트채널: discord.TextChannel
    ):
        await interaction.response.defer(ephemeral=True)

        try:
            db = SessionLocal()
            existing_pair = get_pair_channel(
                db, interaction.guild.id, 등록채널.id, 리스트채널.id
            )
            if existing_pair:
                await interaction.followup.send(
                    f"이미 설정된 채널입니다.\n"
                    f"등록 채널: {등록채널.mention}\n"
                    f"리스트 채널: {리스트채널.mention}",
                    ephemeral=True
                )
                db.close()
                return

            new_pair = insert_pair_channel(
                db, interaction.guild.id, 등록채널.id, 리스트채널.id
            )
            db.commit()

            await interaction.followup.send(f"등록채널 {등록채널.mention}, 리스트채널 {리스트채널.mention} 설정완료.", ephemeral=True)

        except Exception as e:
            logger.error(f"채널 페어링 중 오류 발생: {str(e)}")
            await interaction.followup.send(
                f"채널 설정 중 오류가 발생했습니다: {str(e)}",
                ephemeral=True
            )

    @app_commands.command(name="길드인증", description="길드를 인증합니다.")
    @app_commands.describe(
        유효기간="길드등록 유효기간 입력 (예: 20251231)",
    )
    async def auth_guild(
        self,
        interaction: discord.Interaction,
        유효기간: str
    ):
        await interaction.response.defer(ephemeral=True)
        if interaction.user.id != 307620267067179019:
            await interaction.followup.send(
                "이 명령어는 봇운영자만 사용할 수 있습니다.",
                ephemeral=True
            )
            return
        try:
            if not 유효기간:
                await interaction.followup.send("유효기간을 입력해주세요.", ephemeral=True)
                return
            expire_dt = datetime.strptime(유효기간, "%Y%m%d")

            db = SessionLocal()
            # --- select_guild_auth로 기존 만료일 체크 ---
            existing_count = select_guild_auth(db, interaction.guild.id, expire_dt)
            if existing_count and existing_count[0] > 0:
                await interaction.followup.send("이미 등록된 길드입니다.", ephemeral=True)
                db.close()
                return

            result = insert_guild_auth(
                db,
                interaction.guild.id,
                interaction.guild.name,
                expire_dt
            )
            db.commit()

            if result:
                await interaction.followup.send("길드 인증이 완료되었습니다.", ephemeral=True)
            else:
                await interaction.followup.send("길드 인증에 실패했습니다.", ephemeral=True)
        except Exception as e:
            logger.error(f"길드 인증 중 오류 발생: {str(e)}")
            await interaction.followup.send(
                f"길드 인증 중 오류가 발생했습니다: {str(e)}",
                ephemeral=True
            )

# Cog를 등록하는 설정 함수
async def setup(bot):
    await bot.add_cog(ChannelCog(bot))

