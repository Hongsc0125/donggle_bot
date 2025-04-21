import discord
import logging
from db.session import SessionLocal
from core.utils import interaction_response, interaction_followup
from queries.recruitment_query import select_recruitment, select_participants
from queries.thread_query import insert_complete_recruitment, update_complete_recruitment
from queries.channel_query import select_voice_channel

logger = logging.getLogger(__name__)

# ───────────────────────────────────────────────
#              쓰레드용 임베드
# ───────────────────────────────────────────────
def build_thread_embed(
        dungeon_type: str,
        dungeon_name: str,
        difficulty: str,
        detail: str,
        status: str,
        recru_id: str,
):
    
    if dungeon_type in ['레이드', '심층', '퀘스트']:
        image_url = f"https://harmari.duckdns.org/static/{dungeon_type}.png"
    elif dungeon_type == '어비스':
        image_url = f"https://harmari.duckdns.org/static/{dungeon_name}.png"
    else:
        image_url = "https://harmari.duckdns.org/static/마비로고.png"
    
    embed = discord.Embed(
        title=f"📢 {detail}\n" +f"`{status}`",
        description=f"",
        color=discord.Color.from_rgb(178, 96, 255),
    ).set_thumbnail(url=image_url)

    if(dungeon_name == "모집내용참고" or difficulty == "모집내용참고" or dungeon_name == "미정" or difficulty == "미정"):
        embed.set_author(name=f"{dungeon_type}")
    else:
        embed.set_author(name=f"{dungeon_type} · {dungeon_name} · {difficulty}")

    embed.add_field(name=f"> 하단의 버튼을 눌러 파티원을 초대해주세요.", value="")

    embed.set_footer(text=f"{recru_id}")
    return embed


