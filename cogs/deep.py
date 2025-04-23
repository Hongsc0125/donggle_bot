import discord
from discord.ext import commands
import logging
from discord import app_commands
import asyncio

from db.session import SessionLocal
from core.utils import interaction_response, interaction_followup
from queries.channel_query import select_deep_channel
from queries.alert_query import add_deep_alert_user, select_deep_alert_users

logger = logging.getLogger(__name__)

class DeepLocationSelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(label="얼음협곡", value="얼음협곡", description="얼음협곡 심층 제보"),
            discord.SelectOption(label="여신의뜰", value="여신의뜰", description="여신의뜰 심층 제보")
        ]
        super().__init__(placeholder="심층 위치 선택", options=options)

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_modal(
            TimeInputModal(self.values[0])
        )

class DeepButtonView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)  # 시간 제한 없는 영구 버튼
        self.add_item(DeepLocationSelect())

class TimeInputModal(discord.ui.Modal, title="심층 제보"):
    def __init__(self, location):
        super().__init__()
        self.location = location
        
        self.time_input = discord.ui.TextInput(
            label=f"{location} 남은 시간(분)",
            placeholder="예: 30",
            required=True,
            min_length=1,
            max_length=3
        )
        self.add_item(self.time_input)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            # 입력 검증
            remaining_minutes = int(self.time_input.value)
            if remaining_minutes <= 0 or remaining_minutes > 999:
                await interaction_response(interaction, "남은 시간은 1~999 사이의 숫자로 입력해주세요.", ephemeral=True)
                return
                
            # 제보 정보 생성
            reporter_name = interaction.user.display_name
            location = self.location
            
            # 제보 임베드 생성
            embed = discord.Embed(
                title="심층 제보",
                description=f"**{reporter_name}님이 심층을 제보했습니다.**",
                color=discord.Color.dark_purple()
            )
            embed.add_field(name="위치", value=location, inline=True)
            embed.add_field(name="남은 시간", value=f"{remaining_minutes}분", inline=True)
            embed.set_footer(text=f"제보자: {reporter_name}")
            
            # 채널에 메시지 전송
            await interaction.response.send_message(embed=embed)
            
            # DM 전송 처리
            await self.send_notifications(interaction, location, remaining_minutes)
            
            # 버튼 메시지 초기화
            cog = interaction.client.get_cog("DeepCog")
            if cog:
                await cog.initialize_deep_button(interaction.channel.id)
                
        except ValueError:
            await interaction_response(interaction, "남은 시간은 숫자로 입력해주세요.", ephemeral=True)
        except Exception as e:
            logger.error(f"심층 제보 처리 중 오류: {str(e)}")
            await interaction_response(interaction, "제보 처리 중 오류가 발생했습니다.", ephemeral=True)

    async def send_notifications(self, interaction, location, remaining_minutes):
        with SessionLocal() as db:
            try:
                # deep_alert_user 테이블에서 등록된 사용자 조회
                users = select_deep_alert_users(db, interaction.guild.id)
                
                # DM 알림 내용 생성
                embed = discord.Embed(
                    title="심층 발견 알림",
                    description=f"**{interaction.user.display_name}님이 심층을 제보했습니다.**",
                    color=discord.Color.dark_purple()
                )
                embed.add_field(name="위치", value=location, inline=True)
                embed.add_field(name="남은 시간", value=f"{remaining_minutes}분", inline=True)
                embed.set_footer(text=f"서버: {interaction.guild.name}")
                
                # 각 사용자에게 DM 전송
                sent_count = 0
                for user_data in users:
                    try:
                        user = await interaction.client.fetch_user(int(user_data['user_id']))
                        if user and not user.bot:
                            await user.send(embed=embed)
                            sent_count += 1
                    except Exception as user_error:
                        logger.warning(f"사용자 {user_data['user_id']}에게 DM 전송 실패: {str(user_error)}")
                
                if sent_count > 0:
                    await interaction_followup(interaction, f"{sent_count}명의 사용자에게 심층 알림을 전송했습니다.", ephemeral=True)
                else:
                    await interaction_followup(interaction, "알림을 전송할 사용자가 없습니다.", ephemeral=True)
                    
            except Exception as e:
                logger.error(f"심층 알림 전송 중 오류: {str(e)}")
                await interaction_followup(interaction, "알림 전송 중 오류가 발생했습니다.", ephemeral=True)

class DeepCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_ready(self):
        """봇이 준비되면  초기화"""
        logger.info("심층 제보 시스템 초기화 중...")
        
        try:
            # 모든 길드의 심층 채널 초기화
            for guild in self.bot.guilds:
                with SessionLocal() as db:
                    try:
                        deep_channel_id = select_deep_channel(db, guild.id)
                        if deep_channel_id:
                            await self.initialize_deep_button(deep_channel_id)
                            logger.info(f"길드 {guild.id} 심층 채널 {deep_channel_id} 초기화 완료")
                        else:
                            logger.info(f"길드 {guild.id}에 설정된 심층 채널이 없습니다")
                    except Exception as e:
                        logger.error(f"길드 {guild.id}의 심층 채널 초기화 중 오류: {e}")
            
            logger.info("심층 제보 시스템 초기화 완료")
        except Exception as e:
            logger.error(f"심층 제보 시스템 초기화 중 오류: {e}")

    async def initialize_deep_button(self, channel_id):
        """심층 제보 버튼 초기화"""
        channel = self.bot.get_channel(int(channel_id))
        if not channel:
            logger.warning(f"심층 채널 {channel_id}를 찾을 수 없습니다.")
            return
        
        logger.info(f"심층 채널 {channel_id} 초기화 시작")
        view = DeepButtonView()

        instruction_embed = discord.Embed(
                title="**심층 정보를 공유해 주세요!**",
                description=(
                    "위치를 선택하고 남은 시간을 입력하면 심층 제보가 등록됩니다.\n\n"
                    "허위 제보 시 제재를 받을 수 있으니 주의해 주세요!"
                )
            color=discord.Color.dark_purple()
        )

        # 기존 버튼이 있는지 확인 후 삭제
        try:
            async for message in channel.history(limit=50, oldest_first=False):
                if (
                    message.author.id == self.bot.user.id and
                    message.components and
                    len(message.components) > 0 and
                    len(message.components[0].children) > 0 and
                    isinstance(message.components[0].children[0], discord.ui.SelectMenu)
                ):
                    # 기존 메시지 삭제
                    await message.delete()
                    logger.info(f"심층 채널 {channel_id}의 기존 버튼 메시지 삭제")
                    break
        except Exception as e:
            logger.warning(f"채널 {channel_id} 메시지 삭제 중 오류: {str(e)}")

        # 새 버튼 메시지 전송
        try:
            await channel.send(embed=instruction_embed, view=view)
            logger.info(f"심층 채널 {channel_id} 새 버튼 메시지 생성 완료")
        except Exception as e:
            logger.warning(f"심층 채널 {channel_id}에 버튼 메시지 전송 실패: {str(e)}")

    @app_commands.command(name="심층알림등록", description="심층 발견 시 DM을 받습니다")
    async def register_deep_alert(self, interaction: discord.Interaction):
        """심층 알림 등록 명령어"""
        await interaction.response.defer(ephemeral=True)
        
        with SessionLocal() as db:
            try:
                # 사용자 정보 등록
                result = add_deep_alert_user(
                    db, 
                    interaction.user.id, 
                    interaction.guild.id,
                    interaction.user.display_name
                )
                
                if result:
                    db.commit()
                    await interaction_followup(interaction, "심층 알림이 등록되었습니다. 심층 제보가 있을 때 DM으로 알림을 받습니다.")
                else:
                    await interaction_followup(interaction, "심층 알림 등록에 실패했습니다.")
            except Exception as e:
                logger.error(f"심층 알림 등록 중 오류: {str(e)}")
                db.rollback()
                await interaction_followup(interaction, f"심층 알림 등록 중 오류가 발생했습니다: {str(e)}")

# Cog 등록
async def setup(bot):
    await bot.add_cog(DeepCog(bot))
