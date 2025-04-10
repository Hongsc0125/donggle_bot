from discord.ext import commands, tasks
from database.session import get_database
from views.recruitment_card import RecruitmentCard
from core.config import settings
import discord
from discord import app_commands
from typing import Union, Any
import asyncio
from datetime import datetime
from bson.objectid import ObjectId
import uuid
import aiosqlite
import logging
import traceback
import time
import psutil

# 로깅 설정
logger = logging.getLogger('donggle_bot.party')

# AppCommandChannel 대신 사용할 타입 정의
class AppCommandChannel:
    id: str
    
    def __init__(self, id):
        self.id = id

# 도움말 명령어를 위한 도움말 데이터
HELP_DATA = {
    "모집": {
        "명령어": "/모집",
        "설명": "모집 등록 채널을 안내합니다. 실제 모집은 지정된 모집 등록 채널에서 진행됩니다.",
        "사용법": "/모집",
        "권한": "모든 사용자"
    },
    "모집채널설정": {
        "명령어": "/모집채널설정 [채널]",
        "설명": "모집 공고가 게시될 채널을 설정합니다. 채널을 지정하지 않으면 선택 메뉴가 표시됩니다.",
        "사용법": "/모집채널설정 또는 /모집채널설정 #채널명",
        "권한": "관리자"
    },
    "모집등록채널설정": {
        "명령어": "/모집등록채널설정 [채널]",
        "설명": "모집 등록 양식이 표시될 채널을 설정합니다. 채널을 지정하지 않으면 선택 메뉴가 표시됩니다.",
        "사용법": "/모집등록채널설정 또는 /모집등록채널설정 #채널명",
        "권한": "관리자"
    },
    "채널페어설정": {
        "명령어": "/채널페어설정 [등록채널] [공고채널]",
        "설명": "등록 채널과 공고 채널을 페어링하여, 특정 등록 채널에서 등록된 모집이 특정 공고 채널에만 표시되도록 설정합니다.",
        "사용법": "/채널페어설정 #등록채널 #공고채널",
        "권한": "관리자"
    },
    "채널페어삭제": {
        "명령어": "/채널페어삭제 [등록채널]",
        "설명": "등록 채널과 공고 채널의 페어링을 삭제합니다.",
        "사용법": "/채널페어삭제 #등록채널",
        "권한": "관리자"
    },
    "채널페어목록": {
        "명령어": "/채널페어목록",
        "설명": "설정된 채널 페어 목록을 확인합니다.",
        "사용법": "/채널페어목록",
        "권한": "관리자"
    },
    "동글_도움말": {
        "명령어": "/동글_도움말",
        "설명": "동글봇의 명령어 목록과 사용법을 보여줍니다.",
        "사용법": "/동글_도움말",
        "권한": "모든 사용자"
    }
}

# 채널 설정을 위한 View 클래스 추가
class ChannelSetupView(discord.ui.View):
    def __init__(self, cog, setup_type):
        super().__init__(timeout=None)
        self.cog = cog
        self.setup_type = setup_type  # "announcement" 또는 "registration"
        
        # 채널 선택 메뉴 추가
        self.channel_select = discord.ui.ChannelSelect(
            placeholder="채널을 선택하세요",
            channel_types=[discord.ChannelType.text],
            min_values=1,
            max_values=1,
            row=0
        )
        self.channel_select.callback = self.channel_select_callback
        self.add_item(self.channel_select)
    
    async def channel_select_callback(self, interaction: discord.Interaction):
        """
        채널 선택 콜백 - 사용자가 선택한 채널을 처리합니다.
        채널 타입에 따라 적절한 채널 설정 함수를 호출합니다.
        """
        await interaction.response.defer(ephemeral=True)
        
        # 선택된 채널
        selected_channel = self.channel_select.values[0]
        
        # 채널 유형에 따라 설정 함수 호출
        if self.setup_type == "announcement":
            await self.cog.set_announcement_channel_internal(interaction, selected_channel)
        elif self.setup_type == "registration":
            await self.cog.set_registration_channel_internal(interaction, selected_channel)
        else:
            await interaction.followup.send("알 수 없는 채널 유형입니다.", ephemeral=True)

class PartyCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db = get_database()
        self.announcement_channels = {}  # 서버별 공고 채널 ID 저장 딕셔너리
        self.registration_channels = {}  # 서버별 등록 채널 ID 저장 딕셔너리
        self.channel_pairs = {}  # 서버별 채널 페어 관계 저장 딕셔너리 (등록 채널 ID -> 공고 채널 ID)
        self.registration_locked = False  # 모집 등록 잠금 상태 (5초간)
        self.dungeons = []  # 던전 목록 추가
        self._load_settings_sync()
        self.cleanup_channel.start()  # 채널 정리 작업 시작
        self.recruiting_dict = {}  # 모집 정보를 저장할 딕셔너리
        self.initialization_retries = {}  # 채널 초기화 재시도 카운터

    def _load_settings_sync(self):
        """초기 설정을 동기적으로 로드합니다."""
        try:
            # 초기에는 채널 ID를 빈 딕셔너리로 설정
            self.announcement_channels = {}
            self.registration_channels = {}
            # bot.py가 실행될 때 설정을 로드하기 위해 비동기적으로 설정을 로드하는 작업을 봇 루프에 추가
            self.bot.loop.create_task(self._load_settings_async())
            # 던전 목록 로드 작업 추가
            self.bot.loop.create_task(self._load_dungeons_async())
        except Exception as e:
            logger.error(f"설정 로드 중 오류 발생: {e}")
            logger.error(traceback.format_exc())

    async def _load_channel_id(self, channel_type: str) -> dict:
        """데이터베이스에서 서버별 채널 ID를 로드합니다."""
        try:
            # 모든 서버의 설정 정보 가져오기
            all_settings = await self.db["settings"].find({}).to_list(length=None)
            
            # 서버별 채널 ID를 저장할 딕셔너리
            channel_ids = {}
            
            for settings in all_settings:
                # guild_id가 있는 설정만 처리
                if "guild_id" not in settings:
                    continue
                
                guild_id = settings["guild_id"]
                
                # 채널 유형에 따라 채널 ID 저장
                if channel_type == "announcement" and "announcement_channel_id" in settings:
                    channel_ids[guild_id] = settings["announcement_channel_id"]
                elif channel_type == "registration" and "registration_channel_id" in settings:
                    channel_ids[guild_id] = settings["registration_channel_id"]
            
            logger.info(f"{channel_type} 채널 ID를 로드했습니다: {channel_ids}")
            return channel_ids
            
        except Exception as e:
            logger.error(f"{channel_type} 채널 ID 로드 중 오류 발생: {e}")
            logger.error(traceback.format_exc())
            return {}

    async def _load_settings_async(self):
        """채널 설정을 로드하고 초기화합니다."""
        try:
            logger.info("채널 설정 로드 시작")
            
            # 채널 ID 로드
            self.announcement_channels = await self._load_channel_id("announcement")
            self.registration_channels = await self._load_channel_id("registration")
            
            # 채널 페어 관계 로드
            await self._load_channel_pairs()
            
            logger.info(f"모집 공고 채널 ID 목록을 로드했습니다: {self.announcement_channels}")
            logger.info(f"모집 등록 채널 ID 목록을 로드했습니다: {self.registration_channels}")
            logger.info(f"채널 페어 관계를 로드했습니다: {self.channel_pairs}")
            
            # 각 서버별로 등록 채널 초기화
            for guild_id, channel_id in self.registration_channels.items():
                try:
                    logger.info(f"서버 {guild_id}의 등록 채널 초기화 시작: {channel_id}")
                    
                    # 서버 객체 가져오기
                    guild = self.bot.get_guild(int(guild_id))
                    if not guild:
                        logger.error(f"서버를 찾을 수 없음: {guild_id}")
                        continue
                    
                    # 채널 객체 가져오기
                    registration_channel = guild.get_channel(int(channel_id))
                    if registration_channel:
                        # 채널 알림 설정 변경
                        await registration_channel.edit(
                            default_auto_archive_duration=10080,  # 7일
                            default_thread_auto_archive_duration=10080  # 7일
                        )
                        
                        # 기존 메시지 삭제
                        await registration_channel.purge(limit=None)
                        
                        # 새 등록 양식 생성
                        await self.create_registration_form(registration_channel)
                        logger.info(f"서버 {guild_id}의 등록 채널 초기화 완료")
                    else:
                        logger.error(f"서버 {guild_id}의 등록 채널을 찾을 수 없음: {channel_id}")
                except Exception as e:
                    logger.error(f"서버 {guild_id}의 등록 채널 초기화 중 오류 발생: {e}")
                    logger.error(traceback.format_exc())
            
            # 각 서버별로 공고 채널 초기화
            for guild_id, channel_id in self.announcement_channels.items():
                try:
                    logger.info(f"서버 {guild_id}의 공고 채널 초기화 시작: {channel_id}")
                    
                    # 서버 객체 가져오기
                    guild = self.bot.get_guild(int(guild_id))
                    if not guild:
                        logger.error(f"서버를 찾을 수 없음: {guild_id}")
                        continue
                    
                    # 채널 객체 가져오기
                    announcement_channel = guild.get_channel(int(channel_id))
                    if announcement_channel:
                        # 채널 알림 설정 변경
                        await announcement_channel.edit(
                            default_auto_archive_duration=10080,  # 7일
                            default_thread_auto_archive_duration=10080  # 7일
                        )
                        logger.info(f"서버 {guild_id}의 공고 채널 초기화 완료")
                    else:
                        logger.error(f"서버 {guild_id}의 공고 채널을 찾을 수 없음: {channel_id}")
                except Exception as e:
                    logger.error(f"서버 {guild_id}의 공고 채널 초기화 중 오류 발생: {e}")
                    logger.error(traceback.format_exc())
            
        except Exception as e:
            logger.error(f"채널 설정 로드 중 오류 발생: {e}")
            logger.error(traceback.format_exc())

    async def _load_dungeons_async(self):
        """데이터베이스에서 던전 목록을 비동기적으로 로드합니다."""
        try:
            logger.info("던전 목록 로드 시작")
            # 던전 목록 가져오기
            dungeons_cursor = self.db["dungeons"].find({})
            self.dungeons = [doc async for doc in dungeons_cursor]
            self.dungeons.sort(key=lambda d: (d["type"], d["name"], d["difficulty"]))
            logger.info(f"던전 목록 로드 완료: {len(self.dungeons)}개 던전 로드됨")
        except Exception as e:
            logger.error(f"던전 목록 로드 중 오류 발생: {str(e)}")
            logger.error(traceback.format_exc())

    async def _load_channel_pairs(self):
        """데이터베이스에서 서버별 채널 페어 관계를 로드합니다."""
        try:
            # 모든 서버의 설정 정보 가져오기
            all_settings = await self.db["settings"].find({}).to_list(length=None)
            
            # 서버별 채널 페어 관계를 저장할 딕셔너리
            self.channel_pairs = {}
            
            for settings in all_settings:
                # guild_id가 있는 설정만 처리
                if "guild_id" not in settings:
                    continue
                
                guild_id = settings["guild_id"]
                
                # 채널 페어 정보가 있는 경우 저장
                if "channel_pairs" in settings:
                    self.channel_pairs[guild_id] = settings["channel_pairs"]
                else:
                    self.channel_pairs[guild_id] = {}
            
        except Exception as e:
            logger.error(f"채널 페어 관계 로드 중 오류 발생: {e}")
            logger.error(traceback.format_exc())
            self.channel_pairs = {}

    @commands.Cog.listener()
    async def on_ready(self):
        """봇이 준비되면 저장된 뷰 상태를 복원하고 채널을 초기화합니다."""
        try:
            logger.info("봇 초기화 시작")
            
            # 뷰 상태 복원 수행
            await self._restore_views()
            
            # 채널 초기화 수행
            await self.initialize_channels()
            
            logger.info("봇 초기화 완료")
            
        except Exception as e:
            logger.error(f"봇 초기화 중 오류 발생: {e}")
            logger.error(traceback.format_exc())
            
    async def _restore_views(self):
        """저장된 뷰 상태를 복원합니다."""
        try:
            logger.info("뷰 상태 복원 시작")
            
            # 저장된 모든 뷰 상태 가져오기
            view_states = await self.db["view_states"].find({}).to_list(length=None)
            
            for state in view_states:
                try:
                    # 채널과 메시지 가져오기
                    channel = self.bot.get_channel(int(state["channel_id"]))
                    if not channel:
                        logger.warning(f"채널을 찾을 수 없음: {state['channel_id']}")
                        continue
                        
                    try:
                        message = await channel.fetch_message(int(state["message_id"]))
                    except discord.NotFound:
                        # 메시지를 찾을 수 없는 경우 뷰 상태 삭제
                        logger.warning(f"메시지를 찾을 수 없음: {state['message_id']}")
                        await self.db["view_states"].delete_one({"message_id": state["message_id"]})
                        continue
                    
                    # 메시지의 임베드가 모집 등록 양식인지 확인
                    if not message.embeds or not message.embeds[0].title or "파티 모집 등록 양식" in message.embeds[0].title:
                        logger.debug(f"모집 등록 양식 메시지 건너뛰기: {message.id}")
                        continue
                    
                    # 뷰 복원
                    view = RecruitmentCard(self.dungeons, self.db)
                    view.is_recreated = True  # 재활성화 표시
                    view.message = message
                    view.selected_type = state.get("selected_type")
                    view.selected_kind = state.get("selected_kind")
                    view.selected_diff = state.get("selected_diff")
                    view.recruitment_content = state.get("recruitment_content")
                    view.max_participants = state.get("max_participants", 4)
                    view.status = state.get("status", "active")
                    view.recruitment_id = state.get("recruitment_id")
                    
                    # 참가자 목록 변환 (문자열 ID -> 정수 ID)
                    try:
                        participants = state.get("participants", [])
                        view.participants = [int(p) for p in participants]
                    except ValueError:
                        logger.warning(f"참가자 ID 변환 중 오류: {participants}")
                        view.participants = []
                    
                    try:
                        view.creator_id = int(state.get("creator_id", 0))
                    except ValueError:
                        logger.warning(f"생성자 ID 변환 중 오류: {state.get('creator_id')}")
                        view.creator_id = 0
                    
                    # 모든 기존 항목 제거
                    view.clear_items()
                    
                    # 참가하기 버튼 추가 (row 0)
                    join_button = discord.ui.Button(label="참가하기", style=discord.ButtonStyle.success, custom_id="btn_join", row=0)
                    join_button.callback = view.btn_join_callback
                    view.add_item(join_button)
                    
                    # 신청 취소 버튼 추가 (row 0)
                    cancel_button = discord.ui.Button(label="신청 취소", style=discord.ButtonStyle.danger, custom_id="btn_cancel", row=0)
                    cancel_button.callback = view.btn_cancel_callback
                    view.add_item(cancel_button)
                    
                    # 모집 생성자에게만 모집 취소 버튼 표시 (row 1)
                    if view.creator_id:
                        delete_button = discord.ui.Button(label="모집 취소", style=discord.ButtonStyle.danger, custom_id="btn_delete", row=1)
                        delete_button.callback = view.btn_delete_callback
                        view.add_item(delete_button)
                    
                    # 임베드 생성
                    embed = view.get_embed()
                    embed.title = "파티 모집 공고"
                    
                    # 뷰 업데이트
                    await message.edit(embed=embed, view=view)
                    logger.info(f"뷰 상태 복원 완료: {state['message_id']}")
                    
                except Exception as e:
                    logger.error(f"뷰 상태 복원 중 오류 발생: {e}")
                    logger.error(traceback.format_exc())
                    continue
            
            logger.info("뷰 상태 복원 완료")
            
        except Exception as e:
            logger.error(f"뷰 상태 복원 중 오류 발생: {e}")
            logger.error(traceback.format_exc())
            
    async def initialize_channels(self, force_retry=False):
        """채널을 초기화합니다."""
        try:
            logger.info("채널 초기화 시작")
            
            # 채널 ID가 없으면 로드
            if not self.registration_channels or not self.announcement_channels:
                self.registration_channels = await self._load_channel_id("registration")
                self.announcement_channels = await self._load_channel_id("announcement")
            
            # 서버별 초기화 재시도 딕셔너리 초기화 (강제 재시도 시)
            if force_retry:
                self.initialization_retries = {}
            
            # 각 서버의 등록 채널 초기화
            for guild_id, channel_id in self.registration_channels.items():
                try:
                    # 초기화 재시도 횟수 추적
                    if guild_id not in self.initialization_retries:
                        self.initialization_retries[guild_id] = {"registration": 0, "announcement": 0}
                    
                    logger.info(f"서버 {guild_id}의 모집 등록 채널 초기화 중: {channel_id} (재시도: {self.initialization_retries[guild_id]['registration']}회)")
                    
                    # 서버 객체 가져오기
                    guild = self.bot.get_guild(int(guild_id))
                    if not guild:
                        logger.error(f"서버를 찾을 수 없음: {guild_id}")
                        self.initialization_retries[guild_id]["registration"] += 1
                        continue
                        
                    # 채널 객체 가져오기
                    registration_channel = guild.get_channel(int(channel_id))
                    if registration_channel:
                        try:
                            # 채널 알림 설정 변경
                            await registration_channel.edit(
                                default_auto_archive_duration=10080,  # 7일
                                default_thread_auto_archive_duration=10080  # 7일
                            )
                            
                            # 기존 메시지 삭제
                            await registration_channel.purge(limit=None)
                            
                            # 새 등록 양식 생성
                            await self.create_registration_form(registration_channel)
                            logger.info(f"서버 {guild_id}의 모집 등록 채널 초기화 완료")
                            
                            # 성공하면 재시도 카운터 초기화
                            self.initialization_retries[guild_id]["registration"] = 0
                            
                        except discord.Forbidden:
                            logger.error(f"서버 {guild_id}의 모집 등록 채널 초기화 권한 부족: {channel_id}")
                            self.initialization_retries[guild_id]["registration"] += 1
                        except Exception as e:
                            logger.error(f"서버 {guild_id}의 모집 등록 채널 초기화 중 오류 발생: {e}")
                            logger.error(traceback.format_exc())
                            self.initialization_retries[guild_id]["registration"] += 1
                    else:
                        logger.error(f"서버 {guild_id}의 모집 등록 채널을 찾을 수 없음: {channel_id}")
                        self.initialization_retries[guild_id]["registration"] += 1
                except Exception as e:
                    logger.error(f"서버 {guild_id}의 모집 등록 채널 초기화 중 오류 발생: {e}")
                    logger.error(traceback.format_exc())
                    self.initialization_retries[guild_id]["registration"] += 1
            
            # 각 서버의 공고 채널 초기화
            for guild_id, channel_id in self.announcement_channels.items():
                try:
                    # 초기화 재시도 횟수 추적
                    if guild_id not in self.initialization_retries:
                        self.initialization_retries[guild_id] = {"registration": 0, "announcement": 0}
                        
                    logger.info(f"서버 {guild_id}의 공고 채널 초기화 중: {channel_id} (재시도: {self.initialization_retries[guild_id]['announcement']}회)")
                    
                    # 서버 객체 가져오기
                    guild = self.bot.get_guild(int(guild_id))
                    if not guild:
                        logger.error(f"서버를 찾을 수 없음: {guild_id}")
                        self.initialization_retries[guild_id]["announcement"] += 1
                        continue
                        
                    # 채널 객체 가져오기
                    announcement_channel = guild.get_channel(int(channel_id))
                    if announcement_channel:
                        try:
                            # 채널 알림 설정 변경
                            await announcement_channel.edit(
                                default_auto_archive_duration=10080,  # 7일
                                default_thread_auto_archive_duration=10080  # 7일
                            )
                            
                            # DB에서 해당 서버의 활성 상태인 모집 정보 불러오기
                            active_recruitments = await self.db["recruitments"].find(
                                {"guild_id": guild_id, "status": "active"}
                            ).sort("created_at", -1).to_list(length=None)
                            
                            logger.info(f"서버 {guild_id}의 활성 모집 {len(active_recruitments)}개를 불러왔습니다.")
                            
                            # 먼저 완료된 모집 메시지 삭제 (강제 정리 수행)
                            try:
                                logger.info(f"서버 {guild_id}의 완료된 모집 메시지 삭제를 시도합니다.")
                                await self.force_cleanup_channel(guild_id, channel_id)
                            except Exception as cleanup_error:
                                logger.error(f"서버 {guild_id}의 완료된 모집 메시지 삭제 중 오류 발생: {cleanup_error}")
                                logger.error(traceback.format_exc())
                            
                            # 채널의 모든 메시지 가져오기
                            channel_messages = {}
                            async for message in announcement_channel.history(limit=100):
                                channel_messages[message.id] = message
                            
                            # 각 모집에 대해 처리
                            for recruitment in active_recruitments:
                                try:
                                    recruitment_id = str(recruitment["_id"])
                                    message_id = recruitment.get("announcement_message_id")
                                    
                                    if message_id and int(message_id) in channel_messages:
                                        # 기존 메시지가 있으면 상호작용만 다시 등록
                                        message = channel_messages[int(message_id)]
                                        view = RecruitmentCard(self.dungeons, self.db)
                                        view.is_recreated = True  # 재활성화 표시
                                        view.message = message
                                        view.selected_type = recruitment.get("type")
                                        view.selected_kind = recruitment.get("dungeon")
                                        view.selected_diff = recruitment.get("difficulty")
                                        view.recruitment_content = recruitment.get("description")
                                        view.max_participants = recruitment.get("max_participants", 4)
                                        view.status = recruitment.get("status", "active")
                                        view.recruitment_id = recruitment_id
                                        
                                        # 참가자 목록 변환 (문자열 ID -> 정수 ID)
                                        try:
                                            participants = recruitment.get("participants", [])
                                            view.participants = [int(p) for p in participants]
                                        except ValueError:
                                            logger.warning(f"참가자 ID 변환 중 오류: {participants}")
                                            view.participants = []
                                        
                                        try:
                                            view.creator_id = int(recruitment.get("creator_id", 0))
                                        except ValueError:
                                            logger.warning(f"생성자 ID 변환 중 오류: {recruitment.get('creator_id')}")
                                            view.creator_id = 0
                                        
                                        # 모든 기존 항목 제거
                                        view.clear_items()
                                        
                                        # 참가하기 버튼 추가 (row 0)
                                        join_button = discord.ui.Button(label="참가하기", style=discord.ButtonStyle.success, custom_id="btn_join", row=0)
                                        join_button.callback = view.btn_join_callback
                                        view.add_item(join_button)
                                        
                                        # 신청 취소 버튼 추가 (row 0)
                                        cancel_button = discord.ui.Button(label="신청 취소", style=discord.ButtonStyle.danger, custom_id="btn_cancel", row=0)
                                        cancel_button.callback = view.btn_cancel_callback
                                        view.add_item(cancel_button)
                                        
                                        # 모집 생성자에게만 모집 취소 버튼 표시 (row 1)
                                        if view.creator_id:
                                            delete_button = discord.ui.Button(label="모집 취소", style=discord.ButtonStyle.danger, custom_id="btn_delete", row=1)
                                            delete_button.callback = view.btn_delete_callback
                                            view.add_item(delete_button)
                                        
                                        # 임베드 생성
                                        embed = view.get_embed()
                                        embed.title = "파티 모집 공고"
                                        
                                        # 뷰 업데이트
                                        await message.edit(embed=embed, view=view)
                                        logger.info(f"서버 {guild_id}의 모집 ID {recruitment_id}의 상호작용을 다시 등록했습니다.")
                                    else:
                                        # 메시지가 없으면 새로 생성
                                        view = RecruitmentCard(self.dungeons, self.db)
                                        view.is_recreated = True  # 재활성화 표시
                                        view.selected_type = recruitment.get("type")
                                        view.selected_kind = recruitment.get("dungeon")
                                        view.selected_diff = recruitment.get("difficulty")
                                        view.recruitment_content = recruitment.get("description")
                                        view.max_participants = recruitment.get("max_participants", 4)
                                        view.status = recruitment.get("status", "active")
                                        view.recruitment_id = recruitment_id
                                        
                                        # 참가자 목록 변환 (문자열 ID -> 정수 ID)
                                        try:
                                            participants = recruitment.get("participants", [])
                                            view.participants = [int(p) for p in participants]
                                        except ValueError:
                                            logger.warning(f"참가자 ID 변환 중 오류: {participants}")
                                            view.participants = []
                                        
                                        try:
                                            view.creator_id = int(recruitment.get("creator_id", 0))
                                        except ValueError:
                                            logger.warning(f"생성자 ID 변환 중 오류: {recruitment.get('creator_id')}")
                                            view.creator_id = 0
                                        
                                        # 공고 임베드 생성 - 복제된 뷰 사용
                                        announcement_view = RecruitmentCard(self.dungeons, self.db)
                                        announcement_view.selected_type = view.selected_type
                                        announcement_view.selected_kind = view.selected_kind
                                        announcement_view.selected_diff = view.selected_diff
                                        announcement_view.recruitment_content = view.recruitment_content
                                        announcement_view.max_participants = view.max_participants
                                        announcement_view.status = view.status
                                        announcement_view.recruitment_id = view.recruitment_id
                                        announcement_view.participants = view.participants.copy() if view.participants else []
                                        announcement_view.creator_id = view.creator_id
                                        announcement_view.is_recreated = True  # 재활성화 표시
                                        
                                        # 모든 기존 항목 제거
                                        announcement_view.clear_items()
                                        
                                        # 참가하기 버튼 추가 (row 0)
                                        join_button = discord.ui.Button(label="참가하기", style=discord.ButtonStyle.success, custom_id="btn_join", row=0)
                                        join_button.callback = announcement_view.btn_join_callback
                                        announcement_view.add_item(join_button)
                                        
                                        # 신청 취소 버튼 추가 (row 0)
                                        cancel_button = discord.ui.Button(label="신청 취소", style=discord.ButtonStyle.danger, custom_id="btn_cancel", row=0)
                                        cancel_button.callback = announcement_view.btn_cancel_callback
                                        announcement_view.add_item(cancel_button)
                                        
                                        # 모집 생성자에게만 모집 취소 버튼 표시 (row 1)
                                        if view.creator_id:
                                            delete_button = discord.ui.Button(label="모집 취소", style=discord.ButtonStyle.danger, custom_id="btn_delete", row=1)
                                            delete_button.callback = announcement_view.btn_delete_callback
                                            announcement_view.add_item(delete_button)
                                        
                                        # 임베드 생성
                                        embed = announcement_view.get_embed()
                                        embed.title = "파티 모집 공고"
                                        
                                        # 메시지 생성
                                        message = await announcement_channel.send(embed=embed, view=announcement_view)
                                        announcement_view.message = message
                                        
                                        # 메시지 ID 업데이트
                                        await self.db["recruitments"].update_one(
                                            {"_id": ObjectId(recruitment_id)},
                                            {"$set": {
                                                "announcement_message_id": str(message.id),
                                                "announcement_channel_id": str(channel.id),
                                                "guild_id": guild_id,
                                                "updated_at": datetime.now().isoformat()
                                            }}
                                        )
                                        logger.info(f"서버 {guild_id}의 모집 ID {recruitment_id}의 메시지를 새로 생성했습니다.")
                                        
                                except Exception as e:
                                    logger.error(f"서버 {guild_id}의 모집 공고 처리 중 오류 발생: {e}")
                                    logger.error(traceback.format_exc())
                                    continue
                            
                            logger.info(f"서버 {guild_id}의 공고 채널 초기화 완료: {len(active_recruitments)}개 모집 공고 처리됨")
                            
                            # 성공하면 재시도 카운터 초기화
                            self.initialization_retries[guild_id]["announcement"] = 0
                            
                        except discord.Forbidden:
                            logger.error(f"서버 {guild_id}의 공고 채널 초기화 권한 부족: {channel_id}")
                            self.initialization_retries[guild_id]["announcement"] += 1
                        except Exception as e:
                            logger.error(f"서버 {guild_id}의 공고 채널 초기화 중 오류 발생: {e}")
                            logger.error(traceback.format_exc())
                            self.initialization_retries[guild_id]["announcement"] += 1
                    else:
                        logger.error(f"서버 {guild_id}의 공고 채널을 찾을 수 없음: {channel_id}")
                        self.initialization_retries[guild_id]["announcement"] += 1
                except Exception as e:
                    logger.error(f"서버 {guild_id}의 공고 채널 초기화 중 오류 발생: {e}")
                    logger.error(traceback.format_exc())
                    self.initialization_retries[guild_id]["announcement"] += 1
            
            # 초기화 실패한 서버가 있으면 5초 후 재시도 예약
            failed_servers = {guild_id: retries for guild_id, retries in self.initialization_retries.items() 
                             if retries["registration"] > 0 or retries["announcement"] > 0}
            
            if failed_servers:
                # 최대 10회까지만 재시도
                for guild_id, retries in failed_servers.items():
                    if retries["registration"] <= 10 or retries["announcement"] <= 10:
                        logger.warning(f"서버 {guild_id}의 채널 초기화 실패. 5초 후 재시도합니다. (등록: {retries['registration']}회, 공고: {retries['announcement']}회)")
                        # 5초 후 재시도 예약
                        self.bot.loop.create_task(self._retry_initialization(5))
                        break
            
            logger.info("채널 초기화 완료")
        except Exception as e:
            logger.error(f"채널 초기화 중 오류 발생: {e}")
            logger.error(traceback.format_exc())
            # 오류 발생 시 5초 후 재시도 예약
            self.bot.loop.create_task(self._retry_initialization(5))

    async def _retry_initialization(self, delay_seconds=5):
        """지정된 지연 시간 후 채널 초기화를 다시 시도합니다."""
        await asyncio.sleep(delay_seconds)
        logger.info(f"{delay_seconds}초 지연 후 채널 초기화 재시도 중...")
        await self.initialize_channels()

    @commands.Cog.listener()
    async def on_message(self, message):
        """메시지 수신 이벤트 처리"""
        # 봇 메시지 무시
        if message.author.bot:
            return
            
        # 서버 ID 확인
        if not hasattr(message, 'guild') or not message.guild:
            return
            
        guild_id = str(message.guild.id)
            
        # 공고 채널인지 확인
        if guild_id in self.announcement_channels and str(message.channel.id) == self.announcement_channels[guild_id]:
            try:
                await message.delete()
            except Exception as e:
                logger.error(f"공고 채널 메시지 삭제 중 오류: {e}")
            return
            
        # 등록 채널인지 확인
        if guild_id in self.registration_channels and str(message.channel.id) == self.registration_channels[guild_id]:
            try:
                await message.delete()
            except Exception as e:
                logger.error(f"등록 채널 메시지 삭제 중 오류: {e}")
            return

    async def create_registration_form(self, channel):
        """모집 등록 채널에 빈 양식을 생성합니다."""
        # 던전 목록 가져오기
        dungeons_cursor = self.db["dungeons"].find({})
        dungeons = [doc async for doc in dungeons_cursor]
        dungeons.sort(key=lambda d: (d["type"], d["name"], d["difficulty"]))
        
        # 서버 ID 가져오기
        guild_id = str(channel.guild.id)
        
        # 현재 채널 ID를 설정에 저장
        await self.db["settings"].update_one(
            {"guild_id": guild_id},
            {"$set": {"registration_channel_id": str(channel.id)}},
            upsert=True
        )
        
        # 메모리에도 설정 저장
        self.registration_channels[guild_id] = str(channel.id)
        
        # 해당 등록 채널에 페어링된 공고 채널이 없으면 기본 공고 채널로 설정
        if guild_id not in self.channel_pairs:
            self.channel_pairs[guild_id] = {}
        
        if str(channel.id) not in self.channel_pairs[guild_id] and guild_id in self.announcement_channels:
            # 페어가 없는 경우 기본값으로 설정하지 않음 (NULL 상태 유지)
            logger.info(f"서버 {guild_id}의 등록 채널 {channel.id}에 페어링된 공고 채널이 없습니다.")
        
        # 등록 양식 생성
        view = RecruitmentCard(dungeons, self.db)
        # 등록 채널 ID 저장 (추후 공고 채널 결정에 사용)
        view.registration_channel_id = str(channel.id)
        embed = view.get_embed()
        embed.title = "파티 모집 등록 양식"
        
        # 등록 잠금 상태이면 안내 메시지 수정 및 버튼 비활성화
        if self.registration_locked:
            embed.description = "잠시 후 모집 등록이 가능합니다. 5초만 기다려주세요."
            # 모든 버튼과 선택 메뉴 비활성화
            for item in view.children:
                item.disabled = True
        else:
            embed.description = (
                "아래 순서대로 양식을 작성해주세요:\n\n"
                "1. **던전 유형** 선택: 일반/레이드/기타 중 선택\n"
                "2. **던전 종류** 선택: 선택한 유형에 맞는 던전 선택\n"
                "3. **난이도** 선택: 선택한 던전의 난이도 선택\n"
                "4. **모집 내용** 입력: 파티 모집에 대한 상세 내용 작성\n"
                "5. **최대 인원** 설정: 파티 모집 인원 수 설정\n\n"
                "모든 항목을 작성한 후 '모집 등록' 버튼을 클릭하세요."
            )
        
        # 양식 전송
        message = await channel.send(embed=embed, view=view)
        view.message = message  # persistent 메시지 저장
        self.registration_message = message
        
        return message

    async def post_recruitment_announcement(self, guild_id, recruitment_data, view):
        """모집 공고를 모집 공고 채널에 게시합니다."""
        guild_id = str(guild_id)
        
        # 서버별 공고 채널 ID 가져오기
        if not self.announcement_channels or guild_id not in self.announcement_channels:
            # 공고 채널이 설정되지 않았으면 종료
            logger.error(f"서버 {guild_id}의 모집 공고 채널이 설정되지 않았습니다.")
            return None
        
        try:
            # 채널 가져오기
            guild = self.bot.get_guild(int(guild_id))
            if not guild:
                logger.error(f"길드를 찾을 수 없음: {guild_id}")
                return None
            
            # 등록 채널 ID 확인 (어떤 등록 채널에서 모집이 등록되었는지)
            registration_channel_id = str(view.registration_channel_id) if hasattr(view, 'registration_channel_id') else None
            
            # 등록 정보에 등록 채널 ID 없는 경우 recruitment_data에서 확인
            if not registration_channel_id and recruitment_data and "registration_channel_id" in recruitment_data:
                registration_channel_id = str(recruitment_data["registration_channel_id"])
            
            # 등록된 채널 ID 없는 경우 모집 정보에서 확인
            if not registration_channel_id:
                recruitment_id = str(view.recruitment_id)
                if recruitment_id:
                    recruitment = await self.db["recruitments"].find_one({"_id": ObjectId(recruitment_id)})
                    if recruitment and "registration_channel_id" in recruitment:
                        registration_channel_id = str(recruitment["registration_channel_id"])
            
            # 등록 채널에 페어링된 공고 채널 확인
            target_channel_id = None
            
            if registration_channel_id and guild_id in self.channel_pairs and registration_channel_id in self.channel_pairs[guild_id]:
                # 페어링된 공고 채널이 있으면 해당 채널 사용
                target_channel_id = self.channel_pairs[guild_id][registration_channel_id]
                logger.info(f"서버 {guild_id}의 등록 채널 {registration_channel_id}에 페어링된 공고 채널 {target_channel_id} 사용")
            else:
                # 페어링된 공고 채널이 없으면 기본 공고 채널 사용
                target_channel_id = self.announcement_channels[guild_id]
                logger.info(f"서버 {guild_id}의 등록 채널 {registration_channel_id}에 페어링된 공고 채널이 없어 기본 채널 {target_channel_id} 사용")
            
            # 채널 객체 가져오기
            channel = guild.get_channel(int(target_channel_id))
            if not channel:
                logger.error(f"서버 {guild_id}의 대상 채널을 찾을 수 없음: {target_channel_id}")
                # 대체 채널로 기본 공고 채널 사용
                channel = guild.get_channel(int(self.announcement_channels[guild_id]))
                if not channel:
                    logger.error(f"서버 {guild_id}의 기본 공고 채널도 찾을 수 없음: {self.announcement_channels[guild_id]}")
                    return None

            # 모집 ID 확인
            recruitment_id = str(view.recruitment_id)
            if not recruitment_id:
                logger.error("모집 ID가 없습니다.")
                return None
                
            # 기존 공고 확인
            existing_message = None
            recruitment = await self.db["recruitments"].find_one({"_id": ObjectId(recruitment_id)})
            
            if recruitment and "announcement_message_id" in recruitment and "announcement_channel_id" in recruitment:
                try:
                    if str(channel.id) == recruitment["announcement_channel_id"]:
                        existing_message = await channel.fetch_message(int(recruitment["announcement_message_id"]))
                        logger.info(f"서버 {guild_id}의 기존 모집 공고를 찾았습니다: {recruitment['announcement_message_id']}")
                except discord.NotFound:
                    logger.info(f"서버 {guild_id}의 기존 모집 공고를 찾을 수 없습니다: {recruitment.get('announcement_message_id')}")
                except Exception as e:
                    logger.error(f"서버 {guild_id}의 기존 모집 공고 조회 중 오류: {e}")
            
            # 공고 임베드 생성 - 복제된 뷰 사용
            announcement_view = RecruitmentCard(self.dungeons, self.db)
            announcement_view.selected_type = view.selected_type
            announcement_view.selected_kind = view.selected_kind
            announcement_view.selected_diff = view.selected_diff
            announcement_view.recruitment_content = view.recruitment_content
            announcement_view.max_participants = view.max_participants
            announcement_view.status = view.status
            announcement_view.recruitment_id = view.recruitment_id
            announcement_view.participants = view.participants.copy() if view.participants else []
            announcement_view.creator_id = view.creator_id
            # 등록 채널 정보 복사
            if hasattr(view, 'registration_channel_id'):
                announcement_view.registration_channel_id = view.registration_channel_id
            
            # 모든 기존 항목 제거
            announcement_view.clear_items()
            
            # 참가하기 버튼 추가 (row 0)
            join_button = discord.ui.Button(label="참가하기", style=discord.ButtonStyle.success, custom_id="btn_join", row=0)
            join_button.callback = announcement_view.btn_join_callback
            announcement_view.add_item(join_button)
            
            # 신청 취소 버튼 추가 (row 0)
            cancel_button = discord.ui.Button(label="신청 취소", style=discord.ButtonStyle.danger, custom_id="btn_cancel", row=0)
            cancel_button.callback = announcement_view.btn_cancel_callback
            announcement_view.add_item(cancel_button)
            
            # 모집 생성자에게만 모집 취소 버튼 표시 (row 1)
            if view.creator_id:
                delete_button = discord.ui.Button(label="모집 취소", style=discord.ButtonStyle.danger, custom_id="btn_delete", row=1)
                delete_button.callback = announcement_view.btn_delete_callback
                announcement_view.add_item(delete_button)
            
            # 임베드 생성
            embed = announcement_view.get_embed()
            embed.title = "파티 모집 공고"
            
            message = None
            
            # 기존 메시지가 있으면 업데이트, 없으면 새로 생성
            if existing_message:
                try:
                    await existing_message.edit(embed=embed, view=announcement_view)
                    message = existing_message
                    logger.info(f"서버 {guild_id}의 기존 모집 공고를 업데이트했습니다: {existing_message.id}")
                except Exception as e:
                    logger.error(f"서버 {guild_id}의 모집 공고 업데이트 중 오류: {e}")
                    # 업데이트 실패 시 기존 메시지 삭제 후 새로 생성
                    try:
                        await existing_message.delete()
                    except:
                        pass
                    message = await channel.send(embed=embed, view=announcement_view, silent=True)
                    logger.info(f"서버 {guild_id}의 모집 공고를 새로 생성했습니다: {message.id}")
            else:
                # 기존 메시지가 없으면 새로 생성
                message = await channel.send(embed=embed, view=announcement_view, silent=True)
                logger.info(f"서버 {guild_id}의 모집 공고를 새로 생성했습니다: {message.id}")
            
            # 뷰에 메시지 저장
            announcement_view.message = message

            # 뷰 상태를 데이터베이스에 저장
            view_state = {
                "message_id": str(message.id),
                "channel_id": str(channel.id),
                "guild_id": str(guild_id),
                "recruitment_id": str(view.recruitment_id),
                "selected_type": view.selected_type,
                "selected_kind": view.selected_kind, 
                "selected_diff": view.selected_diff,
                "recruitment_content": view.recruitment_content,
                "max_participants": view.max_participants,
                "status": view.status,
                "participants": [str(p) for p in view.participants] if view.participants else [],
                "creator_id": str(view.creator_id) if view.creator_id else None,
                "registration_channel_id": registration_channel_id,
                "updated_at": datetime.now().isoformat()
            }
            
            await self.db["view_states"].update_one(
                {"message_id": str(message.id)},
                {"$set": view_state},
                upsert=True
            )
            
            # DB에 메시지 ID와 채널 ID 업데이트
            await self.db["recruitments"].update_one(
                {"_id": ObjectId(view.recruitment_id)},
                {"$set": {
                    "announcement_message_id": str(message.id),
                    "announcement_channel_id": str(channel.id),
                    "registration_channel_id": registration_channel_id,
                    "guild_id": str(guild_id),
                    "updated_at": datetime.now().isoformat()
                }}
            )
            
            logger.info(f"서버 {guild_id}의 모집 공고 게시 완료: {view.recruitment_id}")
            return message
        except Exception as e:
            logger.error(f"서버 {guild_id}의 모집 공고 게시 중 오류 발생: {e}")
            logger.error(traceback.format_exc())
            return None

    @app_commands.command(name="동글_도움말", description="동글봇 도움말을 보여줍니다.")
    @app_commands.checks.has_permissions(administrator=True)
    async def dongle_help(self, interaction: discord.Interaction):
        """동글봇 도움말 명령어 - 관리자 전용"""
        try:
            embed = discord.Embed(
                title="동글봇 파티 모집 도움말",
                description="동글봇 파티 모집 기능에 대한 도움말입니다.",
                color=discord.Color.blue()
            )
            
            embed.add_field(
                name="/모집채널설정",
                value="모집 공고가 게시될 채널을 설정합니다. (관리자 전용)",
                inline=False
            )
            
            embed.add_field(
                name="/모집등록채널설정",
                value="모집 등록 양식이 게시될 채널을 설정합니다. (관리자 전용)",
                inline=False
            )
            
            embed.add_field(
                name="/모집초기화",
                value="모집 등록 채널을 초기화합니다. (관리자 전용)",
                inline=False
            )
            
            embed.add_field(
                name="/채널페어설정",
                value="등록 채널과 공고 채널을 페어링하여, 특정 등록 채널에서 등록된 모집이 특정 공고 채널에만 표시되도록 설정합니다. (관리자 전용)",
                inline=False
            )
            
            embed.add_field(
                name="/채널페어삭제",
                value="등록 채널과 공고 채널의 페어링을 삭제합니다. (관리자 전용)",
                inline=False
            )
            
            embed.add_field(
                name="/채널페어목록",
                value="설정된 채널 페어 목록을 확인합니다. (관리자 전용)",
                inline=False
            )
            
            await interaction.response.send_message(embed=embed, ephemeral=True)
            
        except discord.app_commands.errors.MissingPermissions:
            await interaction.response.send_message("이 명령어는 관리자만 사용할 수 있습니다.", ephemeral=True)
        except Exception as e:
            logger.error(f"도움말 표시 중 오류 발생: {e}")
            logger.error(traceback.format_exc())
            if not interaction.response.is_done():
                await interaction.response.send_message("도움말을 표시하는 중 오류가 발생했습니다.", ephemeral=True)

    def cog_unload(self):
        """Cog가 언로드될 때 정리 작업 수행"""
        # 작업 취소
        self.cleanup_channel.cancel()
        self.keep_alive.cancel()  # 새로 추가된 작업 취소
        logger.info("Party cog unloaded")

    @tasks.loop(minutes=5)  # 5분마다 실행
    async def keep_alive(self):
        """봇의 상태를 체크하고 로그를 기록하는 메서드"""
        try:
            logger.info("봇 상태 체크 중...")
            
            # 봇이 연결되어 있는지 확인
            if not self.bot.is_ready():
                logger.warning("봇이 준비되지 않았습니다. 준비될 때까지 대기합니다.")
                await self.bot.wait_until_ready()
                logger.info("봇이 준비되었습니다.")
            
            # 서버 수 확인
            guild_count = len(self.bot.guilds)
            logger.info(f"현재 {guild_count}개의 서버에 연결되어 있습니다.")
            
            # 모집 채널 상태 확인
            registration_channel_count = len(self.registration_channels)
            announcement_channel_count = len(self.announcement_channels)
            logger.info(f"모집 등록 채널: {registration_channel_count}개, 모집 공고 채널: {announcement_channel_count}개")
            
            # 활성 모집 수 확인
            active_recruitments_count = await self.db["recruitments"].count_documents({"status": "active"})
            logger.info(f"활성 모집: {active_recruitments_count}개")
            
            # 메모리 사용량 체크
            process = psutil.Process()
            memory_usage = process.memory_info().rss / 1024 / 1024  # MB 단위
            logger.info(f"현재 메모리 사용량: {memory_usage:.2f} MB")
            
            # 초기화가 필요한 서버 확인 및 처리
            failed_servers = {guild_id: retries for guild_id, retries in self.initialization_retries.items() 
                             if retries["registration"] > 0 or retries["announcement"] > 0}
            
            if failed_servers:
                logger.warning(f"{len(failed_servers)}개의 서버에서 초기화가 필요합니다. 초기화를 시도합니다.")
                await self.initialize_channels(force_retry=True)
            
            logger.info("봇 상태 체크 완료")
            
        except Exception as e:
            logger.error(f"keep_alive 작업 중 오류 발생: {e}")
            logger.error(traceback.format_exc())

    @keep_alive.before_loop
    async def before_keep_alive(self):
        """keep_alive 작업 시작 전 실행되는 메서드"""
        logger.debug("봇 상태 체크 작업 준비 중...")
        await self.bot.wait_until_ready()  # 봇이 준비될 때까지 대기
        logger.debug("봇 상태 체크 작업 시작")

    @tasks.loop(minutes=1)  # 1분마다 실행
    async def cleanup_channel(self):
        """채널 정리 작업"""
        try:
            if not self.announcement_channels:
                return
                
            # 각 서버별로 채널 정리 수행
            for guild_id, channel_id in self.announcement_channels.items():
                try:
                    logger.debug(f"서버 {guild_id}의 채널 정리 작업 시작")
                    
                    # 각 서버별로 force_cleanup_channel 호출
                    try:
                        await self.force_cleanup_channel(guild_id, channel_id)
                    except Exception as e:
                        logger.error(f"서버 {guild_id}의 강제 정리 중 오류 발생: {e}")
                        logger.error(traceback.format_exc())
                    
                except Exception as e:
                    logger.error(f"서버 {guild_id}의 채널 정리 중 오류 발생: {e}")
                    logger.error(traceback.format_exc())
                    continue
            
        except Exception as e:
            logger.error(f"채널 정리 중 오류 발생: {e}")
            logger.error(traceback.format_exc())

    @cleanup_channel.before_loop
    async def before_cleanup_channel(self):
        """채널 정리 작업 시작 전 실행되는 메서드"""
        logger.debug("채널 정리 작업 준비 중...")
        await self.bot.wait_until_ready()  # 봇이 준비될 때까지 대기
        logger.debug("채널 정리 작업 시작")

    async def force_cleanup_channel(self, guild_id, channel_id):
        """특정 채널의 완료된 모집 메시지를 강제로 삭제합니다."""
        try:
            # 서버 객체 가져오기
            guild = self.bot.get_guild(int(guild_id))
            if not guild:
                logger.warning(f"서버를 찾을 수 없음: {guild_id}")
                return
            
            # 채널 객체 가져오기
            channel = guild.get_channel(int(channel_id))
            if not channel:
                logger.warning(f"서버 {guild_id}의 공고 채널을 찾을 수 없음: {channel_id}")
                return
            
            # 서버별 모집 정보 조회
            recruitments = await self.db.recruitments.find({"guild_id": guild_id}).to_list(None)
            
            # 모집 ID와 상태 매핑 생성
            recruitment_status_map = {}
            recruitment_message_map = {}
            message_recruitment_map = {}
            
            # 모집 정보 정리
            for recruitment in recruitments:
                recruitment_id = str(recruitment.get('_id'))
                status = recruitment.get('status', 'unknown')
                recruitment_status_map[recruitment_id] = status
                
                # 공고 메시지 ID가 있으면 매핑에 추가
                if "announcement_message_id" in recruitment:
                    message_id = recruitment["announcement_message_id"]
                    recruitment_message_map[recruitment_id] = message_id
                    message_recruitment_map[message_id] = recruitment_id
            
            logger.debug(f"서버 {guild_id}에서 {len(recruitments)}개의 모집을 찾았습니다.")
            
            # 활성 모집 ID 목록 생성
            active_recruitment_ids = set()
            completed_recruitment_ids = set()
            cancelled_recruitment_ids = set()
            
            for recruitment_id, status in recruitment_status_map.items():
                if status == 'active':
                    active_recruitment_ids.add(recruitment_id)
                elif status == 'complete':
                    completed_recruitment_ids.add(recruitment_id)
                elif status == 'cancelled':
                    cancelled_recruitment_ids.add(recruitment_id)
            
            logger.debug(f"서버 {guild_id} - 활성 모집: {len(active_recruitment_ids)}개, 완료된 모집: {len(completed_recruitment_ids)}개, 취소된 모집: {len(cancelled_recruitment_ids)}개")
            
            # 채널에 있는 메시지 ID를 모집 ID와 매핑
            channel_message_recruitment_map = {}
            
            # 채널의 메시지 확인
            async for message in channel.history(limit=100):  # 최근 100개 메시지만 확인
                try:
                    # 메시지가 임베드를 가지고 있는지 확인
                    if not message.embeds:
                        continue
        
                    # 임베드에서 모집 ID 찾기
                    recruitment_id = None
                    
                    # 임베드의 푸터에서 모집 ID 찾기
                    if message.embeds[0].footer and message.embeds[0].footer.text:
                        footer_text = message.embeds[0].footer.text
                        if footer_text.startswith("모집 ID:"):
                            recruitment_id = footer_text.replace("모집 ID:", "").strip()
                            if " | " in recruitment_id:
                                recruitment_id = recruitment_id.split(" | ")[0].strip()
                    
                    # 임베드의 필드에서 모집 ID 찾기 (이전 방식 호환)
                    if not recruitment_id:
                        for field in message.embeds[0].fields:
                            if field.name == "모집 ID":
                                recruitment_id = field.value
                                break
        
                    if recruitment_id:
                        channel_message_recruitment_map[str(message.id)] = recruitment_id
                        
                        # 활성 모집에 대한 메시지 매핑 업데이트
                        if recruitment_id in active_recruitment_ids:
                            # DB에 메시지 ID 업데이트 (기존 정보가 없을 경우)
                            if recruitment_id not in recruitment_message_map or recruitment_message_map[recruitment_id] != str(message.id):
                                await self.db["recruitments"].update_one(
                                    {"_id": ObjectId(recruitment_id)},
                                    {"$set": {
                                        "announcement_message_id": str(message.id),
                                        "announcement_channel_id": str(channel.id),
                                        "guild_id": guild_id,
                                        "updated_at": datetime.now().isoformat()
                                    }}
                                )
                                logger.info(f"서버 {guild_id}에서 발견된 활성 모집 {recruitment_id}의 메시지 ID를 업데이트했습니다: {message.id}")
        
                except Exception as e:
                    logger.error(f"메시지 처리 중 오류 발생: {e}")
                    logger.error(traceback.format_exc())
                    continue
            
            # 활성 모집 중 메시지가 없는 경우 새로 게시
            active_recruitments_to_post = []
            for recruitment_id in active_recruitment_ids:
                # 채널 내 메시지에서 해당 모집 ID를 찾지 못한 경우
                if not any(r_id == recruitment_id for r_id in channel_message_recruitment_map.values()):
                    # 해당 모집 데이터 찾기
                    recruitment = next((r for r in recruitments if str(r.get('_id')) == recruitment_id), None)
                    if recruitment:
                        active_recruitments_to_post.append(recruitment)
            
            # 누락된 활성 모집 공고 게시
            for recruitment in active_recruitments_to_post:
                try:
                    recruitment_id = str(recruitment.get('_id'))
                    logger.info(f"서버 {guild_id}의 누락된 모집 공고 재게시: {recruitment_id}")
                    
                    # 모집 데이터로 뷰 생성
                    view = RecruitmentCard(self.dungeons, self.db)
                    view.recruitment_id = recruitment_id
                    view.selected_type = recruitment.get("type", "")
                    view.selected_kind = recruitment.get("dungeon", "")
                    view.selected_diff = recruitment.get("difficulty", "")
                    view.recruitment_content = recruitment.get("description", "")
                    view.max_participants = recruitment.get("max_participants", 4)
                    view.status = recruitment.get("status", "active")
                    
                    # 참가자 목록 변환
                    try:
                        participants = recruitment.get("participants", [])
                        view.participants = [int(p) for p in participants]
                    except ValueError:
                        logger.warning(f"참가자 ID 변환 중 오류: {participants}")
                        view.participants = []
                    
                    try:
                        view.creator_id = int(recruitment.get("creator_id", 0))
                    except ValueError:
                        logger.warning(f"생성자 ID 변환 중 오류: {recruitment.get('creator_id')}")
                        view.creator_id = 0
                    
                    # 공고 게시
                    await self.post_recruitment_announcement(guild_id, recruitment, view)
                    
                except Exception as e:
                    logger.error(f"모집 공고 재게시 중 오류 발생: {e}")
                    logger.error(traceback.format_exc())
            
            # 중복된 활성 모집 공고 찾기
            duplicate_messages = {}
            
            # 활성 모집 ID별로 채널 내 메시지 집계
            for message_id, recruitment_id in channel_message_recruitment_map.items():
                if recruitment_id in active_recruitment_ids:
                    if recruitment_id not in duplicate_messages:
                        duplicate_messages[recruitment_id] = []
                    duplicate_messages[recruitment_id].append(message_id)
            
            # 모집 ID별로 2개 이상의 메시지가 있으면 가장 최근 것을 제외하고 삭제
            for recruitment_id, message_ids in duplicate_messages.items():
                if len(message_ids) > 1:
                    logger.info(f"서버 {guild_id}의 모집 ID {recruitment_id}에 대한 중복 메시지 발견: {len(message_ids)}개")
                    # 메시지 ID를 정수로 변환하여 정렬 (최신 메시지가 큰 ID 값을 가짐)
                    sorted_message_ids = sorted([int(mid) for mid in message_ids], reverse=True)
                    # 가장 최신 메시지를 제외한 나머지 삭제
                    for message_id in sorted_message_ids[1:]:
                        try:
                            message = await channel.fetch_message(message_id)
                            await message.delete()
                            logger.info(f"서버 {guild_id}의 중복 메시지 삭제: {message_id}")
                        except Exception as e:
                            logger.error(f"중복 메시지 삭제 중 오류: {e}")
            
            # 완료되거나 취소된 모집의 메시지 삭제
            deleted_count = 0
            async for message in channel.history(limit=100):
                try:
                    # 메시지가 임베드를 가지고 있는지 확인
                    if not message.embeds:
                        continue
        
                    # 임베드에서 모집 ID 찾기
                    recruitment_id = None
                    if message.embeds[0].footer and message.embeds[0].footer.text:
                        footer_text = message.embeds[0].footer.text
                        if footer_text.startswith("모집 ID:"):
                            recruitment_id = footer_text.replace("모집 ID:", "").strip()
                            if " | " in recruitment_id:
                                recruitment_id = recruitment_id.split(" | ")[0].strip()
                    
                    # 임베드의 필드에서 모집 ID 찾기 (이전 방식 호환)
                    if not recruitment_id:
                        for field in message.embeds[0].fields:
                            if field.name == "모집 ID":
                                recruitment_id = field.value
                                break
        
                    if recruitment_id:
                        status = recruitment_status_map.get(recruitment_id, "unknown")
                        
                        # 완료되거나 취소된 모집의 메시지만 삭제
                        if status in ["complete", "cancelled"]:
                            logger.info(f"서버 {guild_id}의 모집 ID {recruitment_id}의 상태가 {status}이므로 메시지를 삭제합니다.")
                            await message.delete()
                            deleted_count += 1
                        elif status == "active":
                            logger.debug(f"서버 {guild_id}의 모집 ID {recruitment_id}는 아직 활성 상태입니다.")
                        elif recruitment_id not in recruitment_status_map:
                            # 데이터베이스에 없는 모집의 메시지는 삭제
                            logger.info(f"서버 {guild_id}의 모집 ID {recruitment_id}가 데이터베이스에 존재하지 않아 메시지를 삭제합니다.")
                            await message.delete()
                            deleted_count += 1
                        else:
                            logger.debug(f"서버 {guild_id}의 모집 ID {recruitment_id}의 상태가 {status}로 처리되지 않았습니다.")
        
                except Exception as e:
                    logger.error(f"메시지 처리 중 오류 발생: {e}")
                    logger.error(traceback.format_exc())
                    continue
            
            logger.debug(f"서버 {guild_id}의 채널 정리 완료: {deleted_count}개의 메시지가 삭제되었습니다.")
        
        except Exception as e:
            logger.error(f"강제 채널 정리 중 오류 발생: {e}")
            logger.error(traceback.format_exc())

    @app_commands.command(name="모집채널설정", description="모집 공고를 게시할 채널을 설정합니다.")
    @app_commands.checks.has_permissions(administrator=True)
    async def set_announcement_channel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        """모집 공고 채널 설정 명령어 - 관리자 전용"""
        try:
            await interaction.response.defer(ephemeral=True)
            await self.set_announcement_channel_internal(interaction, channel)
        except discord.app_commands.errors.MissingPermissions:
            await interaction.response.send_message("이 명령어는 관리자만 사용할 수 있습니다.", ephemeral=True)
        except Exception as e:
            logger.error(f"모집 채널 설정 중 오류 발생: {e}")
            logger.error(traceback.format_exc())
            if not interaction.response.is_done():
                await interaction.response.defer(ephemeral=True)
            await interaction.followup.send("모집 채널 설정 중 오류가 발생했습니다.", ephemeral=True)

    async def set_announcement_channel_internal(self, interaction: discord.Interaction, channel: discord.TextChannel):
        """내부적으로 모집 공고 채널을 설정합니다."""
        try:
            # 서버의 길드 ID 가져오기
            guild_id = str(interaction.guild_id)
            
            # 채널 ID 저장
            update_result = await self.db["settings"].update_one(
                {"guild_id": guild_id},
                {"$set": {
                    "announcement_channel_id": str(channel.id),
                    "updated_at": datetime.now().isoformat()
                }},
                upsert=True
            )
            
            # 메모리에도 설정 저장
            self.announcement_channels[guild_id] = str(channel.id)
            
            # 디버그 로그 추가
            logger.info(f"서버 {guild_id}의 모집 공고 채널이 {channel.id}로 설정되었습니다. DB 결과: {update_result.acknowledged}")
            
            # 응답 메시지
            await interaction.followup.send(f"모집 공고 채널이 {channel.mention}으로 설정되었습니다.", ephemeral=True)
            
        except Exception as e:
            logger.error(f"모집 공고 채널 설정 중 오류 발생: {e}")
            logger.error(traceback.format_exc())
            await interaction.followup.send("모집 공고 채널 설정 중 오류가 발생했습니다.", ephemeral=True)

    @app_commands.command(name="모집등록채널설정", description="모집 등록 양식을 게시할 채널을 설정합니다.")
    @app_commands.checks.has_permissions(administrator=True)
    async def set_registration_channel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        """모집 등록 채널 설정 명령어 - 관리자 전용"""
        try:
            # 서버의 길드 ID 가져오기
            guild_id = str(interaction.guild_id)
            
            # 채널 ID 저장
            await self.db["settings"].update_one(
                {"guild_id": guild_id},
                {"$set": {"registration_channel_id": str(channel.id)}},
                upsert=True
            )
            
            # 메모리에도 설정 저장
            self.registration_channels[guild_id] = str(channel.id)
            
            # 등록 양식 생성
            try:
                # 기존 메시지 삭제
                await channel.purge(limit=None)
                
                # 새 등록 양식 생성
                await self.create_registration_form(channel)
                logger.info(f"서버 {guild_id}의 모집 등록 채널 설정 및 양식 생성 완료")
            except Exception as e:
                logger.error(f"모집 등록 양식 생성 중 오류 발생: {e}")
            
            # 응답 메시지
            await interaction.response.defer(ephemeral=True)
            msg = await interaction.followup.send(f"모집 등록 채널이 {channel.mention}으로 설정되었습니다.", ephemeral=True)
            await asyncio.sleep(2)
            await msg.delete()
            
        except discord.app_commands.errors.MissingPermissions:
            await interaction.response.send_message("이 명령어는 관리자만 사용할 수 있습니다.", ephemeral=True)
        except Exception as e:
            logger.error(f"모집 등록 채널 설정 중 오류 발생: {e}")
            logger.error(traceback.format_exc())
            if not interaction.response.is_done():
                await interaction.response.defer(ephemeral=True)
                msg = await interaction.followup.send("모집 등록 채널 설정 중 오류가 발생했습니다.", ephemeral=True)
                await asyncio.sleep(2)
                await msg.delete()
    
    @app_commands.command(name="모집초기화", description="모집 등록 채널을 초기화합니다.")
    @app_commands.checks.has_permissions(administrator=True)
    async def reset_registration_channel(self, interaction: discord.Interaction):
        """모집 등록 채널 초기화 명령어 - 관리자 전용"""
        try:
            # 서버의 길드 ID 가져오기
            guild_id = str(interaction.guild_id)
            
            # 채널 ID 가져오기
            settings = await self.db["settings"].find_one({"guild_id": guild_id})
            if not settings or "registration_channel_id" not in settings:
                await interaction.response.defer(ephemeral=True)
                msg = await interaction.followup.send("모집 등록 채널이 설정되지 않았습니다.", ephemeral=True)
                await asyncio.sleep(2)
                await msg.delete()
                return
            
            # 채널 가져오기
            channel = interaction.guild.get_channel(int(settings["registration_channel_id"]))
            if not channel:
                await interaction.response.defer(ephemeral=True)
                msg = await interaction.followup.send("모집 등록 채널을 찾을 수 없습니다.", ephemeral=True)
                await asyncio.sleep(2)
                await msg.delete()
                return

            # 채널 초기화
            await channel.purge(limit=None)
            await self.create_registration_form(channel)
            
            # 응답 메시지
            await interaction.response.defer(ephemeral=True)
            msg = await interaction.followup.send("모집 등록 채널이 초기화되었습니다.", ephemeral=True)
            await asyncio.sleep(2)
            await msg.delete()
            
        except discord.app_commands.errors.MissingPermissions:
            await interaction.response.send_message("이 명령어는 관리자만 사용할 수 있습니다.", ephemeral=True)
        except Exception as e:
            logger.error(f"모집 등록 채널 초기화 중 오류 발생: {e}")
            logger.error(traceback.format_exc())
            if not interaction.response.is_done():
                await interaction.response.defer(ephemeral=True)
                msg = await interaction.followup.send("모집 등록 채널 초기화 중 오류가 발생했습니다.", ephemeral=True)
                await asyncio.sleep(2)
                await msg.delete()

    @app_commands.command(name="채널페어설정", description="등록 채널과 공고 채널을 페어링합니다.")
    @app_commands.checks.has_permissions(administrator=True)
    async def set_channel_pair(self, interaction: discord.Interaction, 등록채널: discord.TextChannel, 공고채널: discord.TextChannel):
        """채널 페어 설정 명령어 - 관리자 전용"""
        try:
            await interaction.response.defer(ephemeral=True)
            
            # 서버의 길드 ID 가져오기
            guild_id = str(interaction.guild_id)
            
            # 서버별 채널 페어 관계 가져오기
            settings = await self.db["settings"].find_one({"guild_id": guild_id})
            channel_pairs = settings.get("channel_pairs", {}) if settings else {}
            
            # 채널 페어 관계 업데이트
            channel_pairs[str(등록채널.id)] = str(공고채널.id)
            
            # DB에 저장
            await self.db["settings"].update_one(
                {"guild_id": guild_id},
                {"$set": {
                    "channel_pairs": channel_pairs,
                    "updated_at": datetime.now().isoformat()
                }},
                upsert=True
            )
            
            # 메모리에도 저장
            if guild_id not in self.channel_pairs:
                self.channel_pairs[guild_id] = {}
            self.channel_pairs[guild_id][str(등록채널.id)] = str(공고채널.id)
            
            # 응답 메시지
            await interaction.followup.send(
                f"등록 채널 {등록채널.mention}에서 등록된 모집 공고가 {공고채널.mention} 채널에 게시되도록 설정되었습니다.",
                ephemeral=True
            )
            
        except discord.app_commands.errors.MissingPermissions:
            await interaction.followup.send("이 명령어는 관리자만 사용할 수 있습니다.", ephemeral=True)
        except Exception as e:
            logger.error(f"채널 페어 설정 중 오류 발생: {e}")
            logger.error(traceback.format_exc())
            await interaction.followup.send("채널 페어 설정 중 오류가 발생했습니다.", ephemeral=True)

    @app_commands.command(name="채널페어삭제", description="등록 채널과 공고 채널의 페어링을 삭제합니다.")
    @app_commands.checks.has_permissions(administrator=True)
    async def delete_channel_pair(self, interaction: discord.Interaction, 등록채널: discord.TextChannel):
        """채널 페어 삭제 명령어 - 관리자 전용"""
        try:
            await interaction.response.defer(ephemeral=True)
            
            # 서버의 길드 ID 가져오기
            guild_id = str(interaction.guild_id)
            
            # 서버별 채널 페어 관계 가져오기
            settings = await self.db["settings"].find_one({"guild_id": guild_id})
            channel_pairs = settings.get("channel_pairs", {}) if settings else {}
            
            # 해당 등록 채널의 페어 관계가 있는지 확인
            if str(등록채널.id) not in channel_pairs:
                await interaction.followup.send(f"등록 채널 {등록채널.mention}에 대한 페어 설정이 없습니다.", ephemeral=True)
                return
            
            # 채널 페어 관계에서 해당 등록 채널 삭제
            del channel_pairs[str(등록채널.id)]
            
            # DB에 저장
            await self.db["settings"].update_one(
                {"guild_id": guild_id},
                {"$set": {
                    "channel_pairs": channel_pairs,
                    "updated_at": datetime.now().isoformat()
                }},
                upsert=True
            )
            
            # 메모리에도 저장
            if guild_id in self.channel_pairs and str(등록채널.id) in self.channel_pairs[guild_id]:
                del self.channel_pairs[guild_id][str(등록채널.id)]
            
            # 응답 메시지
            await interaction.followup.send(f"등록 채널 {등록채널.mention}의 페어 설정이 삭제되었습니다.", ephemeral=True)
            
        except discord.app_commands.errors.MissingPermissions:
            await interaction.followup.send("이 명령어는 관리자만 사용할 수 있습니다.", ephemeral=True)
        except Exception as e:
            logger.error(f"채널 페어 삭제 중 오류 발생: {e}")
            logger.error(traceback.format_exc())
            await interaction.followup.send("채널 페어 삭제 중 오류가 발생했습니다.", ephemeral=True)

    @app_commands.command(name="채널페어목록", description="설정된 채널 페어 목록을 확인합니다.")
    @app_commands.checks.has_permissions(administrator=True)
    async def list_channel_pairs(self, interaction: discord.Interaction):
        """채널 페어 목록 명령어 - 관리자 전용"""
        try:
            await interaction.response.defer(ephemeral=True)
            
            # 서버의 길드 ID 가져오기
            guild_id = str(interaction.guild_id)
            
            # 서버별 채널 페어 관계 가져오기
            if guild_id not in self.channel_pairs or not self.channel_pairs[guild_id]:
                await interaction.followup.send("설정된 채널 페어가 없습니다.", ephemeral=True)
                return
            
            # 임베드 생성
            embed = discord.Embed(
                title="채널 페어 설정 목록",
                description="등록 채널과 공고 채널의 페어링 목록입니다.",
                color=discord.Color.blue()
            )
            
            # 채널 페어 목록 추가
            for reg_channel_id, ann_channel_id in self.channel_pairs[guild_id].items():
                reg_channel = interaction.guild.get_channel(int(reg_channel_id))
                ann_channel = interaction.guild.get_channel(int(ann_channel_id))
                
                reg_channel_mention = reg_channel.mention if reg_channel else f"알 수 없는 채널 (ID: {reg_channel_id})"
                ann_channel_mention = ann_channel.mention if ann_channel else f"알 수 없는 채널 (ID: {ann_channel_id})"
                
                embed.add_field(
                    name=f"등록 채널",
                    value=f"{reg_channel_mention} ➡️ {ann_channel_mention}",
                    inline=False
                )
            
            # 응답 메시지
            await interaction.followup.send(embed=embed, ephemeral=True)
            
        except discord.app_commands.errors.MissingPermissions:
            await interaction.followup.send("이 명령어는 관리자만 사용할 수 있습니다.", ephemeral=True)
        except Exception as e:
            logger.error(f"채널 페어 목록 표시 중 오류 발생: {e}")
            logger.error(traceback.format_exc())
            await interaction.followup.send("채널 페어 목록 표시 중 오류가 발생했습니다.", ephemeral=True)

    # 명령어 오류 처리
    async def command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        """명령어 오류 처리"""
        if isinstance(error, app_commands.errors.MissingPermissions):
            await interaction.response.send_message("이 명령어는 관리자만 사용할 수 있습니다.", ephemeral=True)
        else:
            logger.error(f"명령어 실행 중 오류 발생: {error}")
            logger.error(traceback.format_exc())
            if not interaction.response.is_done():
                await interaction.response.send_message("명령어 실행 중 오류가 발생했습니다.", ephemeral=True)
    
    # 각 명령어에 에러 핸들러 추가
    @app_commands.command(name="채널페어설정", description="등록 채널과 공고 채널을 페어링합니다.")
    @app_commands.checks.has_permissions(administrator=True)
    async def set_channel_pair(self, interaction: discord.Interaction, 등록채널: discord.TextChannel, 공고채널: discord.TextChannel):
        """채널 페어 설정 명령어 - 관리자 전용"""
        try:
            await interaction.response.defer(ephemeral=True)
            
            # 서버의 길드 ID 가져오기
            guild_id = str(interaction.guild_id)
            
            # 서버별 채널 페어 관계 가져오기
            settings = await self.db["settings"].find_one({"guild_id": guild_id})
            channel_pairs = settings.get("channel_pairs", {}) if settings else {}
            
            # 채널 페어 관계 업데이트
            channel_pairs[str(등록채널.id)] = str(공고채널.id)
            
            # DB에 저장
            await self.db["settings"].update_one(
                {"guild_id": guild_id},
                {"$set": {
                    "channel_pairs": channel_pairs,
                    "updated_at": datetime.now().isoformat()
                }},
                upsert=True
            )
            
            # 메모리에도 저장
            if guild_id not in self.channel_pairs:
                self.channel_pairs[guild_id] = {}
            self.channel_pairs[guild_id][str(등록채널.id)] = str(공고채널.id)
            
            # 응답 메시지
            await interaction.followup.send(
                f"등록 채널 {등록채널.mention}에서 등록된 모집 공고가 {공고채널.mention} 채널에 게시되도록 설정되었습니다.",
                ephemeral=True
            )
            
        except discord.app_commands.errors.MissingPermissions:
            await interaction.followup.send("이 명령어는 관리자만 사용할 수 있습니다.", ephemeral=True)
        except Exception as e:
            logger.error(f"채널 페어 설정 중 오류 발생: {e}")
            logger.error(traceback.format_exc())
            await interaction.followup.send("채널 페어 설정 중 오류가 발생했습니다.", ephemeral=True)

async def setup(bot):
    await bot.add_cog(PartyCog(bot))
    bot_cog = bot.get_cog('PartyCog')
    if not bot_cog:
        logger.error("PartyCog를 찾을 수 없습니다.")
    else:
        # 활성화 유지 작업 시작
        bot_cog.keep_alive.start()
        logger.info("PartyCog와 활성화 유지 작업이 시작되었습니다.")
