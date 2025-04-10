import discord
from discord import ui, SelectOption, Interaction, TextStyle
import asyncio
import datetime
from bson.objectid import ObjectId


class RecruitmentModal(ui.Modal, title="모집 내용 작성"):
    content = ui.TextInput(
        label="모집 내용",
        style=TextStyle.paragraph,
        placeholder="모집에 대한 상세 내용을 입력해주세요. (최대 500자)",
        max_length=500,
        min_length=1,
        required=True
    )
    
    async def on_submit(self, interaction: Interaction):
        try:
            # 부모 뷰가 없으면 종료
            if not self.parent:
                await interaction.response.send_message("오류가 발생했습니다. 다시 시도해주세요.", ephemeral=True)
                return
                
            # 모집 내용 저장
            self.parent.recruitment_content = self.content.value
            
            # 응답 메시지 전송
            await interaction.response.defer()
            
            # 부모 뷰 업데이트
            await self.parent.update_embed(interaction)
            
            # 임시 메시지 (알림 없음)
            msg = await interaction.followup.send("모집 내용이 저장되었습니다.", ephemeral=True)
            await asyncio.sleep(2)  # 2초 후 메시지 자동 삭제
            await msg.delete()
            
        except Exception as e:
            print(f"[ERROR] 모집 내용 저장 중 오류 발생: {e}")
            await interaction.response.send_message("모집 내용 저장 중 오류가 발생했습니다.", ephemeral=True)


class TypeSelectView(ui.View):
    def __init__(self, parent):
        super().__init__(timeout=None)
        self.parent = parent
        types = sorted({d["type"] for d in self.parent.dungeons})
        options = [SelectOption(label=f"🏰 {t}", value=t) for t in types]
        self.select = ui.Select(placeholder="던전 타입 선택", options=options)
        self.select.callback = self.select_callback
        self.add_item(self.select)

    async def select_callback(self, interaction: Interaction):
        selected = self.select.values[0]
        self.parent.selected_type = selected
        self.parent.selected_kind = None
        self.parent.selected_diff = None
        
        # 먼저 응답을 보냅니다
        await interaction.response.defer()
        await self.parent.update_embed(interaction)

        # 응답 후 메시지 삭제 시도
        try:
            await interaction.message.delete()
        except discord.errors.NotFound:
            pass


class KindSelectView(ui.View):
    def __init__(self, parent):
        super().__init__(timeout=None)
        self.parent = parent
        kinds = sorted({d["name"] for d in self.parent.dungeons if d["type"] == self.parent.selected_type})
        options = [SelectOption(label=f"⚔️ {k}", value=k) for k in kinds]
        self.select = ui.Select(placeholder="던전 종류 선택", options=options)
        self.select.callback = self.select_callback
        self.add_item(self.select)

    async def select_callback(self, interaction: Interaction):
        selected = self.select.values[0]
        self.parent.selected_kind = selected
        self.parent.selected_diff = None
        await self.parent.update_embed(interaction)
        # interaction 메시지 자체를 삭제
        try:
            await interaction.message.delete()
        except discord.errors.NotFound:
            pass


class DiffSelectView(ui.View):
    def __init__(self, parent):
        super().__init__(timeout=None)
        self.parent = parent
        difficulties = sorted({d["difficulty"] for d in self.parent.dungeons
                               if d["type"] == self.parent.selected_type and d["name"] == self.parent.selected_kind})
        options = [SelectOption(label=f"⭐ {diff}", value=diff) for diff in difficulties]
        self.select = ui.Select(placeholder="던전 난이도 선택", options=options)
        self.select.callback = self.select_callback
        self.add_item(self.select)

    async def select_callback(self, interaction: Interaction):
        selected = self.select.values[0]
        self.parent.selected_diff = selected
        await self.parent.update_embed(interaction)
        # interaction 메시지 자체를 삭제
        try:
            await interaction.message.delete()
        except discord.errors.NotFound:
            pass


