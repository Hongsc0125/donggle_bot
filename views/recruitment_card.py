import discord
from discord import ui, Embed, Color, SelectOption, Interaction
from views.recruitment_card_views import RecruitmentModal
import datetime
from core.config import settings
import asyncio

# 슈퍼유저 ID 정의
SUPER_USER_ID = "307620267067179019"

class RecruitmentCard(ui.View):
    def __init__(self, dungeons, db):
        super().__init__(timeout=300)
        self.dungeons = dungeons
        self.db = db  # MongoDB 데이터베이스 객체 저장
        self.selected_type = None
        self.selected_kind = None
        self.selected_diff = None
        self.recruitment_content = None
        self.message = None  # persistent 메시지 저장
        self.status = "대기중"  # 초기 상태: 대기중
        self.recruitment_id = None  # DB에 저장된 모집 ID
        self.participants = []  # 참가자 목록
        self.max_participants = 4  # 기본 최대 인원 수 (본인 포함)
        self.target_channel_id = None  # 모집 공고를 게시할 채널 ID
        self.announcement_message_id = None  # 모집 공고 메시지 ID
        self.creator_id = None  # 모집 생성자 ID
        
        # 타입 선택 메뉴 추가
        self.type_select = self._create_type_select()
        self.add_item(self.type_select)
        
        # 종류 선택 메뉴 (초기에는 비활성화)
        self.kind_select = self._create_kind_select()
        self.kind_select.disabled = True
        self.add_item(self.kind_select)
        
        # 난이도 선택 메뉴 (초기에는 비활성화)
        self.diff_select = self._create_diff_select()
        self.diff_select.disabled = True
        self.add_item(self.diff_select)
        
        # 인원 설정 메뉴 추가
        self.max_participants_select = self._create_max_participants_select()
        self.add_item(self.max_participants_select)
        
        # 초기 버튼 설정
        self._setup_buttons()
        
    def _setup_buttons(self):
        """초기 버튼 설정"""
        # 모든 버튼 제거
        for item in self.children.copy():
            if isinstance(item, ui.Button):
                self.remove_item(item)
        
        # 모집 내용 작성 버튼 추가
        content_button = ui.Button(label="모집 내용 작성", style=discord.ButtonStyle.success, custom_id="btn_content", row=4)
        content_button.callback = self.btn_content_callback
        self.add_item(content_button)
        
        # 모집 등록 버튼 추가
        register_button = ui.Button(label="모집 등록", style=discord.ButtonStyle.primary, custom_id="btn_register", row=4)
        register_button.callback = self.btn_register_callback
        self.add_item(register_button)

    def _create_max_participants_select(self):
        options = [
            SelectOption(label=f"최대 {i}명", value=str(i)) for i in range(2, 5)
        ]
        select = ui.Select(
            placeholder="인원 설정 (기본: 4명)",
            options=options,
            custom_id="max_participants_select",
            row=3
        )
        select.callback = self.max_participants_callback
        return select
    
    def _create_type_select(self):
        types = sorted({d["type"] for d in self.dungeons})
        options = [SelectOption(label=f"🏰 {t}", value=t) for t in types]
        select = ui.Select(
            placeholder="던전 타입 선택",
            options=options,
            custom_id="type_select",
            row=0
        )
        select.callback = self.type_callback
        return select
    
    def _create_kind_select(self):
        options = []
        if self.selected_type:
            kinds = sorted({d["name"] for d in self.dungeons if d["type"] == self.selected_type})
            options = [SelectOption(label=f"⚔️ {k}", value=k) for k in kinds]
        
        select = ui.Select(
            placeholder="던전 종류 선택",
            options=options or [SelectOption(label="먼저 타입을 선택하세요", value="dummy")],
            custom_id="kind_select",
            row=1,
            disabled=not bool(self.selected_type)
        )
        select.callback = self.kind_callback
        return select
    
    def _create_diff_select(self):
        options = []
        if self.selected_type and self.selected_kind:
            difficulties = sorted({d["difficulty"] for d in self.dungeons 
                                if d["type"] == self.selected_type and d["name"] == self.selected_kind})
            options = [SelectOption(label=f"⭐ {diff}", value=diff) for diff in difficulties]
        
        select = ui.Select(
            placeholder="던전 난이도 선택",
            options=options or [SelectOption(label="먼저 종류를 선택하세요", value="dummy")],
            custom_id="diff_select",
            row=2,
            disabled=not (bool(self.selected_type) and bool(self.selected_kind))
        )
        select.callback = self.diff_callback
        return select
    
    def get_embed(self) -> Embed:
        # 임베드 색상 설정 (파란색 계열)
        embed = Embed(
            title="🎮 파티원 모집",
            color=Color.blue()
        )
        
        # 던전 정보 섹션
        if self.selected_type:
            # 구분선 추가
            embed.add_field(
                name="\n───────────────\n",
                value="",
                inline=False
            )
            
            dungeon_info = (
                f"> `{self.selected_type}`"
                f" | `{self.selected_kind}`"
                f" | `{self.selected_diff}`"
            )

            embed.add_field(
                name="\n📌 던전 정보\n",
                value=dungeon_info,
                inline=False
            )

            embed.add_field(
                name="\n───────────────\n",
                value="",
                inline=False
            )
        
        # 모집 내용 섹션
        if self.recruitment_content:
            embed.add_field(
                name="\n📝 모집 내용\n",
                value=f"\n```{self.recruitment_content}```",
                inline=False
            )

            embed.add_field(
                name="\n───────────────\n",
                value="",
                inline=False
            )
        
        # 인원 정보 섹션
        participants_count = len(self.participants)
        max_participants = self.max_participants
        
        embed.add_field(
            name="\n👥 인원 현황",
            value=(
                f"> `{participants_count}명` / `{max_participants}명`"
            ),
            inline=False
        )
        
        # 구분선 추가
        embed.add_field(
            name="\n───────────────\n",
            value="",
            inline=False
        )
        
        # 참가자 목록 섹션
        if self.participants:
            participants_str = "\n".join([
                f"> <@{p}>" 
                for p in self.participants
            ])
            embed.add_field(
                name="\n🎯 참가자 목록\n",
                value=participants_str,
                inline=False
            )
        
            embed.add_field(
                name="\n───────────────\n",
                value="",
                inline=False
            )
        
        # 모집 상태 섹션
        if self.status:
            status_emoji = "🟢" if self.status == "대기중" else "✅"
            embed.add_field(
                name="\n📊 모집 상태\n",
                value=f"\n> {status_emoji} `{self.status}`",
                inline=False
            )
        
        # 푸터 설정
        embed.set_footer(
            text="아래 선택 메뉴에서 각 항목을 선택하세요.",
            icon_url="https://cdn.discordapp.com/emojis/1234567890123456789.png"  # 원하는 아이콘 URL로 변경 가능
        )
        
        return embed

    def clear_items(self):
        """모든 UI 요소를 제거합니다."""
        for item in self.children.copy():
            self.remove_item(item)
            
    async def update_embed(self, interaction: discord.Interaction = None):
        # 각 선택 메뉴 상태 업데이트
        kind_select = self._create_kind_select()
        diff_select = self._create_diff_select()
        
        # 선택된 값이 있으면 placeholder에 표시
        if self.selected_type:
            self.type_select.placeholder = f"🏰 {self.selected_type}"
        
        if self.selected_kind:
            kind_select.placeholder = f"⚔️ {self.selected_kind}"
        
        if self.selected_diff:
            diff_select.placeholder = f"⭐ {self.selected_diff}"
            
        # 인원 설정 메뉴 placeholder 업데이트
        self.max_participants_select.placeholder = f"최대 {self.max_participants}명"
        
        # 기존 메뉴 제거 후 새 메뉴 추가
        for item in self.children.copy():
            if item.custom_id in ["kind_select", "diff_select"]:
                self.remove_item(item)
        
        self.add_item(kind_select)
        self.add_item(diff_select)
        
        # 임베드 업데이트
        embed = self.get_embed()
        await self.message.edit(embed=embed, view=self)
    
    async def type_callback(self, interaction: Interaction):
        self.selected_type = interaction.data["values"][0]
        self.selected_kind = None
        self.selected_diff = None
        await interaction.response.defer()
        await self.update_embed(interaction)
    
    async def kind_callback(self, interaction: Interaction):
        self.selected_kind = interaction.data["values"][0]
        self.selected_diff = None
        await interaction.response.defer()
        await self.update_embed(interaction)
    
    async def diff_callback(self, interaction: Interaction):
        self.selected_diff = interaction.data["values"][0]
        await interaction.response.defer()
        await self.update_embed(interaction)
    
    async def max_participants_callback(self, interaction: Interaction):
        self.max_participants = int(interaction.data["values"][0])
        await interaction.response.defer()
        await self.update_embed(interaction)
    
    def update_buttons(self, interaction: discord.Interaction = None):
        """버튼 상태를 업데이트합니다."""
        # 모든 버튼 제거
        for item in self.children.copy():
            if isinstance(item, ui.Button):
                self.remove_item(item)
        
        if self.status == "대기중":
            # 모집 등록 상태일 때
            content_button = ui.Button(label="모집 내용 작성", style=discord.ButtonStyle.success, custom_id="btn_content", row=4)
            content_button.callback = self.btn_content_callback
            self.add_item(content_button)
            
            register_button = ui.Button(label="모집 등록", style=discord.ButtonStyle.primary, custom_id="btn_register", row=4)
            register_button.callback = self.btn_register_callback
            self.add_item(register_button)
        else:
            # 등록된 모집 공고일 때
            join_button = ui.Button(label="참가하기", style=discord.ButtonStyle.success, custom_id="btn_join", row=4)
            join_button.callback = self.btn_join_callback
            self.add_item(join_button)
            
            cancel_button = ui.Button(label="신청 취소", style=discord.ButtonStyle.danger, custom_id="btn_cancel", row=4)
            cancel_button.callback = self.btn_cancel_callback
            self.add_item(cancel_button)
            
            # 모집 생성자에게만 모집 취소 버튼 표시
            if interaction and interaction.user.id == self.creator_id:
                delete_button = ui.Button(label="모집 취소", style=discord.ButtonStyle.danger, custom_id="btn_delete", row=4)
                delete_button.callback = self.btn_delete_callback
                self.add_item(delete_button)

    async def btn_content_callback(self, interaction: discord.Interaction):
        """모집 내용 작성 버튼 콜백"""
        modal = RecruitmentModal()
        modal.parent = self
        await interaction.response.send_modal(modal)

    async def btn_register_callback(self, interaction: discord.Interaction):
        """모집 등록 버튼 클릭 시 호출되는 콜백"""
        try:
            # 필수 정보 확인
            if not all([self.selected_type, self.selected_kind, self.selected_diff, self.recruitment_content, self.max_participants]):
                await interaction.response.defer(ephemeral=True)
                msg = await interaction.followup.send("모든 필수 정보를 입력해주세요.", ephemeral=True)
                await asyncio.sleep(2)
                await msg.delete()
                return
            
            # 모집 ID 생성 (현재 시간 기반)
            self.recruitment_id = str(int(datetime.datetime.now().timestamp()))
            
            # 모집 상태 변경
            self.status = "모집중"
            self.creator_id = str(interaction.user.id)
            
            # 생성자를 참가자 목록에 추가
            self.participants = [self.creator_id]
            
            # 버튼 업데이트
            self.update_buttons()
            
            # 임베드 업데이트
            embed = self.get_embed()
            await interaction.message.edit(embed=embed, view=self)
            
            # 등록 완료 메시지 (알림 없음)
            await interaction.response.defer(ephemeral=True)
            msg = await interaction.followup.send("모집이 등록되었습니다.", ephemeral=True)
            await asyncio.sleep(2)
            await msg.delete()
            
            # 등록 양식 메시지 삭제
            try:
                await interaction.message.delete()
            except:
                pass
            
            # PartyCog 인스턴스 가져오기
            party_cog = interaction.client.get_cog("PartyCog")
            if not party_cog:
                print("[ERROR] PartyCog를 찾을 수 없음")
                return
            
            # 모집 데이터 생성
            recruitment_data = {
                "recruitment_id": self.recruitment_id,
                "guild_id": str(interaction.guild_id),
                "creator_id": self.creator_id,
                "type": self.selected_type,
                "kind": self.selected_kind,
                "difficulty": self.selected_diff,
                "content": self.recruitment_content,
                "max_participants": self.max_participants,
                "participants": self.participants,
                "status": self.status,
                "created_at": datetime.datetime.now().isoformat()
            }
            
            # DB에 저장
            await self.db["recruitments"].insert_one(recruitment_data)
            
            # 모집 공고 게시
            announcement_message = await party_cog.post_recruitment_announcement(
                interaction.guild_id,
                recruitment_data,
                self
            )
            
            if announcement_message:
                # 공고 메시지 정보 저장
                await self.db["recruitments"].update_one(
                    {"recruitment_id": self.recruitment_id},
                    {
                        "$set": {
                            "announcement_message_id": str(announcement_message.id),
                            "target_channel_id": str(announcement_message.channel.id)
                        }
                    }
                )
            
            # 5초 후 새 등록 양식 생성
            await asyncio.sleep(5)
            await party_cog.create_registration_form(interaction.channel)
            
        except Exception as e:
            print(f"[ERROR] 모집 등록 중 오류 발생: {e}")
            import traceback
            print(f"[ERROR] 상세 오류: {traceback.format_exc()}")
            if not interaction.response.is_done():
                await interaction.response.defer(ephemeral=True)
                msg = await interaction.followup.send("모집 등록 중 오류가 발생했습니다.", ephemeral=True)
                await asyncio.sleep(2)
                await msg.delete()

    async def btn_delete_callback(self, interaction: discord.Interaction):
        """모집 취소 버튼 콜백"""
        # 모집 생성자만 취소 가능
        if interaction.user.id != self.creator_id:
            await interaction.response.defer(ephemeral=True)
            msg = await interaction.followup.send("모집 생성자만 취소할 수 있습니다.", ephemeral=True)
            await asyncio.sleep(2)
            await msg.delete()
            return
        
        # 모집 취소 처리
        self.status = "취소됨"
        
        # 버튼 업데이트
        self.update_buttons(interaction)
        
        # 임베드 업데이트
        await self.update_embed(interaction)
        
        # 모집 취소 메시지
        await interaction.response.defer(ephemeral=True)
        msg = await interaction.followup.send("모집이 취소되었습니다.", ephemeral=True)
        await asyncio.sleep(2)
        await msg.delete()

    async def btn_join_callback(self, interaction: discord.Interaction):
        """참가하기 버튼 클릭 시 호출되는 콜백"""
        try:
            # 모집 정보 가져오기
            recruitment = await self.db["recruitments"].find_one({"recruitment_id": self.recruitment_id})
            if not recruitment:
                print(f"[ERROR] 모집 정보를 찾을 수 없음: {self.recruitment_id}")
                await interaction.response.defer(ephemeral=True)
                msg = await interaction.followup.send("모집 정보를 찾을 수 없습니다.", ephemeral=True)
                await asyncio.sleep(2)
                await msg.delete()
                return
            
            # 사용자 ID
            user_id = str(interaction.user.id)
            
            # 슈퍼유저 체크
            is_super = self.is_super_user(interaction.user)
            
            # 이미 참가한 경우 (슈퍼유저는 중복 참가 가능)
            if not is_super and user_id in self.participants:
                await interaction.response.defer(ephemeral=True)
                msg = await interaction.followup.send("이미 참가 신청하셨습니다.", ephemeral=True)
                await asyncio.sleep(2)
                await msg.delete()
                return
            
            # 최대 인원 초과 확인 (슈퍼유저도 인원 제한 적용)
            current_participants = len(self.participants)
            if current_participants >= self.max_participants:
                await interaction.response.defer(ephemeral=True)
                msg = await interaction.followup.send(f"모집 인원이 마감되었습니다. (최대 {self.max_participants}명)", ephemeral=True)
                await asyncio.sleep(2)
                await msg.delete()
                return
            
            # 참가자 추가 (슈퍼유저는 중복 추가 가능)
            if is_super or user_id not in self.participants:
                await self.db["recruitments"].update_one(
                    {"recruitment_id": self.recruitment_id},
                    {"$push": {"participants": user_id}}
                )
                
                # 참가자 목록 업데이트
                self.participants.append(user_id)
                
                # 임베드 업데이트
                embed = self.get_embed()
                await interaction.message.edit(embed=embed, view=self)
                
                await interaction.response.defer(ephemeral=True)
                msg = await interaction.followup.send("참가 신청이 완료되었습니다.", ephemeral=True)
                await asyncio.sleep(2)
                await msg.delete()
                
                # 인원이 다 찼는지 확인
                if len(self.participants) >= self.max_participants:
                    # 모집 상태를 "모집 완료"로 변경
                    self.status = "모집 완료"
                    
                    # DB 업데이트
                    await self.db["recruitments"].update_one(
                        {"recruitment_id": self.recruitment_id},
                        {"$set": {"status": "모집 완료"}}
                    )
                    
                    # 임베드 업데이트
                    embed = self.get_embed()
                    await interaction.message.edit(embed=embed, view=self)
                    
                    # 비밀 스레드 생성
                    await self.create_private_thread(interaction)
            else:
                await interaction.response.defer(ephemeral=True)
                msg = await interaction.followup.send("이미 참가 신청하셨습니다.", ephemeral=True)
                await asyncio.sleep(2)
                await msg.delete()
            
        except Exception as e:
            print(f"[ERROR] 참가 신청 중 오류 발생: {e}")
            import traceback
            print(f"[ERROR] 상세 오류: {traceback.format_exc()}")
            if not interaction.response.is_done():
                await interaction.response.defer(ephemeral=True)
                msg = await interaction.followup.send("참가 신청 중 오류가 발생했습니다.", ephemeral=True)
                await asyncio.sleep(2)
                await msg.delete()

    async def btn_cancel_callback(self, interaction: discord.Interaction):
        """신청 취소 버튼 클릭 시 호출되는 콜백"""
        try:
            # 모집 정보 가져오기
            recruitment = await self.db["recruitments"].find_one({"recruitment_id": self.recruitment_id})
            if not recruitment:
                print(f"[ERROR] 모집 정보를 찾을 수 없음: {self.recruitment_id}")
                await interaction.response.defer(ephemeral=True)
                msg = await interaction.followup.send("모집 정보를 찾을 수 없습니다.", ephemeral=True)
                await asyncio.sleep(2)
                await msg.delete()
                return
            
            # 사용자 ID
            user_id = str(interaction.user.id)
            
            # 참가 신청한 사용자인지 확인
            if user_id not in recruitment.get("participants", []):
                await interaction.response.defer(ephemeral=True)
                msg = await interaction.followup.send("참가 신청한 내역이 없습니다.", ephemeral=True)
                await asyncio.sleep(2)
                await msg.delete()
                return
            
            # 모집 생성자는 참가 취소 불가능
            if user_id == recruitment.get("creator_id"):
                await interaction.response.defer(ephemeral=True)
                msg = await interaction.followup.send("모집 생성자는 참가를 취소할 수 없습니다.", ephemeral=True)
                await asyncio.sleep(2)
                await msg.delete()
                return
            
            # 참가자 제거
            await self.db["recruitments"].update_one(
                {"recruitment_id": self.recruitment_id},
                {"$pull": {"participants": user_id}}
            )
            
            # 참가자 목록 업데이트
            self.participants.remove(user_id)
            
            # 임베드 업데이트
            embed = self.get_embed()
            await interaction.message.edit(embed=embed, view=self)
            
            await interaction.response.defer(ephemeral=True)
            msg = await interaction.followup.send("참가 신청이 취소되었습니다.", ephemeral=True)
            await asyncio.sleep(2)
            await msg.delete()
            
        except Exception as e:
            print(f"[ERROR] 참가 취소 중 오류 발생: {e}")
            import traceback
            print(f"[ERROR] 상세 오류: {traceback.format_exc()}")
            if not interaction.response.is_done():
                await interaction.response.defer(ephemeral=True)
                msg = await interaction.followup.send("참가 취소 중 오류가 발생했습니다.", ephemeral=True)
                await asyncio.sleep(2)
                await msg.delete()

    async def create_private_thread(self, interaction: discord.Interaction):
        """모집 완료 시 비밀 스레드를 생성합니다."""
        try:
            # 스레드 이름 생성
            thread_name = f"{self.selected_type} {self.selected_kind} {self.selected_diff} 모집 완료"
            
            # 스레드 생성
            thread = await interaction.message.create_thread(
                name=thread_name,
                auto_archive_duration=60  # 1시간 후 자동 보관
            )
            
            # 모집자 멘션과 함께 보관 기간 선택 메시지 전송
            author = self.participants[0]  # 첫 번째 참가자가 모집자
            archive_view = ThreadArchiveView(
                self.db, 
                self.recruitment_id, 
                str(thread.id),
                self.participants, 
                self.selected_type, 
                self.selected_kind, 
                self.selected_diff, 
                self.recruitment_content,
                str(interaction.guild_id)
            )
            
            await thread.send(
                f"<@{author}>\n"
                f"## 스레드 보관 기간을 선택해주세요\n"
                f"아래 버튼에서 스레드 유지 기간을 선택하면\n"
                f"다른 참가자들이 초대되고 채팅이 시작됩니다.",
                view=archive_view
            )
            
            # DB에 스레드 정보 저장
            await self.db["recruitments"].update_one(
                {"recruitment_id": self.recruitment_id},
                {
                    "$set": {
                        "thread_id": str(thread.id),
                        "thread_created_at": datetime.datetime.now().isoformat()
                    }
                }
            )
            
        except Exception as e:
            print(f"[ERROR] 스레드 생성 중 오류 발생: {e}")
            import traceback
            print(f"[ERROR] 상세 오류: {traceback.format_exc()}")
            await interaction.followup.send("스레드 생성 중 오류가 발생했습니다.", ephemeral=True)

    # 슈퍼유저 체크 함수
    def is_super_user(self, user):
        """사용자가 슈퍼유저인지 확인"""
        return str(user.id) == SUPER_USER_ID

