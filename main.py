import logging
import asyncio
import traceback
import time
from datetime import datetime, timedelta

import discord
from discord.ext import commands, tasks
from core.config import settings

# 로깅 기본 설정 추가
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)

# SQLAlchemy 엔진 로거 중복 방지
logging.getLogger("sqlalchemy.engine").propagate = False

logger = logging.getLogger("donggle")

# intents 설정 = 전체
intents = discord.Intents.all()

class Donggle(commands.Bot):
    def __init__(self):
        logger.info("Donggle Bot 시작")

        # 환경 변수들 체크
        logger.info("--------------------------------------------------------------------------------------------------------")
        logger.info(f"DB URL: {settings.DATABASE_URL}")
        logger.info(f"DB USER: {settings.DB_USER}")
        logger.info(f"DB NAME: {settings.DATABASE_NAME}")
        logger.info(f"DB PW: {settings.DB_PW}")
        logger.info(f"DISCORD_TOKEN: {settings.DISCORD_TOKEN}")
        logger.info(f"APPLICATION_ID: {settings.APPLICATION_ID}")
        logger.info(f"PUBLIC_KEY: {settings.PUBLIC_KEY}")
        logger.info(f"OPENAI_API_KEY: {settings.OPENAI_API_KEY}")
        logger.info(f"DEEPSEEK_API_KEY: {settings.DEEPSEEK_API_KEY}")
        logger.info(f"RANK_API_URL: {settings.RANK_API_URL}")
        logger.info(f"ENV: {settings.ENV}")
        logger.info("--------------------------------------------------------------------------------------------------------")


        kwargs = {
            "command_prefix": commands.when_mentioned,  # 프리픽스 명령어 비활성화
            "intents": intents,
            "application_id": settings.APPLICATION_ID,
        }
        super().__init__(**kwargs)
        self.check_channel_status.start()  # 루프 시작
        self.last_heartbeat = datetime.now()
        self.connection_monitor.start()  # 연결 모니터링 시작

    async def setup_hook(self):
        extensions = [
            "cogs.channel",
            "cogs.recruitment",
            "cogs.voice_channel",
            # "cogs.deep",
            "cogs.alert",
            "cogs.chat_assistant",
            # "cogs.rank"
        ]
        for ext in extensions:
            try:
                await self.load_extension(ext)
                logger.info(f"Loaded extension: {ext}")
            except Exception as e:
                logger.error(f"Failed to load extension {ext}: {e}")
        
        # 영구 뷰 등록 (custom_id를 통한 버튼 지속성 보장)
        try:
            from views.recruitment_views.regist_templete import RecruitmentButtonView
            from cogs.alert import AlertRegisterButton
            
            self.add_view(RecruitmentButtonView())
            self.add_view(AlertRegisterButton())
            logger.info("영구 뷰 등록 완료 (RecruitmentButtonView, AlertRegisterButton)")
        except Exception as e:
            logger.error(f"영구 뷰 등록 실패: {e}")
        
        # 봇이 준비되면 자동으로 명령어 동기화
        try:
            # 전역 명령어 동기화 실패 시 개별 길드 동기화로 폴백
            try:
                synced_commands = await self.tree.sync()
                logger.info(f"전역 명령어 트리가 동기화되었습니다. {len(synced_commands)}개 명령어 등록됨.")
            except Exception as e:
                logger.warning(f"전역 명령어 동기화 실패: {e}")
                # 현재 참여 중인 모든 길드에 개별적으로 명령어 등록
                for guild in self.guilds:
                    try:
                        guild_cmds = await self.tree.sync(guild=discord.Object(id=guild.id))
                        logger.info(f"길드 {guild.name} ({guild.id})에 {len(guild_cmds)}개 명령어 등록됨.")
                    except Exception as guild_e:
                        logger.warning(f"길드 {guild.id} 명령어 동기화 실패: {guild_e}")
        except Exception as e:
            logger.error(f"명령어 트리 동기화 중 오류 발생: {e}")

    @tasks.loop(minutes=2)
    async def check_channel_status(self):
        recruitment_cog = self.get_cog("RecruitmentCog")
        if recruitment_cog:
            await recruitment_cog.on_ready()
        
        alert_cog = self.get_cog("AlertCog")
        if alert_cog:
            await alert_cog.on_ready()

    @tasks.loop(seconds=30)
    async def connection_monitor(self):
        """디스코드 연결 상태를 모니터링하고 필요시 재연결"""
        try:
            # 현재 웹소켓 상태 확인
            if self.is_closed():
                logger.warning("웹소켓 연결이 닫혀있음. 재연결 시도...")
                await self.reconnect()
                return

            # 마지막 하트비트가 90초 이상 지났는지 확인
            if datetime.now() - self.last_heartbeat > timedelta(seconds=90):
                logger.warning("하트비트 타임아웃 감지. 재연결 시도...")
                await self.reconnect()
                return
                
            # 연결 상태 로깅
            latency = self.latency * 1000  # ms로 변환
            if latency > 500:  # 지연시간이 500ms 이상이면 경고
                logger.warning(f"높은 지연시간 감지: {latency:.2f}ms")
            else:
                logger.debug(f"현재 지연시간: {latency:.2f}ms")
                
            # 하트비트 전송
            self.last_heartbeat = datetime.now()
            logger.debug(f"하트비트 전송: {self.last_heartbeat}")
            
        except Exception as e:
            logger.error(f"연결 모니터링 중 오류 발생: {e}")

    @connection_monitor.before_loop
    async def before_connection_monitor(self):
        """연결 모니터링 시작 전 봇 준비 대기"""
        await self.wait_until_ready()

    async def reconnect(self):
        """디스코드 연결 재시도"""
        try:
            logger.info("디스코드 재연결 시도 중...")
            # 기존 연결 종료
            if not self.is_closed():
                await self.close()
            
            # 잠시 대기 후 재연결
            await asyncio.sleep(5)
            
            # 재연결
            await self.login(settings.DISCORD_TOKEN)
            await self.connect(reconnect=True)
            
            logger.info("디스코드 재연결 성공")
            self.last_heartbeat = datetime.now()
            
            # 재연결 후 잠시 대기 후 채널 상태 새로고침
            await asyncio.sleep(3)
            await self.refresh_all_channels()
        except Exception as e:
            logger.error(f"재연결 시도 중 오류 발생: {e}")

    async def on_resumed(self):
        """세션이 재개되었을 때 호출되는 이벤트"""
        logger.info("디스코드 세션이 재개되었습니다.")
        self.last_heartbeat = datetime.now()
        
        # 세션 재개시 버튼 상태 재초기화
        await self.refresh_all_channels()

    async def on_connect(self):
        """봇이 디스코드에 연결되었을 때 호출되는 이벤트"""
        logger.info("디스코드에 연결되었습니다.")
        self.last_heartbeat = datetime.now()

    async def on_disconnect(self):
        """봇이 디스코드와 연결이 끊겼을 때 호출되는 이벤트"""
        logger.warning("디스코드와 연결이 끊겼습니다. 자동 재연결을 시도합니다.")

    async def refresh_all_channels(self):
        """모든 채널의 버튼 상태를 새로고침"""
        try:
            recruitment_cog = self.get_cog("RecruitmentCog")
            if recruitment_cog:
                await recruitment_cog.on_ready()
            
            alert_cog = self.get_cog("AlertCog")
            if alert_cog:
                await alert_cog.on_ready()
                
            logger.info("모든 채널 버튼 상태 새로고침 완료")
        except Exception as e:
            logger.error(f"채널 버튼 새로고침 중 오류: {e}")


async def main():
    try:
        # 봇 인스턴스 생성
        bot = Donggle()
        # 봇 실행
        await bot.start(settings.DISCORD_TOKEN)
    except discord.errors.LoginFailure as e:
        logger.critical(f"디스코드 로그인 실패: {e}")
    except discord.errors.ConnectionClosed as e:
        logger.error(f"디스코드 연결 종료: {e}")
    except Exception as e:
        logger.error(f"봇 실행 중 오류 발생: {e}")


# 비동기 메인 함수 실행
if __name__ == "__main__":
    try:
        logger.info("봇 실행 준비 중...")
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("키보드 인터럽트로 봇 종료")
    except Exception as e:
        logger.critical(f"예상치 못한 오류로 봇 종료: {str(e)}")
        traceback.print_exc()