# ───────────────────────────────────────────────
#      쓰레드 버튼 뷰 (파티원초대, 음성채널생성)
# ───────────────────────────────────────────────
class ThreadButtonView(discord.ui.View):
    def __init__(self, recru_id: str):
        super().__init__(timeout=None)
        self.recru_id = recru_id
        self.voice_channel = None

    @discord.ui.button(label="파티원 초대", style=discord.ButtonStyle.primary, custom_id="invite_members")
    async def invite_members(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()

        try:
            with SessionLocal() as db:
                participants_list = select_participants(db, self.recru_id)

                if not participants_list:
                    await interaction.followup.send("❌ 초대할 파티원이 없습니다.", ephemeral=True)
                    return

                thread = interaction.channel
                guild = interaction.guild

                invite_count = 0
                for user_id in participants_list:
                    try:
                        member = await guild.fetch_member(int(user_id))
                        if member:
                            await thread.add_user(member)
                            invite_count += 1
                    except Exception as e:
                        logger.error(f"파티원 초대 중 오류: {e}")

                button.label = f"✅ {invite_count}명 초대 완료"
                button.disabled = True

                # 음성채널 버튼 활성화
                for item in self.children:
                    if item.custom_id == "create_voice":
                        item.disabled = False
                        break

                await interaction.edit_original_response(view=self)

        except Exception as e:
            logger.error(f"파티원 초대 중 오류: {e}")
            await interaction.followup.send("❌ 파티원 초대 중 오류가 발생했습니다.", ephemeral=True)

    @discord.ui.button(label="음성채널 생성", style=discord.ButtonStyle.success, custom_id="create_voice", disabled=True)
    async def create_voice_channel(self, interaction: discord.Interaction, button: discord.ui.Button):

        await interaction.response.defer(ephemeral=True)  # ephemeral=True로 설정하여 본인에게만 보이게 함

        try:
            with SessionLocal() as db:
                recruitment_result = select_recruitment(db, self.recru_id)
                if recruitment_result is None:
                    await interaction.followup.send("❌ 모집 정보를 찾을 수 없습니다.", ephemeral=True)
                    return

                guild = interaction.guild
                
                # 파티장 정보 확인
                creator_id = int(recruitment_result["create_user_id"])
                
                # 파티장만 버튼 클릭 가능
                if interaction.user.id != creator_id:
                    await interaction.followup.send("❌ 파티장만 음성채널을 생성할 수 있습니다.", ephemeral=True)
                    return
                
                # DB에서 부모 음성채널 ID 조회
                parent_voice_ch_id = select_voice_channel(db, guild.id)
                
                if not parent_voice_ch_id:
                    # 부모 음성채널이 설정되지 않은 경우 오류 메시지 표시
                    await interaction.followup.send("❌ 부모 음성채널이 설정되지 않았습니다. 서버 관리자에게 문의하세요.", ephemeral=True)
                    return
                
                # 부모 음성채널이 설정된 경우 해당 채널 안내
                parent_channel = guild.get_channel(int(parent_voice_ch_id))
                if not parent_channel:
                    await interaction.followup.send("❌ 설정된 음성채널을 찾을 수 없습니다.", ephemeral=True)
                    return
                
                # 음성채널 ID 업데이트
                update_complete_recruitment(
                    db,
                    recru_id=self.recru_id,
                    voice_ch_id=parent_channel.id
                )
                db.commit()

                # 버튼 비활성화
                button.disabled = True
                button.label = "🔊 음성채널 안내 완료"
                button.style = discord.ButtonStyle.primary
                
                await interaction.edit_original_response(view=self)
                
                # 파티장에게만 보이는 부모 음성채널 안내 메시지
                embed = discord.Embed(
                    title="🔊 음성채널 입장 안내",
                    description=f"아래 음성채널에 입장하시면 파티원들만 참여할 수 있는 임시 음성채널이 자동으로 생성됩니다.\n\n> 입장 {parent_channel.mention}\n\n⚠️ 임시 음성채널은 서버 채널 목록에서 확인할 수 있으며, 모든 인원이 퇴장하면 자동으로 삭제됩니다.",
                    color=0x5865F2
                )
                await interaction.followup.send(embed=embed, ephemeral=True)

        except discord.NotFound as e:
            if getattr(e, "code", None) == 10062:
                original = await interaction.channel.fetch_message(interaction.message.id)
                new_view = ThreadButtonView(self.recru_id)
                for item in new_view.children:
                    if item.custom_id == "create_voice":
                        item.disabled = False
                        item.label = "음성채널 생성"
                        item.style = discord.ButtonStyle.success
                        break
                await original.edit(view=new_view)
                await interaction.channel.send(
                    f"{interaction.user.mention} ⚠️ 상호작용이 만료되었습니다. 버튼을 갱신했으니 다시 클릭해 주세요.",
                    delete_after=2
                )
            else:
                logger.error(f"음성채널 처리 실패: {e}")
                await interaction.followup.send(f"❌ 음성채널 처리 중 오류가 발생했습니다: {e}", ephemeral=True)

        except Exception as e:
            logger.error(f"음성채널 처리 중 오류: {e}")
            await interaction.followup.send(
                f"❌ 음성채널 처리 중 오류가 발생했습니다: {e}", ephemeral=True
            )



# ─────────────────────────────────────────────
#               쓰레드 생성
# ─────────────────────────────────────────────
async def create_thread(interaction: discord.Interaction, time:int = 10080):
    
    with SessionLocal() as db:
        try:
            recru_id = interaction.message.embeds[0].footer.text
            recruitment_result = select_recruitment(db, recru_id)
            participants_list = select_participants(db, recru_id)
            
            if recruitment_result is None:
                await interaction_followup(interaction, "❌ 모집이 존재하지 않습니다.")
                return
            
            search_member = await interaction.guild.fetch_member(int(recruitment_result["create_user_id"]))
            if search_member is None:
                await interaction_followup(interaction, "❌ 모집자 정보를 찾을 수 없습니다.")
                return
            
            creater_name = search_member.display_name

            channel = interaction.guild.get_channel(int(recruitment_result["parents_thread_ch_id"]))
            if channel is None:
                await interaction_followup(interaction, "❌ 스레드 채널이 설정되지 않았습니다.")
                return

            try:
                thread = await channel.create_thread(
                    name=f"{creater_name}의 {recruitment_result['dungeon_type']} 파티",
                    type=discord.ChannelType.private_thread,
                    invitable=False,
                    auto_archive_duration=time,
                    reason="모집 스레드 생성"
                )
                
                # 모집자만 태그
                await thread.add_user(search_member)
                await thread.send(f"<@{recruitment_result['create_user_id']}>님 파티모집이 완료되었습니다.")

                # 임베드 생성
                embed = build_thread_embed(
                    dungeon_type=recruitment_result["dungeon_type"],
                    dungeon_name=recruitment_result["dungeon_name"],
                    difficulty=recruitment_result["dungeon_difficulty"],
                    detail=recruitment_result["recru_discript"],
                    status=recruitment_result["status"],
                    recru_id=recru_id,
                )

                # 스레드 버튼 생성
                thread_view = ThreadButtonView(recru_id=recru_id)
                
                await thread.send(embed=embed, view=thread_view)
                

                result = insert_complete_recruitment(
                    db,
                    recru_id=recru_id,
                    complete_thread_ch_id=thread.id
                )
                
                if not result:
                    logger.warning(f"스레드 생성 후 DB 업데이트 실패: {recru_id}, {result}")
                
                db.commit()

            except discord.Forbidden:
                logger.error("스레드 생성 실패 - 권한 부족")
                if not interaction.response.is_done():
                    await interaction.response.defer(ephemeral=True)
                await interaction_followup(interaction, "❌ 스레드 생성 권한이 없습니다.")
                return
        
            except discord.HTTPException as e:
                logger.error(f"스레드 생성 실패 - HTTP 오류: {e}")
                if not interaction.response.is_done():
                    await interaction.response.defer(ephemeral=True)
                await interaction_followup(interaction, f"❌ 스레드 생성 중 오류가 발생했습니다: {str(e)}")
                return
            
        except Exception as e:
            logger.error(f"스레드 생성 전역 오류: {e}")
            if not interaction.response.is_done():
                await interaction.response.defer(ephemeral=True)
            await interaction_followup(interaction, "❌ 스레드 생성 중 오류가 발생했습니다.")
            return