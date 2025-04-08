import discord
from discord.ext import commands
from core.config import settings

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

# Cog 불러오기
@bot.event
async def on_ready():
    print(f"{bot.user} 접속 완료!")
    await bot.load_extension("cogs.party")

bot.run(settings.DISCORD_TOKEN)
