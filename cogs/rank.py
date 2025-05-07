import discord
from discord import app_commands
from discord.ext import commands
import aiohttp
import logging
import traceback
import asyncio
from db.session import sessionmaker, rank_engine
from core.config import settings
from sqlalchemy import text
from core.utils import with_priority, execute_concurrently

logger = logging.getLogger(__name__)

# 랭크 요청을 위한 비동기 큐
rank_request_queue = asyncio.Queue()

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

        # 랭크 조회 요청을 큐에 추가
        await self.bot.get_cog("Rank").add_rank_request(server, character, interaction)

class Rank(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.rank_queue = asyncio.Queue()
        self.rank_workers = []
        self._start_rank_workers()
        self.api_semaphore = asyncio.Semaphore(5)  # API 동시 요청 제한
        self.db_semaphore = asyncio.Semaphore(10)  # DB 동시 연결 제한
        
    def _start_rank_workers(self):
        """랭크 조회 워커 시작"""
        for i in range(3):  # 3개의 워커 생성
            task = asyncio.create_task(self._rank_worker())
            self.rank_workers.append(task)
            logger.info(f"랭크 조회 워커 {i} 시작")
            
    async def _rank_worker(self):
        """랭크 조회 요청 처리 워커"""
        while True:
            try:
                # 큐에서 작업 가져오기
                task_data = await self.rank_queue.get()
                
                try:
                    # 작업 처리
                    server = task_data.get("server")
                    character = task_data.get("character")
                    interaction = task_data.get("interaction")
                    
                    # 먼저 DB 조회 시도
                    db_result = await self._fetch_from_db(server, character)
                    
                    if db_result:
                        await self._send_rank_embed(interaction, db_result)
                    else:
                        # DB에 없으면 API 조회
                        await self._fetch_from_api(server, character, interaction)
                        
                except Exception as e:
                    logger.error(f"랭크 작업 처리 중 오류: {str(e)}")
                    logger.error(traceback.format_exc())
                
                # 작업 완료 표시
                self.rank_queue.task_done()
                
            except asyncio.CancelledError:
                logger.info("랭크 조회 워커 종료")
                break
            except Exception as e:
                logger.error(f"랭크 조회 워커 오류: {str(e)}")
                await asyncio.sleep(1)  # 오류 발생 시 잠시 대기

    async def _fetch_from_db(self, server, character):
        """데이터베이스에서 랭크 정보 조회 (세마포어 적용)"""
        async with self.db_semaphore:
            try:
                RankSession = sessionmaker(autocommit=False, autoflush=False, bind=rank_engine)
                with RankSession() as db:
                    # 데이터베이스에서 캐릭터 랭킹 정보 조회 15분 이내 갱신된 데이터만
                    query = text("""
                        SELECT * FROM mabinogi_ranking 
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
                        return {column: value for column, value in rank_data._mapping.items()}
                    return None
            except Exception as e:
                logger.error(f"Database query error: {str(e)}\n{traceback.format_exc()}")
                return None

    async def _fetch_from_api(self, server, character, interaction):
        """API에서 랭크 정보 조회 (세마포어 적용)"""
        async with self.api_semaphore:
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
                        
                        # 임베드 생성 및 전송
                        await self._format_and_send_api_result(interaction, character_info)
            
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

    async def _send_rank_embed(self, interaction, db_result):
        """랭크 정보로 임베드 생성 및 전송"""
        character_info = db_result.get("character", {})
        character_name = db_result.get("character_name", "알 수 없음")
        server_name = db_result.get("server_name", "알 수 없음")
        class_name = db_result.get("class_name", "알 수 없음")
        rank_position = db_result.get("rank_position", "알 수 없음")
        power_value = db_result.get("power_value", "알 수 없음")
        change_amount = db_result.get("change_amount", 0)
        change_type = db_result.get("change_type", "none")

        # 순위 변동에 따른 색상 및 아이콘 결정
        if change_amount == 0:
            embed_color = 0x95A5A6  # 회색
            change_emoji = "-"
            change_text = change_emoji
        elif change_type == "up":
            embed_color = 0x57F287  # 초록색
            change_emoji = "↑"
            change_text = f"{change_emoji} {change_amount}"
        elif change_type == "down":
            embed_color = 0xED4245  # 빨간색
            change_emoji = "↓"
            change_text = f"{change_emoji} {change_amount}"

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

        embed.set_footer(text="정보는 실시간으로 업데이트 되지 않을 수 있습니다. 거의 실시간 조회 중입니다.")

        # 메시지 전송
        await interaction.followup.send(embed=embed)

    async def _format_and_send_api_result(self, interaction, character_info):
        """API 응답으로 임베드 생성 및 전송"""
        character_name = character_info.get("character") or character_info.get("character_name", "알 수 없음")
        server_name = character_info.get("server") or character_info.get("server_name", "알 수 없음")
        class_name = character_info.get("class") or character_info.get("class_name", "알 수 없음")
        rank_position = character_info.get("rank") or character_info.get("rank_position", "알 수 없음")
        power_value = character_info.get("power") or character_info.get("power_value", "알 수 없음")
        change_amount = character_info.get("change") or character_info.get("change_amount", 0)
        change_type = character_info.get("change_type", "none")

        # 순위 변동에 따른 색상 및 아이콘 결정
        if change_amount == 0:
            embed_color = 0x95A5A6  # 회색
            change_emoji = "-"
            change_text = change_emoji
        elif change_type == "up":
            embed_color = 0x57F287  # 초록색
            change_emoji = "↑"
            change_text = f"{change_emoji} {change_amount}"
        elif change_type == "down":
            embed_color = 0xED4245  # 빨간색
            change_emoji = "↓"
            change_text = f"{change_emoji} {change_amount}"

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

        embed.set_footer(text="정보는 실시간으로 업데이트 되지 않습니다.")

        # 메시지 전송
        await interaction.followup.send(embed=embed)

    @app_commands.command(name="랭크", description="캐릭터의 랭킹 정보를 조회합니다")
    @with_priority(0)  # 높은 우선순위
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

    async def add_rank_request(self, server, character, interaction):
        """랭크 조회 요청을 큐에 추가"""
        await self.rank_queue.put({
            "server": server,
            "character": character,
            "interaction": interaction
        })

async def setup(bot):
    await bot.add_cog(Rank(bot))
