import discord
from discord.ext import commands
from discord import app_commands
import logging

from db.session import SessionLocal
from queries.channel_query import get_pair_channel, insert_pair_channel, insert_guild_auth, select_guild_auth
from queries.recruitment_query import select_recruitment_channel, select_dungeon
logger = logging.getLogger(__name__)

class RecruitmentCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_ready(self):
        # 봇이 준비되면 등록 채널에 버튼 메시지 전송
        db = SessionLocal()
        # 등록된 모든 등록채널 조회
        regist_channel_ids = select_recruitment_channel(db)
        db.close()
        for row in regist_channel_ids:
            channel_id = int(row[0])
            channel = self.bot.get_channel(channel_id)
            if channel:
                view = RecruitmentButtonView()
                # 이미 메시지가 있는지 확인
                last_message = None
                try:
                    async for message in channel.history(limit=50, oldest_first=False):
                        if (
                            message.author.id == self.bot.user.id and
                            message.components and
                            any(
                                any(
                                    hasattr(child, "custom_id") and child.custom_id == "recruitment_register"
                                    for child in (component.children if hasattr(component, "children") else [])
                                )
                                for component in message.components
                            )
                        ):
                            last_message = message
                            break
                except Exception as e:
                    logger.warning(f"채널 {channel_id} 메시지 조회 실패: {str(e)}")

                if last_message:
                    # last_message만 남기고 채널의 모든 메시지 삭제
                    try:
                        async for message in channel.history(limit=50, oldest_first=False):
                            if message.id != last_message.id:
                                try:
                                    await message.delete()
                                except Exception as e:
                                    logger.warning(f"메시지 삭제 실패: {str(e)}")
                        # 기존 메시지의 view만 갱신
                        await last_message.edit(view=view)
                    except Exception as e:
                        logger.warning(f"등록 채널 {channel_id} 버튼 갱신/정리 실패: {str(e)}")
                else:
                    # 모든 메시지 삭제 후 새 버튼 메시지 전송
                    try:
                        async for message in channel.history(limit=50, oldest_first=False):
                            try:
                                await message.delete()
                            except Exception as e:
                                logger.warning(f"메시지 삭제 실패: {str(e)}")
                        await channel.send(
                            view=view
                        )
                    except Exception as e:
                        logger.warning(f"등록 채널 {channel_id}에 버튼 메시지 전송 실패: {str(e)}")

class RecruitmentButtonView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="파티 모집 등록", style=discord.ButtonStyle.primary, custom_id="recruitment_register")
    async def register_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        db = SessionLocal()
        dungeon_rows = select_dungeon(db)
        db.close()

        dungeon_types = sorted(set(row[0] for row in dungeon_rows))

        # Select 컴포넌트 정의
        class DungeonTypeSelect(discord.ui.Select):
            def __init__(self, dungeon_rows):
                options = [discord.SelectOption(label=dt, value=dt) for dt in dungeon_types]
                super().__init__(placeholder="던전 타입 선택", options=options, custom_id="dungeon_type_select")
                self.dungeon_rows = dungeon_rows

            async def callback(self, interaction: discord.Interaction):
                selected_type = self.values[0]
                dungeon_names = sorted(set(
                    row[1] for row in self.dungeon_rows if row[0] == selected_type
                ))

                class DungeonNameSelect(discord.ui.Select):
                    def __init__(self, dungeon_rows, selected_type):
                        options = [discord.SelectOption(label=dn, value=dn) for dn in dungeon_names]
                        super().__init__(placeholder="던전 이름 선택", options=options, custom_id="dungeon_name_select")
                        self.dungeon_rows = dungeon_rows
                        self.selected_type = selected_type

                    async def callback(self, interaction: discord.Interaction):
                        selected_name = self.values[0]
                        dungeon_difficulties = sorted(set(
                            row[2] for row in self.dungeon_rows if row[0] == self.selected_type and row[1] == selected_name
                        ))

                        class DifficultySelect(discord.ui.Select):
                            def __init__(self, selected_type, selected_name):
                                options = [discord.SelectOption(label=diff, value=diff) for diff in dungeon_difficulties]
                                super().__init__(placeholder="난이도 선택", options=options, custom_id="difficulty_select")
                                self.selected_type = selected_type
                                self.selected_name = selected_name

                            async def callback(self, interaction: discord.Interaction):
                                selected_diff = self.values[0]
                                embed = discord.Embed(
                                    title="파티 모집 정보",
                                    description=(
                                        f"던전타입: {self.selected_type}\n"
                                        f"던전이름: {self.selected_name}\n"
                                        f"난이도: {selected_diff}\n"
                                        f"추가 정보를 입력하려면 별도 기능을 이용하세요."
                                    ),
                                    color=discord.Color.green()
                                )
                                await interaction.response.send_message(embed=embed, ephemeral=True)

                        view = discord.ui.View(timeout=180)
                        view.add_item(DifficultySelect(self.selected_type, selected_name))
                        await interaction.response.send_message(
                            embed=discord.Embed(
                                title="난이도 선택",
                                description=f"던전 타입: {self.selected_type}\n던전 이름: {selected_name}\n난이도를 선택하세요.",
                                color=discord.Color.blue()
                            ),
                            view=view,
                            ephemeral=True
                        )

                view = discord.ui.View(timeout=180)
                view.add_item(DungeonNameSelect(self.dungeon_rows, selected_type))
                await interaction.response.send_message(
                    embed=discord.Embed(
                        title="던전 이름 선택",
                        description=f"던전 타입: {selected_type}\n던전 이름을 선택하세요.",
                        color=discord.Color.blue()
                    ),
                    view=view,
                    ephemeral=True
                )

        view = discord.ui.View(timeout=180)
        view.add_item(DungeonTypeSelect(dungeon_rows))
        await interaction.response.send_message(
            embed=discord.Embed(
                title="던전 타입 선택",
                description="던전 타입을 선택하세요.",
                color=discord.Color.blue()
            ),
            view=view,
            ephemeral=True
        )

    async def on_error(self, interaction: discord.Interaction, error: Exception):
        await interaction.response.send_message("모집 등록 중 오류가 발생했습니다.", ephemeral=True)

# Cog를 등록하는 설정 함수
async def setup(bot):
    await bot.add_cog(RecruitmentCog(bot))

