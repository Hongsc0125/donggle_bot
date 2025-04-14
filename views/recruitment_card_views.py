import discord
from discord import ui, SelectOption, Interaction, TextStyle
import asyncio
import datetime
from bson.objectid import ObjectId
import logging

# 로깅 설정
logger = logging.getLogger('donggle_bot.recruitment_card')


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
            
            
        except Exception as e:
            #logger.info(f"[ERROR] 모집 내용 저장 중 오류 발생: {e}")
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
                # #logger.info(f"[ERROR] 모집 ID {self.recruitment_id}에 해당하는 모집 정보를 찾을 수 없습니다.")
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
                    logger.warning(f"던전 정보 조회 중 오류 발생: {e}")
            
            # 스레드 이름 재설정 시도
            if valid_kind and valid_diff:
                new_thread_name = f"{valid_kind} {valid_diff}"
                try:
                    await thread.edit(name=new_thread_name)
                    #logger.info(f"[INFO] 스레드 이름을 '{new_thread_name}'으로 변경했습니다.")
                except Exception as e:
                    logger.warning(f"스레드 이름 변경 중 오류 발생: {e}")
            elif valid_kind:
                try:
                    await thread.edit(name=valid_kind)
                    #logger.info(f"[INFO] 스레드 이름을 '{valid_kind}'으로 변경했습니다.")
                except Exception as e:
                    logger.warning(f"스레드 이름 변경 중 오류 발생: {e}")
            
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
            #logger.info(f"스레드 생성 중 오류 발생: {e}")
            import traceback
            #logger.info(f"상세 오류: {traceback.format_exc()}")
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
                #logger.info(f"[ERROR] 모집 ID {self.recruitment_id}에 해당하는 모집 정보를 찾을 수 없습니다.")
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
                # 스레드를 보관하지 않고 삭제 예약 시간 저장
                delete_after = datetime.datetime.now() + datetime.timedelta(minutes=duration_minutes)
                
                # 이름 변경만 수행하고 보관은 하지 않음
                await thread.edit(name=thread_name)
                #logger.info(f"[INFO] 스레드 이름을 '{thread_name}'으로 변경했습니다.")
                
                # DB에 삭제 예정 시간 저장
                await self.db["recruitments"].update_one(
                    {"_id": ObjectId(self.recruitment_id)},
                    {"$set": {
                        "thread_delete_at": delete_after.isoformat(),
                        "thread_archive_duration": duration_minutes,
                        "thread_status": "active",
                        "thread_name": thread_name,
                        "updated_at": now
                    }}
                )
                
                # 스레드 삭제 예약 (비동기 작업)
                self.schedule_thread_deletion(thread, self.recruitment_id, duration_minutes, interaction.guild.id)
                
            except Exception as e:
                #logger.info(f"[WARNING] 스레드 이름 변경 중 오류 발생: {e}")
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
                        logger.info(f"[WARNING] 참가자 ID 변환 실패: {p_id}")
                
                participants_text = f"총 {len(participants)}/{len(participants)}명 참가\n"
                for i, p_id in enumerate(participants):
                    participants_text += f"{i+1}. <@{p_id}>\n"
            except Exception as e:
                logger.info(f"[WARNING] 참가자 목록 처리 중 오류 발생: {e}")
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
                invite_message = "\n\n**🎮 파티원 초대 알림**\n"
                for p_id in participants:
                    invite_message += f"<@{p_id}> "
                invite_message += "\n\n파티가 결성되었습니다! 활발한 소통 부탁드립니다. 😊"
                
                # 참가자 초대 메시지 전송
                await thread.send(invite_message)
            else:
                await thread.send("**🎮 파티가 결성되었습니다!** 활발한 소통 부탁드립니다. 😊")
            
            # 음성 채널 ID 가져오기 - 비동기 호출을 올바르게 처리
            recruitment_info = await self.db["recruitments"].find_one(
                {"_id": ObjectId(self.recruitment_id)},
                {"voice_channel_id": 1}
            )
            voice_channel_id = recruitment_info.get("voice_channel_id") if recruitment_info else None
            
            # 음성 채널 ID가 있는 경우에만 버튼 추가
            if voice_channel_id:
                # 음성 채널 참여 버튼 생성용 뷰 가져오기
                from views.recruitment_card_views import VoiceChannelView
                
                # 음성 채널 참여 버튼 추가
                voice_view = VoiceChannelView(voice_channel_id)
                voice_msg = await thread.send("🔊 **파티 음성 채널에 참여하세요!**", view=voice_view)
                #logger.info(f"[DEBUG] 음성 채널 참여 버튼 생성 완료: 메시지 ID={voice_msg.id}")
        
        except Exception as e:
            #logger.info(f"[ERROR] 스레드 보관 기간 설정 중 오류 발생: {e}")
            import traceback
            #logger.info(f"[ERROR] 상세 오류: {traceback.format_exc()}")
            await interaction.followup.send("스레드 보관 기간 설정 중 오류가 발생했습니다.", ephemeral=True)

    def schedule_thread_deletion(self, thread, recruitment_id, duration_minutes, guild_id):
        """스레드를 일정 시간 후에 삭제하도록 예약합니다."""
        async def delete_thread_later():
            try:
                # 지정된 시간(분) 동안 대기
                await asyncio.sleep(duration_minutes * 60)
                
                # 스레드가 여전히 존재하는지 확인
                try:
                    # 스레드 정보 다시 가져오기
                    guild = self.bot.get_guild(guild_id)
                    if not guild:
                        #logger.info(f"[ERROR] 스레드 삭제 실패: 서버를 찾을 수 없음 (ID: {guild_id})")
                        return
                    
                    # 채널 ID로 스레드 찾기
                    fetched_thread = guild.get_thread(thread.id)
                    if fetched_thread:
                        # 연결된 음성 채널 찾기 및 삭제
                        try:
                            recruitment = await self.db["recruitments"].find_one({"_id": ObjectId(recruitment_id)})
                            if recruitment and "voice_channel_id" in recruitment:
                                voice_channel_id = recruitment["voice_channel_id"]
                                voice_channel = guild.get_channel(int(voice_channel_id))
                                if voice_channel:
                                    await voice_channel.delete(reason="스레드 자동 삭제에 의한 음성 채널 삭제")
                                    #logger.info(f"[INFO] 음성 채널 {voice_channel.id} 삭제 완료")
                        except Exception as voice_error:
                            logger.info(f"[ERROR] 음성 채널 삭제 중 오류: {voice_error}")
                        
                        # 스레드 삭제
                        await fetched_thread.delete()
                        # logger.info(f"[INFO] 스레드 {thread.id} 자동 삭제 완료")
                        
                        # 모집 정보 상태 업데이트
                        await self.db["recruitments"].update_one(
                            {"_id": ObjectId(recruitment_id)},
                            {"$set": {
                                "thread_status": "deleted",
                                "updated_at": datetime.datetime.now().isoformat()
                            }}
                        )
                    else:
                        logger.info(f"[INFO] 스레드 {thread.id}가 이미 삭제되었습니다.")
                except discord.NotFound:
                    logger.info(f"[INFO] 스레드 {thread.id}가 이미 삭제되었습니다.")
                except Exception as thread_error:
                    logger.info(f"[ERROR] 스레드 삭제 확인 중 오류: {thread_error}")
                    logger.info(traceback.format_exc())
            except Exception as e:
                logger.info(f"[ERROR] 스레드 자동 삭제 작업 중 오류 발생: {e}")
                logger.info(traceback.format_exc())
        
        # 비동기 작업 시작
        asyncio.create_task(delete_thread_later())
        #logger.info(f"[INFO] 스레드 {thread.id}가 {duration_minutes}분 후 삭제되도록 예약되었습니다.")

    async def force_cleanup_channel(self, guild_id, channel_id):
        """특정 채널의 완료된 모집 메시지를 강제로 삭제합니다."""
        try:
            # 서버 객체 가져오기
            guild = self.bot.get_guild(int(guild_id))
            if not guild:
                #logger.warning(f"서버를 찾을 수 없음: {guild_id}")
                return
            
            # 채널 객체 가져오기
            channel = guild.get_channel(int(channel_id))
            if not channel:
                #logger.warning(f"서버 {guild_id}의 공고 채널을 찾을 수 없음: {channel_id}")
                return
            
            # 서버별 모집 정보 조회 (완료/취소 상태만)
            completed_recruitments = await self.db.recruitments.find({
                "guild_id": guild_id, 
                "status": {"$in": ["complete", "cancelled"]}
            }).to_list(None)
            
            if not completed_recruitments:
                #logger.info(f"서버 {guild_id}에 완료/취소된 모집이 없습니다.")
                return
            
            #logger.info(f"서버 {guild_id}에서 {len(completed_recruitments)}개의 완료/취소된 모집을 찾았습니다.")
            
            # 1. 먼저 메시지 ID가 있는 완료 모집 처리 (더 효율적)
            message_id_map = {}
            completed_recruitment_ids = set()
            
            for recruitment in completed_recruitments:
                recruitment_id = str(recruitment.get('_id'))
                completed_recruitment_ids.add(recruitment_id)
                
                if "announcement_message_id" in recruitment and "announcement_channel_id" in recruitment:
                    # 이 채널에 있는 메시지만 처리
                    if recruitment["announcement_channel_id"] == str(channel_id):
                        message_id_map[recruitment["announcement_message_id"]] = recruitment_id
            
            # 메시지 ID로 삭제 시도
            deleted_count = 0
            for message_id, recruitment_id in message_id_map.items():
                try:
                    #logger.info(f"메시지 ID로 삭제 시도: {message_id}, 모집 ID: {recruitment_id}")
                    message = await channel.fetch_message(int(message_id))
                    await message.delete()
                    #logger.info(f"서버 {guild_id}의 완료된 모집 ID {recruitment_id} 메시지가 성공적으로 삭제됨 (메시지 ID 매칭)")
                    deleted_count += 1
                except discord.NotFound:
                    logger.info(f"서버 {guild_id}의 모집 ID {recruitment_id}의 메시지를 찾을 수 없음: {message_id}")
                except Exception as e:
                    logger.error(f"메시지 삭제 중 오류: {e}")
            
            # 2. 메시지 ID로 삭제되지 않은 모집은 내용 검사로 시도
            messages_to_check = []
            async for message in channel.history(limit=100):
                messages_to_check.append(message)
            
            #logger.info(f"서버 {guild_id}의 공고 채널에서 {len(messages_to_check)}개의 메시지를 확인합니다.")
            
            for message in messages_to_check:
                try:
                    # 이미 삭제된 메시지 ID는 건너뛰기
                    if str(message.id) in message_id_map:
                        continue
                    
                    # 메시지에 임베드가 없으면 건너뛰기
                    if not message.embeds or len(message.embeds) == 0:
                        continue
                    
                    embed = message.embeds[0]
                    
                    # 임베드에서 모집 ID 찾기
                    recruitment_id = None
                    
                    # 임베드의 푸터에서 모집 ID 찾기
                    if embed.footer and embed.footer.text:
                        footer_text = embed.footer.text
                        
                        if "모집 ID:" in footer_text:
                            # 정규식으로 모집 ID 추출
                            import re
                            # MongoDB ObjectID 형식(24자 16진수)에 맞는 패턴
                            id_match = re.search(r"모집 ID:\s*([a-f0-9]{24})", footer_text)
                            if id_match:
                                recruitment_id = id_match.group(1).strip()
                                #logger.info(f"푸터에서 모집 ID를 추출했습니다: {recruitment_id}")
                    
                    # 임베드의 필드에서 모집 ID 찾기 (이전 방식 호환)
                    if not recruitment_id:
                        for field in embed.fields:
                            if (field.name == "모집 ID"):
                                recruitment_id = field.value.strip()
                                #logger.info(f"필드에서 모집 ID를 추출했습니다: {recruitment_id}")
                                break
                    
                    if recruitment_id and recruitment_id in completed_recruitment_ids:
                        #logger.info(f"서버 {guild_id}의 완료된 모집 ID {recruitment_id} 메시지 삭제 시도 (내용 매칭)")
                        try:
                            await message.delete()
                            deleted_count += 1
                            #logger.info(f"서버 {guild_id}의 완료된 모집 ID {recruitment_id} 메시지가 성공적으로 삭제됨 (내용 매칭)")
                        except Exception as delete_error:
                            logger.error(f"메시지 삭제 중 오류: {delete_error}")
                except Exception as e:
                    logger.error(f"메시지 처리 중 오류 발생: {e}")
                    continue
            
            #logger.info(f"서버 {guild_id}의 강제 채널 정리 완료: {deleted_count}개의 메시지가 삭제되었습니다.")
            
        except Exception as e:
            logger.error(f"강제 채널 정리 중 오류 발생: {e}")
            logger.error(traceback.format_exc())


