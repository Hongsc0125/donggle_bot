import discord
from discord import ui, Embed, Color, SelectOption, Interaction
from views.recruitment_card_views import RecruitmentModal
import datetime
from core.config import settings

# 슈퍼유저 이름 정의
SUPER_USER = "힝트"

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
        self.status = None  # 모집 상태
        self.recruitment_id = None  # DB에 저장된 모집 ID
        self.participants = []  # 참가자 목록
        self.max_participants = 4  # 기본 최대 인원 수 (본인 포함)
        self.target_channel_id = None  # 모집 공고를 게시할 채널 ID
        self.announcement_message_id = None  # 모집 공고 메시지 ID
        
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
                f"> `{p['user_name']}`" 
                for i, p in enumerate(self.participants)
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
    
    @ui.button(label="모집 내용 작성", style=discord.ButtonStyle.success, custom_id="btn_content", row=4)
    async def btn_content(self, interaction: discord.Interaction, button: discord.ui.Button):
        modal = RecruitmentModal()
        modal.parent = self  # 모달이 이 RecruitmentCard 상태를 업데이트할 수 있도록 참조 전달
        await interaction.response.send_modal(modal)
    
    @ui.button(label="모집 등록", style=discord.ButtonStyle.primary, custom_id="btn_register", row=4)
    async def btn_register(self, interaction: discord.Interaction, button: discord.ui.Button):
        # 필수 정보가 모두 입력되었는지 확인
        if not self.selected_type or not self.selected_kind or not self.selected_diff or not self.recruitment_content:
            await interaction.response.send_message("모든 정보를 입력해주세요!", ephemeral=True)
            return
        
        # 이미 등록된 모집인지 확인
        if self.recruitment_id:
            await interaction.response.send_message("이미 등록된 모집입니다!", ephemeral=True)
            return
            
        # 등록 완료 메시지 표시 (모든 사용자에게 보이도록)
        await interaction.response.send_message(f"모집이 등록되었습니다!\n{self.selected_type} {self.selected_kind} ({self.selected_diff}) - {self.max_participants}명\n\n**새로운 모집등록은 5초뒤 가능합니다**")
            
        # 현재 시간을 config에서 가져오기
        now = datetime.datetime.fromisoformat(settings.CURRENT_DATETIME)
        
        # 초기 참가자로 모집 작성자 추가
        self.participants = [{
            "user_id": str(interaction.user.id),
            "user_name": interaction.user.display_name,
            "joined_at": now
        }]
        
        # DB에 저장할 모집 정보 생성
        recruitment_data = {
            "guild_id": str(interaction.guild.id),
            "channel_id": str(interaction.channel.id),
            "message_id": str(self.message.id),
            "author_id": str(interaction.user.id),
            "author_name": interaction.user.display_name,
            "dungeon_type": self.selected_type,
            "dungeon_name": self.selected_kind,
            "dungeon_difficulty": self.selected_diff,
            "content": self.recruitment_content,
            "status": "대기중",  # 초기 상태: 대기중
            "created_at": now,
            "updated_at": now,
            "participants": self.participants,
            "max_participants": self.max_participants
        }
        
        # DB에 모집 정보 저장
        result = await self.db["recruitments"].insert_one(recruitment_data)
        
        # 상태 업데이트
        self.status = "대기중"
        self.recruitment_id = result.inserted_id  # 추후 참조를 위해 ID 저장
        
        # 등록 후 UI 업데이트: 선택 메뉴 비활성화
        # 선택 메뉴 값 표시 및 비활성화
        # 타입 선택 메뉴 업데이트
        self.type_select.placeholder = f"🏰 {self.selected_type}"
        self.type_select.disabled = True
        
        # 종류 선택 메뉴 업데이트
        self.kind_select.placeholder = f"⚔️ {self.selected_kind}"
        self.kind_select.disabled = True
        
        # 난이도 선택 메뉴 업데이트
        self.diff_select.placeholder = f"⭐ {self.selected_diff}"
        self.diff_select.disabled = True
        
        # 인원 설정 메뉴 업데이트
        self.max_participants_select.placeholder = f"최대 {self.max_participants}명"
        self.max_participants_select.disabled = True
        
        # 등록 버튼 비활성화
        button.disabled = True
        
        # 모집 정보 임베드 업데이트
        embed = self.get_embed()
        await self.message.edit(embed=embed, view=self)
        
        # 모집 공고 채널에 공고 게시
        try:
            # cogs에서 PartyCog 가져오기
            party_cog = interaction.client.get_cog("PartyCog")
            if party_cog:
                # 모집 공고 채널에 공고 게시
                await party_cog.post_recruitment_announcement(
                    interaction.guild.id,
                    recruitment_data,
                    self
                )
                
                # 5초 동안 모집 등록 중지 상태 설정
                party_cog.registration_locked = True
                
                # 5초 후 등록 채널 초기화 (비동기 타이머)
                import asyncio
                
                async def delayed_cleanup():
                    await asyncio.sleep(5)  # 5초 대기
                    
                    if party_cog.registration_channel_id:
                        try:
                            # 등록 제한 해제
                            party_cog.registration_locked = False
                            
                            reg_channel = interaction.guild.get_channel(int(party_cog.registration_channel_id))
                            if reg_channel:
                                # 채널의 메시지 삭제 (최근 10개)
                                await reg_channel.purge(limit=10)
                                # 새 등록 양식 생성
                                await party_cog.create_registration_form(reg_channel)
                        except Exception as e:
                            print(f"등록 채널 초기화 중 오류 발생: {e}")
                            # 오류가 발생해도 잠금 해제
                            party_cog.registration_locked = False
                
                # 비동기 타이머 시작
                asyncio.create_task(delayed_cleanup())
                        
        except Exception as e:
            print(f"모집 공고 게시 중 오류 발생: {e}")
            # 오류가 발생해도 5초 후 채널 초기화 시도
            import asyncio
            
            async def delayed_cleanup_fallback():
                await asyncio.sleep(5)  # 5초 대기
                
                try:
                    party_cog = interaction.client.get_cog("PartyCog")
                    if party_cog:
                        # 등록 제한 해제
                        party_cog.registration_locked = False
                        
                        if party_cog.registration_channel_id:
                            reg_channel = interaction.guild.get_channel(int(party_cog.registration_channel_id))
                            if reg_channel:
                                await reg_channel.purge(limit=10)
                                await party_cog.create_registration_form(reg_channel)
                except Exception as e2:
                    print(f"등록 채널 초기화 중 오류 발생: {e2}")
                    # 오류가 발생해도 잠금 해제
                    if party_cog:
                        party_cog.registration_locked = False
            
            # 비동기 타이머 시작
            asyncio.create_task(delayed_cleanup_fallback())
    
    async def btn_join_callback(self, interaction: discord.Interaction):
        # 등록된 모집이 없으면 참가 불가
        if not self.recruitment_id:
            await interaction.response.send_message("등록된 모집이 없습니다!", ephemeral=True)
            return
            
        # 인원 초과 여부 확인
        if len(self.participants) >= self.max_participants:
            await interaction.response.send_message("모집 인원이 다 찼습니다!", ephemeral=True)
            return
        
        # 슈퍼유저 체크
        is_super = self.is_super_user(interaction.user)
        
        # 이미 참가한 사용자인지 확인 (슈퍼유저는 중복 참가 가능)
        user_id = str(interaction.user.id)
        if not is_super and any(p["user_id"] == user_id for p in self.participants):
            await interaction.response.send_message("이미 참가한 모집입니다!", ephemeral=True)
            return
        
        # 응답 처리 (defer)
        await interaction.response.defer(ephemeral=True)
            
        # 현재 시간을 config에서 가져오기
        now = datetime.datetime.fromisoformat(settings.CURRENT_DATETIME)
        
        # 참가자 정보 생성
        participant = {
            "user_id": user_id,
            "user_name": interaction.user.display_name,
            "joined_at": now
        }
        
        # 슈퍼유저 중복 참가 처리
        if is_super and any(p["user_id"] == user_id for p in self.participants):
            # 이름에 번호 추가하여 중복 참가 표시
            count = sum(1 for p in self.participants if p["user_id"] == user_id)
            participant["user_name"] += f" ({count+1})"
        
        # DB에서 최신 상태 확인
        recruitment = await self.db["recruitments"].find_one({"_id": self.recruitment_id})
        if not recruitment:
            await interaction.followup.send("모집 정보를 찾을 수 없습니다.", ephemeral=True)
            return
            
        # 모집이 이미 완료되었는지 확인
        if recruitment["status"] == "모집 완료":
            await interaction.followup.send("이미 모집이 완료되었습니다.", ephemeral=True)
            return
            
        # 현재 참가자 수 확인
        current_participants = len(recruitment["participants"])
        if current_participants >= recruitment["max_participants"]:
            await interaction.followup.send("모집 인원이 다 찼습니다!", ephemeral=True)
            return
            
        # DB 업데이트 (원자적 연산 사용)
        result = await self.db["recruitments"].update_one(
            {
                "_id": self.recruitment_id,
                "status": "대기중",
                "participants": {"$size": current_participants}
            },
            {
                "$push": {"participants": participant},
                "$set": {"updated_at": now}
            }
        )
        
        # 업데이트 실패 시 (다른 사용자가 먼저 참가한 경우)
        if result.modified_count == 0:
            await interaction.followup.send("다른 사용자가 먼저 참가했습니다. 다시 시도해주세요.", ephemeral=True)
            return
        
        # 참가자 목록에 추가
        self.participants.append(participant)
        
        # 임베드 업데이트
        embed = self.get_embed()
        await self.message.edit(embed=embed, view=self)
        
        # 공고 메시지도 업데이트
        if self.announcement_message_id and self.target_channel_id:
            try:
                channel = interaction.guild.get_channel(int(self.target_channel_id))
                announcement_message = await channel.fetch_message(int(self.announcement_message_id))
                await announcement_message.edit(embed=embed, view=self)
            except:
                pass
        
        # 인원이 다 찼으면 스레드 생성
        if len(self.participants) >= self.max_participants:
            # DB에서 다시 한 번 상태 확인
            recruitment = await self.db["recruitments"].find_one({"_id": self.recruitment_id})
            if recruitment["status"] == "모집 완료":
                return
                
            # 상태 업데이트 (원자적 연산 사용)
            result = await self.db["recruitments"].update_one(
                {
                    "_id": self.recruitment_id,
                    "status": "대기중"
                },
                {
                    "$set": {
                        "status": "모집 완료",
                        "updated_at": now
                    }
                }
            )
            
            # 업데이트 실패 시 (다른 사용자가 먼저 상태를 변경한 경우)
            if result.modified_count == 0:
                return
            
            # 상태 업데이트
            self.status = "모집 완료"
            
            # 임베드 업데이트
            embed = self.get_embed()
            await self.message.edit(embed=embed, view=self)
            
            # 공고 메시지도 업데이트
            if self.announcement_message_id and self.target_channel_id:
                try:
                    channel = interaction.guild.get_channel(int(self.target_channel_id))
                    announcement_message = await channel.fetch_message(int(self.announcement_message_id))
                    await announcement_message.edit(embed=embed, view=self)
                except:
                    pass
            
            # 비공개 스레드 생성
            await self.create_private_thread(interaction)
    
    @ui.button(label="신청 취소", style=discord.ButtonStyle.danger, custom_id="btn_cancel", row=4)
    async def btn_cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        # 등록된 모집이 없으면 취소 불가
        if not self.recruitment_id:
            await interaction.response.send_message("등록된 모집이 없습니다!", ephemeral=True)
            return
            
        # 모집 완료 상태면 취소 불가
        if self.status == "모집 완료":
            await interaction.response.send_message("모집이 완료되어 취소할 수 없습니다!", ephemeral=True)
            return
            
        # 응답 처리 (defer)
        await interaction.response.defer(ephemeral=True)
            
        # 현재 시간을 config에서 가져오기
        now = datetime.datetime.fromisoformat(settings.CURRENT_DATETIME)
        
        # DB에서 최신 상태 확인
        recruitment = await self.db["recruitments"].find_one({"_id": self.recruitment_id})
        if not recruitment:
            await interaction.followup.send("모집 정보를 찾을 수 없습니다.", ephemeral=True)
            return
            
        # 모집이 이미 완료되었는지 확인
        if recruitment["status"] == "모집 완료":
            await interaction.followup.send("이미 모집이 완료되었습니다.", ephemeral=True)
            return
            
        # 참가자 목록에서 사용자 찾기
        user_id = str(interaction.user.id)
        participant_index = next((i for i, p in enumerate(recruitment["participants"]) if p["user_id"] == user_id), None)
        if participant_index is None:
            await interaction.followup.send("참가하지 않은 모집입니다!", ephemeral=True)
            return
            
        # DB 업데이트 (원자적 연산 사용)
        result = await self.db["recruitments"].update_one(
            {
                "_id": self.recruitment_id,
                "status": "대기중",
                "participants.user_id": user_id
            },
            {
                "$pull": {"participants": {"user_id": user_id}},
                "$set": {"updated_at": now}
            }
        )
        
        # 업데이트 실패 시
        if result.modified_count == 0:
            await interaction.followup.send("취소할 수 없습니다. 다시 시도해주세요.", ephemeral=True)
            return
        
        # 참가자 목록에서 제거
        self.participants = [p for p in self.participants if p["user_id"] != user_id]
        
        # 임베드 업데이트
        embed = self.get_embed()
        await self.message.edit(embed=embed, view=self)
        
        # 공고 메시지도 업데이트
        if self.announcement_message_id and self.target_channel_id:
            try:
                channel = interaction.guild.get_channel(int(self.target_channel_id))
                announcement_message = await channel.fetch_message(int(self.announcement_message_id))
                await announcement_message.edit(embed=embed, view=self)
            except:
                pass
    
    async def create_private_thread(self, interaction: discord.Interaction):
        # 스레드 생성
        thread_name = f"{self.selected_type} {self.selected_kind} {self.selected_diff} 모집 완료"
        try:
            # Discord.py 버전에 따라 지원하는 방식으로 스레드 생성
            thread = None
            try:
                # 최신 버전 - 초기 보관 시간은 60분으로 설정
                thread = await self.message.create_thread(
                    name=thread_name,
                    auto_archive_duration=60  # 임시 기본값, 사용자가 선택할 예정
                )
            except TypeError:
                # 이전 버전
                thread = await self.message.create_thread(name=thread_name)
            
            if not thread:
                await interaction.followup.send("스레드 생성에 실패했습니다.", ephemeral=True)
                return
            
            # 모집자 정보
            author = self.participants[0]  # 첫 번째 참가자가 모집자
            author_member = interaction.guild.get_member(int(author["user_id"]))
            
            # 스레드 보관 기간 선택 뷰 생성
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
            
            # 스레드에 모집자 멘션과 함께 보관 기간 선택 메시지 전송
            await thread.send(
                f"<@{author['user_id']}>\n"
                f"## 스레드 보관 기간을 선택해주세요\n"
                f"아래 버튼에서 스레드 유지 기간을 선택하면\n"
                f"다른 참가자들이 초대되고 채팅이 시작됩니다.",
                view=archive_view
            )
            
            # DB 업데이트: 스레드 정보 저장
            now = datetime.datetime.fromisoformat(settings.CURRENT_DATETIME)
            await self.db["recruitments"].update_one(
                {"_id": self.recruitment_id},
                {
                    "$set": {
                        "thread_id": str(thread.id),
                        "thread_created_at": now,
                        "updated_at": now
                    }
                }
            )
        except Exception as e:
            print(f"스레드 생성 중 오류 발생: {e}")
            await interaction.followup.send(f"스레드 생성 중 오류가 발생했습니다: {e}", ephemeral=True)

    # 슈퍼유저 체크 함수
    def is_super_user(self, user):
        return user.display_name == SUPER_USER or user.name == SUPER_USER

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
            await interaction.response.send_message("이 버튼은 슈퍼유저만 사용할 수 있습니다.", ephemeral=True)
            return
        await self.set_archive_duration(interaction, 60)  # 1시간
    
    async def set_archive_duration(self, interaction: discord.Interaction, duration_minutes: int):
        try:
            thread = interaction.channel
            
            # 모집자만 버튼을 누를 수 있도록 체크
            author = self.participants[0]  # 첫 번째 참가자가 모집자
            if str(interaction.user.id) != author["user_id"]:
                await interaction.response.send_message("모집자만 스레드 보관 기간을 설정할 수 있습니다.", ephemeral=True)
                return
            
            # 스레드 보관 기간 설정
            await thread.edit(auto_archive_duration=duration_minutes)
            
            # 응답 메시지
            if duration_minutes == 60:
                await interaction.response.send_message("스레드 보관 기간이 1시간으로 설정되었습니다. (테스트용)")
            else:
                days = duration_minutes // 1440
                await interaction.response.send_message(f"스레드 보관 기간이 {days}일로 설정되었습니다.")
            
            # 버튼 비활성화
            for child in self.children:
                child.disabled = True
            
            # 뷰 업데이트
            await interaction.message.edit(view=self)
            
            # DB 업데이트: 스레드 보관 기간 저장
            now = datetime.datetime.fromisoformat(settings.CURRENT_DATETIME)
            await self.db["recruitments"].update_one(
                {"_id": self.recruitment_id},
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
                mentions = " ".join([f"<@{p['user_id']}>" for p in other_participants])
                thread_name = f"{self.dungeon_type} {self.dungeon_kind} {self.dungeon_diff}"
                content = (
                    f"# {thread_name} 모집 완료\n"
                    f"모집이 완료되었습니다! 참가자 여러분 환영합니다.\n\n"
                    f"**던전**: {self.dungeon_type} - {self.dungeon_kind} ({self.dungeon_diff})\n"
                    f"**모집 내용**: {self.recruitment_content}\n\n"
                    f"**참가자 명단**:\n" + 
                    "\n".join([f"{i+1}. {p['user_name']}" for i, p in enumerate(self.participants)])
                )
                
                await thread.send(f"{mentions}\n\n{content}")
            
        except Exception as e:
            print(f"스레드 보관 기간 설정 중 오류 발생: {e}")
            await interaction.response.send_message(f"스레드 보관 기간 설정 중 오류가 발생했습니다: {e}", ephemeral=True)
