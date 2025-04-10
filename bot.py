import discord
from discord.ext import commands, tasks
from core.config import settings
import asyncio
import logging
import datetime
import sys
import traceback
import random

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("bot.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger('donggle_bot')

intents = discord.Intents.default()
intents.message_content = True

class DonggleBot(commands.Bot):
    def __init__(self):
        # application_id가 None이면 해당 매개변수를 제외
        kwargs = {
            "command_prefix": "!",  # 기존 명령어도 유지
            "intents": intents,
            "reconnect": True,  # 연결이 끊기면 자동으로 재연결 시도 활성화
        }
        
        # APPLICATION_ID가 있으면 추가
        if settings.APPLICATION_ID:
            kwargs["application_id"] = settings.APPLICATION_ID
        
        super().__init__(**kwargs)
        
        # 마지막 연결 시간 저장
        self.last_reconnect = datetime.datetime.now()
        self.reconnect_attempts = 0
        
        # 하트비트 및 활동 표시 작업 추가
        self.heartbeat_logger.start()
        self.update_presence.start()
        self.check_connection.start()
        
    async def setup_hook(self):
        # 확장 기능 로드
        extensions = [
            "cogs.party",
            "cogs.auth"  # 새로운 권한 관리 코그 추가
        ]
        
        # 모든 확장 기능 로드
        for extension in extensions:
            try:
                await self.load_extension(extension)
                logger.info(f"확장 기능 로드 완료: {extension}")
            except Exception as e:
                logger.error(f"확장 기능 로드 실패: {extension} - {e}")
                logger.error(traceback.format_exc())
        
        # 봇이 준비되면 자동으로 명령어 동기화
        try:
            # 모든 코그가 로드된 후 명령어 동기화
            synced_commands = await self.tree.sync()
            logger.info(f"명령어 트리가 동기화되었습니다. {len(synced_commands)}개 명령어 등록됨.")
        except Exception as e:
            logger.error(f"명령어 트리 동기화 중 오류 발생: {e}")
            logger.warning("슬래시 명령어를 사용하려면 애플리케이션 ID가 필요합니다.")
            logger.warning("real.env 파일에 APPLICATION_ID=봇ID를 추가해주세요.")
        
    async def on_ready(self):
        self.reconnect_attempts = 0
        self.last_reconnect = datetime.datetime.now()
        logger.info(f"{self.user} 접속 완료!")
        
        if settings.APPLICATION_ID:
            logger.info(f"슬래시 명령어 사용 준비 완료!")
        else:
            logger.warning("슬래시 명령어를 사용하려면 애플리케이션 ID가 필요합니다.")
            logger.warning("real.env 파일에 APPLICATION_ID=봇ID를 추가해주세요.")
    
    async def on_disconnect(self):
        """연결이 끊어졌을 때 호출됩니다."""
        logger.warning("디스코드와의 연결이 끊어졌습니다. 재연결 시도 중...")
        self.reconnect_attempts += 1
    
    async def on_resumed(self):
        """재연결 후에 호출됩니다."""
        logger.info(f"디스코드에 성공적으로 재연결했습니다. (시도 횟수: {self.reconnect_attempts}번)")
        self.reconnect_attempts = 0
        self.last_reconnect = datetime.datetime.now()
    
    async def on_error(self, event_method, *args, **kwargs):
        """오류 발생 시 처리합니다."""
        exc_type, exc_value, exc_traceback = sys.exc_info()
        error_details = ''.join(traceback.format_exception(exc_type, exc_value, exc_traceback))
        logger.error(f"이벤트 처리 중 오류 발생 - {event_method}: {error_details}")
    
    @tasks.loop(minutes=30)
    async def heartbeat_logger(self):
        """30분마다 하트비트 로그를 기록합니다."""
        now = datetime.datetime.now()
        uptime = now - self.last_reconnect
        guild_count = len(self.guilds)
        
        logger.info(f"하트비트: 활성 상태 | 서버 수: {guild_count} | 업타임: {uptime}")
        
        # 서버별로 채널 상태 확인
        for guild in self.guilds:
            try:
                party_cog = self.get_cog('PartyCog')
                if party_cog:
                    guild_id = str(guild.id)
                    # 등록 채널과 공고 채널 ID 확인
                    reg_channel_id = party_cog.registration_channels.get(guild_id)
                    ann_channel_id = party_cog.announcement_channels.get(guild_id)
                    logger.info(f"서버 {guild.name}(ID: {guild_id}) - 등록 채널: {reg_channel_id}, 공고 채널: {ann_channel_id}")
            except Exception as e:
                logger.error(f"서버 {guild.id} 상태 확인 중 오류: {str(e)}")
    
    @tasks.loop(minutes=60)
    async def check_connection(self):
        """1시간마다 연결 상태를 확인하고 필요하면 채널을 재초기화합니다."""
        try:
            # 연결 상태 확인
            if not self.is_ready():
                logger.warning("봇이 준비되지 않았습니다. 재연결이 필요할 수 있습니다.")
                return
            
            # 채널 초기화
            party_cog = self.get_cog('PartyCog')
            if party_cog:
                logger.info("채널 상태 확인 및 초기화 시작...")
                await party_cog.initialize_channels()
                logger.info("채널 초기화 완료")
        except Exception as e:
            logger.error(f"연결 상태 확인 중 오류 발생: {str(e)}")
    
    @tasks.loop(minutes=10)
    async def update_presence(self):
        """10분마다 봇 상태를 업데이트합니다."""
        try:
            if self.is_ready():
                status_options = [
                    "파티 모집 중",
                    "던전 탐험 중",
                    "레이드 준비 중",
                    "모험자 모집 중"
                ]
                
                activity_type = random.choice([
                    discord.ActivityType.playing,
                    discord.ActivityType.watching,
                    discord.ActivityType.listening
                ])
                
                status_text = random.choice(status_options)
                activity = discord.Activity(type=activity_type, name=status_text)
                
                await self.change_presence(activity=activity)
                logger.info(f"봇 상태 업데이트: {activity_type.name} {status_text}")
        except Exception as e:
            logger.error(f"상태 업데이트 중 오류 발생: {str(e)}")
    
    # 봇이 준비된 후에 작업 시작
    @heartbeat_logger.before_loop
    @update_presence.before_loop
    @check_connection.before_loop
    async def before_tasks(self):
        await self.wait_until_ready()

async def main():
    try:
        bot = DonggleBot()
        await bot.start(settings.DISCORD_TOKEN)
    except discord.LoginFailure:
        logger.critical("봇 토큰이 올바르지 않습니다. real.env 파일을 확인하세요.")
    except Exception as e:
        logger.critical(f"봇 실행 중 심각한 오류 발생: {str(e)}")
        traceback.print_exc()

# 비동기 메인 함수 실행
if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("키보드 인터럽트로 봇 종료")
    except Exception as e:
        logger.critical(f"예상치 못한 오류로 봇 종료: {str(e)}")
        traceback.print_exc()
