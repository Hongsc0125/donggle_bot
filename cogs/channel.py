import discord
from discord.ext import commands
from discord import app_commands


class pair_channel_set(commands.Cog):
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
            채널1: discord.TextChannel,
            채널2: discord.TextChannel
    ):
        await interaction.response.defer(ephemeral=True)

        try:

