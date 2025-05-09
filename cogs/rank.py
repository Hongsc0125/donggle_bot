import discord
from discord import app_commands
from discord.ext import commands
import aiohttp
import logging
import traceback
from db.session import sessionmaker, rank_engine
from core.config import settings
from sqlalchemy import text
from views.rank_views.personal_rank_view import _build_rank_embed

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
        await interaction.response.defer(ephemeral=False, thinking=True)
        
        # 입력값 가져오기
        server = self.server.value
        character = self.character.value

        db_result = None
        try:
            RankSession = sessionmaker(autocommit=False, autoflush=False, bind=rank_engine)
            with RankSession() as db:
                # 데이터베이스에서 캐릭터 랭킹 정보 조회 15분 이내 갱신된 데이터만
                query = text("""
                    SELECT
                        character_name
                        , server_name
                        , class_name
                        , TO_CHAR(rank_position, 'FM999,999,999') || '위' AS rank_position
                        , TO_CHAR(power_value, 'FM999,999,999') AS power_value
                        , change_amount
                        , change_type
                    FROM mabinogi_ranking
                    WHERE server_name = :server 
                    AND character_name = :character
                    AND retrieved_at >= NOW() - INTERVAL '15 minutes'
                    ORDER BY retrieved_at DESC
                    LIMIT 1
                """)
                result = db.execute(query, {"server": server, "character": character})
                rank_data = result.fetchone()
                
                if rank_data:
                    # 데이터베이스에서 정보 찾음
                    logger.info(f"Found rank data in DB for {character} ({server})")
                    # SQLAlchemy Row 객체를 안전하게 딕셔너리로 변환
                    db_result = {column: value for column, value in rank_data._mapping.items()}
        except Exception as e:
            logger.error(f"Database query error: {str(e)}\n{traceback.format_exc()}")
        
        if db_result:
            # character_info = db_result.get("character", {}) # This line seems unused if fields are directly accessed
            character_name = db_result.get("character_name", "알 수 없음")
            server_name = db_result.get("server_name", "알 수 없음")
            class_name = db_result.get("class_name", "알 수 없음")
            rank_position = db_result.get("rank_position", "알 수 없음")
            power_value = db_result.get("power_value", "알 수 없음")
            change_amount = db_result.get("change_amount", 0)
            change_type = db_result.get("change_type", "none")

            embed = _build_rank_embed(
                character_name=character_name,
                server_name=server_name,
                class_name=class_name,
                rank_position=str(rank_position), 
                power_value=str(power_value),
                change_amount=int(change_amount),
                change_type=change_type,
                footer_text="정보는 거의 실시간 조회 중입니다.(약간의 오차가 있을 수 있음)"
            )

            # 메시지 전송
            await interaction.followup.send(embed=embed)
            return
        
        
        # API 요청 데이터 준비
        data = {
            "server": server,
            "character": character
        }
        
        try:
            # API 요청 보내기
            async with aiohttp.ClientSession() as session:
                # 타임아웃 값을 30초로 늘려서 API 응답 대기 시간 연장
                async with session.post(settings.RANK_API_URL, json=data, timeout=30) as response:
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
                    # Ensure change_amount is treated as int for logic, API might return string or int
                    raw_change_amount = character_info.get("change") or character_info.get("change_amount", 0)
                    try:
                        change_amount = int(raw_change_amount)
                    except ValueError:
                        change_amount = 0 # Default to 0 if conversion fails
                        logger.warning(f"Could not convert change_amount '{raw_change_amount}' to int. Defaulting to 0.")

                    change_type = character_info.get("change_type", "none")
                    
                    embed = _build_rank_embed(
                        character_name=character_name,
                        server_name=server_name,
                        class_name=class_name,
                        rank_position=str(rank_position), # Ensure string for display
                        power_value=str(power_value),     # Ensure string for display
                        change_amount=change_amount,      # Already int
                        change_type=change_type,
                        footer_text="정보는 거의 실시간 조회 중입니다.(약간의 오차가 있을 수 있음)"
                    )
                    
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
        try:
            # 모달 표시
            modal = RankModal()
            await interaction.response.send_modal(modal)
        except discord.errors.NotFound as e:
            # 상호작용이 이미 만료된 경우 처리
            if e.code == 10062:  # Unknown interaction
                logger.warning(f"상호작용이 만료되었습니다: {interaction.id}")
                # 여기서는 무시하거나 사용자에게 다시 시도하라는 메시지를 보낼 수 없음
                # 이미 상호작용이 만료되었기 때문
                pass
            else:
                # 다른 NotFound 오류는 로그에 기록
                logger.error(f"상호작용 오류: {str(e)}")
        except Exception as e:
            # 기타 예외 처리
            logger.error(f"랭크 명령어 처리 중 오류 발생: {str(e)}\n{traceback.format_exc()}")
            try:
                # 가능하다면 사용자에게 오류 메시지 전송
                await interaction.response.send_message("명령어 처리 중 오류가 발생했습니다. 나중에 다시 시도해주세요.", ephemeral=True)
            except:
                # 이미 응답했거나 상호작용이 만료된 경우 무시
                pass

async def setup(bot):
    await bot.add_cog(Rank(bot))
