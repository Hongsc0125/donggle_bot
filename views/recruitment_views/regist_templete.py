import logging
from typing import List, Tuple

import discord
from db.session import SessionLocal
from queries.recruitment_query import select_dungeon, select_pair_channel_id, select_dungeon_id, insert_recruitment, select_recruitment
from queries.recruitment_query import update_recruitment_message_id, select_max_person_setting

from views.recruitment_views.list_templete import build_recruitment_embed, RecruitmentListButtonView

logger = logging.getLogger(__name__)

# ──────────────────────────────
# 헬퍼
# ──────────────────────────────
DungeonRow = Tuple[str, str, str]

def _start_embed() -> discord.Embed:
    return discord.Embed(
        title="파티 모집 양식",
        description="던전 정보를 순서대로 선택해 주세요.",
        color=discord.Color.from_rgb(178, 96, 255),
    )

def _update_embed(**fields) -> discord.Embed:
    embed = discord.Embed(title="", color=discord.Color.from_rgb(178, 96, 255))
    for k, v in fields.items():
        if v:
            embed.add_field(name=k, value=v, inline=False)
    return embed

def _clone_select(select: discord.ui.Select, *, placeholder: str, disabled: bool):
    """기존 Select를 복제하면서 placeholder/disabled 값만 바꾼 새 Select 반환"""
    new_select = discord.ui.Select(
        placeholder=placeholder,
        options=select.options,
        row=select.row,
        disabled=disabled,
        min_values=select.min_values,
        max_values=select.max_values,
    )
    return new_select

# ──────────────────────────────
# 메인 버튼 뷰
# ──────────────────────────────
class RecruitmentButtonView(discord.ui.View):
    @discord.ui.button(label="파티 모집 등록",
                       style=discord.ButtonStyle.primary,
                       custom_id="recruitment_register")
    async def register_button(self,
                              interaction: discord.Interaction,
                              _: discord.ui.Button):
        db = SessionLocal()
        rows: List[DungeonRow] = select_dungeon(db)
        max_person_settings = select_max_person_setting(db)
        db.close()

        form_view = RecruitmentFormView(rows, max_person_settings)
        await interaction.response.send_message(
            embed=_start_embed(), view=form_view, ephemeral=True
        )
        form_view.root_msg = await interaction.original_response()

