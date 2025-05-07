import discord
import logging
import asyncio
from db.session import SessionLocal
from datetime import datetime
from core.utils import interaction_response, interaction_followup, execute_concurrently
from queries.recruitment_query import select_recruitment, select_participants, insert_participants, select_participants_check
from queries.recruitment_query import update_recruitment_status, delete_participants
from core.config import settings
from views.recruitment_views.thread_templete import create_thread


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
        
        # DB 세션 관리 개선
        self.recru_id = recru_id
        self.recruitment_result = None
        self.participants_list = []

        # 비동기로 데이터 로드
        asyncio.create_task(self.load_data())

    async def load_data(self):
        """비동기 데이터 로드"""
        db = SessionLocal()
        try:
            self.recruitment_result = select_recruitment(db, self.recru_id)
            
            if self.recruitment_result is None:
                logger.error("모집이 존재하지 않습니다.")
                return
            
            self.participants_list = select_participants(db, self.recru_id) or []
            self.remove_all_buttons(self.recruitment_result["status_code"])

        except Exception as e:
            logger.error(f"리스트 버튼 생성중 오류: {e}")
            return
        finally:
            db.close()

    # 지원하기 버튼 & 기능
    @discord.ui.button(label="지원하기", style=discord.ButtonStyle.primary, custom_id="apply")
    async def apply(self, interaction: discord.Interaction, button: discord.ui.Button):
        # 응답 지연 설정
        await interaction.response.defer(ephemeral=True)
        
        db = SessionLocal()
        try:
            recru_id = interaction.message.embeds[0].footer.text
            user = interaction.user

            # DB 접근 최적화 - 필요한 정보만 한 번에 가져오기
            tasks = [
                self.fetch_recruitment(db, recru_id),
                self.fetch_participants(db, recru_id)
            ]
            
            # 비동기 작업 동시 실행
            results = await execute_concurrently(tasks)
            recruitment_result = results[0]
            participants_list = results[1]
            
            if recruitment_result is None:
                await interaction_followup(interaction, "❌ 모집이 존재하지 않습니다.")
                return
            
            # 여러 검증 동시 수행
            validation_results = await self.validate_application(db, recruitment_result, participants_list, user.id)
            if not validation_results["valid"]:
                await interaction_followup(interaction, validation_results["message"])
                return
            
            # 지원자 등록
            insert_result = insert_participants(db, recru_id, user.id)

            if insert_result:
                participants_list.append(user.id)
            else:
                await interaction_followup(interaction, "❌ 시스템 문제로 지원에 실패했습니다.")
                return

            # 재조회(최신화)
            participants_list = select_participants(db, recru_id)

            # 모집인원이 꽉차면 모집마감으로 상태값 업데이트
            create_thread_needed = False
            if recruitment_result["max_person"] <= len(participants_list):
                # 모집마감 상태값 업데이트(3: 모집마감)
                update_result = update_recruitment_status(db, 3, recru_id=recru_id)
                if not update_result:
                    await interaction_followup(interaction, "❌ 모집마감 상태 업데이트에 실패했습니다.")
                    return
                create_thread_needed = True
            
            db.commit()

            # 재조회(최신화)
            recruitment_result = select_recruitment(db, recru_id)

            # 임베드 생성 및 메시지 업데이트
            embed = await self.create_updated_embed(recruitment_result, participants_list, interaction.message.embeds[0].thumbnail.url)

            # 버튼제거 검사 및 제거
            self.remove_all_buttons(recruitment_result["status_code"])

            await interaction.edit_original_response(embed=embed, view=self)
            await interaction.followup.send("지원 완료!", ephemeral=True)

            # 스레드 생성 필요시 비동기로 실행
            if create_thread_needed:
                asyncio.create_task(create_thread(interaction))
            
        except Exception as e:
            logger.error(f"지원하기 버튼 전역오류 : {e}")
            logger.error(traceback.format_exc())
            await interaction_followup(interaction, "❌ 시스템 문제로 지원에 실패했습니다.")
            db.rollback()
        finally:
            db.close()

    async def fetch_recruitment(self, db, recru_id):
        """모집 정보 조회"""
        return select_recruitment(db, recru_id)
        
    async def fetch_participants(self, db, recru_id):
        """참가자 목록 조회"""
        return select_participants(db, recru_id) or []
        
    async def validate_application(self, db, recruitment_result, participants_list, user_id):
        """지원 유효성 검사"""
        if recruitment_result["status_code"] != 2:
            return {"valid": False, "message": "❌ 모집이 마감 또는 취소되었습니다."}
                
        # 파티장은 자신의 모집에 지원할 수 없음
        if user_id == int(recruitment_result["create_user_id"]):
            return {"valid": False, "message": "❌ 파티장은 자신의 모집에 지원할 수 없습니다."}

        if select_participants_check(db, recruitment_result["recru_id"], user_id):
            return {"valid": False, "message": "❌ 이미 지원한 상태입니다."}
        
        if recruitment_result["max_person"] <= len(participants_list):
            return {"valid": False, "message": "❌ 모집인원이 초과되었습니다."}
            
        return {"valid": True, "message": ""}
        
    async def create_updated_embed(self, recruitment_result, participants_list, image_url):
        """업데이트된 임베드 생성"""
        return build_recruitment_embed(
            recruitment_result["dungeon_type"],
            recruitment_result["dungeon_name"],
            recruitment_result["dungeon_difficulty"],
            recruitment_result["recru_discript"],
            recruitment_result["status"],
            recruitment_result["max_person"],
            recruitment_result["create_user_id"],
            participants_list,
            image_url,
            self.recru_id,
            recruitment_result["create_dt"]
        )

    # 나머지 버튼 핸들러도 비슷한 방식으로 최적화
    # ...existing code...

    # ───────────────────────────────────────────────
    #             지원취소 버튼 & 기능
    # ───────────────────────────────────────────────
    @discord.ui.button(label="지원취소", style=discord.ButtonStyle.secondary, custom_id="cancel_apply", row=0)
    async def cancel_apply(self, interaction: discord.Interaction, button: discord.ui.Button):
        db = SessionLocal()
        try:
            recru_id = interaction.message.embeds[0].footer.text
            user = interaction.user

            recruitment_result = select_recruitment(db, recru_id)
            
            if recruitment_result is None:
                await interaction_response(interaction, "❌ 모집이 존재하지 않습니다.")
                return
            
            if recruitment_result["status_code"] != 2:
                await interaction_response(interaction, "❌ 모집이 마감 또는 취소되었습니다.")
                return

            if not select_participants_check(db, recru_id, user.id):
                await interaction_response(interaction, "❌ 지원하지 않은 상태입니다.")
                return

            # 지원자 삭제
            delete_result = delete_participants(db, recru_id, user.id)

            if delete_result:
                participants_list = select_participants(db, recru_id)
            else:
                await interaction_response(interaction, "❌ 시스템 문제로 지원취소에 실패했습니다.")
                return

            db.commit()

            # 재조회(최신화)
            recruitment_result = select_recruitment(db, recru_id)
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
            await interaction_followup(interaction, "지원취소 완료!")

        except Exception as e:
            logger.error(f"지원취소 버튼 전역오류 : {e}")
            await interaction_followup(interaction, "❌ 시스템 문제로 지원취소에 실패했습니다.")

        finally:
            db.close()


    # ───────────────────────────────────────────────
    #             모집마감 버튼 & 기능
    # ───────────────────────────────────────────────
    @discord.ui.button(label="모집마감", style=discord.ButtonStyle.success, custom_id="complete_recruit", row=1)
    async def complete_recruit(self, interaction: discord.Interaction, button: discord.ui.Button):
        db = SessionLocal()
        try:
            recru_id = interaction.message.embeds[0].footer.text

            recruitment_result = select_recruitment(db, recru_id)
            
            if recruitment_result is None:
                await interaction_response(interaction, "❌ 모집이 존재하지 않습니다.")
                return
            
            if recruitment_result["status_code"] != 2:
                await interaction_response(interaction, "❌ 모집이 이미 마감 또는 취소되었습니다.")
                return

            # 파티장 확인 - 파티장만 모집을 마감할 수 있음
            if interaction.user.id != int(recruitment_result["create_user_id"]):
                await interaction_response(interaction, "❌ 파티장만 모집을 마감할 수 있습니다.")
                return

            # 모집마감 상태값 업데이트(3: 모집마감)
            update_result = update_recruitment_status(db, 3, recru_id=recru_id)
                
            if not update_result:
                await interaction_response(interaction, "❌ 모집마감 상태 업데이트에 실패했습니다.")
                return
            
            db.commit()

            # 재조회(최신화)
            recruitment_result = select_recruitment(db, recru_id)
            participants_list = select_participants(db, recru_id)

            # 버튼 제거 및 임베드 재생성
            self.remove_all_buttons(recruitment_result["status_code"])

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
            await interaction_followup(interaction, "모집이 마감되었습니다.")

            await create_thread(interaction)

        except Exception as e:
            logger.error(f"모집마감 버튼 전역오류 : {e}")
            await interaction_followup(interaction, "❌ 시스템 문제로 모집마감에 실패했습니다.")

        finally:
            db.close()


    # ───────────────────────────────────────────────
    #             모집취소 버튼 & 기능
    # ───────────────────────────────────────────────
    @discord.ui.button(label="모집취소", style=discord.ButtonStyle.danger, custom_id="cancel_recruit", row=1)
    async def cancel_recruit(self, interaction: discord.Interaction, button: discord.ui.Button):
        db = SessionLocal()
        try:
            recru_id = interaction.message.embeds[0].footer.text

            recruitment_result = select_recruitment(db, recru_id)
            
            if recruitment_result is None:
                await interaction_response(interaction, "❌ 모집이 존재하지 않습니다.")
                return
            
            if recruitment_result["status_code"] != 2:
                await interaction_response(interaction, "❌ 모집이 마감 또는 취소되었습니다.")
                return
            
            if int(recruitment_result["create_user_id"]) != interaction.user.id:
                await interaction_response(interaction, "❌ 모집자만 취소할 수 있습니다.")
                return
            
            # 모집 상태값 업데이트(4: 모집취소)
            update_result = update_recruitment_status(db, 4, recru_id=recru_id)
            
            # 버튼 제거 후 임베드 업데이트    
            if not update_result:
                await interaction_response(interaction, "❌ 모집취소 상태 업데이트에 실패했습니다.")
                return
            
            db.commit()

            # 재조회(최신화)
            recruitment_result = select_recruitment(db, recru_id)
            participants_list = select_participants(db, recru_id)

            # 임베드 재생성
            self.remove_all_buttons(recruitment_result["status_code"])

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
            

            if not update_result:
                await interaction_response(interaction, "❌ 모집취소 상태 업데이트에 실패했습니다.")
                return
        except Exception as e:
            logger.error(f"모집취소 버튼 전역오류 : {e}")
            await interaction_followup(interaction, "❌ 시스템 문제로 모집취소에 실패했습니다.")

        finally:
            db.close()

        await interaction_followup(interaction, "모집이 취소되었습니다.")



    # ───────────────────────────────────────────────
    #             버튼 제거
    # ───────────────────────────────────────────────
    def remove_all_buttons(self, status_code: int):
    # 모집중이 아닐시 View에서 모든 버튼을 제거합니다. 
        if status_code != 2:
            for item in list(self.children):
                if isinstance(item, discord.ui.Button):
                    self.remove_item(item)