class RecruitmentCard(discord.ui.View):
    def __init__(self, dungeons, db):
        super().__init__(timeout=None)
        self.dungeons = dungeons
        self.db = db
        self.selected_type = None
        self.selected_kind = None
        self.selected_diff = None
        self.recruitment_content = None
        self.max_participants = 4
        self.participants = []
        self.status = "active"
        self.recruitment_id = None
        self.creator_id = None
        self.is_recreated = False  # 재활성화 여부를 나타내는 속성 추가

    def get_embed(self):
        """현재 상태에 따른 임베드를 생성합니다."""
        embed = discord.Embed(
            title="파티 모집",
            color=discord.Color.blue()
        )
        
        # 상태에 따른 설명 추가
        if self.status == "active":
            embed.description = "파티 모집이 진행 중입니다."
        elif self.status == "complete":
            embed.description = "파티 모집이 완료되었습니다."
        elif self.status == "cancelled":
            embed.description = "파티 모집이 취소되었습니다."
        
        # 선택된 값들 추가
        if self.selected_type:
            embed.add_field(name="던전 유형", value=self.selected_type, inline=True)
        if self.selected_kind:
            embed.add_field(name="던전 종류", value=self.selected_kind, inline=True)
        if self.selected_diff:
            embed.add_field(name="난이도", value=self.selected_diff, inline=True)
        
        # 모집 내용 추가
        if self.recruitment_content:
            embed.add_field(name="모집 내용", value=self.recruitment_content, inline=False)
        
        # 참가자 목록 추가
        participants_text = "참가자 없음"
        if self.participants:
            participants_text = "\n".join([f"<@{p}>" for p in self.participants])
        embed.add_field(name=f"참가자 ({len(self.participants)}/{self.max_participants})", value=participants_text, inline=False)
        
        # 모집 ID 추가
        if self.recruitment_id:
            embed.set_footer(text=f"모집 ID: {self.recruitment_id}")
        
        # UI 요소 초기화
        self.clear_items()
        
        # 재활성화 시에는 선택 메뉴를 추가하지 않음
        if not self.is_recreated:
            # 던전 유형 선택 메뉴
            type_select = discord.ui.Select(
                placeholder="던전 유형을 선택하세요",
                options=[
                    discord.SelectOption(label="일반", value="일반"),
                    discord.SelectOption(label="레이드", value="레이드"),
                    discord.SelectOption(label="기타", value="기타")
                ],
                row=0
            )
            type_select.callback = self.type_select_callback
            self.add_item(type_select)
            
            # 던전 종류 선택 메뉴
            kind_select = discord.ui.Select(
                placeholder="던전 종류를 선택하세요",
                options=[],
                row=1
            )
            kind_select.callback = self.kind_select_callback
            self.add_item(kind_select)
            
            # 난이도 선택 메뉴
            diff_select = discord.ui.Select(
                placeholder="난이도를 선택하세요",
                options=[],
                row=2
            )
            diff_select.callback = self.diff_select_callback
            self.add_item(diff_select)
        
        # 참가하기 버튼
        join_button = discord.ui.Button(
            label="참가하기",
            style=discord.ButtonStyle.green,
            custom_id="join",
            row=3
        )
        join_button.callback = self.join_callback
        self.add_item(join_button)
        
        # 신청 취소 버튼
        cancel_button = discord.ui.Button(
            label="신청 취소",
            style=discord.ButtonStyle.red,
            custom_id="cancel",
            row=3
        )
        cancel_button.callback = self.cancel_callback
        self.add_item(cancel_button)
        
        # 모집 취소 버튼 (생성자만 보임)
        if self.creator_id:
            delete_button = discord.ui.Button(
                label="모집 취소",
                style=discord.ButtonStyle.danger,
                custom_id="delete",
                row=3
            )
            delete_button.callback = self.delete_callback
            self.add_item(delete_button)
        
        return embed

    async def create_private_thread(self, interaction: discord.Interaction):
        """모집 완료 시 스레드를 생성합니다."""
        try:
            # DB에서 모집 정보 가져오기
            recruitment = await self.db["recruitments"].find_one({"_id": ObjectId(self.recruitment_id)})
            if not recruitment:
                print(f"[ERROR] 모집 ID {self.recruitment_id}에 해당하는 모집 정보를 찾을 수 없습니다.")
                if not interaction.response.is_done():
                    await interaction.response.defer(ephemeral=True)
                msg = await interaction.followup.send("모집 정보를 찾을 수 없습니다.", ephemeral=True)
                await asyncio.sleep(2)
                await msg.delete()
                return
                
            # 모집자 ID 가져오기
            creator_id = int(recruitment.get("creator_id", 0))
            if not creator_id:
                creator_id = int(self.participants[0]) if self.participants else None
            
            # 모집자만 스레드 생성 가능 (힝트 제외)
            if interaction.user.id != creator_id and interaction.user.name != "힝트" and interaction.user.display_name != "힝트":
                if not interaction.response.is_done():
                    await interaction.response.defer(ephemeral=True)
                msg = await interaction.followup.send("모집자만 스레드를 생성할 수 있습니다.", ephemeral=True)
                await asyncio.sleep(2)
                await msg.delete()
                return
            
            # DB에서 모집 정보 불러오기
            selected_type = recruitment.get("type", self.selected_type)
            selected_kind = recruitment.get("dungeon", self.selected_kind)
            selected_diff = recruitment.get("difficulty", self.selected_diff)
            
            # 스레드 이름 생성
            thread_name = "파티 모집 완료"  # 기본 이름으로 먼저 생성
            
            # 스레드 생성
            thread = await interaction.channel.create_thread(
                name=thread_name,
                type=discord.ChannelType.public_thread,
                auto_archive_duration=60  # 기본값 1시간
            )
            
            # 스레드 ID 저장
            now = datetime.datetime.now().isoformat()
            await self.db["recruitments"].update_one(
                {"_id": ObjectId(self.recruitment_id)},
                {
                    "$set": {
                        "thread_id": str(thread.id),
                        "thread_status": "pending",
                        "updated_at": now
                    }
                }
            )
            
            # DB에서 참가자 목록 불러오기
            participants = recruitment.get("participants", [])
            if not participants and self.participants:
                participants = [str(p) for p in self.participants]
            
            # 스레드 제목에 사용할 정보 확인
            valid_kind = selected_kind if selected_kind and selected_kind != "None" else None
            valid_diff = selected_diff if selected_diff and selected_diff != "None" else None
            
            # DB에서 추가 정보 조회 시도
            if not valid_kind or not valid_diff:
                try:
                    # 던전 정보 조회 (type과 difficulty 기준으로)
                    dungeon_info = await self.db["dungeons"].find_one({
                        "type": selected_type, 
                        "difficulty": selected_diff
                    })
                    
                    if dungeon_info:
                        if not valid_kind and "name" in dungeon_info:
                            valid_kind = dungeon_info["name"]
                        if not valid_diff and "difficulty" in dungeon_info:
                            valid_diff = dungeon_info["difficulty"]
                except Exception as e:
                    print(f"[WARNING] 던전 정보 조회 중 오류 발생: {e}")
            
            # 스레드 이름 재설정 시도
            if valid_kind and valid_diff:
                new_thread_name = f"{valid_kind} {valid_diff}"
                try:
                    await thread.edit(name=new_thread_name)
                    print(f"[INFO] 스레드 이름을 '{new_thread_name}'으로 변경했습니다.")
                except Exception as e:
                    print(f"[WARNING] 스레드 이름 변경 중 오류 발생: {e}")
            elif valid_kind:
                try:
                    await thread.edit(name=valid_kind)
                    print(f"[INFO] 스레드 이름을 '{valid_kind}'으로 변경했습니다.")
                except Exception as e:
                    print(f"[WARNING] 스레드 이름 변경 중 오류 발생: {e}")
            
            # 스레드 설정용 뷰 생성
            archive_view = ThreadArchiveView(
                self.recruitment_id, 
                [int(p) for p in participants], 
                selected_type if selected_type and selected_type != "None" else "미정", 
                valid_kind if valid_kind else "미정", 
                valid_diff if valid_diff else "미정", 
                recruitment.get("description", self.recruitment_content),
                self.db
            )
            
            # 모집자에게만 보이는 메시지 전송
            if not interaction.response.is_done():
                await interaction.response.defer(ephemeral=True)
            msg = await interaction.followup.send(f"스레드가 생성되었습니다. 보관 기간을 설정해주세요.", ephemeral=True)
            await asyncio.sleep(2)
            await msg.delete()
            
            # 스레드에 보관 기간 설정 메시지 전송
            await thread.send(f"<@{creator_id}> 스레드 보관 기간을 설정해주세요.", view=archive_view)
            
        except Exception as e:
            print(f"스레드 생성 중 오류 발생: {e}")
            import traceback
            print(f"상세 오류: {traceback.format_exc()}")
            if not interaction.response.is_done():
                await interaction.response.defer(ephemeral=True)
            msg = await interaction.followup.send("스레드 생성 중 오류가 발생했습니다.", ephemeral=True)
            await asyncio.sleep(2)
            await msg.delete()


