import logging

import discord
from discord.ext import commands, tasks
from core.config import settings

logger = logging.getLogger("donggle")

# intents 설정 = 전체
intents = discord.Intents.all()

# bot 초기화
bot = commands.Bot(command_prefix="/", intents=intents)

@bot.event
async def on_ready():
    logger.info(f"Logged in as {bot.user} (ID: {bot.user.id})")
    logger.info("------")

@bot.command(name="테스트")
async def test(ctx):
    await ctx.send("안녕?")

bot.run(settings.DISCORD_TOKEN)