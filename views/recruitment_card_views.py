import discord
from discord import ui, SelectOption, Interaction, Embed, TextStyle


class RecruitmentModal(ui.Modal, title="모집 내용 작성"):
    recruitment_content = ui.TextInput(
        label="모집 내용",
        style=TextStyle.paragraph,
        placeholder="모집 내용을 입력하세요...",
        required=True,
        max_length=500
    )

    async def on_submit(self, interaction: Interaction):
        # 모달 제출 시, 부모 RecruitmentCard의 모집 내용을 업데이트합니다.
        self.parent.recruitment_content = self.recruitment_content.value
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
        await self.parent.update_embed(interaction)

        # interaction 메시지 자체를 삭제
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
