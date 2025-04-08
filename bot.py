import discord
from discord.ext import commands
from core.config import settings
import asyncio

intents = discord.Intents.default()
intents.message_content = True

class DonggleBot(commands.Bot):
    def __init__(self):
        # application_id가 None이면 해당 매개변수를 제외
        kwargs = {
            "command_prefix": "!",  # 기존 명령어도 유지
            "intents": intents,
        }
        
        # APPLICATION_ID가 있으면 추가
        if settings.APPLICATION_ID:
            kwargs["application_id"] = settings.APPLICATION_ID
        
        super().__init__(**kwargs)
        
    async def setup_hook(self):
        # 확장 기능 로드
        await self.load_extension("cogs.party")
        
        # 봇이 준비되면 자동으로 명령어 동기화
        try:
            await self.tree.sync()
            print("명령어 트리가 동기화되었습니다.")
        except Exception as e:
            print(f"명령어 트리 동기화 중 오류 발생: {e}")
            print("슬래시 명령어를 사용하려면 애플리케이션 ID가 필요합니다.")
            print("real.env 파일에 APPLICATION_ID=봇ID를 추가해주세요.")
        
    async def on_ready(self):
        print(f"{self.user} 접속 완료!")
        if settings.APPLICATION_ID:
            print(f"슬래시 명령어 사용 준비 완료!")
        else:
            print("슬래시 명령어를 사용하려면 애플리케이션 ID가 필요합니다.")
            print("real.env 파일에 APPLICATION_ID=봇ID를 추가해주세요.")

async def main():
    bot = DonggleBot()
    await bot.start(settings.DISCORD_TOKEN)

# 비동기 메인 함수 실행
if __name__ == "__main__":
    asyncio.run(main())