# ──────────────────────────────
# 1차 뷰 : 타입→이름→난이도
# ──────────────────────────────
class RecruitmentFormView(discord.ui.View):
    def __init__(self, rows: List[DungeonRow], max_person_settings=None):
        super().__init__(timeout=180)
        self.rows = rows
        self.root_msg: discord.WebhookMessage | None = None
        self.max_person_settings = max_person_settings
        self.type = self.name = self.diff = None

        # 타입 Select (시작부터 표시)
        self.type_select = discord.ui.Select(
            placeholder="던전 타입",
            options=[discord.SelectOption(label=t, value=t)
                     for t in sorted({r[0] for r in rows})],
            row=0,
        )
        self.type_select.callback = self.on_type
        self.add_item(self.type_select)

        # 이름/난이도 Select는 나중에 동적 생성
        self.name_select: discord.ui.Select | None = None
        self.diff_select: discord.ui.Select | None = None

        # '다음' 버튼
        self.next_btn = discord.ui.Button(
            label="다음", style=discord.ButtonStyle.success,
            disabled=True, row=3
        )
        # '취소' 버튼
        self.cancel_btn = discord.ui.Button(
            label="취소", style=discord.ButtonStyle.danger,
            disabled=False, row=3
        )
        self.next_btn.callback = self.open_member_select
        self.add_item(self.next_btn)
        self.cancel_btn.callback = self.cancel_recruitment
        self.add_item(self.cancel_btn)

    # ───── 타입 선택
    async def on_type(self, interaction: discord.Interaction):
        await interaction.response.defer()

        self.type = self.type_select.values[0]

        # 1) 타입 Select 완료 표시(비활성)
        done_type = _clone_select(
            self.type_select,
            placeholder=f"✅ {self.type}", disabled=True
        )
        self.remove_item(self.type_select)
        self.type_select = done_type
        self.add_item(self.type_select)

        # 2) 이름 Select 새로 생성 & 활성화
        names = sorted({r[1] for r in self.rows if r[0] == self.type})
        self.name_select = discord.ui.Select(
            placeholder="던전 이름",
            options=[discord.SelectOption(label=n, value=n) for n in names],
            row=1,
        )
        self.name_select.callback = self.on_name
        self.add_item(self.name_select)

        # 난이도 초기화
        self.name = self.diff = None
        if self.diff_select and self.diff_select in self.children:
            self.remove_item(self.diff_select)
        self.diff_select = None

        await self.refresh_view()

    # ───── 던전 이름 선택
    async def on_name(self, interaction: discord.Interaction):
        await interaction.response.defer()

        self.name = self.name_select.values[0]

        # 이름 Select 완료 표시
        done_name = _clone_select(
            self.name_select,
            placeholder=f"✅ {self.name}", disabled=True
        )
        self.remove_item(self.name_select)
        self.name_select = done_name
        self.add_item(self.name_select)

        # 난이도 Select 생성
        diffs = sorted({r[2] for r in self.rows
                        if r[0] == self.type and r[1] == self.name})
        self.diff_select = discord.ui.Select(
            placeholder="난이도",
            options=[discord.SelectOption(label=d, value=d) for d in diffs],
            row=2,
        )
        self.diff_select.callback = self.on_diff
        self.add_item(self.diff_select)

        self.diff = None
        await self.refresh_view()

    # ───── 난이도 선택
    async def on_diff(self, interaction: discord.Interaction):
        await interaction.response.defer()

        self.diff = self.diff_select.values[0]

        done_diff = _clone_select(
            self.diff_select,
            placeholder=f"✅ {self.diff}", disabled=True
        )
        self.remove_item(self.diff_select)
        self.diff_select = done_diff
        self.add_item(self.diff_select)

        await self.refresh_view()

    # ───── 다음 단계 (모집 인원 뷰 호출)
    async def open_member_select(self, interaction: discord.Interaction):
        await interaction.response.defer()

        await self.root_msg.edit(
            embed=_update_embed(
                **{
                    "던전 타입": self.type,
                    "던전 이름": self.name,
                    "난이도": self.diff,
                    "모집 인원": "선택 대기…",
                }
            ),
            view=MemberCountView(self, self.max_person_settings),
        )
    
    # ───── 취소
    async def cancel_recruitment(self, interaction: discord.Interaction):
        """모집 과정을 취소하고 에페메럴 안내 후 마스터 메시지 삭제."""
        await interaction.response.send_message(
            "모집 등록이 취소되었습니다.", ephemeral=True
        )
        # 마스터 메시지 제거
        if self.root_msg:
            await self.root_msg.delete()

    # ───── Embed & 버튼 상태 갱신
    async def refresh_view(self):
        self.next_btn.disabled = not all([self.type, self.name, self.diff])
        await self.root_msg.edit(
            embed=_update_embed(
                **{
                    "던전 타입": self.type,
                    "던전 이름": self.name,
                    "난이도": self.diff
                }
            ),
            view=self
        )

# ──────────────────────────────
# 2차 뷰 : 모집 인원
# ──────────────────────────────
class MemberCountView(discord.ui.View):
    def __init__(self, form_view: RecruitmentFormView, max_person_settings=None):
        super().__init__(timeout=180)
        self.form_view = form_view

        select = discord.ui.Select(
            placeholder="모집 인원(본인 제외)",
            options=[discord.SelectOption(label=f"{i}명(본인제외)", value=str(i))
                     for i in range(1, max_person_settings)],
            row=0,
        )
        # '취소' 버튼
        self.cancel_btn = discord.ui.Button(
            label="취소", style=discord.ButtonStyle.danger,
            disabled=False, row=3
        )
        select.callback = self.on_member_selected
        self.cancel_btn.callback = self.form_view.cancel_recruitment
        self.add_item(select)
        self.add_item(self.cancel_btn)

    async def on_member_selected(self, interaction: discord.Interaction):
        count = interaction.data["values"][0]
        self.form_view.member_count = count
        await interaction.response.send_modal(
            DetailModal(self.form_view, count)
        )

# ──────────────────────────────
# 상세 내용 입력 : 모달
# ──────────────────────────────
class DetailModal(discord.ui.Modal, title="모집 상세 정보"):
    description = discord.ui.TextInput(
        label="모집 상세내용",
        style=discord.TextStyle.paragraph,
        required=False,
        max_length=30,
        placeholder="추가 설명이나 요구사항 등을 입력하세요",
    )

    def __init__(self, form: RecruitmentFormView, count: str):
        super().__init__()
        self.form = form
        self.count = count

    async def on_submit(self, interaction: discord.Interaction):
        data = {
            "던전 타입": self.form.type,
            "던전 이름": self.form.name,
            "난이도": self.form.diff,
            "모집 인원 표시": f"{self.count}명(본인 포함)",
            "모집 인원": self.count,
            "상세 내용": self.description.value or "추가 내용 없음",
        }

        confirm_embed = discord.Embed(
            title="모집 정보 확인",
            description="\n".join(f"**{k}:** {v}" for k, v in data.items()),
            color=discord.Color.from_rgb(178, 96, 255),
        )
        await self.form.root_msg.edit(
            embed=confirm_embed,
            view=ConfirmationView(data, self.form.root_msg),
        )
        await interaction.response.defer()

