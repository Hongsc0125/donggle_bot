import discord
import logging
from db.session import SessionLocal
from datetime import datetime
from queries.recruitment_query import select_recruitment, select_participants, insert_participants, select_participants_check

SEPARATOR = "─" * 25
logger = logging.getLogger(__name__)

# ───────────────────────────────────────────────
#              파티모집공고 임베드
# ───────────────────────────────────────────────
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
    create_dt: str,
) -> discord.Embed:

    # 날짜형식 포메팅 YY-MM-DD HH:MM
    formatted_dt = create_dt.strftime('%y-%m-%d %H:%M')


    embed = discord.Embed(
        title=f"📢 {detail}\n" +f"`{status}`",
        description=f"> **모집인원** : `{len(applicants)} / {max_person}`",
        color=discord.Color.from_rgb(178, 96, 255),
    ).set_thumbnail(url=image_url)

    if(dungeon_name == "모집내용참고" or difficulty == "모집내용참고" or dungeon_name == "미정" or difficulty == "미정"):
        embed.set_author(name=f"{dungeon_type}")
    else:
        embed.set_author(name=f"{dungeon_type} · {dungeon_name} · {difficulty}")

    # ── 구분선 ───────────────────────────────
    embed.add_field(name="", value=SEPARATOR, inline=False)

    # ── 지원자 & 파티장 목록 ───────────────────────────
    joined = "\n".join(f"• <@{uid}>" for uid in applicants) if applicants else "_아직 없음_"

    embed.add_field(
        name="👑 **파티장**\n\n",
        value=f"<@{recruiter}>",
        inline=True
    )

    embed.add_field(
        name="🙋 **지원자**\n\n",
        value=joined,
        inline=True
    )

    # ── 구분선 ───────────────────────────────
    # embed.add_field(name="\u200b", value=SEPARATOR, inline=False)
    embed.add_field(name="", value=SEPARATOR, inline=False)

    embed.add_field(
        name="",
        value=f"{formatted_dt}",
        inline=False
    )

    # ── 푸터 ─────────────────────────────────
    embed.set_footer(text=f"{recru_id}")

    return embed


# ───────────────────────────────────────────────
#              모집 리스트 버튼
# ───────────────────────────────────────────────
class RecruitmentListButtonView(discord.ui.View):
    def __init__(self, show_apply=True, show_cancel=True, show_complete=True, show_cancel_recruit=True, recru_id=None):
        super().__init__(timeout=None)

        db = SessionLocal()

        try:
            self.recru_id = recru_id
            self.recruitment_result = select_recruitment(db, recru_id)
            
            if self.recruitment_result is None:
                logger.error("모집이 존재하지 않습니다.")
                return
            
            self.participants_list = select_participants(db, recru_id) or []

            # 모집이 마감된 경우 버튼전부 비활성화 (1: 입력중, 2: 모집중, 3: 모집마감, 4: 모집취소)
            logger.info(f"모집상태코드: {self.recruitment_result['status_code']}")
            if self.recruitment_result["status_code"] != 2:
                for item in list(self.children):
                    if isinstance(item, discord.ui.Button):
                        self.remove_item(item)

        except Exception as e:
            logger.error(f"리스트 버튼 생성중 오류: {e}")
            return

        finally:
            db.close()

    # ───────────────────────────────────────────────
    #             지원하기 버튼 & 기능
    # ───────────────────────────────────────────────
    @discord.ui.button(label="지원하기", style=discord.ButtonStyle.primary, custom_id="apply")
    async def apply(self, interaction: discord.Interaction, button: discord.ui.Button):

        db = SessionLocal()
        try:
            recru_id = interaction.message.embeds[0].footer.text
            user = interaction.user

            recruitment_result = select_recruitment(db, recru_id)
            
            if recruitment_result is None:
                await interaction.response.send_message("❌ 모집이 존재하지 않습니다.", ephemeral=True)
                return
            
            if recruitment_result["status_code"] != 2:
                await interaction.response.send_message("❌ 모집이 마감 또는 취소되었습니다.", ephemeral=True)
                return

            if select_participants_check(db, recru_id, user.id):
                await interaction.response.send_message("❌ 이미 지원한 상태입니다.", ephemeral=True)
                return
            
            participants_list = select_participants(db, recru_id)
            if recruitment_result["max_person"] <= len(participants_list):
                await interaction.response.send_message("❌ 모집인원이 초과되었습니다.", ephemeral=True)
                return
            
            insert_result = insert_participants(db, recru_id, user.id)

            if insert_result:
                participants_list.append(user.id)
            else:
                await interaction.response.send_message("❌ 시스템 문제로 지원에 실패했습니다.", ephemeral=True)
                return

            # 재조회(최신화)
            participants_list = select_participants(db, recru_id)

            embed = build_recruitment_embed(
                recruitment_result["dungeon_type"],
                recruitment_result["dungeon_name"],
                recruitment_result["dungeon_difficulty"],
                recruitment_result["recru_discript"],
                recruitment_result["status"],
                recruitment_result["max_person"],
                recruitment_result["create_user_id"],
                participants_list,
                interaction.message.embeds[0].thumbnail.url,
                self.recru_id,
                recruitment_result["create_dt"]
            )

            await interaction.response.edit_message(embed=embed, view=self)
            await interaction.followup.send("지원 완료!", ephemeral=True)
            db.commit()

        except Exception as e:
            logger.error(f"지원하기 버튼 전역오류 : {e}")
            await interaction.response.send_message("❌ 시스템 문제로 지원에 실패했습니다.", ephemeral=True)

        finally:
            db.close()


    # ───────────────────────────────────────────────
    #             지원취소 버튼 & 기능
    # ───────────────────────────────────────────────
    @discord.ui.button(label="지원취소", style=discord.ButtonStyle.secondary, custom_id="cancel_apply", row=0)
    async def cancel_apply(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("지원 취소!", ephemeral=True)


    # ───────────────────────────────────────────────
    #             모집마감 버튼 & 기능
    # ───────────────────────────────────────────────
    @discord.ui.button(label="모집마감", style=discord.ButtonStyle.success, custom_id="complete_recruit", row=1)
    async def complete_recruit(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("모집이 마감되었습니다.", ephemeral=True)


    # ───────────────────────────────────────────────
    #             모집취소 버튼 & 기능
    # ───────────────────────────────────────────────
    @discord.ui.button(label="모집취소", style=discord.ButtonStyle.danger, custom_id="cancel_recruit", row=1)
    async def cancel_recruit(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("모집이 취소되었습니다.", ephemeral=True)




