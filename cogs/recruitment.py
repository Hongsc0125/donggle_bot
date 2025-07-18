import discord
import asyncio
from typing import List, Tuple
from discord.ext import commands
from discord import app_commands
import logging

from db.session import SessionLocal
from core.utils import interaction_response, interaction_followup
from queries.recruitment_query import select_recruitment_channel, select_recruitment, select_participants, select_active_recruitments, update_recruitment_message_id, select_list_channels, select_dungeon, select_max_person_setting
from views.recruitment_views.regist_templete import RecruitmentButtonView, RecruitmentFormView, _start_embed
from views.recruitment_views.list_templete import build_recruitment_embed, RecruitmentListButtonView, get_member_names

logger = logging.getLogger(__name__)
DungeonRow = Tuple[str, str, str]

class RecruitmentCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="등록", description="새로운 파티 모집을 등록합니다")
    async def register_recruitment(self, interaction: discord.Interaction):
        """파티 모집 등록 명령어 - 파티모집버튼과 동일한 기능"""
        try:
            # 파티모집버튼과 완전히 동일한 로직 사용
            db = SessionLocal()

            # 등록채널인지 여부 조회
            channel_id = interaction.channel_id
            regist_channel = select_recruitment_channel(db)
            if not any(int(row[0]) == channel_id for row in regist_channel):
                await interaction_response(interaction, "등록 채널이 아닙니다.", ephemeral=True)
                return

            rows: List[DungeonRow] = select_dungeon(db)
            max_person_settings = select_max_person_setting(db)
            db.close()

            form_view = RecruitmentFormView(rows, max_person_settings)
            await interaction.response.send_message(
                embed=_start_embed(), view=form_view, ephemeral=True
            )
            form_view.root_msg = await interaction.original_response()

        except Exception as e:
            logger.error(f"등록 명령어 처리 중 오류: {str(e)}")
            await interaction_response(interaction, "명령어 처리 중 오류가 발생했습니다.", ephemeral=True)

    @commands.Cog.listener()
    async def on_ready(self):
        logger.info("모집 시스템 초기화 시작...")
        # db = SessionLocal()
        with SessionLocal() as db:
            try:
                # 1. 모집중인 공고 목록 조회
                active_recruitments = select_active_recruitments(db)
                logger.info(f"활성 모집 공고 {len(active_recruitments)}개 로드됨")
                
                # 2. 등록채널 버튼 메시지 초기화
                regist_channel_ids = select_recruitment_channel(db)
                logger.info(f"등록 채널 {len(regist_channel_ids)}개 로드됨")
                
                for row in regist_channel_ids:
                    channel_id = int(row[0])
                    await self.initialize_registration_channel(channel_id)
                
                # 3. 리스트 채널 초기화
                # 모든 리스트 채널 조회
                list_channels = select_list_channels(db)
                logger.info(f"리스트 채널 {len(list_channels)}개 로드됨")
                
                # 모집 공고 수집 - 채널 별로 정리
                channel_messages = {}
                for recruitment in active_recruitments:
                    list_ch_id = int(recruitment['list_ch_id'])
                    if list_ch_id not in channel_messages:
                        channel_messages[list_ch_id] = []
                    channel_messages[list_ch_id].append(recruitment)
                
                # 채널별로 처리 (모든 리스트 채널 처리)
                for channel_id in list_channels:
                    ch_id = int(channel_id[0])
                    recruitments = channel_messages.get(ch_id, [])
                    logger.info(f"리스트 채널 {ch_id} 초기화 시작 (공고 {len(recruitments)}개)")
                    await self.initialize_list_channel(db, ch_id, recruitments)
                
                db.commit()
                logger.info("모든 채널 초기화 완료")
            except Exception as e:
                db.rollback()
                logger.error(f"채널 초기화 중 오류 발생: {str(e)}")

    async def initialize_registration_channel(self, channel_id):
        """등록 채널 초기화 - 버튼 메시지 설정"""
        channel = self.bot.get_channel(channel_id)
        if not channel:
            logger.warning(f"등록 채널 {channel_id}를 찾을 수 없습니다.")
            return
        
        logger.info(f"등록 채널 {channel_id} 초기화 시작")
        view = RecruitmentButtonView()

        instruction_embed = discord.Embed(
            title="**파티 모집 버튼을 눌러주세요!**",
            description="버튼이 동작을 안한다면 명령어를 입력해주세요.\n\n" +
            "> **모집 등록 명령어** \n"
            "> `/등록`\n\n" +
            "> **사용법**\n" +
            "> `/등록` 명령어를 입력한 후 절차에 따라 정보를 선택하세요.",
            color=discord.Color.from_rgb(178, 96, 255)
        ).set_thumbnail(url="https://harmari.duckdns.org/static/마비로고.png")

        last_message = None
        try:
            async for message in channel.history(limit=5, oldest_first=False):
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
            try:
                async for message in channel.history(limit=5, oldest_first=False):
                    if message.id != last_message.id and message.author.id == self.bot.user.id:
                        try:
                            await message.delete()
                        except Exception as e:
                            logger.warning(f"메시지 삭제 실패: {str(e)}")
                await last_message.edit(embed=instruction_embed, view=view)
                logger.info(f"등록 채널 {channel_id} 기존 버튼 메시지 업데이트 완료")
            except Exception as e:
                logger.warning(f"등록 채널 {channel_id} 버튼 갱신/정리 실패: {str(e)}")
        else:
            try:
                async for message in channel.history(limit=5, oldest_first=False):
                    if message.author.id == self.bot.user.id:
                        try:
                            await message.delete()
                        except Exception as e:
                            logger.warning(f"메시지 삭제 실패: {str(e)}")
                await channel.send(
                    embed=instruction_embed,
                    view=view
                )
                logger.info(f"등록 채널 {channel_id} 새 버튼 메시지 생성 완료")
            except Exception as e:
                logger.warning(f"등록 채널 {channel_id}에 버튼 메시지 전송 실패: {str(e)}")

    async def initialize_list_channel(self, db, channel_id, recruitments):
        """리스트 채널 초기화 - 모집 공고 업데이트 및 불필요 메시지 제거"""
        channel = self.bot.get_channel(channel_id)
        if not channel:
            logger.warning(f"리스트 채널 {channel_id}를 찾을 수 없습니다.")
            return
        
        # 기존 메시지 ID 목록 (유지할 메시지들)
        keep_message_ids = set()
        
        # 각 공고별로 메시지 처리
        for recruitment in recruitments:
            recru_id = recruitment['recru_id']
            message_id = recruitment['list_message_id']
            
            if not message_id:
                logger.warning(f"공고 {recru_id}의 메시지 ID가 없습니다.")
                continue
            
            keep_message_ids.add(int(message_id))
            
            # 참가자 목록 조회
            participants = select_participants(db, recru_id)
            
            # 닉네임 정보 수집
            recruiter_name, applicant_names = await get_member_names(
                channel.guild, 
                recruitment['create_user_id'], 
                participants
            )
            
            # 이미지 URL 설정
            if recruitment['dungeon_type'] in ['심층', '퀘스트']:
                image_url = f"https://harmari.duckdns.org/static/{recruitment['dungeon_type']}.png"
            elif recruitment['dungeon_type'] in ['레이드', '어비스']:
                image_url = f"https://harmari.duckdns.org/static/{recruitment['dungeon_name']}.png"
            else:
                image_url = "https://harmari.duckdns.org/static/마비로고.png"
            
            # 공고 임베드 생성
            embed = build_recruitment_embed(
                dungeon_type=recruitment['dungeon_type'],
                dungeon_name=recruitment['dungeon_name'],
                difficulty=recruitment['dungeon_difficulty'],
                detail=recruitment['recru_discript'],
                status=recruitment['status'],
                max_person=recruitment['max_person'],
                recruiter=recruitment['create_user_id'],
                applicants=participants,
                image_url=image_url,
                recru_id=recru_id,
                create_dt=recruitment['create_dt'],
                recruiter_name=recruiter_name,
                applicant_names=applicant_names
            )
            
            # 버튼 뷰 생성 - 상태에 따라 버튼 표시 여부 결정
            view = None
            if recruitment['status_code'] == 2:  # 모집중인 경우만 버튼 포함
                view = RecruitmentListButtonView(recru_id=recru_id)
            else:
                # 모집 완료/취소 상태일 때는 버튼 없는 뷰로 설정
                view = RecruitmentListButtonView(recru_id=recru_id)
                view.remove_all_buttons(recruitment['status_code'])
            
            # 메시지 찾아서 업데이트
            try:
                message = await channel.fetch_message(int(message_id))
                await message.edit(embed=embed, view=view)
                logger.info(f"공고 {recru_id} 메시지 업데이트 완료")
            except discord.NotFound:
                # 메시지를 찾을 수 없는 경우 새로 생성
                logger.warning(f"메시지 {message_id}를 찾을 수 없습니다. 새로 생성합니다.")
                new_message = await channel.send(embed=embed, view=view)
                
                # DB에 새 메시지 ID 업데이트
                update_result = update_recruitment_message_id(db, new_message.id, recru_id)
                if update_result:
                    keep_message_ids.add(new_message.id)
                    logger.info(f"공고 {recru_id} 메시지 ID 업데이트 완료: {new_message.id}")
                else:
                    logger.error(f"공고 {recru_id} 메시지 ID 업데이트 실패")
            except Exception as e:
                logger.error(f"공고 {recru_id} 메시지 업데이트 중 오류: {str(e)}")
        
        # 불필요한 메시지 삭제 (봇이 보낸 메시지 중 현재 모집과 관련 없는 메시지만)
        try:
            deleted_count = 0
            async for message in channel.history(limit=5):
                if message.id not in keep_message_ids and message.author.id == self.bot.user.id:
                    # 임베드 확인해서 모집 공고인지 확인 (푸터에 recruitment ID가 있는지)
                    is_recruitment = False
                    if message.embeds:
                        for embed in message.embeds:
                            if embed.footer and embed.footer.text and embed.footer.text.strip():
                                # 모집 ID 형식 - 숫자로만 이루어진 ID 또는 특정 패턴 확인
                                is_recruitment = True
                                break
                    
                    # 모집 공고로 보이지 않는 메시지만 삭제
                    if not is_recruitment:
                        try:
                            await message.delete()
                            deleted_count += 1
                        except Exception as e:
                            logger.warning(f"메시지 {message.id} 삭제 실패: {str(e)}")
            
            logger.info(f"리스트 채널 {channel_id}에서 불필요한 메시지 {deleted_count}개 삭제")
        except Exception as e:
            logger.error(f"채널 {channel_id} 메시지 정리 중 오류: {str(e)}")


# ───────────────────────────────────────────────
# Cog를 등록하는 설정 함수
# ───────────────────────────────────────────────
async def setup(bot):
    await bot.add_cog(RecruitmentCog(bot))

