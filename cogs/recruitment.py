import discord
import asyncio
from discord.ext import commands
from discord import app_commands
import logging

from db.session import SessionLocal
from core.utils import interaction_response, interaction_followup
from queries.recruitment_query import select_recruitment_channel, select_recruitment, select_participants, select_active_recruitments, update_recruitment_message_id, select_list_channels
from views.recruitment_views.regist_templete import RecruitmentButtonView
from views.recruitment_views.list_templete import build_recruitment_embed, RecruitmentListButtonView

logger = logging.getLogger(__name__)

class RecruitmentCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

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
        last_message = None
        try:
            async for message in channel.history(limit=50, oldest_first=False):
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
                async for message in channel.history(limit=50, oldest_first=False):
                    if message.id != last_message.id and message.author.id == self.bot.user.id:
                        try:
                            await message.delete()
                        except Exception as e:
                            logger.warning(f"메시지 삭제 실패: {str(e)}")
                await last_message.edit(view=view)
                logger.info(f"등록 채널 {channel_id} 기존 버튼 메시지 업데이트 완료")
            except Exception as e:
                logger.warning(f"등록 채널 {channel_id} 버튼 갱신/정리 실패: {str(e)}")
        else:
            try:
                async for message in channel.history(limit=50, oldest_first=False):
                    if message.author.id == self.bot.user.id:
                        try:
                            await message.delete()
                        except Exception as e:
                            logger.warning(f"메시지 삭제 실패: {str(e)}")
                await channel.send(
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
            
            # 이미지 URL 설정
            if recruitment['dungeon_type'] in ['레이드', '심층', '퀘스트']:
                image_url = f"https://harmari.duckdns.org/static/{recruitment['dungeon_type']}.png"
            elif recruitment['dungeon_type'] == '어비스':
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
                create_dt=recruitment['create_dt']
            )
            
            # 메시지 찾아서 업데이트
            try:
                message = await channel.fetch_message(int(message_id))
                await message.edit(embed=embed, view=RecruitmentListButtonView(recru_id=recru_id))
                logger.info(f"공고 {recru_id} 메시지 업데이트 완료")
            except discord.NotFound:
                # 메시지를 찾을 수 없는 경우 새로 생성
                logger.warning(f"메시지 {message_id}를 찾을 수 없습니다. 새로 생성합니다.")
                new_message = await channel.send(embed=embed, view=RecruitmentListButtonView(recru_id=recru_id))
                
                # DB에 새 메시지 ID 업데이트
                update_result = update_recruitment_message_id(db, new_message.id, recru_id)
                if update_result:
                    keep_message_ids.add(new_message.id)
                    logger.info(f"공고 {recru_id} 메시지 ID 업데이트 완료: {new_message.id}")
                else:
                    logger.error(f"공고 {recru_id} 메시지 ID 업데이트 실패")
            except Exception as e:
                logger.error(f"공고 {recru_id} 메시지 업데이트 중 오류: {str(e)}")
        
        # 불필요한 메시지 삭제
        try:
            deleted_count = 0
            async for message in channel.history(limit=100):
                if message.id not in keep_message_ids and message.author.id == self.bot.user.id:
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

