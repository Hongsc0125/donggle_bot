import logging
import asyncio
import traceback
import time
from datetime import datetime, timedelta
import functools
from typing import List, Dict, Any, Optional, Callable, Coroutine, Union

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

# 작업 우선순위 정의
class Priority:
    HIGH = 0    # 즉시 처리 필요(유저 상호작용)
    MEDIUM = 1  # 준실시간 필요(채널 관리)
    LOW = 2     # 백그라운드 작업(메시지 정리)

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
        
        # 작업 큐 시스템 초기화
        self.message_queues = {
            Priority.HIGH: asyncio.Queue(),
            Priority.MEDIUM: asyncio.Queue(),
            Priority.LOW: asyncio.Queue(),
        }
        self.worker_tasks = []
        self._init_worker_pool()
        
        # 기존 루프 시작
        self.check_channel_status.start()
        self.last_heartbeat = datetime.now()
        self.connection_monitor.start()
        
        # 메시지 배치 처리 상태
        self.batch_message_tasks = {}
        self.batch_message_process.start()

    def _init_worker_pool(self):
        """작업자 풀 초기화"""
        # 우선순위별 작업자 수
        worker_counts = {
            Priority.HIGH: 5,   # 높은 우선순위 작업용
            Priority.MEDIUM: 3, # 중간 우선순위 작업용
            Priority.LOW: 2,    # 낮은 우선순위 작업용
        }
        
        for priority, count in worker_counts.items():
            for i in range(count):
                worker = self.create_worker(priority)
                self.worker_tasks.append(worker)
                asyncio.create_task(worker, name=f"worker-{priority}-{i}")
        
        logger.info(f"작업자 풀 초기화 완료: {sum(worker_counts.values())}개 작업자 생성")

    async def create_worker(self, priority: int) -> Coroutine:
        """우선순위 큐 작업자"""
        queue = self.message_queues[priority]
        while True:
            try:
                # 큐에서 작업 가져오기
                task_data = await queue.get()
                
                try:
                    func = task_data["func"]
                    args = task_data.get("args", [])
                    kwargs = task_data.get("kwargs", {})
                    
                    # 작업 실행
                    await func(*args, **kwargs)
                except Exception as e:
                    logger.error(f"작업 처리 중 오류: {str(e)}")
                    logger.error(traceback.format_exc())
                
                # 작업 완료 표시
                queue.task_done()
            except asyncio.CancelledError:
                logger.info(f"우선순위 {priority} 작업자 종료")
                break
            except Exception as e:
                logger.error(f"작업자 루프 중 오류: {str(e)}")
                await asyncio.sleep(1)  # 오류 시 잠시 대기

    def schedule_task(self, priority: int, func: Callable, *args, **kwargs):
        """작업 스케줄링"""
        task_data = {
            "func": func,
            "args": args,
            "kwargs": kwargs
        }
        asyncio.create_task(self.message_queues[priority].put(task_data))
        return True

    async def batch_execute(self, coro_list):
        """여러 코루틴을 동시에 실행"""
        if not coro_list:
            return []
            
        try:
            # Python 3.11+ 에서는 TaskGroup 사용, 이전 버전은 gather 사용
            if hasattr(asyncio, 'TaskGroup'):
                async with asyncio.TaskGroup() as tg:
                    tasks = [tg.create_task(coro) for coro in coro_list]
                results = [task.result() for task in tasks]
            else:
                results = await asyncio.gather(*coro_list, return_exceptions=True)
                
            # 예외 처리
            for i, result in enumerate(results):
                if isinstance(result, Exception):
                    logger.error(f"배치 실행 중 오류 (작업 {i}): {str(result)}")
            
            return [r for r in results if not isinstance(r, Exception)]
        except Exception as e:
            logger.error(f"배치 실행 중 오류: {str(e)}")
            return []

    async def setup_hook(self):
        extensions = [
            "cogs.channel",
            "cogs.recruitment",
            "cogs.voice_channel",
            "cogs.deep",
            "cogs.alert",
            "cogs.chat_assistant",
            "cogs.rank"
        ]
        for ext in extensions:
            try:
                await self.load_extension(ext)
                logger.info(f"Loaded extension: {ext}")
            except Exception as e:
                logger.error(f"Failed to load extension {ext}: {e}")
        
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
        except Exception as e:
            logger.error(f"재연결 시도 중 오류 발생: {e}")

    async def on_resumed(self):
        """세션이 재개되었을 때 호출되는 이벤트"""
        logger.info("디스코드 세션이 재개되었습니다.")
        self.last_heartbeat = datetime.now()

    async def on_connect(self):
        """봇이 디스코드에 연결되었을 때 호출되는 이벤트"""
        logger.info("디스코드에 연결되었습니다.")
        self.last_heartbeat = datetime.now()

    async def on_disconnect(self):
        """봇이 디스코드와 연결이 끊겼을 때 호출되는 이벤트"""
        logger.warning("디스코드와 연결이 끊겼습니다. 자동 재연결을 시도합니다.")

    @tasks.loop(minutes=1)
    async def batch_message_process(self):
        """메시지 배치 처리 작업"""
        try:
            # 각 채널별 배치 작업 처리
            for channel_id, batch in list(self.batch_message_tasks.items()):
                if len(batch) > 0:
                    logger.info(f"채널 {channel_id}의 {len(batch)} 개 메시지 배치 처리 시작")
                    channel = self.get_channel(int(channel_id))
                    if not channel:
                        del self.batch_message_tasks[channel_id]
                        continue
                    
                    # 배치 작업 실행 후 비우기
                    await self.batch_execute(batch)
                    self.batch_message_tasks[channel_id] = []
        except Exception as e:
            logger.error(f"배치 메시지 처리 중 오류: {str(e)}")

    @batch_message_process.before_loop
    async def before_batch_message_process(self):
        """배치 처리 루프 시작 전 봇이 준비될 때까지 대기"""
        await self.wait_until_ready()

    def add_to_batch(self, channel_id, coro):
        """채널별 배치 작업에 코루틴 추가"""
        if channel_id not in self.batch_message_tasks:
            self.batch_message_tasks[channel_id] = []
        
        self.batch_message_tasks[channel_id].append(coro)
        
        # 배치 크기가 10개 이상이면 즉시 처리
        if len(self.batch_message_tasks[channel_id]) >= 10:
            self.schedule_task(
                Priority.MEDIUM, 
                self.process_channel_batch, 
                channel_id
            )

    async def process_channel_batch(self, channel_id):
        """특정 채널의 배치 작업 즉시 처리"""
        if channel_id in self.batch_message_tasks and len(self.batch_message_tasks[channel_id]) > 0:
            batch = self.batch_message_tasks[channel_id]
            self.batch_message_tasks[channel_id] = []
            await self.batch_execute(batch)

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