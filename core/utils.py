import discord
from discord.ext import commands
import asyncio
import logging


logger = logging.getLogger(__name__)

# 2초 후 삭제되는 ephemeral 메시지 전송
async def interaction_response(interaction: discord.Interaction, message: str, ephemeral: bool = True):
    try:
        if ephemeral:
            msg = await interaction.response.send_message(message, ephemeral=True)
            # await asyncio.sleep(2)
            # await msg.delete()
    except discord.HTTPException as e:
        logger.error(f"Interaction response error: {e}")

# 2초 후 삭제되는 ephemeral followup 메시지 전송
async def interaction_followup(interaction: discord.Interaction, message: str, ephemeral: bool = True):
    try:
        if ephemeral:
            msg = await interaction.followup.send(message, ephemeral=True)
            # await asyncio.sleep(2)
            # await msg.delete()
    except discord.HTTPException as e:
        logger.error(f"Interaction followup error: {e}")