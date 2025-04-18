import discord
from db.session import SessionLocal
from queries.recruitment_query import select_com_code_status

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
        title=f"📢 {detail}\n" +f"> `{status}`",
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
    joined = "\n".join(f"• {u.mention}" for u in applicants) if applicants else "_아직 없음_"
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
    def __init__(self):
        super().__init__(timeout=None)

    # ── 버툰 ─────────────────────────────────
    @discord.ui.button(label="지원하기", style=discord.ButtonStyle.primary, custom_id="apply")
    async def apply(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("지원 완료!", ephemeral=False)

    @discord.ui.button(label="지원취소", style=discord.ButtonStyle.secondary, custom_id="cancel_apply")
    async def cancel_apply(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("지원 취소!", ephemeral=False)

    @discord.ui.button(label="모집취소", style=discord.ButtonStyle.danger, custom_id="cancel_recruit")
    async def cancel_recruit(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("모집이 취소되었습니다.", ephemeral=False)

    @discord.ui.button(label="모집마감", style=discord.ButtonStyle.success, custom_id="complete_recruit")
    async def complete_recruit(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("모집이 마감되었습니다.", ephemeral=False)
