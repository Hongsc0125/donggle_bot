import discord
from discord.ext import commands
from database.session import get_database
from views.recruitment_card import RecruitmentCard

class PartyCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db = get_database()

    @commands.command(name="모집")
    async def recruit_party(self, ctx):
        dungeons_cursor = self.db["dungeons"].find({})
        dungeons = [doc async for doc in dungeons_cursor]
        dungeons.sort(key=lambda d: (d["type"], d["name"], d["difficulty"]))
        view = RecruitmentCard(dungeons)
        embed = view.get_embed()
        message = await ctx.send(embed=embed, view=view)
        view.message = message  # persistent 메시지 저장

async def setup(bot):
    await bot.add_cog(PartyCog(bot))