# 음성 채널 참여 버튼 클래스
class VoiceChannelJoinButton(discord.ui.Button):
    def __init__(self, voice_channel_id):
        super().__init__(
            style=discord.ButtonStyle.success,
            label="임시 음성채팅 참여",
            emoji="🔊",
            custom_id=f"voice_join_{voice_channel_id}"
        )
        self.voice_channel_id = voice_channel_id
    
    async def callback(self, interaction: discord.Interaction):
        try:
            # 음성 채널 찾기
            voice_channel = interaction.guild.get_channel(int(self.voice_channel_id))
            if not voice_channel:
                await interaction.response.send_message("음성 채널을 찾을 수 없습니다.", ephemeral=True)
                return
            
            # member 객체 가져오기 및 None 체크 추가
            member = interaction.guild.get_member(interaction.user.id)
            if not member:
                # 멤버를 찾을 수 없는 경우 (캐시 문제일 수 있음)
                try:
                    # 멤버 페치 시도
                    member = await interaction.guild.fetch_member(interaction.user.id)
                    if not member:
                        await interaction.response.send_message("서버에서 사용자 정보를 찾을 수 없습니다.", ephemeral=True)
                        return
                except discord.NotFound:
                    await interaction.response.send_message("서버에서 사용자를 찾을 수 없습니다.", ephemeral=True)
                    return
                except Exception as e:
                    #logger.info(f"[ERROR] 사용자 정보 조회 중 오류 발생: {e}")
                    await interaction.response.send_message("사용자 정보를 확인하는 중 오류가 발생했습니다.", ephemeral=True)
                    return
            
            # voice 속성이 있는지 확인 (더 안전한 방어 코드 추가)
            if not hasattr(member, 'voice'):
                #logger.info(f"[WARNING] 멤버 객체에 voice 속성이 없습니다. 멤버 ID: {member.id}, 타입: {type(member)}")
                await interaction.response.send_message(
                    f"음성 채널 상태를 확인할 수 없습니다. 직접 {voice_channel.mention} 채널에 접속해주세요.",
                    ephemeral=True
                )
                return
            
            # 사용자가 이미 음성 채널에 있는지 확인 (안전하게 속성 체크)
            in_target_channel = (
                member.voice is not None and 
                member.voice.channel is not None and 
                member.voice.channel.id == voice_channel.id
            )
            
            if in_target_channel:
                await interaction.response.send_message("이미 해당 음성 채널에 접속해 있습니다.", ephemeral=True)
                return
            
            # 사용자가 현재 음성 채널에 있는지 확인
            if member.voice and member.voice.channel:
                try:
                    # 사용자 음성 상태 다시 확인 (이동 직전 다시 체크)
                    if not member.voice or not member.voice.channel:
                        await interaction.response.send_message(
                            f"음성 채널에 연결되어 있지 않습니다. 먼저 디스코드 음성에 접속한 후, {voice_channel.mention} 채널로 이동해주세요.",
                            ephemeral=True
                        )
                        return
                        
                    # 이동 권한 확인
                    permissions = voice_channel.permissions_for(interaction.guild.me)
                    if permissions.move_members:
                        try:
                            await member.move_to(voice_channel)
                            await interaction.response.send_message(f"{voice_channel.name} 음성 채널로 이동했습니다.", ephemeral=True)
                        except discord.errors.HTTPException as http_error:
                            # 음성 채널 연결 끊김 처리
                            if http_error.code == 40032:  # Target user is not connected to voice
                                await interaction.response.send_message(
                                    f"음성 채널 연결이 끊어졌습니다. 다시 접속 후 {voice_channel.mention} 채널로 이동해주세요.",
                                    ephemeral=True
                                )
                            else:
                                raise http_error
                    else:
                        await interaction.response.send_message(
                            f"봇에 사용자를 이동시킬 권한이 없습니다. 직접 {voice_channel.mention} 채널에 접속해주세요.", 
                            ephemeral=True
                        )
                except Exception as e:
                    #logger.info(f"[ERROR] 사용자 음성 채널 이동 중 오류: {e}")
                    await interaction.response.send_message(
                        f"음성 채널로 이동할 수 없습니다. 직접 {voice_channel.mention} 채널에 접속해주세요.", 
                        ephemeral=True
                    )
            else:
                # 사용자가 음성 채널에 없는 경우
                # 직접 참여할 수 있는 임베드 메시지 제공
                embed = discord.Embed(
                    title="음성 채널 참여",
                    description=f"{voice_channel.mention} 채널을 눌러 바로 참여할 수 있습니다. 또는 아래 링크를 클릭하세요.",
                    color=discord.Color.green()
                )
                
                # 채널 링크 형식 생성 (디스코드의 채널 연결 링크)
                channel_link = f"https://discord.com/channels/{interaction.guild.id}/{voice_channel.id}"
                
                # 버튼 뷰 생성
                view = discord.ui.View()
                view.add_item(discord.ui.Button(
                    label="음성 채널 참여하기", 
                    style=discord.ButtonStyle.link, 
                    url=channel_link
                ))
                
                await interaction.response.send_message(
                    embed=embed,
                    view=view,
                    ephemeral=True
                )
                
        except Exception as e:
            #logger.info(f"[ERROR] 음성 채널 참여 중 오류 발생: {e}")
            import traceback
            #logger.info(f"[ERROR] 상세 오류: {traceback.format_exc()}")
            await interaction.response.send_message("음성 채널 참여 중 오류가 발생했습니다.", ephemeral=True)

# 임시 음성 채널 관리 뷰
class VoiceChannelView(discord.ui.View):
    def __init__(self, voice_channel_id):
        super().__init__(timeout=None)
        self.add_item(VoiceChannelJoinButton(voice_channel_id))
