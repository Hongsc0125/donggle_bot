import discord
from discord import ui, Embed, Color, SelectOption, Interaction
from views.recruitment_card_views import RecruitmentModal
import datetime
from core.config import settings
import asyncio
import traceback  # traceback 모듈 추가
from bson.objectid import ObjectId
from core.logger import logger

# 슈퍼유저 ID 정의
SUPER_USER_ID = "307620267067179019"

class CreatorOnlyButton(ui.Button):
    """모집 생성자에게만 보이는 버튼 클래스"""
    def __init__(self, label, style, custom_id, callback, creator_id, row=0):
        super().__init__(label=label, style=style, custom_id=custom_id, row=row)
        self.creator_id = creator_id
        self.real_callback = callback
    
    async def callback(self, interaction: discord.Interaction):
        # 모집 생성자인지 확인
        if interaction.user.id != self.creator_id:
            await interaction.response.defer(ephemeral=True)
            msg = await interaction.followup.send("모집 생성자만 이 버튼을 사용할 수 있습니다.", ephemeral=True)
            await asyncio.sleep(2)
            await msg.delete()
            return
        
        # 실제 콜백 함수 호출
        await self.real_callback(interaction)

class RecruitmentCard(ui.View):
    def __init__(self, dungeons, db):
        super().__init__(timeout=None)
        self.dungeons = dungeons
        self.db = db  # MongoDB 데이터베이스 객체 저장
        self.selected_type = None
        self.selected_kind = None
        self.selected_diff = None
        self.recruitment_content = None
        self.message = None  # persistent 메시지 저장
        self.status = "pending"  # 초기 상태: pending
        self.recruitment_id = None  # DB에 저장된 모집 ID (MongoDB _id)
        self.participants = []  # 참가자 목록
        self.max_participants = None  # 기본 최대 인원 수 (본인 포함)
        self.announcement_channel_id = None  # 모집 공고를 게시할 채널 ID
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
        content_button = ui.Button(label="모집 상세내용 입력", style=discord.ButtonStyle.success, custom_id="btn_content", row=4)
        content_button.callback = self.btn_content_callback
        self.add_item(content_button)
        
        # 모집 등록 버튼 추가 (초기에는 비활성화)
        register_button = ui.Button(label="모집 등록", style=discord.ButtonStyle.primary, custom_id="btn_register", row=4)
        register_button.callback = self.btn_register_callback
        
        # 각 필수값의 상태 로깅
        has_type = bool(self.selected_type)
        has_kind = bool(self.selected_kind)
        has_diff = bool(self.selected_diff)
        has_content = bool(self.recruitment_content)
        has_max_participants = bool(self.max_participants)
        
        # 모든 필수 정보가 입력되었는지 확인하여 버튼 활성화 여부 결정
        button_enabled = all([has_type, has_kind, has_diff, has_content, has_max_participants])
        register_button.disabled = not button_enabled
        
        # 디버그 로그 추가
        logger.debug(f"_setup_buttons - 모집 등록 버튼 활성화 상태: {not register_button.disabled}")
        logger.debug(f"_setup_buttons - 필수값 상태 (각각): type={has_type}, kind={has_kind}, diff={has_diff}, content={has_content}, max_participants={has_max_participants}")
        logger.debug(f"_setup_buttons - 필수값 상태 (all 함수): {button_enabled}")
        logger.debug(f"_setup_buttons - 필수값 실제 값: type={self.selected_type}, kind={self.selected_kind}, diff={self.selected_diff}, content_len={len(self.recruitment_content) if self.recruitment_content else 0}, max_participants={self.max_participants}")
        
        self.add_item(register_button)

    def _create_max_participants_select(self):
        options = [
            SelectOption(label=f"최대 {i}명 (본인포함)", value=str(i)) for i in range(2, 5)
        ]
        select = ui.Select(
            placeholder="인원 설정",
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
    
    def get_embed(self):
        """현재 상태로 임베드를 생성합니다."""
        embed = discord.Embed(title="파티 모집 카드", color=discord.Color.blue())
        
        if self.status == "active":
            embed.description = "현재 모집 중인 파티입니다."
        elif self.status == "complete":
            embed.description = "모집이 완료된 파티입니다."
            embed.color = discord.Color.green()
        elif self.status == "cancelled":
            embed.description = "취소된 모집입니다."
            embed.color = discord.Color.red()
        else:
            embed.description = "파티 모집 양식입니다. 아래 항목을 모두 작성해주세요."
        
        # 던전 정보 (타입, 종류, 난이도)
        if self.selected_type:
            embed.add_field(name="던전 유형", value=f"`{self.selected_type}`", inline=True)
        else:
            embed.add_field(name="던전 유형", value="선택되지 않음", inline=True)
            
        if self.selected_kind:
            embed.add_field(name="던전 종류", value=f"`{self.selected_kind}`", inline=True)
        else:
            embed.add_field(name="던전 종류", value="선택되지 않음", inline=True)
            
        if self.selected_diff:
            embed.add_field(name="난이도", value=f"`{self.selected_diff}`", inline=True)
        else:
            embed.add_field(name="난이도", value="선택되지 않음", inline=True)
        
        # 구분선
        embed.add_field(name="\n───────────────\n", value="", inline=False)
            
        # 모집 내용
        if self.recruitment_content:
            embed.add_field(name="모집 내용", value=self.recruitment_content, inline=False)
        else:
            embed.add_field(name="모집 내용", value="작성되지 않음", inline=False)
            
        # 모집 인원
        if self.max_participants:
            embed.add_field(name="최대 인원", value=f"{self.max_participants}명", inline=True)
        else:
            embed.add_field(name="최대 인원", value="설정되지 않음", inline=True)
            
        # 모집 상태
        if self.status == "active":
            embed.add_field(name="상태", value="모집 중 🔍", inline=True)
        elif self.status == "complete":
            embed.add_field(name="상태", value="모집 완료 ✅", inline=True)
        elif self.status == "cancelled":
            embed.add_field(name="상태", value="모집 취소 ❌", inline=True)
        else:
            embed.add_field(name="상태", value="작성 중", inline=True)
        
        # 구분선
        embed.add_field(name="\n───────────────\n", value="", inline=False)
            
        # 참가자 목록
        participants_text = ""
        if self.participants:
            participants_text = f"현재 {len(self.participants)}/{self.max_participants}명 참가 중\n"
            for i, p_id in enumerate(self.participants):
                participants_text += f"{i+1}. <@{p_id}>\n"
        else:
            participants_text = "참가자가 없습니다."
        
        embed.add_field(name="참가자 목록", value=participants_text, inline=False)
        
        # 모집 ID가 있으면 푸터에 표시
        if self.recruitment_id:
            embed.set_footer(text=f"모집 ID: {self.recruitment_id}")
        
        return embed
        
    async def update_embed_participants(self, interaction):
        """참가자 목록을 최신 정보로 업데이트한 임베드를 반환합니다."""
        embed = self.get_embed()
        
        # 참가자 목록 업데이트
        participants_text = f"현재 {len(self.participants)}/{self.max_participants}명 참가 중\n"
        for i, p_id in enumerate(self.participants):
            try:
                participant = interaction.guild.get_member(p_id)
                if participant:
                    participants_text += f"{i+1}. {participant.mention} ({participant.display_name})\n"
                else:
                    participants_text += f"{i+1}. <@{p_id}> (알 수 없는 사용자)\n"
            except Exception as e:
                logger.error(f"참가자 정보 조회 중 오류: {e}")
                participants_text += f"{i+1}. <@{p_id}>\n"
        
        # 참가자 필드 업데이트
        for i, field in enumerate(embed.fields):
            if field.name.startswith("참가자"):
                embed.set_field_at(
                    i, 
                    name=f"참가자 목록", 
                    value=participants_text or "참가자가 없습니다.", 
                    inline=False
                )
                break
        
        return embed

    def clear_items(self):
        """모든 UI 요소를 제거합니다."""
        for item in self.children.copy():
            self.remove_item(item)
            
    async def update_embed(self, interaction: discord.Interaction = None):
        # 디버그 로그 추가
        logger.debug("update_embed - 시작")
        
        try:
            # 모든 UI 요소 제거
            for item in self.children.copy():
                self.remove_item(item)
            
            # 각 선택 메뉴 상태 업데이트
            # 타입 선택 메뉴 (row 0)
            self.type_select = self._create_type_select()
            # 선택된 값이 있으면 placeholder에 표시
            if self.selected_type:
                self.type_select.placeholder = f"🏰 {self.selected_type}"
            self.add_item(self.type_select)
            
            # 종류 선택 메뉴 (row 1)
            self.kind_select = self._create_kind_select()
            # 선택된 값이 있으면 placeholder에 표시
            if self.selected_kind:
                self.kind_select.placeholder = f"⚔️ {self.selected_kind}"
            self.add_item(self.kind_select)
            
            # 난이도 선택 메뉴 (row 2)
            self.diff_select = self._create_diff_select()
            # 선택된 값이 있으면 placeholder에 표시
            if self.selected_diff:
                self.diff_select.placeholder = f"⭐ {self.selected_diff}"
            self.add_item(self.diff_select)
            
            # 인원 설정 메뉴 (row 3)
            self.max_participants_select = self._create_max_participants_select()
            # 선택된 값이 있으면 placeholder에 표시
            if self.max_participants:
                self.max_participants_select.placeholder = f"최대 {self.max_participants}명"
            self.add_item(self.max_participants_select)
            
            # 필요한 버튼 추가 (row 4)
            if self.status == "pending":
                # 모집 내용 작성 버튼 추가
                content_button = ui.Button(label="모집 내용 작성", style=discord.ButtonStyle.success, custom_id="btn_content", row=4)
                content_button.callback = self.btn_content_callback
                self.add_item(content_button)
                
                # 모집 등록 버튼 추가
                register_button = ui.Button(label="모집 등록", style=discord.ButtonStyle.primary, custom_id="btn_register", row=4)
                register_button.callback = self.btn_register_callback
                
                # 각 필수값의 상태 로깅
                has_type = bool(self.selected_type)
                has_kind = bool(self.selected_kind)
                has_diff = bool(self.selected_diff)
                has_content = bool(self.recruitment_content)
                has_max_participants = bool(self.max_participants)
                
                # 모든 필수 정보가 입력되었는지 확인하여 버튼 활성화 여부 결정
                button_enabled = all([has_type, has_kind, has_diff, has_content, has_max_participants])
                register_button.disabled = not button_enabled
                
                # 디버그 로그 추가
                logger.debug(f"update_embed - 모집 등록 버튼 활성화 상태: {not register_button.disabled}")
                logger.debug(f"update_embed - 필수값 상태 (각각): type={has_type}, kind={has_kind}, diff={has_diff}, content={has_content}, max_participants={has_max_participants}")
                logger.debug(f"update_embed - 필수값 상태 (all 함수): {button_enabled}")
                if self.recruitment_content:
                    content_preview = self.recruitment_content[:30] + "..." if len(self.recruitment_content) > 30 else self.recruitment_content
                    logger.debug(f"update_embed - 모집 내용 미리보기: {content_preview}")
                
                self.add_item(register_button)
            else:
                # 등록된 모집 공고일 때 - 버튼들을 row 4에 배치
                join_button = ui.Button(label="참가하기", style=discord.ButtonStyle.success, custom_id="btn_join", row=4)
                join_button.callback = self.btn_join_callback
                self.add_item(join_button)
                
                cancel_button = ui.Button(label="신청 취소", style=discord.ButtonStyle.danger, custom_id="btn_cancel", row=4)
                cancel_button.callback = self.btn_cancel_callback
                self.add_item(cancel_button)
                
                # 모집 취소 버튼 (첫 번째 참가자에게만 보이는 버튼으로 변경)
                if self.participants and len(self.participants) > 0:
                    first_participant_id = None
                    try:
                        first_participant_id = int(self.participants[0]) if isinstance(self.participants[0], str) else self.participants[0]
                    except (ValueError, TypeError):
                        logger.warning(f"첫 번째 참가자 ID를 정수로 변환할 수 없음: {self.participants[0]}")
                    
                    if first_participant_id:
                        delete_button = CreatorOnlyButton(
                            label="모집 취소",
                            style=discord.ButtonStyle.danger,
                            custom_id="btn_delete",
                            callback=self.btn_delete_callback,
                            creator_id=first_participant_id,
                            row=4
                        )
                        self.add_item(delete_button)
                        logger.debug(f"모집 취소 버튼이 첫 번째 참가자 ID {first_participant_id}에게 표시됩니다.")
            
            # 임베드 업데이트
            embed = self.get_embed()
            
            # 디버그 로그 추가
            logger.debug("update_embed - 임베드 생성 완료, 메시지 편집 시작")
            logger.debug(f"update_embed - 선택된 값들: type={self.selected_type}, kind={self.selected_kind}, diff={self.selected_diff}, max_participants={self.max_participants}")
            logger.debug(f"update_embed - 선택 메뉴 placeholder: type={self.type_select.placeholder}, kind={self.kind_select.placeholder}, diff={self.diff_select.placeholder}, max_participants={self.max_participants_select.placeholder}")
            
            await self.message.edit(embed=embed, view=self)
            logger.debug("update_embed - 완료")
        except Exception as e:
            logger.error(f"update_embed - 메시지 편집 중 오류 발생: {e}")
            import traceback
            logger.error(f"update_embed - 상세 오류: {traceback.format_exc()}")
    
    async def type_callback(self, interaction: Interaction):
        self.selected_type = interaction.data["values"][0]
        self.selected_kind = None
        self.selected_diff = None
        
        # 디버그 로그 추가
        logger.debug(f"type_callback - 던전 타입 선택됨: {self.selected_type}")
        logger.debug(f"type_callback - 종류와 난이도 초기화: kind={self.selected_kind}, diff={self.selected_diff}")
        
        await interaction.response.defer()
        await self.update_embed(interaction)
    
    async def kind_callback(self, interaction: Interaction):
        self.selected_kind = interaction.data["values"][0]
        self.selected_diff = None
        
        # 디버그 로그 추가
        logger.debug(f"kind_callback - 던전 종류 선택됨: {self.selected_kind}")
        logger.debug(f"kind_callback - 난이도 초기화: diff={self.selected_diff}")
        
        await interaction.response.defer()
        await self.update_embed(interaction)
    
    async def diff_callback(self, interaction: Interaction):
        self.selected_diff = interaction.data["values"][0]
        
        # 디버그 로그 추가
        logger.debug(f"diff_callback - 난이도 선택됨: {self.selected_diff}")
        
        await interaction.response.defer()
        await self.update_embed(interaction)
    
    async def max_participants_callback(self, interaction: Interaction):
        self.max_participants = int(interaction.data["values"][0])
        
        # 디버그 로그 추가
        logger.debug(f"max_participants_callback - 최대 인원 설정: {self.max_participants}")
        
        await interaction.response.defer()
        await self.update_embed(interaction)
    
    async def btn_content_callback(self, interaction: discord.Interaction):
        """모집 내용 작성 버튼 콜백"""
        modal = RecruitmentModal()
        modal.parent = self
        await interaction.response.send_modal(modal)
        # 모달 제출 후 버튼 상태가 RecruitmentModal에서 업데이트됨

    async def btn_register_callback(self, interaction: discord.Interaction):
        """모집 등록 버튼 콜백"""
        try:
            # 모집 정보 생성
            recruitment_data = {
                "type": self.selected_type,
                "dungeon": self.selected_kind,
                "difficulty": self.selected_diff,
                "max_participants": self.max_participants,
                "description": self.recruitment_content,
                "creator_id": str(interaction.user.id),
                "creator_name": interaction.user.display_name,
                "participants": [str(interaction.user.id)],
                "status": "active",
                "registration_channel_id": str(interaction.channel.id),
                "guild_id": str(interaction.guild.id),
                "created_at": datetime.datetime.now().isoformat(),
                "updated_at": datetime.datetime.now().isoformat()
            }
            
            # 공지 전송 준비
            from cogs.party import PartyCog
            party_cog = None
            
            # PartyCog 찾기
            for cog in interaction.client.cogs.values():
                if isinstance(cog, PartyCog):
                    party_cog = cog
                    break
            
            if not party_cog:
                logger.error("PartyCog를 찾을 수 없습니다.")
                await interaction.response.defer(ephemeral=True)
                msg = await interaction.followup.send("모집 등록 중 오류가 발생했습니다. 잠시 후 다시 시도해주세요.", ephemeral=True)
                await asyncio.sleep(2)
                await msg.delete()
                return
            
            # DB에 모집 정보 저장
            result = await self.db["recruitments"].insert_one(recruitment_data)
            self.recruitment_id = str(result.inserted_id)
            logger.info(f"새 모집 등록: {self.recruitment_id}")
            
            # 참가자 목록 초기화 (모집자가 첫 번째 참가자)
            self.participants = [str(interaction.user.id)]
            self.creator_id = str(interaction.user.id)
            
            # 공고 전송
            announcement_message = await party_cog.post_recruitment_announcement(
                str(interaction.guild.id), 
                recruitment_data,
                self
            )
            
            # 임시 성공 메시지 전송
            await interaction.response.defer(ephemeral=True)
            msg = await interaction.followup.send("모집이 등록되었습니다!", ephemeral=True)
            
            if announcement_message:
                # 공고 메시지 정보 저장
                await self.db["recruitments"].update_one(
                    {"_id": ObjectId(self.recruitment_id)},
                    {
                        "$set": {
                            "announcement_message_id": str(announcement_message.id),
                            "announcement_channel_id": str(announcement_message.channel.id),
                            "updated_at": datetime.datetime.now().isoformat()
                        }
                    }
                )
            
            # 등록 양식 메시지 삭제
            try:
                await interaction.message.delete()
            except:
                pass
            
            # 5초 후 새 등록 양식 생성
            await asyncio.sleep(5)
            await party_cog.create_registration_form(interaction.channel)
            
        except Exception as e:
            logger.error(f"모집 등록 중 오류 발생: {e}")
            import traceback
            logger.error(f"상세 오류: {traceback.format_exc()}")
            if not interaction.response.is_done():
                await interaction.response.defer(ephemeral=True)
                msg = await interaction.followup.send("모집 등록 중 오류가 발생했습니다.", ephemeral=True)
                await asyncio.sleep(2)
                await msg.delete()

    async def btn_delete_callback(self, interaction: discord.Interaction):
        """모집 취소 버튼 콜백"""
        try:
            # 참가자 목록 확인
            if not self.participants or len(self.participants) == 0:
                await interaction.response.defer(ephemeral=True)
                msg = await interaction.followup.send("참가자 정보가 없습니다.", ephemeral=True)
                await asyncio.sleep(2)
                await msg.delete()
                return
            
            # 첫 번째 참가자(모집자) 확인
            first_participant_id = None
            try:
                first_participant_id = int(self.participants[0]) if isinstance(self.participants[0], str) else self.participants[0]
            except (ValueError, TypeError):
                logger.warning(f"첫 번째 참가자 ID를 정수로 변환할 수 없음: {self.participants[0]}")
                await interaction.response.defer(ephemeral=True)
                msg = await interaction.followup.send("참가자 정보 처리 중 오류가 발생했습니다.", ephemeral=True)
                await asyncio.sleep(2)
                await msg.delete()
                return
            
            # 첫 번째 참가자만 취소 가능
            if interaction.user.id != first_participant_id:
                await interaction.response.defer(ephemeral=True)
                msg = await interaction.followup.send("모집 생성자만 취소할 수 있습니다.", ephemeral=True)
                await asyncio.sleep(2)
                await msg.delete()
                return
            
            # 모집 취소 처리
            self.status = "cancelled"
            
            # DB 업데이트
            await self.db["recruitments"].update_one(
                {"_id": ObjectId(self.recruitment_id)},
                {
                    "$set": {
                        "status": "cancelled",
                        "updated_at": datetime.datetime.now().isoformat()
                    }
                }
            )
            
            # 뷰 상태 업데이트
            await self.db["view_states"].update_one(
                {"message_id": str(interaction.message.id)},
                {
                    "$set": {
                        "status": "cancelled",
                        "updated_at": datetime.datetime.now().isoformat()
                    }
                }
            )
            
            try:
                # 임베드만 먼저 업데이트
                embed = self.get_embed()
                await interaction.message.edit(embed=embed)
                
                # 모든 UI 요소를 제거한 뷰로 업데이트
                self.clear_items()
                cancelled_text = ui.Button(label="모집이 취소되었습니다", style=discord.ButtonStyle.secondary, disabled=True, row=0)
                self.add_item(cancelled_text)
                await interaction.message.edit(view=self)
            except Exception as e:
                logger.error(f"btn_delete_callback - 메시지 편집 오류: {e}")
                import traceback
                logger.error(f"btn_delete_callback - 상세 오류: {traceback.format_exc()}")
            
            # 모집 취소 메시지
            await interaction.response.defer(ephemeral=True)
            msg = await interaction.followup.send("모집이 취소되었습니다.", ephemeral=True)
            await asyncio.sleep(2)
            await msg.delete()
            
        except Exception as e:
            logger.error(f"모집 취소 중 오류 발생: {e}")
            import traceback
            logger.error(f"상세 오류: {traceback.format_exc()}")
            if not interaction.response.is_done():
                await interaction.response.defer(ephemeral=True)
                msg = await interaction.followup.send("모집 취소 중 오류가 발생했습니다.", ephemeral=True)
                await asyncio.sleep(2)
                await msg.delete()

    async def create_private_thread(self, interaction: discord.Interaction, creator_id=None, initiator_id=None):
        """모집 완료 시 비밀 스레드를 지정된 채널에 생성합니다."""
        try:
            # 전달된 creator_id가 없으면 첫 번째 참가자를 모집자로 사용
            if creator_id is None:
                creator_id = int(self.participants[0]) if self.participants else None
            
            # 이 작업을 시작한 사용자 ID 기록 (디버깅용)
            actual_initiator = initiator_id or interaction.user.id
            
            logger.debug(f"스레드 생성 시작 - 모집자 ID: {creator_id}, 액션 수행자 ID: {actual_initiator}")
            
            # 모집자만 스레드 생성 가능하도록 체크
            # if interaction.user.id != creator_id:
            #     if not interaction.response.is_done():
            #         await interaction.response.defer(ephemeral=True)
            #     msg = await interaction.followup.send("모집자만 스레드를 생성할 수 있습니다.", ephemeral=True)
            #     await asyncio.sleep(2)
            #     await msg.delete()
            #     return
            
            # 스레드 이름 생성
            thread_name = f"{self.selected_kind} {self.selected_diff}"
            logger.debug(f"스레드 이름 생성: {thread_name}")
            
            # 스레드를 생성할 채널 찾기 (설정에서 불러오기)
            guild = interaction.guild
            guild_id = str(guild.id)
            
            # DB에서 스레드 채널 ID 가져오기 (settings 컬렉션에 thread_channel_id로 저장되어 있다고 가정)
            settings = await self.db["settings"].find_one({"guild_id": guild_id})
            thread_channel_id = settings.get("thread_channel_id") if settings else None
            
            thread_channel = None
            if thread_channel_id:
                thread_channel = guild.get_channel(int(thread_channel_id))
            
            # 지정된 채널이 없으면 현재 채널 사용
            if not thread_channel:
                thread_channel = interaction.channel
                logger.warning(f"지정된 스레드 채널이 없어 현재 채널을 사용합니다: {thread_channel.id}")
            
            try:
                # 비밀 스레드 생성
                thread = await thread_channel.create_thread(
                    name=thread_name,
                    type=discord.ChannelType.private_thread,  # 비밀 스레드로 변경
                    auto_archive_duration=1440  # 기본값 1일로 변경
                )
                logger.debug(f"비밀 스레드 생성 성공 - 스레드 ID: {thread.id}")
                
                # 모집자를 제외한 다른 참가자들 (초대될 사람들)
                other_participants = [p for p in self.participants if int(p) != creator_id]
                logger.debug(f"초대할 참가자 수: {len(other_participants)}")
                
                # 참가자를 직접 추가하지 않고 초대 메시지만 전송
                # if other_participants:
                #     # 초대 메시지에 모집자만 멘션
                #     mentions = " ".join([f"<@{p}>" for p in other_participants])
                #     await thread.send(
                #         f"{mentions}\n"
                #         f"**{self.selected_kind} {self.selected_diff}** 파티 스레드에 초대되었습니다.\n"
                #         f"이 메시지를 확인하면 자동으로 스레드에 참여됩니다."
                #     )
                
            except discord.Forbidden:
                logger.error("스레드 생성 실패 - 권한 부족")
                if not interaction.response.is_done():
                    await interaction.response.defer(ephemeral=True)
                msg = await interaction.followup.send("스레드 생성 권한이 없습니다.", ephemeral=True)
                await asyncio.sleep(2)
                await msg.delete()
                return
            except discord.HTTPException as e:
                logger.error(f"스레드 생성 실패 - HTTP 오류: {e}")
                if not interaction.response.is_done():
                    await interaction.response.defer(ephemeral=True)
                msg = await interaction.followup.send("스레드 생성 중 오류가 발생했습니다.", ephemeral=True)
                await asyncio.sleep(2)
                await msg.delete()
                return
            
            # 스레드 ID 저장 (음성 채널 연동을 위해 thread_id를 확실히 저장)
            now = datetime.datetime.now().isoformat()
            try:
                await self.db["recruitments"].update_one(
                    {"_id": ObjectId(self.recruitment_id)},
                    {
                        "$set": {
                            "thread_id": str(thread.id),
                            "thread_channel_id": str(thread_channel.id),
                            "thread_status": "pending",
                            "updated_at": now
                        }
                    }
                )
                logger.debug(f"스레드 정보 DB 저장 성공 - 스레드 ID: {thread.id}")
            except Exception as e:
                logger.error(f"스레드 정보 DB 저장 실패: {e}")
                # DB 저장 실패해도 스레드 생성은 계속 진행
            
            # ================ 비밀 음성 채널 생성 로직 추가 ================
            voice_channel = None
            try:
                logger.debug("비밀 임시 음성 채널 생성 시작")
                
                # 음성 채널을 생성할 카테고리 찾기 - 스레드의 부모 채널과 동일한 카테고리 사용
                category = thread.parent.category
                if not category:
                    logger.warning("스레드 부모 채널의 카테고리를 찾을 수 없습니다. 기본 카테고리를 사용합니다.")
                    # 기본 카테고리가 없으면 채널이 속한 첫 번째 카테고리 사용
                    for category_obj in interaction.guild.categories:
                        category = category_obj
                        break
                
                logger.debug(f"음성 채널 생성 카테고리: {category.name if category else '없음'}")
                
                # 비밀 음성 채널 생성
                voice_channel = await interaction.guild.create_voice_channel(
                    name=f"🔊 {thread_name}",
                    category=category,
                    user_limit=len(self.participants) or 4,  # 참가자 수로 제한, 기본값 4
                    reason="파티 음성 채팅"
                )
                
                logger.debug(f"음성 채널 생성 성공: {voice_channel.name} (ID: {voice_channel.id})")
                
                # 채널 권한 설정 - 기본적으로 모든 사용자에게 비공개
                await voice_channel.set_permissions(
                    interaction.guild.default_role,
                    view_channel=False,  # 채널을 볼 수 없음
                    connect=False        # 연결할 수 없음
                )
                
                logger.debug("음성 채널 기본 권한 설정 완료")
                
                # 봇에게 권한 부여
                await voice_channel.set_permissions(
                    interaction.guild.me,
                    view_channel=True,
                    connect=True,
                    speak=True,
                    move_members=True,
                    manage_channels=True  # 채널 관리 권한 추가
                )
                
                logger.debug("봇 권한 설정 완료")
                
                # 참가자들에게 채널 접근 권한 부여
                participants_with_access = 0
                for participant_id in self.participants:
                    try:
                        member = interaction.guild.get_member(int(participant_id))
                        if member:
                            await voice_channel.set_permissions(
                                member,
                                view_channel=True,  # 채널을 볼 수 있음
                                connect=True,       # 연결할 수 있음
                                speak=True          # 말할 수 있음
                            )
                            participants_with_access += 1
                            logger.debug(f"참가자 권한 설정 완료: {member.display_name}")
                        else:
                            logger.warning(f"참가자를 찾을 수 없음: {participant_id}")
                            # 실패한 경우 API에서 직접 멤버 조회 시도
                            try:
                                fetched_member = await interaction.guild.fetch_member(int(participant_id))
                                if fetched_member:
                                    await voice_channel.set_permissions(
                                        fetched_member,
                                        view_channel=True,
                                        connect=True,
                                        speak=True
                                    )
                                    participants_with_access += 1
                                    logger.debug(f"참가자 권한 설정 완료 (fetch): {fetched_member.display_name}")
                            except Exception as fetch_error:
                                logger.error(f"참가자 fetch 중 오류: {fetch_error}")
                    except Exception as e:
                        logger.warning(f"음성 채널 권한 설정 중 오류 (ID: {participant_id}): {e}")
                
                logger.info(f"비밀 음성 채널 생성 성공: {voice_channel.name} (ID: {voice_channel.id})")
                logger.info(f"{participants_with_access}/{len(self.participants)} 참가자에게 권한 부여 완료")
                
                # DB에 음성 채널 정보 저장
                await self.db["recruitments"].update_one(
                    {"_id": ObjectId(self.recruitment_id)},
                    {"$set": {
                        "voice_channel_id": str(voice_channel.id),
                        "voice_channel_name": voice_channel.name,
                        "updated_at": now
                    }}
                )
                logger.debug(f"음성 채널 정보 DB 저장 성공 - 채널 ID: {voice_channel.id}")
                
                # # 음성 채널 참여 버튼 생성용 뷰 가져오기
                # from views.recruitment_card_views import VoiceChannelView
                
                # # 음성 채널 참여 버튼 추가
                # voice_view = VoiceChannelView(voice_channel.id)
                # voice_msg = await thread.send("🔊 **파티 음성 채널에 참여하세요!**", view=voice_view)
                # logger.debug(f"음성 채널 참여 버튼 생성 완료: 메시지 ID={voice_msg.id}")
                
            except Exception as e:
                logger.error(f"비밀 음성 채널 생성 중 오류: {e}")
                logger.error(traceback.format_exc())
                voice_channel = None
            # ================ 비밀 음성 채널 생성 로직 끝 ================
            
            # 스레드 설정용 뷰 생성
            from views.recruitment_card_views import ThreadArchiveView
            archive_view = ThreadArchiveView(
                self.recruitment_id, 
                self.participants, 
                self.selected_type, 
                self.selected_kind, 
                self.selected_diff, 
                self.recruitment_content,
                self.db
            )
            
            try:
                # 스레드에 보관 기간 설정 메시지 전송
                archive_msg = await thread.send(f"<@{creator_id}> 스레드 보관 기간을 설정해주세요.", view=archive_view)
                logger.debug(f"스레드 보관 기간 설정 메시지 전송 완료: {archive_msg.id}")
                
                # 모집에 참여한 사람들 멘션 - 개별 초대 메시지로 변경하므로 제거
                # 대신 모집 정보만 전송
                info_message = "\n\n **🎮 스레드 보관 기간**을 선택하면 참여자들이 초대됩니다."
                # if voice_channel:
                #     info_message += f"\n\n🔊 **음성 채널**도 생성되었으니 위 버튼을 눌러 참여해보세요!"
                
                # 정보 메시지 전송
                info_msg = await thread.send(info_message)
                logger.debug(f"파티 정보 메시지 전송 완료: {info_msg.id}")
                
                logger.debug("스레드 초기 메시지 전송 성공")
                
                # 모집자에게만 비밀 메시지로 알림 (ephemeral)
                if not interaction.response.is_done():
                    await interaction.response.defer(ephemeral=True)
                    
                # 음성 채널 정보 포함 알림
                notification_text = f"비밀 스레드가 생성되었습니다: {thread.jump_url}"
                if voice_channel:
                    notification_text += f"\n음성 채널도 함께 생성되었습니다: {voice_channel.mention}"
                
                await interaction.followup.send(notification_text, ephemeral=True)
                
            except Exception as e:
                logger.error(f"스레드 초기 메시지 전송 실패: {e}")
                logger.error(traceback.format_exc())
                # 메시지 전송 실패해도 스레드 생성은 완료된 것으로 간주
                if not interaction.response.is_done():
                    await interaction.response.defer(ephemeral=True)
                await interaction.followup.send("스레드가 생성되었지만 메시지 전송에 실패했습니다.", ephemeral=True)
            
        except Exception as e:
            logger.error(f"스레드 생성 중 오류 발생: {e}")
            logger.error(traceback.format_exc())
            if not interaction.response.is_done():
                await interaction.response.defer(ephemeral=True)
            msg = await interaction.followup.send("스레드 생성 중 오류가 발생했습니다.", ephemeral=True)
            await asyncio.sleep(2)
            await msg.delete()

    async def btn_join_callback(self, interaction: discord.Interaction):
        """참가하기 버튼 클릭 시 호출되는 콜백"""
        try:
            # 오류 발생을 방지하기 위해 응답 먼저 처리
            await interaction.response.defer(ephemeral=True)
            
            # 모집 정보 가져오기
            recruitment = await self.db["recruitments"].find_one({"_id": ObjectId(self.recruitment_id)})
            if not recruitment:
                logger.error(f"모집 정보를 찾을 수 없음: {self.recruitment_id}")
                msg = await interaction.followup.send("모집 정보를 찾을 수 없습니다.", ephemeral=True)
                await asyncio.sleep(2)
                await msg.delete()
                return
            
            # 모집 상태 확인 (이미 완료된 모집인지)
            if recruitment.get("status") == "complete":
                msg = await interaction.followup.send("이미 완료된 모집입니다.", ephemeral=True)
                await asyncio.sleep(2)
                await msg.delete()
                return
            
            # 최신 참가자 목록 가져오기 (동시성 문제 방지)
            up_to_date_participants = recruitment.get("participants", [])
            # 문자열 ID를 정수로 변환
            self.participants = [int(p) if isinstance(p, str) and p.isdigit() else p for p in up_to_date_participants]
            
            # 사용자 ID
            user_id = int(interaction.user.id)
            
            # 슈퍼유저 체크
            is_super = self.is_super_user(interaction.user)
            
            # 이미 참가한 경우 (슈퍼유저는 중복 참가 가능)
            if not is_super and user_id in self.participants:
                msg = await interaction.followup.send("이미 참가 신청하셨습니다.", ephemeral=True)
                await asyncio.sleep(2)
                await msg.delete()
                return
            
            # 최대 인원 초과 확인
            current_participants = len(self.participants)
            if current_participants >= self.max_participants:
                msg = await interaction.followup.send(f"모집 인원이 마감되었습니다. (최대 {self.max_participants}명)", ephemeral=True)
                await asyncio.sleep(2)
                await msg.delete()
                return
            
            # 참가자 추가 (슈퍼유저는 중복 추가 가능)
            if is_super or user_id not in self.participants:
                # 참가자 목록 업데이트
                self.participants.append(user_id)
                
                # DB 업데이트
                await self.db["recruitments"].update_one(
                    {"_id": ObjectId(self.recruitment_id)},
                    {
                        "$set": {
                            "participants": [str(p) for p in self.participants],
                            "updated_at": datetime.datetime.now().isoformat()
                        }
                    }
                )
                
                # 뷰 상태 업데이트
                await self.db["view_states"].update_one(
                    {"message_id": str(interaction.message.id)},
                    {
                        "$set": {
                            "participants": [str(p) for p in self.participants],
                            "updated_at": datetime.datetime.now().isoformat()
                        }
                    },
                    upsert=True
                )
                
                # 임베드 업데이트
                embed = self.get_embed()
                await interaction.message.edit(embed=embed, view=self)
                
                msg = await interaction.followup.send("참가 신청이 완료되었습니다.", ephemeral=True)
                await asyncio.sleep(2)
                await msg.delete()
                
                # 인원이 다 찼는지 확인
                if len(self.participants) >= self.max_participants:
                    # 모집 상태를 "complete"로 변경하기 전에 동시성 검사
                    # 최신 상태 다시 확인
                    latest_recruitment = await self.db["recruitments"].find_one({"_id": ObjectId(self.recruitment_id)})
                    if latest_recruitment.get("status") != "complete":
                        # 모집 상태를 "complete"로 변경
                        self.status = "complete"
                        
                        # DB 업데이트
                        await self.db["recruitments"].update_one(
                            {"_id": ObjectId(self.recruitment_id)},
                            {
                                "$set": {
                                    "status": "complete",
                                    "updated_at": datetime.datetime.now().isoformat()
                                }
                            }
                        )
                        
                        # 뷰 상태 업데이트
                        await self.db["view_states"].update_one(
                            {"message_id": str(interaction.message.id)},
                            {
                                "$set": {
                                    "status": "complete",
                                    "updated_at": datetime.datetime.now().isoformat()
                                }
                            }
                        )
                        
                        # 임베드 업데이트
                        embed = self.get_embed()
                        await interaction.message.edit(embed=embed, view=self)
                        
                        # 비밀 스레드 생성 - interaction 대신 필요한 정보들만 전달
                        # 첫 번째 참가자(모집자) ID 가져오기
                        creator_id = int(self.participants[0]) if self.participants else None
                        
                        # 스레드 생성에 필요한 정보만 전달
                        await self.create_private_thread(
                            interaction=interaction,
                            creator_id=creator_id,
                            initiator_id=interaction.user.id  # 실제 이 액션을 시작한 사용자
                        )
                    else:
                        # 이미 완료 상태인 경우
                        logger.info(f"모집 ID {self.recruitment_id}는 이미 완료 상태입니다.")
            else:
                msg = await interaction.followup.send("이미 참가 신청하셨습니다.", ephemeral=True)
                await asyncio.sleep(2)
                await msg.delete()
            
        except Exception as e:
            logger.error(f"참가 신청 중 오류 발생: {e}")
            import traceback
            logger.error(f"상세 오류: {traceback.format_exc()}")
            if not interaction.response.is_done():
                await interaction.response.defer(ephemeral=True)
            msg = await interaction.followup.send("참가 신청 중 오류가 발생했습니다.", ephemeral=True)
            await asyncio.sleep(2)
            await msg.delete()

    async def btn_cancel_callback(self, interaction: discord.Interaction):
        """신청 취소 버튼 클릭 시 호출되는 콜백"""
        try:
            # 모집 정보 가져오기
            recruitment = await self.db["recruitments"].find_one({"_id": ObjectId(self.recruitment_id)})
            if not recruitment:
                logger.error(f"모집 정보를 찾을 수 없음: {self.recruitment_id}")
                await interaction.response.defer(ephemeral=True)
                msg = await interaction.followup.send("모집 정보를 찾을 수 없습니다.", ephemeral=True)
                await asyncio.sleep(2)
                await msg.delete()
                return
            
            # 사용자 ID
            user_id = int(interaction.user.id)
            
            # 참가 신청한 사용자인지 확인
            if user_id not in self.participants:
                await interaction.response.defer(ephemeral=True)
                msg = await interaction.followup.send("참가 신청한 내역이 없습니다.", ephemeral=True)
                await asyncio.sleep(2)
                await msg.delete()
                return
            
            # 모집 생성자(첫 번째 참가자)는 참가 취소 불가능
            if self.participants and len(self.participants) > 0:
                first_participant_id = None
                try:
                    first_participant_id = int(self.participants[0]) if isinstance(self.participants[0], str) else self.participants[0]
                    if user_id == first_participant_id:
                        await interaction.response.defer(ephemeral=True)
                        msg = await interaction.followup.send("모집 생성자는 참가를 취소할 수 없습니다.", ephemeral=True)
                        await asyncio.sleep(2)
                        await msg.delete()
                        return
                except (ValueError, TypeError):
                    logger.warning(f"첫 번째 참가자 ID를 정수로 변환할 수 없음: {self.participants[0]}")
            
            # 참가자 제거
            self.participants.remove(user_id)
            
            # DB 업데이트
            await self.db["recruitments"].update_one(
                {"_id": ObjectId(self.recruitment_id)},
                {
                    "$set": {
                        "participants": [str(p) for p in self.participants],
                        "updated_at": datetime.datetime.now().isoformat()
                    }
                }
            )
            
            # 뷰 상태 업데이트
            await self.db["view_states"].update_one(
                {"message_id": str(interaction.message.id)},
                {
                    "$set": {
                        "participants": [str(p) for p in self.participants],
                        "updated_at": datetime.datetime.now().isoformat()
                    }
                }
            )
            
            # 임베드 업데이트
            embed = self.get_embed()
            await interaction.message.edit(embed=embed, view=self)
            
            await interaction.response.defer(ephemeral=True)
            msg = await interaction.followup.send("참가 신청이 취소되었습니다.", ephemeral=True)
            await asyncio.sleep(2)
            await msg.delete()
            
        except Exception as e:
            logger.error(f"참가 취소 중 오류 발생: {e}")
            import traceback
            logger.error(f"상세 오류: {traceback.format_exc()}")
            if not interaction.response.is_done():
                await interaction.response.defer(ephemeral=True)
                msg = await interaction.followup.send("참가 취소 중 오류가 발생했습니다.", ephemeral=True)
                await asyncio.sleep(2)
                await msg.delete()

    # 슈퍼유저 체크 함수
    def is_super_user(self, user):
        """사용자가 슈퍼유저인지 확인"""
        return str(user.id) == SUPER_USER_ID

    def get_thread_embed(self):
        """스레드용 임베드를 생성합니다."""
        embed = discord.Embed(
            title=f"파티 모집 정보 - {self.selected_type} {self.selected_kind} {self.selected_diff}",
            description="모집이 완료된 파티 정보입니다.",
            color=discord.Color.green()
        )
        
        # 던전 정보 추가
        embed.add_field(name="던전 유형", value=f"`{self.selected_type}`", inline=True)
        embed.add_field(name="던전 종류", value=f"`{self.selected_kind}`", inline=True)
        embed.add_field(name="난이도", value=f"`{self.selected_diff}`", inline=True)
        
        # 구분선
        embed.add_field(name="\u200b", value="───────────────", inline=False)
        
        # 모집 내용
        if self.recruitment_content:
            embed.add_field(name="모집 내용", value=self.recruitment_content, inline=False)
        
        # 구분선
        embed.add_field(name="\u200b", value="───────────────", inline=False)
        
        # 참가자 목록
        participants_text = f"총 {len(self.participants)}/{len(self.participants)}명 참가\n"
        for i, p_id in enumerate(self.participants):
            participants_text += f"{i+1}. <@{p_id}>\n"
        
        embed.add_field(name="참가자 명단", value=participants_text, inline=False)
        
        # 기타 정보
        if self.creator_id:
            embed.add_field(name="모집자", value=f"<@{self.creator_id}>", inline=True)
        
        if self.recruitment_id:
            embed.set_footer(text=f"모집 ID: {self.recruitment_id}")
        
        return embed

# 스레드 보관 기간 선택을 위한 뷰 클래스
class ThreadArchiveView(discord.ui.View):
    def __init__(self, recruitment_id, participants, dungeon_type, dungeon_kind, dungeon_diff, recruitment_content, db):
        super().__init__(timeout=None)
        self.recruitment_id = recruitment_id
        self.participants = participants
        self.dungeon_type = dungeon_type
        self.dungeon_kind = dungeon_kind
        self.dungeon_diff = dungeon_diff
        self.recruitment_content = recruitment_content
        self.db = db
        self.thread_archive_duration = None
        self.thread_status = "pending"  # pending, active, archived
        
        # 보관 기간 선택 버튼 추가
        self.add_item(ThreadArchiveButton(60, "1시간"))
        self.add_item(ThreadArchiveButton(1440, "1일"))
        self.add_item(ThreadArchiveButton(4320, "3일"))
        self.add_item(ThreadArchiveButton(10080, "7일"))
    
    async def set_archive_duration(self, interaction: discord.Interaction, duration_minutes: int):
        try:
            thread = interaction.channel
            
            # 모집자만 버튼을 누를 수 있도록 체크
            author_id = int(self.participants[0])  # 첫 번째 참가자가 모집자
            if interaction.user.id != author_id:
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
                msg = await interaction.followup.send("스레드 보관 기간이 1시간으로 설정되었습니다.")
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
                {"_id": ObjectId(self.recruitment_id)},
                {
                    "$set": {
                        "thread_archive_duration": duration_minutes,
                        "thread_status": "active",
                        "updated_at": now
                    }
                }
            )
            
            # 모집 정보 임베드 직접 생성 (RecruitmentCard 사용하지 않음)
            embed = discord.Embed(
                title=f"파티 모집 정보 - {self.dungeon_type} {self.dungeon_kind} {self.dungeon_diff}",
                description="모집이 완료된 파티 정보입니다.",
                color=discord.Color.green()
            )
            
            # 던전 정보 추가
            embed.add_field(name="던전 유형", value=f"`{self.dungeon_type}`", inline=True)
            embed.add_field(name="던전 종류", value=f"`{self.dungeon_kind}`", inline=True)
            embed.add_field(name="난이도", value=f"`{self.dungeon_diff}`", inline=True)
            
            # 구분선
            embed.add_field(name="\u200b", value="───────────────", inline=False)
            
            # 모집 내용
            if self.recruitment_content:
                embed.add_field(name="모집 내용", value=self.recruitment_content, inline=False)
            
            # 구분선
            embed.add_field(name="\u200b", value="───────────────", inline=False)
            
            # 참가자 목록
            participants_text = f"총 {len(self.participants)}/{len(self.participants)}명 참가\n"
            for i, p_id in enumerate(self.participants):
                participants_text += f"{i+1}. <@{p_id}>\n"
            
            embed.add_field(name="참가자 명단", value=participants_text, inline=False)
            
            # 기타 정보
            if len(self.participants) > 0:
                embed.add_field(name="모집자", value=f"<@{self.participants[0]}>", inline=True)
            
            # 보관 기간 정보 푸터에 추가
            embed.set_footer(text=f"모집 ID: {self.recruitment_id} | 스레드 보관 기간: {duration_minutes // 1440}일")
            
            # 모집 완료 임베드 전송
            await thread.send(embed=embed)
            
            # 참가자들 멘션 (모집자 제외)
            if len(self.participants) > 1:
                mentions = " ".join([f"<@{p_id}>" for p_id in self.participants[1:]])
                await thread.send(mentions)
                await thread.send("파티원분들은 스레드에 참가해주세요!")
            
        except Exception as e:
            logger.error(f"스레드 보관 기간 설정 중 오류 발생: {e}")
            import traceback
            logger.error(f"상세 오류: {traceback.format_exc()}")
            if not interaction.response.is_done():
                await interaction.response.defer(ephemeral=True)
                msg = await interaction.followup.send(f"스레드 보관 기간 설정 중 오류가 발생했습니다: {e}", ephemeral=True)
                await asyncio.sleep(2)
                await msg.delete()

class ThreadArchiveButton(discord.ui.Button):
    def __init__(self, duration_minutes: int, label: str):
        super().__init__(
            label=label,
            style=discord.ButtonStyle.primary,
            custom_id=f"thread_archive_{duration_minutes}"
        )
        self.duration_minutes = duration_minutes
    
    async def callback(self, interaction: discord.Interaction):
        await self.view.set_archive_duration(interaction, self.duration_minutes)
