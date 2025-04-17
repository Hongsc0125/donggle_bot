import discord
from db.session import SessionLocal
from queries.recruitment_query import select_com_code_status

SEPARATOR = "─" * 30     # 원하는 길이·문자 조정
db = SessionLocal()

def build_recruitment_embed(
    dungeon_type: str,
    dungeon_name: str,
    difficulty: str,
    detail: str,
    status: str,
    max_person: int,
    recruiter: discord.User,
    applicants: list[discord.User],
    image_url: str,
    recru_id: str,
) -> discord.Embed:
    
    status = select_com_code_status(db, status)
    if status:
        status = f"**{status}**"
    else:
        status = "❓**알수없음**"

    embed = discord.Embed(
        title=f"⚔️ {detail}",
        color=discord.Color.dark_red()
    ).set_thumbnail(url=image_url)

    embed.set_author(name=f"{dungeon_type} · {dungeon_name} · {difficulty} \n\n")

    # ── 인원 & 모집자 ────────────────────────
    embed.add_field(
        name=f"",
        value=f"- **모집인원** : `{len(applicants)}` / `{max_person}`\n"
                +f"{status}",
        inline=False
    )

    # ── 구분선 ───────────────────────────────
    embed.add_field(name="\u200b", value=SEPARATOR, inline=False)

    embed.add_field(
        name="👑 **파티장**\n\n",
        value=recruiter,
        inline=True
    )
    # ── 지원자 목록 ───────────────────────────
    joined = "\n".join(f"• {u.mention}" for u in applicants) if applicants else "_아직 없음_"
    embed.add_field(
        name="🙋 **지원자**\n\n",
        value=joined,
        inline=True
    )

    # ── 구분선 ───────────────────────────────
    embed.add_field(name="\u200b", value=SEPARATOR, inline=False)


    # ── 푸터 ─────────────────────────────────
    embed.set_footer(text=f"Recruitment ID: {recru_id}")

    return embed
