import discord
from discord import app_commands
from discord.ext import commands
import aiohttp
import logging
import traceback
from core.config import settings

logger = logging.getLogger(__name__)

# 랭크 조회를 위한 모달 클래스
class RankModal(discord.ui.Modal, title='캐릭터 랭킹 조회'):
    server = discord.ui.TextInput(
        label='서버 이름',
        placeholder='예: 던컨',
        required=True,
        max_length=10
    )
    
    character = discord.ui.TextInput(
        label='캐릭터 이름',
        placeholder='정확한 캐릭터 이름을 입력하세요',
        required=True,
        max_length=30
    )
    
    async def on_submit(self, interaction: discord.Interaction):
        # 응답 지연 설정
        await interaction.response.defer(ephemeral=False)
        
        # 입력값 가져오기
        server = self.server.value
        character = self.character.value
        
        # API 요청 데이터 준비
        data = {
            "server": server,
            "character": character
        }
        
        try:
            # API 요청 보내기
            async with aiohttp.ClientSession() as session:
                async with session.post(settings.RANK_API_URL, json=data, timeout=10) as response:
                    if response.status != 200:
                        await interaction.followup.send(f"API 요청 실패: {response.status}")
                        return
                    
                    result = await response.json()
                    
                    if not result.get("success"):
                        error_msg = result.get('message', '알 수 없는 오류')
                        await interaction.followup.send(
                            f"데이터 조회 실패: {error_msg}\n\n" + 
                            "서버명과 캐릭터명을 정확하게 입력했는지 확인해주세요."
                        )
                        return
                    
                    # 캐릭터 정보 추출 및 키 매핑
                    character_info = result.get("character", {})
                    character_name = character_info.get("character") or character_info.get("character_name", "알 수 없음")
                    server_name = character_info.get("server") or character_info.get("server_name", "알 수 없음")
                    class_name = character_info.get("class") or character_info.get("class_name", "알 수 없음")
                    rank_position = character_info.get("rank") or character_info.get("rank_position", "알 수 없음")
                    power_value = character_info.get("power") or character_info.get("power_value", "알 수 없음")
                    change_amount = character_info.get("change") or character_info.get("change_amount", 0)
                    change_type = character_info.get("change_type", "none")
                    
                    # 순위 변동에 따른 색상 및 아이콘 결정
                    if change_type == "up":
                        embed_color = 0x57F287  # 초록색
                        change_emoji = "↑"
                        change_text = f"{change_emoji} {change_amount}"
                    elif change_type == "down":
                        embed_color = 0xED4245  # 빨간색
                        change_emoji = "↓"
                        change_text = f"{change_emoji} {change_amount}"
                    else:
                        embed_color = 0x95A5A6  # 회색
                        change_emoji = "-"
                        change_text = change_emoji
                    
                    # 임베드 생성
                    embed = discord.Embed(
                        title=f"🏆 {character_name}",
                        color=embed_color,
                        description=f"**클래스**: {class_name} \n **서버**: {server_name}",
                    )
                    
                    # 필드 추가
                    embed.add_field(name="🥇 랭킹", value=f"```{rank_position}```", inline=True)
                    embed.add_field(name="⚔️ 전투력", value=f"```{power_value}```", inline=True)
                    embed.add_field(name="📊 순위 변동", value=f"```{change_text}```", inline=True)
                    
                    # 캐시 정보
                    # if result.get("from_cache", False):
                    #     embed.set_footer(text=f"캐시된 정보: {result.get('message', '')}")
                    
                    # 메시지 전송
                    await interaction.followup.send(embed=embed)
        
        except aiohttp.ClientError as e:
            logger.error(f"API 요청 중 오류: {str(e)}")
            await interaction.followup.send(
                f"API 서버 연결 중 오류가 발생했습니다: {str(e)}\n" +
                "잠시 후 다시 시도해주세요."
            )
        except Exception as e:
            logger.error(f"처리 중 오류: {str(e)}\n{traceback.format_exc()}")
            await interaction.followup.send(
                f"데이터 처리 중 오류가 발생했습니다: {str(e)}\n" +
                "서버명과 캐릭터명을 정확하게 입력했는지 확인해주세요."
            )

class Rank(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        
    @app_commands.command(name="랭크", description="캐릭터의 랭킹 정보를 조회합니다")
    async def rank(self, interaction: discord.Interaction):
        # 모달 표시
        modal = RankModal()
        await interaction.response.send_modal(modal)

async def setup(bot):
    await bot.add_cog(Rank(bot))
