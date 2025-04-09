import discord
from discord import ui, SelectOption, Interaction, TextStyle


class RecruitmentModal(ui.Modal, title="모집 상세내용 입력"):
    recruitment_content = ui.TextInput(
        label="모집 내용",
        style=TextStyle.paragraph,
        placeholder="모집 내용을 입력하세요...",
        required=True,
        max_length=500
    )

    async def on_submit(self, interaction: Interaction):
        # 모달 제출 시, 부모 RecruitmentCard의 모집 내용을 업데이트합니다.
        content_value = self.recruitment_content.value
        print(f"[DEBUG] RecruitmentModal.on_submit - 입력된 모집 내용 길이: {len(content_value)}")
        print(f"[DEBUG] RecruitmentModal.on_submit - 입력된 모집 내용 타입: {type(content_value)}")
        print(f"[DEBUG] RecruitmentModal.on_submit - 입력된 모집 내용 미리보기: {content_value[:30]}...")
        
        # 부모 객체에 모집 내용 설정
        self.parent.recruitment_content = content_value
        
        # 디버그 로그 추가
        print(f"[DEBUG] RecruitmentModal.on_submit - 모집 내용 부모 객체에 설정 완료")
        print(f"[DEBUG] RecruitmentModal.on_submit - 부모 recruitment_content 길이: {len(self.parent.recruitment_content)}")
        print(f"[DEBUG] RecruitmentModal.on_submit - 부모 recruitment_content 타입: {type(self.parent.recruitment_content)}")
        print(f"[DEBUG] RecruitmentModal.on_submit - 부모 recruitment_content 미리보기: {self.parent.recruitment_content[:30]}...")
        
        # 메시지 없이 상호작용 응답 처리 (defer)
        await interaction.response.defer(ephemeral=True)
        
        # 임베드 업데이트 (내부에서 버튼 상태도 업데이트됨)
        await self.parent.update_embed(interaction)


class TypeSelectView(ui.View):
    def __init__(self, parent):
        super().__init__(timeout=60)
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
        super().__init__(timeout=60)
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
        super().__init__(timeout=60)
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
