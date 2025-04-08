import discord
from discord import ui, Embed, Color
from views.recruitment_card_views import TypeSelectView, KindSelectView, DiffSelectView, RecruitmentModal

class RecruitmentCard(ui.View):
    def __init__(self, dungeons):
        super().__init__(timeout=300)
        self.dungeons = dungeons
        self.selected_type = None
        self.selected_kind = None
        self.selected_diff = None
        self.recruitment_content = None
        self.message = None  # persistent 메시지 저장

    def get_embed(self) -> Embed:
        embed = Embed(title="파티 모집 카드", color=Color.blue())
        embed.add_field(name="던전 타입", value=self.selected_type or "미선택", inline=True)
        embed.add_field(name="던전 종류", value=self.selected_kind or "미선택", inline=True)
        embed.add_field(name="던전 난이도", value=self.selected_diff or "미선택", inline=True)
        embed.add_field(name="모집 내용", value=self.recruitment_content or "미작성", inline=False)
        embed.set_footer(text="아래 버튼을 눌러 각 항목을 업데이트하세요.")
        return embed

    async def update_embed(self, interaction: discord.Interaction = None):
        embed = self.get_embed()
        await self.message.edit(embed=embed, view=self)

    @ui.button(label="타입 선택", style=discord.ButtonStyle.primary, custom_id="btn_type")
    async def btn_type(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(view=TypeSelectView(self), ephemeral=True)

    @ui.button(label="종류 선택", style=discord.ButtonStyle.primary, custom_id="btn_kind")
    async def btn_kind(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.selected_type:
            await interaction.response.send_message("먼저 던전 타입을 선택하세요.", ephemeral=True)
            return
        await interaction.response.send_message(view=KindSelectView(self), ephemeral=True)

    @ui.button(label="난이도 선택", style=discord.ButtonStyle.primary, custom_id="btn_diff")
    async def btn_diff(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.selected_type or not self.selected_kind:
            await interaction.response.send_message("먼저 던전 타입과 종류를 선택하세요.", ephemeral=True)
            return
        await interaction.response.send_message(view=DiffSelectView(self), ephemeral=True)

    @ui.button(label="모집 내용 작성", style=discord.ButtonStyle.success, custom_id="btn_content")
    async def btn_content(self, interaction: discord.Interaction, button: discord.ui.Button):
        modal = RecruitmentModal()
        modal.parent = self  # 모달이 이 RecruitmentCard 상태를 업데이트할 수 있도록 참조 전달
        await interaction.response.send_modal(modal)
