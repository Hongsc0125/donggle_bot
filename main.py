import logging
import asyncio
import traceback

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
        kwargs = {
            "command_prefix": commands.when_mentioned,  # 프리픽스 명령어 비활성화
            "intents": intents,
            "application_id": settings.APPLICATION_ID,
        }
        super().__init__(**kwargs)
        self.check_channel_status.start()  # 루프 시작

    async def setup_hook(self):
        extensions = [
            "cogs.channel",
            "cogs.recruitment"
        ]
        for ext in extensions:
            try:
                await self.load_extension(ext)
                logger.info(f"Loaded extension: {ext}")
            except Exception as e:
                logger.error(f"Failed to load extension {ext}: {e}")
        # 봇이 준비되면 자동으로 명령어 동기화
        try:
            synced_commands = await self.tree.sync()

            # 테스트길드 바로 동기화
            await self.tree.sync(guild=discord.Object(id=1359677298604900462))

            logger.info(f"명령어 트리가 동기화되었습니다. {len(synced_commands)}개 명령어 등록됨.")

            # 명령어 목록 로그 출력
            # if synced_commands:
            #     logger.info("등록된 명령어 목록:")
            #     for cmd in synced_commands:
            #         logger.info(f"- {cmd.name}: {cmd.description}")
            # else:
            #     logger.info("등록된 명령어가 없습니다.")

        except Exception as e:
            logger.error(f"명령어 트리 동기화 중 오류 발생: {e}")

    @tasks.loop(minutes=10)
    async def check_channel_status(self):
        recruitment_cog = self.get_cog("RecruitmentCog")
        if recruitment_cog:
            await recruitment_cog.on_ready()


async def main():
    try:
        # 봇 인스턴스 생성
        bot = Donggle()
        # 봇 실행
        await bot.start(settings.DISCORD_TOKEN)
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