# 스레드 아카이브 기간 선택 버튼
class ThreadArchiveButton(discord.ui.Button):
    def __init__(self, duration_minutes, label):
        super().__init__(
            style=discord.ButtonStyle.primary,
            label=label,
            custom_id=f"archive_{duration_minutes}"
        )
        self.duration_minutes = duration_minutes
    
    async def callback(self, interaction: discord.Interaction):
        # 부모 뷰의 콜백 호출
        view = self.view
        await view.set_archive_duration(interaction, self.duration_minutes)


# 스레드 보관 기간 선택을 위한 뷰 클래스
class ThreadArchiveView(discord.ui.View):
    def __init__(self, recruitment_id, participants, dungeon_type, dungeon_kind, dungeon_diff, recruitment_content, db):
        super().__init__(timeout=None)
        self.recruitment_id = recruitment_id
        self.participants = participants
        
        # None 값 처리
        self.dungeon_type = dungeon_type if dungeon_type and dungeon_type != "None" else "미정"
        self.dungeon_kind = dungeon_kind if dungeon_kind and dungeon_kind != "None" else "미정"
        self.dungeon_diff = dungeon_diff if dungeon_diff and dungeon_diff != "None" else "미정"
        self.recruitment_content = recruitment_content
        
        self.db = db
        self.thread_archive_duration = None
        self.thread_status = "pending"  # pending, active, archived
        
        # 보관 기간 선택 버튼 추가
        self.add_item(ThreadArchiveButton(60, "1시간"))
        self.add_item(ThreadArchiveButton(1440, "1일"))
        self.add_item(ThreadArchiveButton(4320, "3일"))
        self.add_item(ThreadArchiveButton(10080, "7일"))
    
    async def set_archive_duration(self, interaction, duration_minutes):
        """스레드 보관 기간을 설정합니다."""
        try:
            # 응답 지연
            await interaction.response.defer()
            
            # DB에서 최신 모집 정보 가져오기
            recruitment = await self.db["recruitments"].find_one({"_id": ObjectId(self.recruitment_id)})
            if not recruitment:
                print(f"[ERROR] 모집 ID {self.recruitment_id}에 해당하는 모집 정보를 찾을 수 없습니다.")
                await interaction.followup.send("모집 정보를 찾을 수 없습니다.", ephemeral=True)
                return
                
            # DB의 최신 정보로 업데이트
            type_value = recruitment.get("type", "미정")
            kind_value = recruitment.get("dungeon", "미정")
            diff_value = recruitment.get("difficulty", "미정")
            content_value = recruitment.get("description", "")
            participants_list = recruitment.get("participants", [])
            
            # None 값 처리
            display_type = type_value if type_value and type_value != "None" else "미정"
            display_kind = kind_value if kind_value and kind_value != "None" else "미정"
            display_diff = diff_value if diff_value and diff_value != "None" else "미정"
            
            # 스레드 제목 생성
            thread_name = "파티 모집"
            if display_kind != "미정" and display_diff != "미정":
                thread_name = f"{display_kind} {display_diff}"
            elif display_kind != "미정":
                thread_name = display_kind
            
            # 스레드 보관 기간 설정 및 이름 변경
            thread = interaction.channel
            try:
                await thread.edit(name=thread_name, auto_archive_duration=duration_minutes)
                print(f"[INFO] 스레드 이름을 '{thread_name}'으로 변경하고 보관 기간을 {duration_minutes}분으로 설정했습니다.")
            except Exception as e:
                print(f"[WARNING] 스레드 이름 변경 중 오류 발생: {e}")
                # 이름 변경 실패 시 보관 기간만 설정
                await thread.edit(auto_archive_duration=duration_minutes)
            
            # 보관 기간 문자열 설정
            if duration_minutes == 60:
                duration_str = "1시간"
            elif duration_minutes == 1440:
                duration_str = "1일"
            elif duration_minutes == 4320:
                duration_str = "3일"
            elif duration_minutes == 10080:
                duration_str = "7일"
            else:
                duration_str = f"{duration_minutes}분"
            
            # 현재 시간
            now = datetime.datetime.now().isoformat()
            
            # DB에 보관 기간 저장
            await self.db["recruitments"].update_one(
                {"_id": ObjectId(self.recruitment_id)},
                {
                    "$set": {
                        "thread_archive_duration": duration_minutes,
                        "thread_status": "active",
                        "thread_name": thread_name,
                        "updated_at": now
                    }
                }
            )
            
            # 제목 생성
            title = "파티 모집 정보"
            parts = []
            if display_type != "미정":
                parts.append(display_type)
            if display_kind != "미정":
                parts.append(display_kind)
            if display_diff != "미정":
                parts.append(display_diff)
            if parts:
                title += f" - {' '.join(parts)}"
            
            # 임베드 생성
            embed = discord.Embed(
                title=title,
                description="모집이 완료된 파티 정보입니다.",
                color=discord.Color.green()
            )
            
            # 던전 정보 추가
            embed.add_field(name="던전 유형", value=f"`{display_type}`", inline=True)
            embed.add_field(name="던전 종류", value=f"`{display_kind}`", inline=True)
            embed.add_field(name="난이도", value=f"`{display_diff}`", inline=True)
            
            # 구분선
            embed.add_field(name="\u200b", value="───────────────", inline=False)
            
            # 모집 내용
            if content_value and content_value != "None":
                embed.add_field(name="모집 내용", value=content_value, inline=False)
                # 구분선
                embed.add_field(name="\u200b", value="───────────────", inline=False)
            
            # 참가자 목록
            try:
                # 참가자 ID가 문자열인지 확인하고 정수로 변환
                participants = []
                for p_id in participants_list:
                    try:
                        participants.append(int(p_id))
                    except (ValueError, TypeError):
                        print(f"[WARNING] 참가자 ID 변환 실패: {p_id}")
                
                participants_text = f"총 {len(participants)}/{len(participants)}명 참가\n"
                for i, p_id in enumerate(participants):
                    participants_text += f"{i+1}. <@{p_id}>\n"
            except Exception as e:
                print(f"[WARNING] 참가자 목록 처리 중 오류 발생: {e}")
                participants_text = "참가자 정보를 불러올 수 없습니다."
                participants = []
            
            embed.add_field(name="참가자 명단", value=participants_text, inline=False)
            
            # 보관 기간 정보 추가
            embed.add_field(name="보관 기간", value=f"`{duration_str}`", inline=True)
            
            # 모집 ID 추가
            embed.set_footer(text=f"모집 ID: {self.recruitment_id} | 스레드 보관 기간: {duration_str}")
            
            # 버튼 비활성화 및 메시지 업데이트
            for child in self.children:
                child.disabled = True
            
            # 메시지 업데이트
            await interaction.message.edit(content=f"보관 기간이 **{duration_str}**로 설정되었습니다.", embed=embed, view=self)
            
            # 참가자 초대 메시지
            if participants:
                invite_message = "**🎮 파티원 초대 알림**\n"
                for p_id in participants:
                    invite_message += f"<@{p_id}> "
                invite_message += "\n\n파티가 결성되었습니다! 활발한 소통 부탁드립니다. 😊"
                
                # 참가자 초대 메시지 전송
                await thread.send(invite_message)
            else:
                await thread.send("**🎮 파티가 결성되었습니다!** 활발한 소통 부탁드립니다. 😊")
            
        except Exception as e:
            print(f"[ERROR] 스레드 보관 기간 설정 중 오류 발생: {e}")
            import traceback
            print(f"[ERROR] 상세 오류: {traceback.format_exc()}")
            await interaction.followup.send("스레드 보관 기간 설정 중 오류가 발생했습니다.", ephemeral=True)
