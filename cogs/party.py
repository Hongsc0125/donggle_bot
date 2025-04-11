from discord.ext import commands, tasks
from database.session import get_database
from views.recruitment_card import RecruitmentCard, CreatorOnlyButton
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
import copy

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
        """초기화"""
        self.bot = bot
        self.db = get_database()  # bot.database 대신 get_database() 함수 사용
        self.dungeons = []
        self.announcement_channels = {}
        self.registration_channels = {}
        self.channel_pairs = {}
        self.thread_channels = {}
        self.allowed_guild_ids = {}
        self.initialization_retries = {}
        self.refresh_running = False
        self.initialization_completed = False  # 초기화 완료 여부를 추적하는 플래그
        
        # 백그라운드 작업 시작
        self.initialize_and_cleanup.start()
        self.refresh_registration_forms.start()
        
        # 설정 로드
        self.bot.loop.create_task(self._load_settings_async())
        self.bot.loop.create_task(self._load_dungeons_async())
        
        logger.info("Party cog initialized")

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
            
            # 허용된 길드 ID 설정 - 특정 두 개의 길드만 허용
            self.allowed_guild_ids = {
                "1359541321185886400": True,
                "1359677298604900462": True
            }
            
            # 모든 서버를 허용하도록 수정
            for guild in self.bot.guilds:
                self.allowed_guild_ids[str(guild.id)] = True
                
            logger.info(f"허용된 길드 ID 목록을 설정했습니다: {self.allowed_guild_ids}")
            
            # 채널 초기화는 on_ready 이벤트에서 수행하도록 변경
            # 여기서 초기화를 수행하지 않음
            
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
        """봇이 준비되면 호출되는 이벤트"""
        try:
            # 이미 초기화가 완료되었으면 건너뜀
            if self.initialization_completed:
                logger.info("이미 초기화가 완료되었으므로 on_ready 이벤트 처리를 건너뜁니다.")
                return
                
            # 초기화 작업 시작 전에 플래그 설정 (중복 초기화 방지)
            self.initialization_completed = True

            logger.info("봇 초기화 시작")
            
            # 명령어 동기화 시도
            try:
                logger.info("[DEBUG] 명령어 동기화 시도 중...")
                # 명령어 트리 동기화
                commands = await self.bot.tree.sync()
                logger.info(f"[DEBUG] 명령어 트리 동기화 완료 - {len(commands)}개 명령어")
                
                # 사용 가능한 명령어 목록 출력
                for cmd in commands:
                    logger.info(f"[DEBUG] 등록된 명령어: /{cmd.name} - {cmd.description}")
            except Exception as e:
                logger.error(f"[DEBUG] 명령어 동기화 오류: {e}")
                logger.error(traceback.format_exc())
            
            # 봇이 준비된 상태이므로 서버 전체 목록 확인
            logger.info(f"봇이 연결된 서버 수: {len(self.bot.guilds)}")
            for guild in self.bot.guilds:
                logger.info(f"연결된 서버: {guild.name} (ID: {guild.id})")
                # 허용 목록에 추가
                self.allowed_guild_ids[str(guild.id)] = True
            
            # 뷰 상태 복원
            await self._restore_views()
            
            # 채널 초기화 - 봇이 완전히 연결된 후 진행
            await asyncio.sleep(3)  # 추가적인 안전을 위해 3초 대기
            await self.initialize_channels()
            
            # 초기화 완료 플래그 설정
            logger.info("봇 초기화 완료")
        except Exception as e:
            logger.error(f"봇 초기화 중 오류 발생: {e}")
            logger.error(traceback.format_exc())

    async def _restore_views(self):
        """저장된 뷰 상태를 복원합니다."""
        try:
            logger.info("뷰 상태 복원 시작")
            
            # 저장된 뷰 상태 가져오기
            states = await self.db["view_states"].find({}).to_list(length=None)
            
            # 뷰 상태 복원
            for state in states:
                try:
                    # 필수 필드 확인
                    if "channel_id" not in state:
                        logger.warning(f"뷰 상태에 channel_id가 없습니다: {state.get('message_id', 'unknown')}")
                        continue
                    
                    if "message_id" not in state:
                        logger.warning(f"뷰 상태에 message_id가 없습니다: {state['channel_id']}")
                        continue
                    
                    if "recruitment_id" not in state:
                        logger.warning(f"뷰 상태에 recruitment_id가 없습니다: {state['message_id']}")
                        continue
                    
                    # 상태 정보 추출
                    channel_id = state["channel_id"]
                    message_id = state["message_id"]
                    recruitment_id = state["recruitment_id"]
                    guild_id = state.get("guild_id", "unknown")
                    
                    # 채널 객체 가져오기
                    channel = self.bot.get_channel(int(channel_id))
                    if not channel:
                        logger.warning(f"채널을 찾을 수 없음: {channel_id}")
                        continue
                    
                    # 메시지 객체 가져오기
                    try:
                        message = await channel.fetch_message(int(message_id))
                    except discord.NotFound:
                        logger.warning(f"메시지를 찾을 수 없음: {message_id} (채널: {channel_id})")
                        # 메시지가 없으면 DB에서 삭제
                        await self.db["view_states"].delete_one({"message_id": message_id})
                        continue
                    except Exception as e:
                        logger.error(f"메시지 조회 중 오류: {e}")
                        continue
                    
                    # 뷰 객체 생성
                    view = RecruitmentCard(self.dungeons, self.db)
                    
                    # 뷰 상태 복원
                    view.message = message
                    view.selected_type = state.get("selected_type", None)
                    view.selected_kind = state.get("selected_kind", None)
                    view.selected_diff = state.get("selected_diff", None)
                    view.recruitment_content = state.get("recruitment_content", "")
                    view.max_participants = state.get("max_participants", 0)
                    view.status = state.get("status", "모집중")
                    view.recruitment_id = recruitment_id
                    
                    if "participants" in state:
                        view.participants = []
                        for p_id in state["participants"]:
                            try:
                                view.participants.append(int(p_id))
                            except ValueError:
                                logger.error(f"참가자 ID 변환 오류: {p_id}")
                                continue
                    
                    view.creator_id = int(state["creator_id"]) if "creator_id" in state and state["creator_id"] else None
                    
                    # 임베드 생성
                    embed = view.get_embed()
                    embed.title = "파티 모집 공고"
                    
                    # 뷰 업데이트
                    try:
                        await message.edit(embed=embed, view=view)
                        logger.info(f"서버 {guild_id}의 모집 ID {recruitment_id}의 상호작용을 다시 등록했습니다.")
                    except discord.NotFound:
                        logger.warning(f"서버 {guild_id}의 모집 ID {recruitment_id}의 메시지({message_id})를 찾을 수 없어 업데이트를 건너뜁니다.")
                        # DB에서 해당 메시지 관련 정보 삭제
                        await self.db["view_states"].delete_one({"message_id": message_id})
                        continue
                    except Exception as e:
                        logger.error(f"서버 {guild_id}의 모집 ID {recruitment_id}의 메시지 업데이트 중 오류: {e}")
                        logger.error(traceback.format_exc())
                        continue
                    
                except KeyError as e:
                    logger.error(f"뷰 상태 복원 중 키 오류 발생: {e}")
                    continue
                except Exception as e:
                    # state에서 필요한 정보 안전하게 추출
                    safe_guild_id = state.get("guild_id", "unknown")
                    safe_recruitment_id = state.get("recruitment_id", "unknown")
                    
                    logger.error(f"서버 {safe_guild_id}의 모집 ID {safe_recruitment_id} 뷰 상태 복원 중 오류 발생: {e}")
                    logger.error(traceback.format_exc())
                    continue
            
            logger.info("뷰 상태 복원 완료")
        except Exception as e:
            logger.error(f"뷰 상태 복원 중 오류 발생: {e}")
            logger.error(traceback.format_exc())

    async def initialize_channels(self, force_retry=False):
        """모집 등록 채널과 공고 채널을 초기화합니다."""
        # 이미 초기화가 완료되었고 강제 재시도가 아니면 건너뜀
        if self.initialization_completed and not force_retry:
            logger.info("이미 초기화가 완료되었으므로 채널 초기화를 건너뜁니다.")
            return
            
        try:
            logger.info("채널 초기화 시작")
            
            # 디버깅 정보 출력
            logger.info(f"[DEBUG] 초기화할 등록 채널: {self.registration_channels}")
            logger.info(f"[DEBUG] 초기화할 공고 채널: {self.announcement_channels}")
            logger.info(f"[DEBUG] 채널 페어 관계: {self.channel_pairs}")
            
            # 등록 채널 초기화
            for guild_id, channel_id in self.registration_channels.items():
                logger.info(f"서버 {guild_id}의 모집 등록 채널 초기화 중: {channel_id}")
                
                # 길드 객체 가져오기
                guild = self.bot.get_guild(int(guild_id))
                if not guild:
                    logger.warning(f"서버를 찾을 수 없음: {guild_id}")
                    continue
                
                # 채널 객체 가져오기
                channel = guild.get_channel(int(channel_id))
                if not channel:
                    logger.warning(f"채널을 찾을 수 없음: {channel_id}")
                    continue
                
                try:
                    # 기존 메시지 삭제
                    await self.clear_channel_messages(channel, guild_id)
                    
                    # 새 등록 양식 생성
                    await self.create_registration_form(channel)
                    logger.info(f"서버 {guild_id}의 모집 등록 채널 초기화 완료")
                    
                    # 채널 페어링 관계 확인
                    if guild_id in self.channel_pairs:
                        logger.info(f"[DEBUG] 서버 {guild_id}의 채널 페어 검사 중: {self.channel_pairs[guild_id]}")
                        
                        # 추가 등록 채널 초기화
                        for reg_channel_id, _ in self.channel_pairs[guild_id].items():
                            # 현재 처리 중인 등록 채널이 아닌 다른 등록 채널만 처리
                            if reg_channel_id != channel_id:
                                logger.info(f"[DEBUG] 페어링된 추가 등록 채널 초기화 중: {reg_channel_id}")
                                
                                # 채널 객체 가져오기
                                reg_channel = guild.get_channel(int(reg_channel_id))
                                if not reg_channel:
                                    logger.warning(f"페어링된 등록 채널을 찾을 수 없음: {reg_channel_id}")
                                    continue
                                
                                try:
                                    # 기존 메시지 삭제
                                    await self.clear_channel_messages(reg_channel, guild_id, is_paired=True, paired_id=reg_channel_id)
                                    
                                    # 새 등록 양식 생성
                                    message = await self.create_registration_form(reg_channel)
                                    if message:
                                        logger.info(f"[DEBUG] 페어링된 등록 채널 {reg_channel_id}에 양식 생성 성공: {message.id}")
                                    else:
                                        logger.error(f"[DEBUG] 페어링된 등록 채널 {reg_channel_id}에 양식 생성 실패")
                                    
                                except Exception as e:
                                    logger.error(f"서버 {guild_id}의 페어링된 추가 등록 채널 {reg_channel_id} 초기화 중 오류 발생: {e}")
                                    logger.error(traceback.format_exc())
                                    continue
                                    
                                logger.info(f"서버 {guild_id}의 페어링된 추가 등록 채널 {reg_channel_id} 초기화 완료")
                    
                except Exception as e:
                    logger.error(f"서버 {guild_id}의 등록 채널 {channel_id} 초기화 중 오류 발생: {e}")
                    logger.error(traceback.format_exc())
                    
                    if force_retry:
                        # 오류 발생 시 재시도
                        await self._retry_initialization(delay_seconds=2)
            
            # 공고 채널 초기화
            for guild_id, channel_id in self.announcement_channels.items():
                logger.info(f"서버 {guild_id}의 공고 채널 초기화 중: {channel_id}")
                
                # 길드 객체 가져오기
                guild = self.bot.get_guild(int(guild_id))
                if not guild:
                    logger.warning(f"서버를 찾을 수 없음: {guild_id}")
                    continue
                
                # 채널 객체 가져오기
                announcement_channel = guild.get_channel(int(channel_id))
                if not announcement_channel:
                    logger.warning(f"채널을 찾을 수 없음: {channel_id}")
                    continue
                
                try:
                    # 활성 모집 정보 가져오기
                    active_recruitments = await self.db["recruitments"].find(
                        {"guild_id": guild_id, "status": "active"}
                    ).to_list(length=None)
                    
                    logger.info(f"서버 {guild_id}의 활성 모집 {len(active_recruitments)}개를 불러왔습니다.")
                    
                    # 모든 공고 채널 목록 생성
                    all_announcement_channels = set([channel_id])
                    if guild_id in self.channel_pairs:
                        for _, announcement_id in self.channel_pairs[guild_id].items():
                            all_announcement_channels.add(announcement_id)
                    
                    logger.info(f"[DEBUG] 서버 {guild_id}의 모든 공고 채널 IDs: {all_announcement_channels}")
                    
                    # 모든 페어링된 공고 채널도 초기화
                    for announcement_ch_id in all_announcement_channels:
                        if announcement_ch_id != channel_id:  # 기본 공고 채널은 이미 처리 중
                            logger.info(f"[DEBUG] 페어링된 추가 공고 채널 초기화 중: {announcement_ch_id}")
                            
                            # 채널 객체 가져오기
                            ann_channel = guild.get_channel(int(announcement_ch_id))
                            if not ann_channel:
                                logger.warning(f"페어링된 공고 채널을 찾을 수 없음: {announcement_ch_id}")
                                continue
                            
                            # 완료된 모집 메시지 삭제 시도
                            logger.info(f"[DEBUG] 페어링된 공고 채널 {announcement_ch_id}의 완료된 모집 메시지 삭제 시도")
                            
                            # 해당 채널 메시지 히스토리 검사
                            if self.is_allowed_guild(guild_id):
                                try:
                                    # 활성 모집 정보와 메시지 히스토리 비교 및 대응
                                    await self.process_active_recruitments(guild, guild_id, active_recruitments, ann_channel)
                                except Exception as e:
                                    logger.error(f"서버 {guild_id}의 페어링된 공고 채널 {announcement_ch_id} 초기화 중 오류 발생: {e}")
                                    logger.error(traceback.format_exc())
                                    continue
                            
                            logger.info(f"서버 {guild_id}의 페어링된 추가 공고 채널 {announcement_ch_id} 초기화 완료")
                    
                    # 기본 공고 채널에서 활성 모집 처리
                    if self.is_allowed_guild(guild_id):
                        try:
                            # 활성 모집 정보와 메시지 히스토리 비교 및 대응
                            await self.process_active_recruitments(guild, guild_id, active_recruitments, announcement_channel)
                        except Exception as e:
                            logger.error(f"서버 {guild_id}의 공고 채널 {channel_id} 초기화 중 활성 모집 처리 오류: {e}")
                            logger.error(traceback.format_exc())
                    
                    # 데이터베이스 업데이트
                    await self.db["channels"].update_one(
                        {"guild_id": guild_id, "type": "announcement"},
                        {"$set": {"channel_id": announcement_channel.id}},
                        upsert=True
                    )
                    
                except Exception as e:
                    logger.error(f"서버 {guild_id}의 공고 채널 {channel_id} 초기화 중 오류 발생: {e}")
                    logger.error(traceback.format_exc())
                    
                    if force_retry:
                        # 오류 발생 시 재시도
                        await self._retry_initialization(delay_seconds=2)
            
            # 초기화 완료 플래그 설정
            logger.info("채널 초기화 완료")
            logger.info("채널 초기화 완료")
            
        except Exception as e:
            logger.error(f"채널 초기화 중 오류 발생: {e}")
            logger.error(traceback.format_exc())
            
            if force_retry:
                # 오류 발생 시 재시도
                await self._retry_initialization()

    async def _retry_initialization(self, delay_seconds=5):
        """지정된 지연 시간 후 채널 초기화를 다시 시도합니다."""
        await asyncio.sleep(delay_seconds)
        logger.info(f"{delay_seconds}초 지연 후 채널 초기화 재시도 중...")
        await self.initialize_channels()

    async def clear_channel_messages(self, channel, guild_id, is_paired=False, paired_id=None):
        """채널의 메시지를 안전하게 삭제합니다."""
        channel_desc = f"페어링된 등록 채널 {paired_id}" if is_paired else "등록 채널"
        
        try:
            # 봇이 보낸 메시지 확인
            bot_messages = []
            try:
                # 채널 히스토리에서 봇이 보낸 메시지만 필터링
                async for message in channel.history(limit=30):
                    if message.author.id == self.bot.user.id:
                        bot_messages.append(message)
                
                logger.info(f"서버 {guild_id}의 {channel_desc}에서 봇 메시지 {len(bot_messages)}개 발견")
            except Exception as e:
                logger.error(f"서버 {guild_id}의 {channel_desc} 메시지 히스토리 조회 중 오류: {e}")
                logger.error(traceback.format_exc())
                return
            
            # 메시지가 없으면 삭제 과정 건너뜀
            if not bot_messages:
                logger.info(f"서버 {guild_id}의 {channel_desc}에 삭제할 메시지가 없습니다.")
                return
                
            # purge 메소드로 일괄 삭제 시도
            try:
                # 봇이 보낸 메시지만 삭제하는 필터 함수
                def is_bot_message(msg):
                    return msg.author.id == self.bot.user.id
                
                deleted = await channel.purge(limit=30, check=is_bot_message)
                logger.info(f"서버 {guild_id}의 {channel_desc}에서 {len(deleted)}개 메시지 일괄 삭제 완료")
                
            except discord.errors.Forbidden:
                logger.error(f"서버 {guild_id}의 {channel_desc}에서 메시지 삭제 권한이 없습니다.")
                return
                
            except (discord.errors.NotFound, discord.errors.HTTPException) as e:
                logger.warning(f"서버 {guild_id}의 {channel_desc}에서 일괄 삭제 중 오류 발생: {e}")
                logger.info(f"개별 메시지 삭제 방식으로 전환합니다.")
                
                # 개별 삭제로 대체
                deleted_count = 0
                for message in bot_messages:
                    try:
                        await message.delete()
                        deleted_count += 1
                        # API 속도 제한 방지
                        await asyncio.sleep(0.5)
                    except Exception as delete_error:
                        logger.error(f"메시지 개별 삭제 중 오류: {delete_error}")
                
                logger.info(f"서버 {guild_id}의 {channel_desc}에서 {deleted_count}개 메시지 개별 삭제 완료")
                
            except Exception as e:
                logger.error(f"서버 {guild_id}의 {channel_desc}에서 메시지 삭제 중 오류: {e}")
                logger.error(traceback.format_exc())
            
            # 삭제 후 잠시 대기
            await asyncio.sleep(1)
            
        except Exception as e:
            logger.error(f"서버 {guild_id}의 {channel_desc} 메시지 삭제 과정 중 오류 발생: {e}")
            logger.error(traceback.format_exc())

    async def process_active_recruitments(self, guild, guild_id, active_recruitments, channel):
        logger.info(f"[DEBUG] process_active_recruitments 시작 - 서버: {guild_id}, 채널: {channel.id}")
        try:
            updated_count = 0
            created_count = 0
            deleted_count = 0
            duplicate_deleted_count = 0

            # 먼저 채널의 모든 메시지를 불러와서 모집 ID별로 정리
            logger.info(f"[DEBUG] 채널 {channel.id}의 메시지를 불러와 모집 ID 매핑을 생성합니다")
            recruitment_messages = {}  # 모집 ID -> 메시지 목록
            try:
                # 최대 100개의 메시지만 조회
                async for message in channel.history(limit=100):
                    # 메시지가 임베드를 가지고 있는지 확인
                    if not message.embeds or not message.embeds[0].footer:
                        continue
                    
                    # 임베드에서 모집 ID 찾기
                    footer_text = message.embeds[0].footer.text
                    if footer_text and footer_text.startswith("모집 ID:"):
                        recruitment_id = footer_text.replace("모집 ID:", "").strip()
                        if " | " in recruitment_id:
                            recruitment_id = recruitment_id.split(" | ")[0].strip()
                        
                        if recruitment_id:
                            if recruitment_id not in recruitment_messages:
                                recruitment_messages[recruitment_id] = []
                            recruitment_messages[recruitment_id].append(message)
                            logger.info(f"[DEBUG] 채널 {channel.id}에서 모집 ID {recruitment_id}의 메시지 {message.id} 발견")
            except Exception as e:
                logger.error(f"[DEBUG] 채널 메시지 조회 중 오류: {e}")
                logger.error(traceback.format_exc())
            
            # 각 모집 ID별로 중복 메시지 처리
            for recruitment_id, messages in recruitment_messages.items():
                if len(messages) > 1:
                    logger.info(f"[DEBUG] 모집 ID {recruitment_id}의 중복 메시지 {len(messages)}개 발견")
                    # 모든 중복 메시지 삭제 (새로 생성할 예정이므로)
                    for message in messages:
                        try:
                            await message.delete()
                            duplicate_deleted_count += 1
                            logger.info(f"[DEBUG] 중복 모집 ID {recruitment_id}의 메시지 {message.id} 삭제")
                        except Exception as e:
                            logger.error(f"[DEBUG] 중복 메시지 삭제 중 오류: {e}")
                    # 해당 ID의 모든 메시지를 삭제했으므로 목록 비우기
                    recruitment_messages[recruitment_id] = []

            # 이제 각 활성 모집 처리
            for recruitment in active_recruitments:
                recruitment_id = str(recruitment.get('_id'))
                logger.info(f"[DEBUG] 모집 처리 시작 - ID: {recruitment_id}")
                logger.info(f"[DEBUG] 모집 데이터: {recruitment}")
                
                # 모집 데이터 검증
                required_fields = ['type', 'dungeon', 'difficulty', 'max_participants', 'description']
                missing_fields = [field for field in required_fields if not recruitment.get(field)]
                if missing_fields:
                    logger.warning(f"[DEBUG] 모집 {recruitment_id}에 누락된 필드: {missing_fields}")
                    continue
                
                # 각 모집이 해당 채널에 속하는지 확인
                registration_channel_id = str(recruitment.get("registration_channel_id", "0"))
                announcement_channel_id = str(recruitment.get("announcement_channel_id", "0"))
                announcement_message_id = str(recruitment.get("announcement_message_id", "0"))
                
                # 이 채널이 해당 모집의 공고 채널인지, 또는 페어링된 채널인지 확인
                channel_id_str = str(channel.id)
                is_paired_channel = False
                
                # 이 모집의 등록 채널이 현재 채널과 페어링되어 있는지 확인
                pairs = self.channel_pairs.get(guild_id, {})
                if registration_channel_id in pairs and pairs[registration_channel_id] == channel_id_str:
                    logger.info(f"모집 {recruitment_id}는 이 채널({channel_id_str})과 페어링된 등록 채널({registration_channel_id})에서 왔으므로 표시")
                    is_paired_channel = True
                
                # 공고 채널이 현재 채널인 경우
                if announcement_channel_id == channel_id_str:
                    logger.info(f"모집 {recruitment_id}는 이 채널({channel_id_str})을 공고 채널로 지정했으므로 표시")
                    is_paired_channel = True
                
                # 해당 모집이 이 채널에 표시되어야 하는 경우만 처리
                if not is_paired_channel:
                    logger.info(f"모집 {recruitment_id}는 이 채널({channel_id_str})과 관련이 없어 건너뜁니다")
                    continue
                
                # 1. 이미 게시된 공고 메시지가 있는지 확인
                existing_messages = recruitment_messages.get(recruitment_id, [])
                existing_message = None if not existing_messages else existing_messages[0]
                needs_update = False
                
                if existing_message:
                    # 기존 메시지가 있으면 업데이트가 필요한지 확인
                    needs_update = await self.check_announcement_needs_update(existing_message, recruitment)
                    logger.info(f"[DEBUG] 모집 {recruitment_id} 업데이트 필요 여부: {needs_update}")
                
                # 2. 모집 View 생성 및 값 설정
                view = RecruitmentCard(self.dungeons, self.db)
                # 모집 ID 설정
                view.recruitment_id = recruitment_id
                # 모집 상태 설정
                view.status = recruitment.get("status", "active")
                
                # *** 중요: 모집 데이터에서 값 설정 추가 ***
                # 던전 정보 설정
                view.selected_type = recruitment.get("type")
                view.selected_kind = recruitment.get("dungeon")
                view.selected_diff = recruitment.get("difficulty")
                # 모집 내용 설정
                view.recruitment_content = recruitment.get("description")
                # 최대 인원수 설정
                view.max_participants = recruitment.get("max_participants")
                # 참가자 목록 설정 (문자열 ID를 정수로 변환)
                participants = recruitment.get("participants", [])
                view.participants = [int(p) if isinstance(p, str) and p.isdigit() else p for p in participants]
                # 모집자 ID 설정
                view.creator_id = recruitment.get("creator_id")
                # 공고 채널 ID 설정
                view.announcement_channel_id = announcement_channel_id
                # 공고 메시지 ID 설정
                view.announcement_message_id = announcement_message_id
                # 등록 채널 ID 설정
                view.registration_channel_id = registration_channel_id
                
                # 3. 상황에 따라 메시지 생성 또는 업데이트
                if existing_message and not needs_update:
                    # 기존 메시지가 있고 업데이트가 필요 없는 경우, 상호작용(버튼/선택메뉴)만 업데이트
                    logger.info(f"[DEBUG] 모집 {recruitment_id}의 상호작용만 업데이트합니다")
                    try:
                        # 메시지 객체를 view에 연결
                        view.message = existing_message
                        
                        # 기존 임베드는 그대로 유지하고 상호작용(view)만 업데이트
                        await existing_message.edit(view=view)
                        updated_count += 1
                        logger.info(f"[DEBUG] 모집 {recruitment_id}의 상호작용 업데이트 완료")
                    except Exception as e:
                        logger.error(f"[DEBUG] 모집 {recruitment_id}의 상호작용 업데이트 중 오류: {e}")
                        logger.error(traceback.format_exc())
                else:
                    # 기존 메시지가 없거나 업데이트가 필요한 경우
                    if existing_message:
                        logger.info(f"[DEBUG] 모집 {recruitment_id}의 내용이 변경되어 완전히 업데이트합니다")
                        try:
                            # 기존 메시지 삭제
                            await existing_message.delete()
                            deleted_count += 1
                            logger.info(f"[DEBUG] 기존 메시지 {existing_message.id} 삭제 완료")
                        except Exception as e:
                            logger.error(f"[DEBUG] 기존 메시지 삭제 중 오류: {e}")
                    else:
                        logger.info(f"[DEBUG] 모집 {recruitment_id}의 새 공고 메시지를 생성합니다")
                    
                    # 새 메시지 생성
                    try:
                        result = await self.post_recruitment_announcement(guild_id, recruitment, view)
                        if result:
                            created_count += 1
                            logger.info(f"[DEBUG] 모집 {recruitment_id}의 새 공고 생성 완료 (메시지 ID: {result.id})")
                        else:
                            logger.error(f"[DEBUG] 모집 {recruitment_id}의 새 공고 생성 실패")
                    except Exception as e:
                        logger.error(f"[DEBUG] 모집 {recruitment_id}의 새 공고 생성 중 오류: {e}")
                        logger.error(traceback.format_exc())
            
            logger.info(f"[DEBUG] 활성 모집 처리 완료 - 생성: {created_count}개, 상호작용 업데이트: {updated_count}개, 삭제: {deleted_count}개, 중복 삭제: {duplicate_deleted_count}개")
            return True
        except Exception as e:
            logger.error(f"process_active_recruitments 오류: {e}")
            logger.error(traceback.format_exc())
            return False

    async def create_recruitment_announcement(self, guild_id, recruitment_data):
        """모집 정보를 바탕으로 공고를 새로 생성합니다."""
        try:
            logger.info(f"모집 ID {recruitment_data.get('_id')}에 대한 공고 생성 시작")
            logger.info(f"모집 데이터:::::: {recruitment_data}")
            
            # 모집 데이터로 뷰 생성
            view = RecruitmentCard(self.dungeons, self.db)
            view.recruitment_id = str(recruitment_data.get("_id"))
            view.selected_type = recruitment_data.get("type", "")
            view.selected_kind = recruitment_data.get("dungeon", "")
            view.selected_diff = recruitment_data.get("difficulty", "")
            view.recruitment_content = recruitment_data.get("description", "")
            view.max_participants = recruitment_data.get("max_participants", 4)
            view.status = recruitment_data.get("status", "active")
            
            # 참가자 목록 변환
            try:
                participants = recruitment_data.get("participants", [])
                view.participants = [int(p) for p in participants]
            except ValueError:
                logger.warning(f"참가자 ID 변환 중 오류: {participants}")
                view.participants = []
            
            try:
                view.creator_id = int(recruitment_data.get("creator_id", 0))
            except ValueError:
                logger.warning(f"생성자 ID 변환 중 오류: {recruitment_data.get('creator_id')}")
                view.creator_id = 0
            
            # 등록 채널 ID 저장
            registration_channel_id = str(recruitment_data.get("registration_channel_id", "0"))
            view.registration_channel_id = registration_channel_id
            
            # 공고 게시
            await self.post_recruitment_announcement(guild_id, recruitment_data, view)
            
        except Exception as e:
            logger.error(f"모집 공고 생성 중 오류 발생: {e}")
            logger.error(traceback.format_exc())

    async def check_announcement_needs_update(self, message, recruitment_data):
        """공고 메시지가 업데이트가 필요한지 확인합니다."""
        try:
            # 기본값은 업데이트 필요 없음
            needs_update = False
            
            # 임베드가 없으면 업데이트 필요
            if not message.embeds:
                return True
            
            embed = message.embeds[0]
            
            # 필수 필드 확인
            if not embed.fields:
                return True
            
            # 던전 정보 확인
            dungeon_field = next((f for f in embed.fields if f.name == "던전"), None)
            db_dungeon = f"{recruitment_data.get('type', '')} > {recruitment_data.get('dungeon', '')} [{recruitment_data.get('difficulty', '')}]"
            if not dungeon_field or dungeon_field.value != db_dungeon:
                return True
            
            # 모집 내용 확인
            description_field = next((f for f in embed.fields if f.name == "모집 내용"), None)
            if not description_field or description_field.value != recruitment_data.get('description', ''):
                return True
            
            # 모집 인원 확인
            members_field = next((f for f in embed.fields if f.name == "모집 인원"), None)
            max_participants = recruitment_data.get('max_participants', 4)
            participants = recruitment_data.get('participants', [])
            db_members_text = f"{len(participants)}/{max_participants}"
            if not members_field or not members_field.value.startswith(db_members_text):
                return True
            
            # 상태 확인
            status_field = next((f for f in embed.fields if f.name == "상태"), None)
            db_status = recruitment_data.get('status', 'active')
            message_status = "모집중" if db_status == "active" else ("모집완료" if db_status == "complete" else "취소됨")
            if not status_field or status_field.value != message_status:
                return True
            
            return needs_update
            
        except Exception as e:
            logger.error(f"공고 업데이트 필요성 확인 중 오류 발생: {e}")
            logger.error(traceback.format_exc())
            # 오류 발생 시 안전하게 업데이트 필요로 간주
            return True

    async def get_recruitments_by_guild(self, guild_id, status="active"):
        """데이터베이스에서 특정 길드의 모집 정보를 가져옵니다."""
        try:
            # 길드 ID 문자열로 변환 (안전을 위해)
            guild_id = str(guild_id)
            
            # 데이터베이스에서 모집 정보 조회
            query = {"guild_id": guild_id}
            
            # 상태 필터 적용
            if status:
                query["status"] = status
            
            # 모집 정보 조회 (최신순)
            recruitments = await self.db["recruitments"].find(query).sort("created_at", -1).to_list(length=None)
            
            logger.info(f"서버 {guild_id}에서 상태가 {status}인 모집 {len(recruitments)}개를 조회했습니다.")
            
            return recruitments
            
        except Exception as e:
            logger.error(f"모집 정보 조회 중 오류 발생: {e}")
            logger.error(traceback.format_exc())
            return []

    async def get_recruitment_by_id(self, recruitment_id):
        """데이터베이스에서 모집 ID로 특정 모집 정보를 가져옵니다."""
        try:
            # 모집 ID로 모집 정보 조회
            recruitment = await self.db["recruitments"].find_one({"_id": ObjectId(recruitment_id)})
            
            if recruitment:
                logger.info(f"모집 ID {recruitment_id}에 대한 정보를 조회했습니다.")
            else:
                logger.warning(f"모집 ID {recruitment_id}에 대한 정보를 찾을 수 없습니다.")
            
            return recruitment
            
        except Exception as e:
            logger.error(f"모집 정보 조회 중 오류 발생: {e}")
            logger.error(traceback.format_exc())
            return None

    @app_commands.command(name="모집목록", description="서버의 모든 모집 목록을 보여줍니다.")
    async def list_recruitments(self, interaction: discord.Interaction, 상태: str = "모집중"):
        """서버의 모집 목록을 보여주는 명령어"""
        try:
            # 입력된 상태를 DB에서 사용하는 형식으로 변환
            status_map = {
                "모집중": "active",
                "완료": "complete",
                "취소": "cancelled",
                "전체": None
            }
            
            status = status_map.get(상태, "active")
            
            # 서버 ID
            guild_id = str(interaction.guild_id)
            
            # 모집 정보 조회
            recruitments = await self.get_recruitments_by_guild(guild_id, status)
            
            if not recruitments:
                await interaction.response.send_message(f"현재 서버에 {상태} 상태인 모집이 없습니다.", ephemeral=True)
                return
            
            # 임베드 생성
            embed = discord.Embed(
                title=f"모집 목록 ({상태})",
                description=f"총 {len(recruitments)}개의 모집이 있습니다.",
                color=discord.Color.blue()
            )
            
            # 각 모집 정보 추가
            for i, recruitment in enumerate(recruitments[:10]):  # 최대 10개만 표시
                recruitment_id = str(recruitment.get("_id"))
                dungeon_type = recruitment.get("type", "")
                dungeon_name = recruitment.get("dungeon", "")
                difficulty = recruitment.get("difficulty", "")
                description = recruitment.get("description", "")
                max_participants = recruitment.get("max_participants", 4)
                participants = recruitment.get("participants", [])
                
                # 필드 값 생성
                field_value = (
                    f"**던전**: {dungeon_type} > {dungeon_name} [{difficulty}]\n"
                    f"**내용**: {description[:50]}{'...' if len(description) > 50 else ''}\n"
                    f"**인원**: {len(participants)}/{max_participants}\n"
                    f"**ID**: {recruitment_id}"
                )
                
                embed.add_field(
                    name=f"{i+1}. {dungeon_name} [{difficulty}]",
                    value=field_value,
                    inline=False
                )
            
            # 10개 초과인 경우 안내 추가
            if len(recruitments) > 10:
                embed.set_footer(text=f"총 {len(recruitments)}개 중 10개만 표시됩니다.")
            
            await interaction.response.send_message(embed=embed, ephemeral=True)
            
        except Exception as e:
            logger.error(f"모집 목록 표시 중 오류 발생: {e}")
            logger.error(traceback.format_exc())
            await interaction.response.send_message("모집 목록을 불러오는 중 오류가 발생했습니다.", ephemeral=True)

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
        guild_name = message.guild.name
        
        # 허용되지 않은 길드는 무시
        if not self.is_allowed_guild(guild_id):
            logger.debug(f"허용되지 않은 길드에서 메시지 수신: ID={guild_id}, 이름={guild_name}, 채널={message.channel.name}, 사용자={message.author.name}")
            return
            
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
        """모집 등록 양식을 생성합니다."""
        try:
            logger.info(f"채널 {channel.id}에 모집 등록 양식 생성 시도")
            
            # 기존 등록 양식 확인 및 삭제
            try:
                # 봇이 보낸 메시지 중 모집 등록 양식인지 확인하여 삭제
                existing_forms = []
                async for message in channel.history(limit=10):
                    if message.author.id == self.bot.user.id and message.embeds:
                        for embed in message.embeds:
                            if embed.title and "파티 모집 등록 양식" in embed.title:
                                existing_forms.append(message)
                
                # 중복 양식이 있으면 모두 삭제
                if len(existing_forms) > 0:
                    logger.info(f"채널 {channel.id}에서 기존 등록 양식 {len(existing_forms)}개 발견, 삭제 시도")
                    for form in existing_forms:
                        try:
                            await form.delete()
                            logger.info(f"채널 {channel.id}의 기존 등록 양식 삭제 완료: {form.id}")
                        except Exception as delete_error:
                            logger.error(f"기존 등록 양식 삭제 중 오류: {delete_error}")
                    
                    # 삭제 후 잠시 대기 (API 속도 제한 방지)
                    await asyncio.sleep(1)
            except Exception as e:
                logger.error(f"기존 등록 양식 확인 및 삭제 중 오류: {e}")
                logger.error(traceback.format_exc())
            
            # 새 임베드 생성
            embed = discord.Embed(
                title="파티 모집 등록 양식",
                description="아래 버튼을 클릭하여 파티 모집을 등록하세요.",
                color=discord.Color.blue()
            )
            
            embed.set_author(name=f"동글봇")
            embed.set_footer(text=f"채널: {channel.name} | ID: {channel.id}")
            
            # 모집 등록 양식 뷰 생성
            view = RecruitmentCard(self.dungeons, self.db)
            view.registration_channel_id = str(channel.id)
            
            # 모집 등록 양식 메시지 보내기
            try:
                message = await channel.send(embed=embed, view=view)
                view.message = message
                logger.info(f"채널 {channel.id}에 모집 등록 양식 생성 완료: {message.id}")
                return message
            except Exception as e:
                logger.error(f"모집 등록 양식 메시지 전송 중 오류: {e}")
                logger.error(traceback.format_exc())
                return None
                
        except Exception as e:
            logger.error(f"모집 등록 양식 생성 중 오류: {e}")
            logger.error(traceback.format_exc())
            return None

    async def post_recruitment_announcement(self, guild_id, recruitment_data, view):
        """모집 공고를 공고 채널에 게시합니다."""
        try:
            if not self.is_allowed_guild(guild_id):
                return None
            
            logger.info(f"서버 {guild_id}의 모집 ID {view.recruitment_id}에 대한 공고 게시 시작")
            
            # 길드 객체 가져오기
            guild = self.bot.get_guild(int(guild_id))
            if not guild:
                logger.error(f"서버를 찾을 수 없음: {guild_id}")
                return None
            
            # 모집 정보에서 등록 채널 ID 확인
            registration_channel_id = str(recruitment_data.get("registration_channel_id", "0"))
            if registration_channel_id == "0" or not registration_channel_id:
                logger.warning(f"모집 {view.recruitment_id}의 등록 채널 ID가 없습니다. 기본 공고 채널을 사용합니다.")
                
                # 공고 채널 ID 가져오기
                announcement_channel_id = self.announcement_channels.get(guild_id)
                if not announcement_channel_id:
                    logger.error(f"서버 {guild_id}의 공고 채널을 찾을 수 없음")
                    return None
                
                # 채널 객체 가져오기
                announcement_channel = guild.get_channel(int(announcement_channel_id))
                if not announcement_channel:
                    logger.error(f"서버 {guild_id}의 공고 채널 객체를 가져올 수 없음: {announcement_channel_id}")
                    return None
                    
                logger.info(f"서버 {guild_id}의 기본 공고 채널에 모집 공고를 게시합니다: {announcement_channel_id}")
            else:
                # 페어링된 채널 확인
                logger.info(f"모집 {view.recruitment_id}의 등록 채널 ID: {registration_channel_id}")
                
                # 해당 등록 채널에 대응하는 공고 채널 확인
                if guild_id in self.channel_pairs and registration_channel_id in self.channel_pairs[guild_id]:
                    # 채널 페어링이 존재하는 경우, 해당 공고 채널 사용
                    announcement_channel_id = self.channel_pairs[guild_id][registration_channel_id]
                    logger.info(f"서버 {guild_id}의 페어링된 공고 채널을 사용합니다: {announcement_channel_id}")
                    
                    # 채널 객체 가져오기
                    announcement_channel = guild.get_channel(int(announcement_channel_id))
                    if not announcement_channel:
                        logger.error(f"서버 {guild_id}의 페어링된 공고 채널 객체를 가져올 수 없음: {announcement_channel_id}")
                        
                        # 대체로 기본 공고 채널 사용
                        fallback_channel_id = self.announcement_channels.get(guild_id)
                        if not fallback_channel_id:
                            logger.error(f"서버 {guild_id}의 대체 공고 채널도 찾을 수 없음")
                            return None
                            
                        announcement_channel = guild.get_channel(int(fallback_channel_id))
                        if not announcement_channel:
                            logger.error(f"서버 {guild_id}의 대체 공고 채널 객체도 가져올 수 없음: {fallback_channel_id}")
                            return None
                            
                        logger.warning(f"서버 {guild_id}의 페어링된 공고 채널을 찾을 수 없어 기본 채널로 대체: {fallback_channel_id}")
                else:
                    # 채널 페어링이 없는 경우, 기본 공고 채널 사용
                    logger.info(f"서버 {guild_id}의 등록 채널 {registration_channel_id}에 대한 페어링이 없어 기본 공고 채널을 사용합니다.")
                    announcement_channel_id = self.announcement_channels.get(guild_id)
                    if not announcement_channel_id:
                        logger.error(f"서버 {guild_id}의 공고 채널을 찾을 수 없음")
                        return None
                    
                    # 채널 객체 가져오기
                    announcement_channel = guild.get_channel(int(announcement_channel_id))
                    if not announcement_channel:
                        logger.error(f"서버 {guild_id}의 공고 채널 객체를 가져올 수 없음: {announcement_channel_id}")
                        return None
            
            # 공고용 임베드 생성
            embed = view.get_embed()
            embed.title = "파티 모집 공고"
            
            # 공고용 뷰 생성 (deepcopy 대신 새 객체 생성)
            announcement_view = RecruitmentCard(self.dungeons, self.db)
            
            # 필요한 속성만 복사
            announcement_view.recruitment_id = view.recruitment_id
            announcement_view.selected_type = view.selected_type
            announcement_view.selected_kind = view.selected_kind
            announcement_view.selected_diff = view.selected_diff
            announcement_view.recruitment_content = view.recruitment_content
            announcement_view.max_participants = view.max_participants
            announcement_view.status = view.status
            
            # participants 복사 (list는 얕은 복사로 충분)
            if hasattr(view, 'participants') and view.participants:
                announcement_view.participants = view.participants.copy()
            else:
                announcement_view.participants = []
                
            # creator_id 복사
            if hasattr(view, 'creator_id'):
                announcement_view.creator_id = view.creator_id
            
            # 기존 항목 제거 (이미 새 객체라 필요 없지만 안전을 위해 유지)
            announcement_view.clear_items()
            
            # 참가하기 버튼 추가 (row 0)
            join_button = discord.ui.Button(label="참가하기", style=discord.ButtonStyle.success, custom_id="btn_join", row=0)
            join_button.callback = announcement_view.btn_join_callback
            announcement_view.add_item(join_button)
            
            # 신청 취소 버튼 추가 (row 0)
            cancel_button = discord.ui.Button(label="신청 취소", style=discord.ButtonStyle.danger, custom_id="btn_cancel", row=0)
            cancel_button.callback = announcement_view.btn_cancel_callback
            announcement_view.add_item(cancel_button)
            
            # 모집 취소 버튼 추가 (첫 번째 참가자에게만 보이도록 - row 1)
            # 참가자 목록이 있고 첫 번째 참가자 ID가 있을 경우에만 추가
            first_participant_id = None
            if hasattr(announcement_view, 'participants') and announcement_view.participants:
                try:
                    first_participant_id = int(announcement_view.participants[0])
                except (ValueError, TypeError):
                    logger.warning(f"첫 번째 참가자 ID를 정수로 변환할 수 없음: {announcement_view.participants[0]}")
            
            if first_participant_id:
                delete_button = CreatorOnlyButton(
                    label="모집 취소", 
                    style=discord.ButtonStyle.danger, 
                    custom_id="btn_delete", 
                    callback=announcement_view.btn_delete_callback,
                    creator_id=first_participant_id,
                    row=1
                )
                announcement_view.add_item(delete_button)
                logger.debug(f"모집 취소 버튼이 첫 번째 참가자 ID {first_participant_id}에게 표시됩니다.")
            
            # 공고 전송
            try:
                announcement_message = await announcement_channel.send(embed=embed, view=announcement_view)
                announcement_view.message = announcement_message
                
                # DB 업데이트 (메시지 ID, 채널 ID)
                await self.db["recruitments"].update_one(
                    {"_id": ObjectId(view.recruitment_id)},
                    {"$set": {
                        "announcement_message_id": str(announcement_message.id),
                        "announcement_channel_id": str(announcement_channel.id),
                        "registration_channel_id": registration_channel_id,  # 등록 채널 ID도 함께 저장
                        "updated_at": datetime.now().isoformat()
                    }}
                )
                
                logger.info(f"서버 {guild_id}의 모집 ID {view.recruitment_id}에 대한 공고가 채널 {announcement_channel.id}에 성공적으로 게시되었습니다.")
                return announcement_message
                
            except Exception as e:
                logger.error(f"공고 메시지 전송 중 오류: {e}")
                logger.error(traceback.format_exc())
                return None
                
        except Exception as e:
            logger.error(f"모집 공고 게시 중 오류: {e}")
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
                name="/쓰레드채널설정",
                value="파티 모집 완료 시 비밀 쓰레드가 생성될 채널을 설정합니다. (관리자 전용)",
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
        """Cog 언로드시 호출되는 메서드"""
        logger.info("Party cog unloading...")
        # 작업 취소
        self.initialize_and_cleanup.cancel()
        self.refresh_registration_forms.cancel()  # 새로 추가된 양식 갱신 작업 취소
        logger.info("Party cog unloaded")

    @tasks.loop(minutes=10)  # 10분마다 실행
    async def initialize_and_cleanup(self):
        logger.info("[DEBUG] 채널 초기화 및 정리 시작")
        try:
            # 모든 서버에 대해 채널 초기화 및 정리 수행
            for guild in self.bot.guilds:
                try:
                    logger.info(f"[DEBUG] 서버 {guild.id} 처리 시작")
                    # 채널 초기화
                    await self.initialize_channels(force_retry=True)
                    
                    # 활성 모집 처리
                    active_recruitments = await self.get_recruitments_by_guild(str(guild.id), status="active")
                    if active_recruitments:
                        logger.info(f"[DEBUG] 서버 {guild.id}의 활성 모집 {len(active_recruitments)}개 발견")
                        for channel_id in self.announcement_channels.get(str(guild.id), []):
                            channel = guild.get_channel(int(channel_id))
                            if channel:
                                await self.process_active_recruitments(guild, str(guild.id), active_recruitments, channel)
                    
                    # 채널 정리
                    for channel_id in self.announcement_channels.get(str(guild.id), []):
                        await self.force_cleanup_channel(str(guild.id), channel_id)
                        
                except Exception as e:
                    logger.error(f"[DEBUG] 서버 {guild.id} 처리 중 오류: {e}")
                    continue
                    
        except Exception as e:
            logger.error(f"[DEBUG] initialize_and_cleanup 전체 오류: {e}")
            logger.error(traceback.format_exc())

    @initialize_and_cleanup.before_loop
    async def before_initialize_and_cleanup(self):
        """initialize_and_cleanup 작업 시작 전 실행되는 메서드"""
        logger.debug("봇 상태 체크 작업 준비 중...")
        await self.bot.wait_until_ready()  # 봇이 준비될 때까지 대기
        logger.debug("봇 상태 체크 작업 시작")

    async def force_cleanup_channel(self, guild_id, channel_id):
        """특정 채널의 완료된 모집 메시지를 강제로 삭제합니다."""
        # 허용된 길드인지 확인
        guild = self.bot.get_guild(int(guild_id))
        guild_name = guild.name if guild else "알 수 없음"
        
        if not self.is_allowed_guild(guild_id):
            logger.debug(f"허용되지 않은 길드의 채널 정리 요청 무시: ID={guild_id}, 이름={guild_name}")
            return
            
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
            
            # 누락된 활성 모집 공고는 process_active_recruitments에서 처리하도록 변경
            # 활성 모집 ID별로 채널 내 메시지 집계
            duplicate_messages = {}  # 여기에 duplicate_messages 변수 정의 추가
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
            updated_count = 0
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
                            
                            # 활성 모집의 경우 상호작용을 갱신
                            try:
                                # 모집 데이터 가져오기
                                recruitment = await self.db.recruitments.find_one({"_id": ObjectId(recruitment_id)})
                                if recruitment:
                                    # 해당 모집 데이터로 뷰 생성
                                    from views.recruitment_card import RecruitmentCard
                                    view = RecruitmentCard(self.dungeons, self.db)
                                    view.recruitment_id = recruitment_id
                                    view.selected_type = recruitment.get("dungeon_type")
                                    view.selected_kind = recruitment.get("dungeon_kind") 
                                    view.selected_diff = recruitment.get("dungeon_difficulty")
                                    view.recruitment_content = recruitment.get("content")
                                    view.max_participants = recruitment.get("max_participants")
                                    view.status = recruitment.get("status", "active")
                                    view.participants = [str(p) for p in recruitment.get("participants", [])]
                                    
                                    # 임베드 생성
                                    embed = view.get_embed()
                                    
                                    # 버튼 설정
                                    view.clear_items()
                                    
                                    # 참가하기 버튼 추가
                                    join_button = discord.ui.Button(label="참가하기", style=discord.ButtonStyle.success, custom_id="btn_join", row=0)
                                    join_button.callback = view.btn_join_callback
                                    view.add_item(join_button)
                                    
                                    # 신청 취소 버튼 추가
                                    cancel_button = discord.ui.Button(label="신청 취소", style=discord.ButtonStyle.danger, custom_id="btn_cancel", row=0)
                                    cancel_button.callback = view.btn_cancel_callback
                                    view.add_item(cancel_button)
                                    
                                    # 첫 번째 참가자에게만 모집 취소 버튼 표시
                                    if view.participants and len(view.participants) > 0:
                                        first_participant_id = None
                                        try:
                                            first_participant_id = int(view.participants[0]) if isinstance(view.participants[0], str) else view.participants[0]
                                        except (ValueError, TypeError):
                                            logger.warning(f"첫 번째 참가자 ID를 정수로 변환할 수 없음: {view.participants[0]}")
                                        
                                        if first_participant_id:
                                            from views.recruitment_card import CreatorOnlyButton
                                            delete_button = CreatorOnlyButton(
                                                label="모집 취소",
                                                style=discord.ButtonStyle.danger,
                                                custom_id="btn_delete",
                                                callback=view.btn_delete_callback,
                                                creator_id=first_participant_id,
                                                row=1
                                            )
                                            view.add_item(delete_button)
                                    
                                    # 메시지 업데이트
                                    await message.edit(embed=embed, view=view)
                                    view.message = message
                                    updated_count += 1
                                    logger.debug(f"서버 {guild_id}의 모집 ID {recruitment_id}의 메시지를 갱신했습니다.")
                            except Exception as e:
                                logger.error(f"활성 모집 메시지 갱신 중 오류 발생: {e}")
                                logger.error(traceback.format_exc())
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
            
            logger.debug(f"서버 {guild_id}의 채널 정리 완료: {deleted_count}개의 메시지가 삭제되었고, {updated_count}개의 메시지가 갱신되었습니다.")
        
        except Exception as e:
            logger.error(f"강제 채널 정리 중 오류 발생: {e}")
            logger.error(traceback.format_exc())

    @app_commands.command(name="모집채널설정", description="모집 공고를 게시할 채널을 설정합니다.")
    @app_commands.checks.has_permissions(administrator=True)
    async def set_announcement_channel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        """모집 공고 채널을 설정하는 명령어"""
        try:
            logger.info(f"[DEBUG] 모집채널설정 명령어 시작 - 사용자: {interaction.user.id}, 서버: {interaction.guild.id}, 채널: {channel.id}")
            await interaction.response.defer(ephemeral=True)
            
            # 내부 메서드 호출
            result = await self.set_announcement_channel_internal(interaction, channel)
            logger.info(f"[DEBUG] 모집채널설정 명령어 완료 - 결과: {result}")
            
        except Exception as e:
            logger.error(f"[DEBUG] 모집채널설정 명령어 오류: {e}")
            logger.error(traceback.format_exc())
            try:
                await interaction.followup.send("모집 공고 채널 설정 중 오류가 발생했습니다.", ephemeral=True)
            except:
                logger.error("[DEBUG] 모집채널설정 에러 메시지 전송 실패")

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
        """모집 등록 양식을 게시할 채널을 설정하는 명령어"""
        try:
            logger.info(f"[DEBUG] 모집등록채널설정 명령어 시작 - 사용자: {interaction.user.id}, 서버: {interaction.guild.id}, 채널: {channel.id}")
            # 응답 지연 (더 긴 작업을 위해)
            await interaction.response.defer(ephemeral=True)
            
            guild_id = str(interaction.guild.id)
            channel_id = str(channel.id)
            
            # 디버그 정보 추가
            try:
                permission_check = channel.permissions_for(interaction.guild.me)
                logger.info(f"[DEBUG] 채널 권한 확인: 메시지 보내기={permission_check.send_messages}, 메시지 관리={permission_check.manage_messages}")
            except Exception as e:
                logger.error(f"[DEBUG] 권한 체크 중 오류: {e}")
            
            # DB에 저장
            try:
                await self.db["settings"].update_one(
                    {"guild_id": guild_id},
                    {"$set": {"registration_channel_id": channel_id}},
                    upsert=True
                )
                logger.info(f"[DEBUG] DB 업데이트 성공 - guild_id: {guild_id}, channel_id: {channel_id}")
            except Exception as e:
                logger.error(f"[DEBUG] DB 업데이트 오류: {e}")
                raise
            
            # 캐시 업데이트
            self.registration_channels[guild_id] = channel_id
            
            # 기존 채널과 페어링 확인 및 설정
            if guild_id not in self.channel_pairs:
                self.channel_pairs[guild_id] = {}
            
            # 채널 초기화 - 기존 메시지 삭제
            try:
                delete_count = 0
                async for message in channel.history(limit=50):
                    if message.author.id == self.bot.user.id:
                        await message.delete()
                        delete_count += 1
                logger.info(f"[DEBUG] 채널 메시지 삭제 성공 - {delete_count}개 삭제됨")
            except Exception as e:
                logger.error(f"[DEBUG] 채널 메시지 삭제 오류: {e}")
                logger.error(traceback.format_exc())
            
            # 새 등록 양식 생성
            try:
                form = await self.create_registration_form(channel)
                if form:
                    logger.info(f"[DEBUG] 등록 양식 생성 성공 - 메시지 ID: {form.id}")
                else:
                    logger.error("[DEBUG] 등록 양식 생성 실패 - 반환값 없음")
            except Exception as e:
                logger.error(f"[DEBUG] 등록 양식 생성 중 오류: {e}")
                logger.error(traceback.format_exc())
                raise
            
            # 응답 전송
            await interaction.followup.send(f"모집 등록 양식이 {channel.mention}에 생성되었습니다.", ephemeral=True)
            logger.info(f"[DEBUG] 모집등록채널설정 명령어 완료 - 서버: {guild_id}")
            
        except Exception as e:
            logger.error(f"[DEBUG] 모집등록채널설정 명령어 전체 오류: {e}")
            logger.error(traceback.format_exc())
            try:
                await interaction.followup.send("모집 등록 채널 설정 중 오류가 발생했습니다.", ephemeral=True)
            except:
                logger.error("[DEBUG] 모집등록채널설정 에러 메시지 전송 실패")
    
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

    # 길드 ID 유효성 검사 메서드 추가
    def is_allowed_guild(self, guild_id):
        """허용된 길드인지 확인합니다."""
        guild_id_str = str(guild_id)
        
        # 길드 정보 디버그
        logger.info(f"[DEBUG] is_allowed_guild 호출 - 길드 ID: {guild_id_str}")
        
        # 무조건 허용하도록 수정
        is_allowed = True
        
        # 길드 이름 가져오기 시도
        guild_name = "알 수 없음"
        guild = self.bot.get_guild(int(guild_id_str))
        if guild:
            guild_name = guild.name
            logger.info(f"[DEBUG] 길드 정보 - 이름: {guild_name}, ID: {guild_id_str}")
        else:
            logger.info(f"[DEBUG] 길드 객체를 찾을 수 없음 - ID: {guild_id_str}")
        
        # 없는 경우 allowed_guild_ids에 추가
        if guild_id_str not in self.allowed_guild_ids:
            logger.info(f"[DEBUG] 새로운 길드 허용 추가 - ID: {guild_id_str}")
            self.allowed_guild_ids[guild_id_str] = True
        
        logger.info(f"허용된 길드 접근: ID={guild_id_str}, 이름={guild_name}")
        
        return is_allowed

    # 각 명령어에 대한 길드 ID 검사 추가
    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """앱 명령어 상호작용 전 권한을 확인합니다."""
        # 상호작용이 서버에서 실행되었는지 확인
        if not interaction.guild_id:
            try:
                logger.info(f"[DEBUG] 서버 외부 명령어 시도 - 사용자: {interaction.user.id}, 명령어: {interaction.command.name if interaction.command else '알 수 없음'}")
                await interaction.response.send_message("이 명령어는 서버에서만 사용할 수 있습니다.", ephemeral=True)
            except Exception as e:
                logger.error(f"[DEBUG] 서버 외부 응답 오류: {e}")
                # 이미 응답이 시작된 경우
                try:
                    await interaction.followup.send("이 명령어는 서버에서만 사용할 수 있습니다.", ephemeral=True)
                except Exception as e:
                    logger.error(f"[DEBUG] 서버 외부 followup 응답 오류: {e}")
            
            logger.warning(f"서버 외부에서 명령어 사용 시도: 사용자={interaction.user.name}, 명령어={interaction.command.name if interaction.command else '알 수 없음'}")
            return False
        
        # 허용된 길드인지 확인
        guild_id = str(interaction.guild_id)
        guild_name = interaction.guild.name if interaction.guild else "알 수 없음"
        
        # 허용 여부 디버그 로그 추가
        logger.info(f"[DEBUG] 길드 권한 체크 - 길드 ID: {guild_id}, 길드 이름: {guild_name}")
        logger.info(f"[DEBUG] 허용된 길드 목록: {self.allowed_guild_ids}")
        is_allowed = self.is_allowed_guild(guild_id)
        logger.info(f"[DEBUG] 길드 허용 여부: {is_allowed}")
        
        if not is_allowed:
            try:
                logger.info(f"[DEBUG] 허용되지 않은 길드 응답 시도 - 사용자: {interaction.user.id}")
                await interaction.response.send_message("이 봇은 동글봇 개발팀과 연동된 서버만 사용 가능합니다.", ephemeral=True)
            except Exception as e:
                logger.error(f"[DEBUG] 허용되지 않은 길드 응답 오류: {e}")
                # 이미 응답이 시작된 경우
                try:
                    await interaction.followup.send("이 봇은 동글봇 개발팀과 연동된 서버만 사용 가능합니다.", ephemeral=True)
                except Exception as e:
                    logger.error(f"[DEBUG] 허용되지 않은 길드 followup 응답 오류: {e}")
                
            logger.warning(f"허용되지 않은 길드에서 명령어 사용 시도: ID={guild_id}, 이름={guild_name}, 사용자={interaction.user.name}, 명령어={interaction.command.name if interaction.command else '알 수 없음'}")
            return False
        
        logger.info(f"명령어 사용: 길드={guild_name}({guild_id}), 사용자={interaction.user.name}, 명령어={interaction.command.name if interaction.command else '알 수 없음'}")
        return True

    # 명령어 실행 전 권한 확인 메서드 추가
    async def cog_check(self, ctx):
        """Cog 명령어 실행 전 권한을 확인합니다."""
        # 서버에서 실행된 명령어인지 확인
        if not ctx.guild:
            return False
        
        # 허용된 길드인지 확인
        return self.is_allowed_guild(ctx.guild.id)

    @app_commands.command(name="쓰레드채널설정", description="파티 모집 완료 시 비밀 쓰레드가 생성될 채널을 설정합니다.")
    @app_commands.checks.has_permissions(administrator=True)
    async def set_thread_channel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        """비밀 쓰레드가 생성될 채널을 설정하는 명령어"""
        try:
            guild_id = str(interaction.guild.id)
            channel_id = str(channel.id)
            
            # DB에 저장
            await self.db["settings"].update_one(
                {"guild_id": guild_id},
                {"$set": {"thread_channel_id": channel_id}},
                upsert=True
            )
            
            await interaction.response.send_message(f"비밀 쓰레드 생성 채널이 {channel.mention}으로 설정되었습니다.", ephemeral=True)
            logger.info(f"서버 {guild_id}의 쓰레드 채널 설정: {channel_id}")
        except Exception as e:
            logger.error(f"쓰레드 채널 설정 중 오류 발생: {e}")
            logger.error(traceback.format_exc())
            await interaction.response.send_message("쓰레드 채널 설정 중 오류가 발생했습니다.", ephemeral=True)

    @set_thread_channel.error
    async def thread_channel_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        """쓰레드 채널 설정 중 오류 처리"""
        if isinstance(error, app_commands.errors.MissingPermissions):
            await interaction.response.send_message("이 명령어는 관리자만 사용할 수 있습니다.", ephemeral=True)
        else:
            logger.error(f"쓰레드 채널 설정 중 오류: {error}")
            await interaction.response.send_message("명령어 실행 중 오류가 발생했습니다.", ephemeral=True)

    @tasks.loop(minutes=15)  # 15분마다 실행 
    async def refresh_registration_forms(self):
        """모집 등록 양식을 주기적으로 갱신합니다."""
        try:
            logger.info("모집 등록 양식 갱신 작업 시작...")
            if not self.registration_channels:
                logger.info("등록된 모집 등록 채널이 없습니다.")
                return
            
            # 각 서버별로 등록 양식 갱신
            for guild_id, channel_id in self.registration_channels.items():
                try:
                    # 서버 객체 가져오기
                    guild = self.bot.get_guild(int(guild_id))
                    if not guild:
                        logger.warning(f"모집 양식 갱신 - 서버를 찾을 수 없음: {guild_id}")
                        continue
                    
                    # 채널 객체 가져오기
                    channel = guild.get_channel(int(channel_id))
                    if not channel:
                        logger.warning(f"모집 양식 갱신 - 서버 {guild_id}의 등록 채널을 찾을 수 없음: {channel_id}")
                        continue
                    
                    # 채널 메시지 일괄 삭제 시도 (2주 이내 메시지만 가능)
                    try:
                        # 일괄 삭제 시도
                        deleted = await channel.purge(limit=50, check=lambda m: m.author.id == self.bot.user.id)
                        deleted_count = len(deleted)
                        logger.info(f"모집 양식 갱신 - 서버 {guild_id}의 등록 채널에서 {deleted_count}개 메시지 일괄 삭제 성공")
                    except Exception as bulk_error:
                        # 일괄 삭제 실패 시 개별 삭제 시도
                        logger.warning(f"모집 양식 갱신 - 일괄 삭제 실패, 개별 삭제 시도: {bulk_error}")
                        deleted_count = 0
                        try:
                            async for message in channel.history(limit=30):
                                if message.author.id == self.bot.user.id:
                                    try:
                                        await message.delete()
                                        deleted_count += 1
                                        await asyncio.sleep(0.5)  # API 속도 제한 방지
                                    except Exception as e:
                                        logger.error(f"모집 양식 갱신 - 메시지 삭제 중 오류: {e}")
                            logger.info(f"모집 양식 갱신 - 서버 {guild_id}의 등록 채널에서 {deleted_count}개 메시지 개별 삭제")
                        except Exception as e:
                            logger.error(f"모집 양식 갱신 - 채널 히스토리 조회 중 오류: {e}")
                    
                    # 새 등록 양식 생성 전 잠시 대기
                    await asyncio.sleep(2)  # 삭제 후 생성 간 충분한 대기 시간 확보
                    
                    # 새 등록 양식 생성
                    try:
                        new_form = await self.create_registration_form(channel)
                        if new_form:
                            logger.info(f"모집 양식 갱신 - 서버 {guild_id}의 등록 채널에 새 양식 생성 성공 (메시지 ID: {new_form.id})")
                        else:
                            logger.error(f"모집 양식 갱신 - 서버 {guild_id}의 등록 채널에 새 양식 생성 실패 (반환값 없음)")
                    except Exception as form_error:
                        logger.error(f"모집 양식 갱신 - 서버 {guild_id}의 등록 채널에 새 양식 생성 중 오류: {form_error}")
                        logger.error(traceback.format_exc())
                    
                    logger.info(f"서버 {guild_id}의 모집 등록 양식 자동 갱신 완료")
                    
                except Exception as e:
                    logger.error(f"모집 양식 갱신 - 서버 {guild_id}의 양식 갱신 중 오류: {e}")
                    logger.error(traceback.format_exc())
            
            logger.info("모집 등록 양식 갱신 작업 완료")
            
        except Exception as e:
            logger.error(f"모집 양식 갱신 작업 중 오류 발생: {e}")
            logger.error(traceback.format_exc())

    @refresh_registration_forms.before_loop
    async def before_refresh_registration_forms(self):
        """양식 갱신 작업 시작 전 실행되는 메서드"""
        logger.debug("모집 등록 양식 갱신 작업 준비 중...")
        await self.bot.wait_until_ready()  # 봇이 준비될 때까지 대기
        logger.debug("모집 등록 양식 갱신 작업 시작")

    @app_commands.command(name="모집_양식_갱신", description="모집 등록 양식을 갱신합니다.")
    @app_commands.checks.has_permissions(administrator=True)
    async def refresh_registration_form(self, interaction: discord.Interaction):
        """모집 등록 양식을 갱신하는 명령어"""
        try:
            guild_id = str(interaction.guild.id)
            
            # 등록된 모집 등록 채널 확인
            if guild_id not in self.registration_channels:
                await interaction.response.send_message("모집 등록 채널이 설정되지 않았습니다. 먼저 `/모집등록채널설정` 명령어를 사용해주세요.", ephemeral=True)
                return
            
            channel_id = self.registration_channels[guild_id]
            channel = interaction.guild.get_channel(int(channel_id))
            
            if not channel:
                await interaction.response.send_message("모집 등록 채널을 찾을 수 없습니다. 다시 `/모집등록채널설정` 명령어를 사용해주세요.", ephemeral=True)
                return
            
            await interaction.response.defer(ephemeral=True)
            
            # 채널 메시지 일괄 삭제 시도 (2주 이내 메시지만 가능)
            try:
                # 일괄 삭제 시도
                deleted = await channel.purge(limit=50, check=lambda m: m.author.id == self.bot.user.id)
                deleted_count = len(deleted)
                logger.info(f"모집 양식 갱신 - 서버 {guild_id}의 등록 채널에서 {deleted_count}개 메시지 일괄 삭제 성공")
            except Exception as bulk_error:
                # 일괄 삭제 실패 시 개별 삭제 시도
                logger.warning(f"모집 양식 갱신 - 일괄 삭제 실패, 개별 삭제 시도: {bulk_error}")
                deleted_count = 0
                try:
                    async for message in channel.history(limit=30):
                        if message.author.id == self.bot.user.id:
                            try:
                                await message.delete()
                                deleted_count += 1
                                await asyncio.sleep(0.5)  # API 속도 제한 방지
                            except Exception as e:
                                logger.error(f"모집 양식 갱신 - 메시지 삭제 중 오류: {e}")
                    logger.info(f"모집 양식 갱신 - 서버 {guild_id}의 등록 채널에서 {deleted_count}개 메시지 개별 삭제")
                except Exception as e:
                    logger.error(f"모집 양식 갱신 - 채널 히스토리 조회 중 오류: {e}")
            
            # 새 등록 양식 생성 전 잠시 대기
            await asyncio.sleep(2)  # 삭제 후 생성 간 충분한 대기 시간 확보
            
            # 새 등록 양식 생성
            try:
                new_form = await self.create_registration_form(channel)
                if new_form:
                    logger.info(f"모집 양식 갱신 - 서버 {guild_id}의 등록 채널에 새 양식 생성 성공 (메시지 ID: {new_form.id})")
                    await interaction.followup.send(f"모집 등록 양식이 갱신되었습니다. {deleted_count}개의 이전 양식이 삭제되었습니다.", ephemeral=True)
                else:
                    logger.error(f"모집 양식 갱신 - 서버 {guild_id}의 등록 채널에 새 양식 생성 실패 (반환값 없음)")
                    await interaction.followup.send("모집 등록 양식 갱신이 완료되었으나, 새 양식 생성에 문제가 있을 수 있습니다.", ephemeral=True)
            except Exception as form_error:
                logger.error(f"모집 양식 갱신 - 서버 {guild_id}의 등록 채널에 새 양식 생성 중 오류: {form_error}")
                logger.error(traceback.format_exc())
                await interaction.followup.send("모집 등록 양식 갱신 중 오류가 발생했습니다. 관리자에게 문의하세요.", ephemeral=True)
                return
            
            logger.info(f"서버 {guild_id}의 모집 등록 양식 수동 갱신 완료")
            
        except Exception as e:
            logger.error(f"모집 양식 갱신 명령어 실행 중 오류: {e}")
            logger.error(traceback.format_exc())
            await interaction.followup.send("모집 등록 양식 갱신 중 오류가 발생했습니다.", ephemeral=True)

    @app_commands.command(name="명령어동기화", description="슬래시 명령어를 동기화합니다.")
    @app_commands.checks.has_permissions(administrator=True)
    async def sync_commands(self, interaction: discord.Interaction):
        """명령어를 동기화하는 명령어"""
        try:
            await interaction.response.defer(ephemeral=True)
            logger.info(f"[DEBUG] 명령어 동기화 명령 실행 - 사용자: {interaction.user.id}")
            
            try:
                # 명령어 트리 동기화
                commands = await self.bot.tree.sync()
                command_list = "\n".join([f"/{cmd.name} - {cmd.description}" for cmd in commands])
                
                logger.info(f"[DEBUG] 명령어 동기화 성공 - {len(commands)}개 명령어")
                logger.info(f"[DEBUG] 동기화된 명령어 목록:\n{command_list}")
                
                await interaction.followup.send(f"명령어 동기화가 완료되었습니다. {len(commands)}개의 명령어가 등록되었습니다.", ephemeral=True)
            except Exception as e:
                logger.error(f"[DEBUG] 명령어 동기화 실행 오류: {e}")
                logger.error(traceback.format_exc())
                await interaction.followup.send(f"명령어 동기화 중 오류가 발생했습니다: {str(e)}", ephemeral=True)
        except Exception as e:
            logger.error(f"[DEBUG] 명령어 동기화 명령어 전체 오류: {e}")
            logger.error(traceback.format_exc())
            try:
                await interaction.followup.send("명령어 실행 중 오류가 발생했습니다.", ephemeral=True)
            except:
                pass

async def setup(bot):
    await bot.add_cog(PartyCog(bot))
    bot_cog = bot.get_cog('PartyCog')
    if not bot_cog:
        logger.error("PartyCog를 찾을 수 없습니다.")
    else:
        # 태스크는 이미 생성자에서 시작되었으므로 여기서는 시작하지 않음
        logger.info("PartyCog가 로드되었습니다.")