# ──────────────────────────────
# 4차 뷰 : 등록 / 취소
# ──────────────────────────────
class ConfirmationView(discord.ui.View):
    def __init__(self, data: dict, root_msg: discord.WebhookMessage):
        super().__init__(timeout=180)
        self.data = data
        self.root_msg = root_msg

    @discord.ui.button(label="모집등록", style=discord.ButtonStyle.success)
    async def confirm(self, interaction: discord.Interaction, _):
        try:
            db = SessionLocal()
            # 모집 정보 저장
            pair_id = select_pair_channel_id(
                db, interaction.guild_id, self.root_msg.channel.id
            )

            dungeon_id = select_dungeon_id(
                db, self.data["던전 타입"],
                self.data["던전 이름"], self.data["난이도"]
            )

            if not pair_id and not dungeon_id:
                await interaction.response.send_message(
                    "❌ PAIR_ID, DUNGEON_ID 데이터베이스 조회 실패. 운영자에게 문의해주세요.", ephemeral=True
                )
                return
            
            recru_id = insert_recruitment(
                db
                , dungeon_id
                , pair_id
                , interaction.user.id
                , self.data["상세 내용"]
                , int(self.data["모집 인원"])
                , 2 # 모집중
            )

            if(not recru_id):
                await interaction.response.send_message(
                    "❌ 모집 등록 실패. 운영자에게 문의해주세요.", ephemeral=True
                )
                return
            else:
                logger.info(f"모집 등록 성공: {recru_id}")
            

            # 가져온다 DB에 저장한 등록정보를!
            regist_data = select_recruitment(db, recru_id)

            if regist_data is None:
                await interaction.response.send_message(
                    "❌ 모집 정보를 불러오지 못했습니다.", ephemeral=True
                )
                db.rollback()
                return

            if regist_data['dungeon_type'] == '레이드' or regist_data['dungeon_type'] == '심층' or regist_data['dungeon_type'] == '퀘스트':
                image_url = f"https://harmari.duckdns.org/static/{regist_data['dungeon_type']}.png"
            elif regist_data['dungeon_type'] == '어비스':
                image_url = f"https://harmari.duckdns.org/static/{regist_data['dungeon_name']}.png"
            else:
                image_url = f"https://harmari.duckdns.org/static/마비로고.png"


            channel = interaction.guild.get_channel(int(regist_data['list_ch_id']))
            if channel is None:
                await interaction.response.send_message(
                    "❌ 모집 등록 실패(채널가져오기 실패). 운영자에게 문의해주세요.", ephemeral=True
                )
                db.rollback()
                return
            
            db.commit()

            # 공고 등록
            embed = build_recruitment_embed(
                dungeon_type = regist_data['dungeon_type'],
                dungeon_name = regist_data['dungeon_name'],
                difficulty = regist_data['dungeon_difficulty'],
                detail = regist_data['recru_discript'],
                status = regist_data['status'],
                max_person = regist_data['max_person'],
                recruiter = regist_data['create_user_id'],
                applicants=[],
                image_url=image_url,
                recru_id=recru_id,
                create_dt=regist_data['create_dt']
            )
            msg = await channel.send(embed=embed, view=RecruitmentListButtonView(recru_id=recru_id))
            message_id = msg.id

            # 등록한 모집정보에 메시지 ID 저장
            result = update_recruitment_message_id(db, message_id, recru_id)

            logger.info(f"모집 등록 {result} : {recru_id} / 메시지 ID: {message_id}")

            if not result:
                await interaction.response.send_message(
                    "❌ 모집 등록 실패(메시지 ID 저장 실패). 운영자에게 문의해주세요.", ephemeral=True
                )
                db.rollback()
                await msg.delete()
                return

            await interaction.response.send_message(
                "✅ 모집이 성공적으로 등록되었습니다!", ephemeral=True
            )

            db.commit()

        except Exception:
            logger.exception("모집 등록 실패")
            await interaction.response.send_message(
                "❌ 모집 등록 중 오류가 발생했습니다.", ephemeral=True
            )
            db.rollback()
        finally:
            await self.root_msg.delete()
            db.close()

    @discord.ui.button(label="취소", style=discord.ButtonStyle.danger)
    async def cancel(self, interaction: discord.Interaction, _):
        await interaction.response.send_message(
            "모집 등록이 취소되었습니다.", ephemeral=True
        )
        await self.root_msg.delete()