# 스레드 보관 기간 선택을 위한 뷰 클래스
class ThreadArchiveView(ui.View):
    def __init__(self, db, recruitment_id, thread_id, participants, dungeon_type, dungeon_kind, dungeon_diff, recruitment_content, guild_id):
        super().__init__(timeout=None)  # 타임아웃 없음 (영구적으로 유지)
        self.db = db
        self.recruitment_id = recruitment_id
        self.thread_id = thread_id
        self.participants = participants
        self.dungeon_type = dungeon_type
        self.dungeon_kind = dungeon_kind
        self.dungeon_diff = dungeon_diff
        self.recruitment_content = recruitment_content
        self.guild_id = guild_id
    
    @ui.button(label="1일", style=discord.ButtonStyle.primary, custom_id="archive_1day")
    async def btn_archive_1day(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.set_archive_duration(interaction, 1440)  # 1일 (분 단위)
    
    @ui.button(label="3일", style=discord.ButtonStyle.primary, custom_id="archive_3days")
    async def btn_archive_3days(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.set_archive_duration(interaction, 4320)  # 3일 (분 단위)
    
    @ui.button(label="7일", style=discord.ButtonStyle.primary, custom_id="archive_7days")
    async def btn_archive_7days(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.set_archive_duration(interaction, 10080)  # 7일 (분 단위)
    
    @ui.button(label="1시간 (테스트)", style=discord.ButtonStyle.danger, custom_id="archive_1hour", row=1)
    async def btn_archive_1hour(self, interaction: discord.Interaction, button: discord.ui.Button):
        # 슈퍼유저 체크
        if interaction.user.name != "힝트" and interaction.user.display_name != "힝트":
            await interaction.response.defer(ephemeral=True)
            msg = await interaction.followup.send("이 버튼은 슈퍼유저만 사용할 수 있습니다.", ephemeral=True)
            await asyncio.sleep(2)
            await msg.delete()
            return
        await self.set_archive_duration(interaction, 60)  # 1시간
    
    async def set_archive_duration(self, interaction: discord.Interaction, duration_minutes: int):
        try:
            thread = interaction.channel
            
            # 모집자만 버튼을 누를 수 있도록 체크
            author = self.participants[0]  # 첫 번째 참가자가 모집자
            if str(interaction.user.id) != author:
                await interaction.response.defer(ephemeral=True)
                msg = await interaction.followup.send("모집자만 스레드 보관 기간을 설정할 수 있습니다.", ephemeral=True)
                await asyncio.sleep(2)
                await msg.delete()
                return
            
            # 스레드 보관 기간 설정
            await thread.edit(auto_archive_duration=duration_minutes)
            
            # 응답 메시지
            if duration_minutes == 60:
                await interaction.response.defer(ephemeral=True)
                msg = await interaction.followup.send("스레드 보관 기간이 1시간으로 설정되었습니다. (테스트용)")
                await asyncio.sleep(2)
                await msg.delete()
            else:
                days = duration_minutes // 1440
                await interaction.response.defer(ephemeral=True)
                msg = await interaction.followup.send(f"스레드 보관 기간이 {days}일로 설정되었습니다.")
                await asyncio.sleep(2)
                await msg.delete()
            
            # 버튼 비활성화
            for child in self.children:
                child.disabled = True
            
            # 뷰 업데이트
            await interaction.message.edit(view=self)
            
            # DB 업데이트: 스레드 보관 기간 저장
            now = datetime.datetime.now().isoformat()
            await self.db["recruitments"].update_one(
                {"recruitment_id": self.recruitment_id},
                {
                    "$set": {
                        "thread_archive_duration": duration_minutes,
                        "updated_at": now
                    }
                }
            )
            
            # 나머지 참가자들을 스레드에 초대하는 메시지 전송
            other_participants = self.participants[1:]  # 모집자 제외
            if other_participants:
                mentions = " ".join([f"<@{p}>" for p in other_participants])
                thread_name = f"{self.dungeon_type} {self.dungeon_kind} {self.dungeon_diff}"
                content = (
                    f"# {thread_name} 모집 완료\n"
                    f"모집이 완료되었습니다! 참가자 여러분 환영합니다.\n\n"
                    f"**던전**: {self.dungeon_type} - {self.dungeon_kind} ({self.dungeon_diff})\n"
                    f"**모집 내용**: {self.recruitment_content}\n\n"
                    f"**참가자 명단**:\n" + 
                    "\n".join([f"{i+1}. <@{p}>" for i, p in enumerate(self.participants)])
                )
                
                await thread.send(f"{mentions}\n\n{content}")
            
        except Exception as e:
            print(f"스레드 보관 기간 설정 중 오류 발생: {e}")
            import traceback
            print(f"상세 오류: {traceback.format_exc()}")
            if not interaction.response.is_done():
                await interaction.response.defer(ephemeral=True)
                msg = await interaction.followup.send(f"스레드 보관 기간 설정 중 오류가 발생했습니다: {e}", ephemeral=True)
                await asyncio.sleep(2)
                await msg.delete()
