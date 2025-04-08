import discord
from discord import ui, SelectOption, Interaction, Embed, TextStyle

# 모집 내용을 입력받을 모달
class RecruitmentModal(ui.Modal, title="모집 내용 작성"):
    recruitment_content = ui.TextInput(
        label="모집 내용",
        style=TextStyle.paragraph,
        placeholder="모집 내용을 입력하세요...",
        required=True,
        max_length=500
    )

    async def on_submit(self, interaction: Interaction):
        # 모달 제출 시, 입력한 내용을 확인하는 Embed 전송 (추후 이 값을 저장하거나 추가 처리할 수 있습니다)
        embed = Embed(title="모집 내용 제출됨", description=self.recruitment_content.value, color=0x00aaee)
        await interaction.response.send_message(embed=embed, ephemeral=True)

# 여러 셀렉트 박스와 버튼을 포함하는 View
class MultiDungeonSelectView(ui.View):
    def __init__(self, dungeons):
        super().__init__(timeout=120)
        self.dungeons = dungeons

        self.selected_type = None
        self.selected_kind = None
        self.selected_diff = None

        # 1. 던전 타입 선택 (이모지 추가)
        types = sorted({d["type"] for d in dungeons})
        type_options = [SelectOption(label=f"🏰 {t}", value=t) for t in types]
        self.type_select = ui.Select(
            placeholder="던전 타입 선택",
            options=type_options,
            custom_id="type_select"
        )
        self.type_select.callback = self.on_type_select
        self.add_item(self.type_select)

        # 2. 던전 종류 선택 (초기에는 더미 옵션; 실제 옵션은 타입 선택 후 업데이트)
        dummy_option = SelectOption(label="⚠️ 선택 없음", value="none")
        self.kind_select = ui.Select(
            placeholder="던전 종류 선택",
            options=[dummy_option],
            custom_id="kind_select",
            disabled=True
        )
        self.kind_select.callback = self.on_kind_select
        self.add_item(self.kind_select)

        # 3. 던전 난이도 선택 (초기에는 더미 옵션; 실제 옵션은 종류 선택 후 업데이트)
        self.diff_select = ui.Select(
            placeholder="던전 난이도 선택",
            options=[dummy_option],
            custom_id="diff_select",
            disabled=True
        )
        self.diff_select.callback = self.on_diff_select
        self.add_item(self.diff_select)

        # 4. 모집 내용 입력 버튼: 누르면 모달이 뜹니다.
        self.recruit_button = ui.Button(
            label="모집 내용 작성",
            style=discord.ButtonStyle.primary,
            custom_id="recruit_button"
        )
        self.recruit_button.callback = self.on_recruit_button
        self.add_item(self.recruit_button)

    async def on_type_select(self, interaction: Interaction):
        new_type = self.type_select.values[0]
        self.selected_type = new_type

        # 선택된 타입을 default로 설정
        for option in self.type_select.options:
            option.default = (option.value == new_type)

        # 해당 타입에 맞는 던전 종류 추출
        kinds = sorted({d["name"] for d in self.dungeons if d["type"] == self.selected_type})
        if kinds:
            kind_options = [SelectOption(label=f"⚔️ {k}", value=k) for k in kinds]
        else:
            kind_options = [SelectOption(label="⚠️ 선택 없음", value="none")]
        self.kind_select.options = kind_options
        self.kind_select.disabled = False

        # 종류 선택 시 난이도 초기화
        self.selected_kind = None
        self.diff_select.options = [SelectOption(label="⚠️ 선택 없음", value="none")]
        self.diff_select.disabled = True
        self.selected_diff = None

        await interaction.response.edit_message(view=self)

    async def on_kind_select(self, interaction: Interaction):
        new_kind = self.kind_select.values[0]
        self.selected_kind = new_kind

        # 선택된 종류를 default로 설정
        for option in self.kind_select.options:
            option.default = (option.value == new_kind)

        # 해당 타입과 종류에 맞는 난이도 추출 (DB에 저장된 값 그대로 사용)
        difficulties = sorted({d["difficulty"] for d in self.dungeons
                               if d["type"] == self.selected_type and d["name"] == self.selected_kind})
        if difficulties:
            diff_options = [SelectOption(label=f"⭐ {diff}", value=diff) for diff in difficulties]
            self.diff_select.options = diff_options
            self.diff_select.disabled = False
        else:
            self.diff_select.options = [SelectOption(label="⚠️ 선택 없음", value="none")]
            self.diff_select.disabled = True

        self.selected_diff = None

        await interaction.response.edit_message(view=self)

    async def on_diff_select(self, interaction: Interaction):
        new_diff = self.diff_select.values[0]
        self.selected_diff = new_diff

        # 선택된 난이도를 default로 설정
        for option in self.diff_select.options:
            option.default = (option.value == new_diff)

        await interaction.response.edit_message(view=self)

    async def on_recruit_button(self, interaction: Interaction):
        # 모집 내용 입력 모달 띄우기
        await interaction.response.send_modal(RecruitmentModal())
