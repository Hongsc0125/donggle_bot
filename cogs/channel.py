import discord
from discord.ext import commands
from discord import app_commands
import logging
from datetime import datetime
import traceback  # Add this import

from db.session import SessionLocal
from core.utils import interaction_response, interaction_followup
from queries.channel_query import (
    get_pair_channel, insert_pair_channel, insert_guild_auth,
    select_guild_auth, select_super_user, update_thread_channel,
    update_voice_channel, update_alert_channel, insert_deep_pair
)
# from cogs.deep import initialize_deep_button

logger = logging.getLogger(__name__)


def is_super_user():
    def predicate(interaction: discord.Interaction) -> bool:
        """봇 운영자 확인 함수"""
        with SessionLocal() as db:
            try:
                super_user_list = select_super_user(db)
                if interaction.user.id in super_user_list:
                    return True
                return False
            except Exception as e:
                logger.error(f"봇 운영자 확인 중 오류 발생: {str(e)}")
                return False

    return app_commands.check(predicate)


class ChannelCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @is_super_user()
    @app_commands.command(name="채널설정", description="등록, 리스트 채널을 설정하고 연결합니다.")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(
        등록채널="등록채널을 선택",
        리스트채널="파티모집 리스트가 나올 채널을 선택"
    )
    async def pair_channels(
            self,
            interaction: discord.Interaction,
            등록채널: discord.TextChannel,
            리스트채널: discord.TextChannel
    ):
        await interaction.response.defer(ephemeral=True)

        # db = SessionLocal()
        with SessionLocal() as db:
            try:
                existing_pair = get_pair_channel(
                    db, interaction.guild.id, 등록채널.id, 리스트채널.id
                )
                if existing_pair:
                    await interaction_followup(interaction,
                        f"이미 설정된 채널입니다.\n"
                        f"등록 채널: {등록채널.mention}\n"
                        f"리스트 채널: {리스트채널.mention}"
                    )
                    return

                new_pair = insert_pair_channel(
                    db, interaction.guild.id, 등록채널.id, 리스트채널.id
                )
                db.commit()

                await interaction_followup(interaction, f"등록채널 {등록채널.mention}, 리스트채널 {리스트채널.mention} 설정완료.")

            except Exception as e:
                logger.error(f"채널 페어링 중 오류 발생: {str(e)}")
                await interaction_followup(interaction, f"채널 설정 중 오류가 발생했습니다: {str(e)}")

    @is_super_user()
    @app_commands.command(name="길드인증", description="길드를 인증합니다.")
    @app_commands.describe(
        유효기간="길드등록 유효기간 입력 (예: 20251231)",
    )
    async def auth_guild(
        self,
        interaction: discord.Interaction,
        유효기간: str
    ):
        await interaction.response.defer(ephemeral=True)
        
        # 봇 운영자 확인
        # if not self.is_bot_owner(interaction.user.id):
        #     await interaction.followup.send(
        #         "이 명령어는 봇운영자만 사용할 수 있습니다.",
        #         ephemeral=True
        #     )
        #     return
        with SessionLocal() as db:
            try:
                if not 유효기간:
                    await interaction_followup(interaction, "유효기간을 입력해주세요.")
                    return
                
                # 유효기간 형식 체크
                try:
                    expire_dt = datetime.strptime(유효기간, "%Y%m%d")
                except ValueError:
                    await interaction_followup(interaction, "❌ 유효기간은 `YYYYMMDD` 형식으로 입력해주세요.")
                    return
                
                # --- select_guild_auth로 기존 만료일 체크 ---
                existing_count = select_guild_auth(db, interaction.guild.id, expire_dt)
                if existing_count and existing_count[0] > 0:
                    await interaction_followup(interaction, "이미 등록된 길드입니다.")
                    return

                result = insert_guild_auth(
                    db,
                    interaction.guild.id,
                    interaction.guild.name,
                    expire_dt
                )
                db.commit()

                if result:
                    await interaction_followup(interaction, "길드 인증이 완료되었습니다.")
                else:
                    await interaction_followup(interaction, "길드 인증에 실패했습니다.")
            except Exception as e:
                logger.error(f"길드 인증 중 오류 발생: {str(e)}")
                await interaction_followup(interaction, f"길드 인증 중 오류가 발생했습니다: {str(e)}")

    @auth_guild.error
    async def auth_guild_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        """길드 인증 중 오류 처리"""
        if isinstance(error, app_commands.errors.MissingPermissions):
            await interaction_response(interaction, "이 명령어는 봇 운영자만 사용할 수 있습니다.")
        else:
            logger.error(f"길드 인증 중 오류: {error}")
            await interaction_response(interaction, "명령어 실행 중 오류가 발생했습니다.")

    @is_super_user()
    @app_commands.command(name="스레드채널설정", description="파티 모집 완료 시 비밀 쓰레드가 생성될 채널을 설정합니다.")
    # @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(
        channel="비밀 쓰레드가 생성될 채널을 선택"
    )
    async def set_thread_channel(
            self,
            interaction: discord.Interaction,
            channel: discord.TextChannel
    ):
        await interaction.response.defer(ephemeral=True)
        with SessionLocal() as db:
            try:
                update_result = update_thread_channel(
                    db, interaction.guild.id, channel.id
                )

                if not update_result:
                    await interaction_followup(interaction, "채널 설정에 실패했습니다.")
                    return

                db.commit()
                await interaction_followup(interaction, f"비밀 쓰레드 채널 {channel.mention} 설정완료.")

            except Exception as e:
                logger.error(f"스레드 채널 설정 중 오류 발생: {str(e)}")
                await interaction_followup(interaction, f"채널 설정 중 오류가 발생했습니다: {str(e)}")

    @set_thread_channel.error
    async def thread_channel_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        """쓰레드 채널 설정 중 오류 처리"""
        if isinstance(error, app_commands.errors.MissingPermissions):
            await interaction_response(interaction, "이 명령어는 관리자만 사용할 수 있습니다.")
        else:
            logger.error(f"쓰레드 채널 설정 중 오류: {error}")
            await interaction_response(interaction, "명령어 실행 중 오류가 발생했습니다.")

    @app_commands.command(name="음성채널설정", description="음성채널 버튼 클릭 시 입장할 음성채널을 설정합니다.")
    # @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(
        channel="입장할 음성채널을 선택"
    )
    async def set_voice_channel(
            self,
            interaction: discord.Interaction,
            channel: discord.VoiceChannel
    ):
        await interaction.response.defer(ephemeral=True)
        with SessionLocal() as db:
            try:
                update_result = update_voice_channel(
                    db, interaction.guild.id, channel.id
                )

                if not update_result:
                    await interaction_followup(interaction, "음성채널 설정에 실패했습니다.")
                    return

                db.commit()
                await interaction_followup(interaction, f"음성채널 {channel.mention} 설정완료.")

            except Exception as e:
                logger.error(f"음성채널 설정 중 오류 발생: {str(e)}")
                await interaction_followup(interaction, f"음성채널 설정 중 오류가 발생했습니다: {str(e)}")

    @set_voice_channel.error
    async def voice_channel_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        """음성채널 설정 중 오류 처리"""
        if isinstance(error, app_commands.errors.MissingPermissions):
            await interaction_response(interaction, "이 명령어는 관리자만 사용할 수 있습니다.")
        else:
            logger.error(f"음성채널 설정 중 오류: {error}")
            await interaction_response(interaction, "명령어 실행 중 오류가 발생했습니다.")

    @is_super_user()
    @app_commands.command(name="알림채널설정", description="알림 기능을 사용할 채널을 설정합니다.")
    # @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(
        channel="알림 채널을 선택"
    )
    async def set_alert_channel(
            self,
            interaction: discord.Interaction,
            channel: discord.TextChannel
    ):
        await interaction.response.defer(ephemeral=True)
        with SessionLocal() as db:
            try:
                update_result = update_alert_channel(
                    db, interaction.guild.id, channel.id
                )

                if not update_result:
                    await interaction_followup(interaction, "알림 채널 설정에 실패했습니다.")
                    return

                db.commit()
                
                # 알림 Cog 가져오기
                alert_cog = self.bot.get_cog("AlertCog")
                if alert_cog:
                    # 알림 채널 초기화
                    await alert_cog.initialize_alert_channel(channel.id)
                
                await interaction_followup(interaction, f"알림 채널 {channel.mention} 설정완료.")

            except Exception as e:
                logger.error(f"알림 채널 설정 중 오류 발생: {str(e)}")
                await interaction_followup(interaction, f"알림 채널 설정 중 오류가 발생했습니다: {str(e)}")

    @set_alert_channel.error
    async def alert_channel_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        """알림 채널 설정 중 오류 처리"""
        if isinstance(error, app_commands.errors.MissingPermissions):
            await interaction_response(interaction, "이 명령어는 관리자만 사용할 수 있습니다.")
        else:
            logger.error(f"알림 채널 설정 중 오류: {error}")
            await interaction_response(interaction, "명령어 실행 중 오류가 발생했습니다.")

    @is_super_user()
    @app_commands.command(name="심층채널", description="심층 컨텐츠를 위한 텍스트 채널을 설정합니다.")
    @app_commands.describe(
        channel="심층 제보용 텍스트 채널을 선택",
        auth="권한 그룹명 입력"
    ) 
    async def set_deep_channel(
            self,
            interaction: discord.Interaction,
            channel: discord.TextChannel,
            auth: str
    ):
        logger.info(f"심층채널 명령어 실행: 사용자 {interaction.user.id}, 채널 {channel.id}, 권한 {auth}")
        
        try:
            await interaction.response.defer(ephemeral=True)
            logger.info("응답 대기 상태로 전환됨")
            
            with SessionLocal() as db:
                try:
                    # 권한 그룹명 유효성 검사
                    if not auth or len(auth.strip()) == 0:
                        logger.warning(f"권한 그룹명이 비어있음: '{auth}'")
                        await interaction_followup(interaction, "❌ 권한 그룹명을 입력해주세요.")
                        return
                    
                    auth = auth.strip()  # 공백 제거
                    logger.info(f"권한 그룹명 정제: '{auth}'")
                    
                    # 심층 채널과 권한 매핑 등록
                    logger.info(f"insert_deep_pair 함수 호출 전: guild_id={interaction.guild.id}, channel_id={channel.id}, auth={auth}")
                    insert_result = insert_deep_pair(
                        db, interaction.guild.id, channel.id, auth
                    )
                    logger.info(f"insert_deep_pair 결과: {insert_result}")
        
                    if not insert_result:
                        logger.error("심층 채널 설정 실패")
                        await interaction_followup(interaction, "❌ 심층 채널 설정에 실패했습니다.")
                        return
        
                    db.commit()
                    logger.info("데이터베이스 변경사항 커밋됨")
                    
                    # Deep Cog에서 초기화
                    deep_cog = self.bot.get_cog("DeepCog")
                    if deep_cog:
                        logger.info(f"DeepCog 찾음: {deep_cog}")
                        await deep_cog.initialize_deep_button(channel.id, auth)
                        logger.info(f"채널 초기화 완료: {channel.id}")
                    else:
                        logger.error("DeepCog를 찾을 수 없음")
                        
                    await interaction_followup(interaction, f"✅ 심층 채널 {channel.mention} 설정완료 (권한 그룹: {auth}).")
                    logger.info(f"심층채널 명령어 처리 완료: 채널 {channel.id}, 권한 {auth}")
                    
                except Exception as e:
                    logger.error(f"심층 채널 설정 중 오류 발생: {str(e)}")
                    logger.error(f"오류 세부정보: {traceback.format_exc()}")
                    await interaction_followup(interaction, f"❌ 심층 채널 설정 중 오류가 발생했습니다: {str(e)}")
                    db.rollback()
        except Exception as outer_e:
            logger.error(f"심층채널 명령어 처리 중 예외 발생: {str(outer_e)}")
            logger.error(f"오류 세부정보: {traceback.format_exc()}")
            if not interaction.response.is_done():
                await interaction.response.send_message("❌ 명령어 처리 중 오류가 발생했습니다.", ephemeral=True)
            else:
                await interaction.followup.send("❌ 명령어 처리 중 오류가 발생했습니다.", ephemeral=True)
    
    @set_deep_channel.error
    async def deep_channel_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        """심층 채널 설정 중 오류 처리"""
        if isinstance(error, app_commands.errors.CheckFailure):
            await interaction_response(interaction, "이 명령어는 봇 운영자만 사용할 수 있습니다.")
        else:
            logger.error(f"심층 채널 설정 중 오류: {error}")
            await interaction_response(interaction, "명령어 실행 중 오류가 발생했습니다.")
    

# ───────────────────────────────────────────────
# Cog를 등록하는 설정 함수
# ───────────────────────────────────────────────
async def setup(bot):
    await bot.add_cog(ChannelCog(bot))

