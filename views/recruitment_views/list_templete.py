import discord
from db.session import SessionLocal
from queries.recruitment_query import select_recruitment, select_participants

SEPARATOR = "─" * 20
db = SessionLocal()

def build_recruitment_embed(
    dungeon_type: str,
    dungeon_name: str,
    difficulty: str,
    detail: str,
    status: str,
    max_person: int,
    recruiter: str,
    applicants: list[str],
    image_url: str,
    recru_id: str,
) -> discord.Embed:

    embed = discord.Embed(
        title=f"📢 {detail}\n" +f"`{status}`",
        description=f"> **모집인원** : `{len(applicants)}` / `{max_person}`",
        color=discord.Color.from_rgb(178, 96, 255),
    ).set_thumbnail(url=image_url)

    if(dungeon_name == "모집내용참고" or difficulty == "모집내용참고" or dungeon_name == "미정" or difficulty == "미정"):
        embed.set_author(name=f"{dungeon_type}")
    else:
        embed.set_author(name=f"{dungeon_type} · {dungeon_name} · {difficulty}")

    # ── 구분선 ───────────────────────────────
    embed.add_field(name="\u200b", value=SEPARATOR, inline=False)

    # ── 지원자 & 파티장 목록 ───────────────────────────
    joined = "\n".join(f"• <@{uid}>" for uid in applicants) if applicants else "_아직 없음_"
    embed.add_field(
        name="🙋 **지원자**\n\n",
        value=joined,
        inline=True
    )

    embed.add_field(
        name="👑 **파티장**\n\n",
        value=f"<@{recruiter}>",
        inline=True
    )

    # ── 구분선 ───────────────────────────────
    embed.add_field(name="\u200b", value=SEPARATOR, inline=False)


    # ── 푸터 ─────────────────────────────────
    embed.set_footer(text=f"{recru_id}")

    return embed


class RecruitmentListButtonView(discord.ui.View):
    def __init__(self, applicants=None, **embed_kwargs):
        super().__init__(timeout=None)

    # ── 버툰 ─────────────────────────────────
    # 지원하기 버튼 & 기능
    @discord.ui.button(label="지원하기", style=discord.ButtonStyle.primary, custom_id="apply")
    async def apply(self, interaction: discord.Interaction, button: discord.ui.Button):
        user = interaction.user
        recru_id = interaction.message.embeds[0].footer.text

        recruitment_result = select_recruitment(db, recru_id)
        participants_list = select_participants(db, recru_id)

        if recruitment_result is None:
            await interaction.response.send_message("모집이 존재하지 않습니다.", ephemeral=True)
            return
        
        build_recruitment_embed(
            recruitment_result["dungeon_type"],
            recruitment_result["dungeon_name"],
            recruitment_result["dungeon_difficulty"],
            recruitment_result["recru_discript"],
            recruitment_result["status"],
            recruitment_result["max_person"],
            recruitment_result["create_user_id"],
            participants_list,
            interaction.message.embeds[0].thumbnail.url,
            recru_id
        )

        if int(recruitment_result["max_person"]) == len(participants_list):
            await interaction.response.send_message("모집이 마감되었습니다.", ephemeral=True)
            # 하는중 TO_DO: 모집 마감시 버튼 비활성화
            return
        


        await interaction.response.edit_message(embed=embed, view=self)
        await interaction.response.send_message("지원 완료!", ephemeral=True)

    @discord.ui.button(label="지원취소", style=discord.ButtonStyle.secondary, custom_id="cancel_apply")
    async def cancel_apply(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("지원 취소!", ephemeral=True)

    @discord.ui.button(label="모집취소", style=discord.ButtonStyle.danger, custom_id="cancel_recruit")
    async def cancel_recruit(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("모집이 취소되었습니다.", ephemeral=True)

    @discord.ui.button(label="모집마감", style=discord.ButtonStyle.success, custom_id="complete_recruit")
    async def complete_recruit(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("모집이 마감되었습니다.", ephemeral=True)


