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
        super().__init__(timeout=60)
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
        self.announcement_channel_id = None
        self.registration_channel_id = None
        self.registration_locked = False  # 모집 등록 잠금 상태 (5초간)
        self.dungeons = []  # 던전 목록 추가
        self._load_settings_sync()
        self.cleanup_channel.start()  # 채널 정리 작업 시작

    def _load_settings_sync(self):
        """초기 설정을 동기적으로 로드합니다."""
        try:
            # 초기에는 채널 ID를 None으로 설정
            self.announcement_channel_id = None
            self.registration_channel_id = None
            # bot.py가 실행될 때 설정을 로드하기 위해 비동기적으로 설정을 로드하는 작업을 봇 루프에 추가
            self.bot.loop.create_task(self._load_settings_async())
            # 던전 목록 로드 작업 추가
            self.bot.loop.create_task(self._load_dungeons_async())
        except Exception as e:
            print(f"설정 로드 중 오류 발생: {e}")

    async def _load_channel_id(self, channel_type: str) -> str:
        """데이터베이스에서 채널 ID를 로드합니다."""
        try:
            settings = await self.db["bot_settings"].find_one({"setting_type": "channels"})
            if settings:
                if channel_type == "announcement":
                    return settings.get("announcement_channel_id")
                elif channel_type == "registration":
                    return settings.get("registration_channel_id")
            print(f"[ERROR] {channel_type} 채널 ID를 찾을 수 없음")
            return None
        except Exception as e:
            print(f"[ERROR] {channel_type} 채널 ID 로드 중 오류 발생: {e}")
            import traceback
            print(f"[ERROR] 상세 오류: {traceback.format_exc()}")
            return None

    async def _load_settings_async(self):
        """채널 설정을 로드하고 초기화합니다."""
        try:
            print("[DEBUG] 채널 설정 로드 시작")
            
            # 채널 ID 로드
            self.announcement_channel_id = await self._load_channel_id("announcement")
            self.registration_channel_id = await self._load_channel_id("registration")
            
            print(f"모집 공고 채널 ID를 로드했습니다: {self.announcement_channel_id}")
            print(f"모집 등록 채널 ID를 로드했습니다: {self.registration_channel_id}")
            
            # 등록 채널 초기화
            if self.registration_channel_id:
                print(f"[DEBUG] 등록 채널 초기화 시작: {self.registration_channel_id}")
                try:
                    registration_channel = self.bot.get_channel(int(self.registration_channel_id))
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
                        print("[DEBUG] 등록 채널 초기화 완료")
                    else:
                        print(f"[ERROR] 등록 채널을 찾을 수 없음: {self.registration_channel_id}")
                except Exception as e:
                    print(f"[ERROR] 등록 채널 초기화 중 오류 발생: {e}")
                    import traceback
                    print(f"[ERROR] 상세 오류: {traceback.format_exc()}")
            
            # 공고 채널 초기화
            if self.announcement_channel_id:
                print(f"[DEBUG] 공고 채널 초기화 시작: {self.announcement_channel_id}")
                try:
                    announcement_channel = self.bot.get_channel(int(self.announcement_channel_id))
                    if announcement_channel:
                        # 채널 알림 설정 변경
                        await announcement_channel.edit(
                            default_auto_archive_duration=10080,  # 7일
                            default_thread_auto_archive_duration=10080  # 7일
                        )
                        print("[DEBUG] 공고 채널 초기화 완료")
                    else:
                        print(f"[ERROR] 공고 채널을 찾을 수 없음: {self.announcement_channel_id}")
                except Exception as e:
                    print(f"[ERROR] 공고 채널 초기화 중 오류 발생: {e}")
                    import traceback
                    print(f"[ERROR] 상세 오류: {traceback.format_exc()}")
            
        except Exception as e:
            print(f"[ERROR] 채널 설정 로드 중 오류 발생: {e}")
            import traceback
            print(f"[ERROR] 상세 오류: {traceback.format_exc()}")

    async def _load_dungeons_async(self):
        """데이터베이스에서 던전 목록을 비동기적으로 로드합니다."""
        try:
            print("[DEBUG] 던전 목록 로드 시작")
            # 던전 목록 가져오기
            dungeons_cursor = self.db["dungeons"].find({})
            self.dungeons = [doc async for doc in dungeons_cursor]
            self.dungeons.sort(key=lambda d: (d["type"], d["name"], d["difficulty"]))
            print(f"[DEBUG] 던전 목록 로드 완료: {len(self.dungeons)}개 던전 로드됨")
        except Exception as e:
            print(f"[ERROR] 던전 목록 로드 중 오류 발생: {str(e)}")
            import traceback
            print(f"[ERROR] 상세 오류: {traceback.format_exc()}")

    @commands.Cog.listener()
    async def on_ready(self):
        """봇이 준비되면 저장된 뷰 상태를 복원하고 채널을 초기화합니다."""
        try:
            print("[INFO] 봇 초기화 시작")
            
            # 뷰 상태 복원 수행
            await self._restore_views()
            
            # 채널 초기화 수행
            await self.initialize_channels()
            
            print("[INFO] 봇 초기화 완료")
            
        except Exception as e:
            print(f"[ERROR] 봇 초기화 중 오류 발생: {e}")
            import traceback
            print(f"[ERROR] 상세 오류: {traceback.format_exc()}")
            
    async def _restore_views(self):
        """저장된 뷰 상태를 복원합니다."""
        try:
            print("[DEBUG] 뷰 상태 복원 시작")
            
            # 저장된 모든 뷰 상태 가져오기
            view_states = await self.db["view_states"].find({}).to_list(length=None)
            
            for state in view_states:
                try:
                    # 채널과 메시지 가져오기
                    channel = self.bot.get_channel(int(state["channel_id"]))
                    if not channel:
                        print(f"[WARNING] 채널을 찾을 수 없음: {state['channel_id']}")
                        continue
                        
                    try:
                        message = await channel.fetch_message(int(state["message_id"]))
                    except discord.NotFound:
                        # 메시지를 찾을 수 없는 경우 뷰 상태 삭제
                        print(f"[WARNING] 메시지를 찾을 수 없음: {state['message_id']}")
                        await self.db["view_states"].delete_one({"message_id": state["message_id"]})
                        continue
                    
                    # 메시지의 임베드가 모집 등록 양식인지 확인
                    if not message.embeds or not message.embeds[0].title or "파티 모집 등록 양식" in message.embeds[0].title:
                        print(f"[DEBUG] 모집 등록 양식 메시지 건너뛰기: {message.id}")
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
                        print(f"[WARNING] 참가자 ID 변환 중 오류: {participants}")
                        view.participants = []
                    
                    try:
                        view.creator_id = int(state.get("creator_id", 0))
                    except ValueError:
                        print(f"[WARNING] 생성자 ID 변환 중 오류: {state.get('creator_id')}")
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
                    print(f"[DEBUG] 뷰 상태 복원 완료: {state['message_id']}")
                    
                except Exception as e:
                    print(f"[ERROR] 뷰 상태 복원 중 오류 발생: {e}")
                    import traceback
                    print(f"[ERROR] 상세 오류: {traceback.format_exc()}")
                    continue
            
            print("[DEBUG] 뷰 상태 복원 완료")
            
        except Exception as e:
            print(f"[ERROR] 뷰 상태 복원 중 오류 발생: {e}")
            import traceback
            print(f"[ERROR] 상세 오류: {traceback.format_exc()}")
            
    async def initialize_channels(self):
        """채널을 초기화합니다."""
        try:
            print("[INFO] 채널 초기화 시작")
            
            # 채널 ID가 없으면 로드
            if not self.registration_channel_id or not self.announcement_channel_id:
                self.registration_channel_id = await self._load_channel_id("registration")
                self.announcement_channel_id = await self._load_channel_id("announcement")
            
            # 모집 등록 채널 초기화
            if self.registration_channel_id:
                print(f"[INFO] 모집 등록 채널 초기화 중: {self.registration_channel_id}")
                registration_channel = self.bot.get_channel(int(self.registration_channel_id))
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
                        print("[INFO] 모집 등록 채널 초기화 완료")
                    except discord.Forbidden:
                        print(f"[ERROR] 모집 등록 채널 초기화 권한 부족: {self.registration_channel_id}")
                    except Exception as e:
                        print(f"[ERROR] 모집 등록 채널 초기화 중 오류 발생: {e}")
                        import traceback
                        print(f"[ERROR] 상세 오류: {traceback.format_exc()}")
                else:
                    print(f"[ERROR] 모집 등록 채널을 찾을 수 없음: {self.registration_channel_id}")
            
            # 공고 채널 초기화
            if self.announcement_channel_id:
                print(f"[INFO] 공고 채널 초기화 중: {self.announcement_channel_id}")
                announcement_channel = self.bot.get_channel(int(self.announcement_channel_id))
                if announcement_channel:
                    try:
                        # 채널 알림 설정 변경
                        await announcement_channel.edit(
                            default_auto_archive_duration=10080,  # 7일
                            default_thread_auto_archive_duration=10080  # 7일
                        )
                        
                        # DB에서 활성 상태인 모집 정보 불러오기
                        active_recruitments = await self.db["recruitments"].find(
                            {"status": "active"}
                        ).sort("created_at", -1).to_list(length=None)
                        
                        print(f"[INFO] 활성 모집 {len(active_recruitments)}개를 불러왔습니다.")
                        
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
                                    view.selected_type = recruitment.get("selected_type")
                                    view.selected_kind = recruitment.get("selected_kind")
                                    view.selected_diff = recruitment.get("selected_diff")
                                    view.recruitment_content = recruitment.get("recruitment_content")
                                    view.max_participants = recruitment.get("max_participants", 4)
                                    view.status = recruitment.get("status", "active")
                                    view.recruitment_id = recruitment_id
                                    
                                    # 참가자 목록 변환 (문자열 ID -> 정수 ID)
                                    try:
                                        participants = recruitment.get("participants", [])
                                        view.participants = [int(p) for p in participants]
                                    except ValueError:
                                        print(f"[WARNING] 참가자 ID 변환 중 오류: {participants}")
                                        view.participants = []
                                    
                                    try:
                                        view.creator_id = int(recruitment.get("creator_id", 0))
                                    except ValueError:
                                        print(f"[WARNING] 생성자 ID 변환 중 오류: {recruitment.get('creator_id')}")
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
                                    print(f"[INFO] 모집 ID {recruitment_id}의 상호작용을 다시 등록했습니다.")
                                else:
                                    # 메시지가 없으면 새로 생성
                                    view = RecruitmentCard(self.dungeons, self.db)
                                    view.is_recreated = True  # 재활성화 표시
                                    view.selected_type = recruitment.get("selected_type")
                                    view.selected_kind = recruitment.get("selected_kind")
                                    view.selected_diff = recruitment.get("selected_diff")
                                    view.recruitment_content = recruitment.get("recruitment_content")
                                    view.max_participants = recruitment.get("max_participants", 4)
                                    view.status = recruitment.get("status", "active")
                                    view.recruitment_id = recruitment_id
                                    
                                    # 참가자 목록 변환 (문자열 ID -> 정수 ID)
                                    try:
                                        participants = recruitment.get("participants", [])
                                        view.participants = [int(p) for p in participants]
                                    except ValueError:
                                        print(f"[WARNING] 참가자 ID 변환 중 오류: {participants}")
                                        view.participants = []
                                    
                                    try:
                                        view.creator_id = int(recruitment.get("creator_id", 0))
                                    except ValueError:
                                        print(f"[WARNING] 생성자 ID 변환 중 오류: {recruitment.get('creator_id')}")
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
                                    
                                    # 메시지 생성
                                    message = await announcement_channel.send(embed=embed, view=view)
                                    view.message = message
                                    
                                    # 메시지 ID 업데이트
                                    await self.db["recruitments"].update_one(
                                        {"_id": recruitment["_id"]},
                                        {"$set": {"announcement_message_id": str(message.id)}}
                                    )
                                    print(f"[INFO] 모집 ID {recruitment_id}의 메시지를 새로 생성했습니다.")
                                    
                            except Exception as e:
                                print(f"[ERROR] 모집 공고 처리 중 오류 발생: {e}")
                                import traceback
                                print(f"[ERROR] 상세 오류: {traceback.format_exc()}")
                                continue
                        
                        print(f"[INFO] 공고 채널 초기화 완료: {len(active_recruitments)}개 모집 공고 처리됨")
                    except discord.Forbidden:
                        print(f"[ERROR] 공고 채널 초기화 권한 부족: {self.announcement_channel_id}")
                    except Exception as e:
                        print(f"[ERROR] 공고 채널 초기화 중 오류 발생: {e}")
                        import traceback
                        print(f"[ERROR] 상세 오류: {traceback.format_exc()}")
                else:
                    print(f"[ERROR] 공고 채널을 찾을 수 없음: {self.announcement_channel_id}")
            
            print("[INFO] 채널 초기화 완료")
        except Exception as e:
            print(f"[ERROR] 채널 초기화 중 오류 발생: {e}")
            import traceback
            print(f"[ERROR] 상세 오류: {traceback.format_exc()}")

    @commands.Cog.listener()
    async def on_message(self, message):
        # 봇의 메시지는 무시
        if message.author.bot:
            return

        # 파티_모집 채널인지 확인
        if str(message.channel.id) == self.announcement_channel_id:
            await message.delete()
            return

        # 파티_모집_등록 채널인지 확인
        if str(message.channel.id) == self.registration_channel_id:
            await message.delete()
            return

    @app_commands.command(name="모집", description="파티 모집을 시작합니다.")
    async def recruitment(self, interaction: discord.Interaction):
        """파티 모집 명령어"""
        try:
            # 모집 명령어 사용 안내
            await interaction.response.defer(ephemeral=True)
            msg = await interaction.followup.send("이제 모집 명령어는 사용하지 않습니다. 대신 모집 등록 채널에서 양식을 작성해주세요.", ephemeral=True)
            await asyncio.sleep(2)
            await msg.delete()
            
        except Exception as e:
            print(f"[ERROR] 모집 명령어 실행 중 오류 발생: {e}")
            import traceback
            print(f"[ERROR] 상세 오류: {traceback.format_exc()}")
            if not interaction.response.is_done():
                await interaction.response.defer(ephemeral=True)
                msg = await interaction.followup.send("모집 명령어 실행 중 오류가 발생했습니다.", ephemeral=True)
                await asyncio.sleep(2)
                await msg.delete()

    @app_commands.command(name="모집채널설정", description="모집 공고를 게시할 채널을 설정합니다.")
    async def set_announcement_channel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        """모집 공고 채널 설정 명령어"""
        try:
            # 채널 ID 저장
            await self.db["settings"].update_one(
                {"guild_id": str(interaction.guild_id)},
                {"$set": {"announcement_channel_id": str(channel.id)}},
                upsert=True
            )
            
            # 응답 메시지
            await interaction.response.defer(ephemeral=True)
            msg = await interaction.followup.send(f"모집 공고 채널이 {channel.mention}으로 설정되었습니다.", ephemeral=True)
            await asyncio.sleep(2)
            await msg.delete()
            
        except Exception as e:
            print(f"[ERROR] 모집 채널 설정 중 오류 발생: {e}")
            import traceback
            print(f"[ERROR] 상세 오류: {traceback.format_exc()}")
            if not interaction.response.is_done():
                await interaction.response.defer(ephemeral=True)
                msg = await interaction.followup.send("모집 채널 설정 중 오류가 발생했습니다.", ephemeral=True)
                await asyncio.sleep(2)
                await msg.delete()

    @app_commands.command(name="모집등록채널설정", description="모집 등록 양식을 게시할 채널을 설정합니다.")
    async def set_registration_channel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        """모집 등록 채널 설정 명령어"""
        try:
            # 채널 ID 저장
            await self.db["settings"].update_one(
                {"guild_id": str(interaction.guild_id)},
                {"$set": {"registration_channel_id": str(channel.id)}},
                upsert=True
            )
            
            # 응답 메시지
            await interaction.response.defer(ephemeral=True)
            msg = await interaction.followup.send(f"모집 등록 채널이 {channel.mention}으로 설정되었습니다.", ephemeral=True)
            await asyncio.sleep(2)
            await msg.delete()
            
        except Exception as e:
            print(f"[ERROR] 모집 등록 채널 설정 중 오류 발생: {e}")
            import traceback
            print(f"[ERROR] 상세 오류: {traceback.format_exc()}")
            if not interaction.response.is_done():
                await interaction.response.defer(ephemeral=True)
                msg = await interaction.followup.send("모집 등록 채널 설정 중 오류가 발생했습니다.", ephemeral=True)
                await asyncio.sleep(2)
                await msg.delete()

    @app_commands.command(name="모집초기화", description="모집 등록 채널을 초기화합니다.")
    async def reset_registration_channel(self, interaction: discord.Interaction):
        """모집 등록 채널 초기화 명령어"""
        try:
            # 채널 ID 가져오기
            settings = await self.db["settings"].find_one({"guild_id": str(interaction.guild_id)})
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
            
        except Exception as e:
            print(f"[ERROR] 모집 등록 채널 초기화 중 오류 발생: {e}")
            import traceback
            print(f"[ERROR] 상세 오류: {traceback.format_exc()}")
            if not interaction.response.is_done():
                await interaction.response.defer(ephemeral=True)
                msg = await interaction.followup.send("모집 등록 채널 초기화 중 오류가 발생했습니다.", ephemeral=True)
                await asyncio.sleep(2)
                await msg.delete()

    async def create_registration_form(self, channel):
        """모집 등록 채널에 빈 양식을 생성합니다."""
        # 던전 목록 가져오기
        dungeons_cursor = self.db["dungeons"].find({})
        dungeons = [doc async for doc in dungeons_cursor]
        dungeons.sort(key=lambda d: (d["type"], d["name"], d["difficulty"]))
        
        # 등록 양식 생성
        view = RecruitmentCard(dungeons, self.db)
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
        if not self.announcement_channel_id:
            # 공고 채널이 설정되지 않았으면 종료
            print("[ERROR] 모집 공고 채널이 설정되지 않았습니다.")
            return None
        
        try:
            # 채널 가져오기
            guild = self.bot.get_guild(int(guild_id))
            if not guild:
                print(f"[ERROR] 길드를 찾을 수 없음: {guild_id}")
                return None
            
            channel = guild.get_channel(int(self.announcement_channel_id))
            if not channel:
                print(f"[ERROR] 공고 채널을 찾을 수 없음: {self.announcement_channel_id}")
                return None

            # 모집 ID 확인
            recruitment_id = str(view.recruitment_id)
            if not recruitment_id:
                print("[ERROR] 모집 ID가 없습니다.")
                return None
                
            # 기존 공고 확인
            existing_message = None
            recruitment = await self.db["recruitments"].find_one({"_id": ObjectId(recruitment_id)})
            
            if recruitment and "announcement_message_id" in recruitment and "announcement_channel_id" in recruitment:
                try:
                    if str(channel.id) == recruitment["announcement_channel_id"]:
                        existing_message = await channel.fetch_message(int(recruitment["announcement_message_id"]))
                        print(f"[INFO] 기존 모집 공고를 찾았습니다: {recruitment['announcement_message_id']}")
                except discord.NotFound:
                    print(f"[INFO] 기존 모집 공고를 찾을 수 없습니다: {recruitment.get('announcement_message_id')}")
                except Exception as e:
                    print(f"[ERROR] 기존 모집 공고 조회 중 오류: {e}")
            
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
                    print(f"[INFO] 기존 모집 공고를 업데이트했습니다: {existing_message.id}")
                except Exception as e:
                    print(f"[ERROR] 모집 공고 업데이트 중 오류: {e}")
                    # 업데이트 실패 시 기존 메시지 삭제 후 새로 생성
                    try:
                        await existing_message.delete()
                    except:
                        pass
                    message = await channel.send(embed=embed, view=announcement_view, silent=True)
                    print(f"[INFO] 모집 공고를 새로 생성했습니다: {message.id}")
            else:
                # 기존 메시지가 없으면 새로 생성
                message = await channel.send(embed=embed, view=announcement_view, silent=True)
                print(f"[INFO] 모집 공고를 새로 생성했습니다: {message.id}")
            
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
                    "updated_at": datetime.now().isoformat()
                }}
            )
            
            print(f"[INFO] 모집 공고 게시 완료: {view.recruitment_id}")
            return message
        except Exception as e:
            print(f"[ERROR] 모집 공고 게시 중 오류 발생: {e}")
            import traceback
            print(f"[ERROR] 상세 오류: {traceback.format_exc()}")
            return None

    @app_commands.command(name="동글_도움말")
    async def help_command(self, interaction: discord.Interaction):
        """동글봇의 명령어 목록과 사용법을 보여줍니다."""
        embed = discord.Embed(
            title="🤖 동글봇 도움말",
            description="동글봇의 사용 가능한 명령어 목록입니다.",
            color=discord.Color.blue()
        )
        
        # 각 명령어별 설명 추가
        for cmd_name, cmd_info in HELP_DATA.items():
            value = f"**설명**: {cmd_info['설명']}\n**사용법**: {cmd_info['사용법']}\n**권한**: {cmd_info['권한']}"
            embed.add_field(name=f"/{cmd_name}", value=value, inline=False)
        
        # 모집 시스템 간단 설명 추가
        embed.add_field(
            name="📝 모집 시스템 사용법",
            value=(
                "1. 관리자가 `/모집채널설정`과 `/모집등록채널설정`으로 채널을 설정합니다.\n"
                "2. 사용자는 모집 등록 채널에서 양식을 작성하고 '모집 등록' 버튼을 클릭합니다.\n"
                "3. 등록된 모집은 모집 공고 채널에 자동으로 게시됩니다.\n"
                "4. 다른 사용자들은 모집 공고에서 '참가하기' 버튼을 클릭하여 참가할 수 있습니다.\n"
                "5. 인원이 다 차면 비공개 스레드가 자동으로 생성되고 참가자들이 초대됩니다."
            ),
            inline=False
        )
        
        # 슈퍼유저 명령어 설명 (힝트 사용자용)
        if interaction.user.name == "힝트" or interaction.user.display_name == "힝트":
            embed.add_field(
                name="🔑 슈퍼유저 기능 (힝트 전용)",
                value=(
                    "- 중복 참가 가능\n"
                    "- 인원 제한 무시 가능\n"
                    "- 모집 등록 시 값 자동 완성\n"
                    "- '스레드 생성' 버튼으로 즉시 스레드 생성 가능"
                ),
                inline=False
            )
        
        embed.set_footer(text="문제가 발생하거나 건의사항이 있으시면 관리자에게 문의해주세요.")
        
        await interaction.response.send_message(embed=embed, ephemeral=True)

    def cog_unload(self):
        """코그가 언로드될 때 실행되는 메서드"""
        self.cleanup_channel.cancel()  # 채널 정리 작업 중지

    @tasks.loop(minutes=1)  # 1분마다 실행
    async def cleanup_channel(self):
        """채널 정리 작업"""
        try:
            if not self.announcement_channel_id:
                return
                
            # 데이터베이스에서 모든 모집 정보 조회
            recruitments = await self.db.recruitments.find({}).to_list(None)
            
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
            
            print(f"[DEBUG] 데이터베이스에서 {len(recruitments)}개의 모집을 찾았습니다.")
            
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
            
            print(f"[DEBUG] 활성 모집: {len(active_recruitment_ids)}개, 완료된 모집: {len(completed_recruitment_ids)}개, 취소된 모집: {len(cancelled_recruitment_ids)}개")
            
            # 채널의 모든 메시지 조회
            channel = self.bot.get_channel(int(self.announcement_channel_id))
            if not channel:
                print(f"[ERROR] 공고 채널을 찾을 수 없음: {self.announcement_channel_id}")
                return

            print(f"[DEBUG] 공고 채널 확인: {channel.name}")
            
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
                                        "updated_at": datetime.now().isoformat()
                                    }}
                                )
                                print(f"[INFO] 채널에서 발견된 활성 모집 {recruitment_id}의 메시지 ID를 업데이트했습니다: {message.id}")

                except Exception as e:
                    print(f"[ERROR] 메시지 처리 중 오류 발생: {e}")
                    import traceback
                    print(f"[ERROR] 상세 오류: {traceback.format_exc()}")
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
                    print(f"[INFO] 누락된 모집 공고 재게시: {recruitment_id}")
                    
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
                        print(f"[WARNING] 참가자 ID 변환 중 오류: {participants}")
                        view.participants = []
                    
                    try:
                        view.creator_id = int(recruitment.get("creator_id", 0))
                    except ValueError:
                        print(f"[WARNING] 생성자 ID 변환 중 오류: {recruitment.get('creator_id')}")
                        view.creator_id = 0
                    
                    # 공고 게시
                    await self.post_recruitment_announcement(channel.guild.id, recruitment, view)
                    
                except Exception as e:
                    print(f"[ERROR] 모집 공고 재게시 중 오류 발생: {e}")
                    import traceback
                    print(f"[ERROR] 상세 오류: {traceback.format_exc()}")
            
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
                    print(f"[INFO] 모집 ID {recruitment_id}에 대한 중복 메시지 발견: {len(message_ids)}개")
                    # 메시지 ID를 정수로 변환하여 정렬 (최신 메시지가 큰 ID 값을 가짐)
                    sorted_message_ids = sorted([int(mid) for mid in message_ids], reverse=True)
                    # 가장 최신 메시지를 제외한 나머지 삭제
                    for message_id in sorted_message_ids[1:]:
                        try:
                            message = await channel.fetch_message(message_id)
                            await message.delete()
                            print(f"[INFO] 중복 메시지 삭제: {message_id}")
                        except Exception as e:
                            print(f"[ERROR] 중복 메시지 삭제 중 오류: {e}")
            
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
                            print(f"[INFO] 모집 ID {recruitment_id}의 상태가 {status}이므로 메시지를 삭제합니다.")
                            await message.delete()
                            deleted_count += 1
                        elif status == "active":
                            print(f"[DEBUG] 모집 ID {recruitment_id}는 아직 활성 상태입니다.")
                        elif recruitment_id not in recruitment_status_map:
                            # 데이터베이스에 없는 모집의 메시지는 삭제
                            print(f"[INFO] 모집 ID {recruitment_id}가 데이터베이스에 존재하지 않아 메시지를 삭제합니다.")
                            await message.delete()
                            deleted_count += 1
                        else:
                            print(f"[DEBUG] 모집 ID {recruitment_id}의 상태가 {status}로 처리되지 않았습니다.")

                except Exception as e:
                    print(f"[ERROR] 메시지 처리 중 오류 발생: {e}")
                    import traceback
                    print(f"[ERROR] 상세 오류: {traceback.format_exc()}")
                    continue

            print(f"[DEBUG] 채널 정리 완료: {deleted_count}개의 메시지가 삭제되었습니다.")
            
        except Exception as e:
            print(f"[ERROR] 채널 정리 중 오류 발생: {e}")
            import traceback
            print(f"[ERROR] 상세 오류: {traceback.format_exc()}")

    @cleanup_channel.before_loop
    async def before_cleanup_channel(self):
        """채널 정리 작업 시작 전 실행되는 메서드"""
        print("[DEBUG] 채널 정리 작업 준비 중...")
        await self.bot.wait_until_ready()  # 봇이 준비될 때까지 대기
        print("[DEBUG] 채널 정리 작업 시작")

async def setup(bot):
    await bot.add_cog(PartyCog(bot))
    bot_cog = bot.get_cog('PartyCog')
    if not bot_cog:
        print("PartyCog를 찾을 수 없습니다.")
