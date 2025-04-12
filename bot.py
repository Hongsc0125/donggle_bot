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
        self.cleanup_old_threads_and_channels.start()
        
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
        
        # 스레드 이벤트 리스너 등록
        self.add_listener(self.on_thread_delete, 'on_thread_delete')
        self.add_listener(self.on_thread_update, 'on_thread_update')
    
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
    
    async def on_thread_delete(self, thread):
        """스레드가 삭제되면 연결된 음성 채널도 삭제합니다."""
        try:
            logger.info(f"스레드 삭제 감지: {thread.name} (ID: {thread.id})")
            
            # 스레드와 연결된 모집 정보 찾기
            party_cog = self.get_cog('PartyCog')
            if not party_cog or not party_cog.db:
                logger.warning("PartyCog 또는 DB 연결을 찾을 수 없습니다.")
                return
            
            logger.info(f"스레드 {thread.id}에 연결된 모집 정보 조회 시도")
            
            # DB에서 스레드 ID로 모집 정보 조회
            recruitment = await party_cog.db["recruitments"].find_one({"thread_id": str(thread.id)})
            if not recruitment:
                logger.info(f"삭제된 스레드 {thread.id}와 연결된 모집 정보가 없습니다.")
                return
            
            logger.info(f"스레드 {thread.id}와 연결된 모집 정보 찾음: {recruitment.get('_id')}")
            
            # 음성 채널이 있는지 확인
            voice_channel_id = recruitment.get("voice_channel_id")
            if not voice_channel_id:
                logger.info(f"스레드 {thread.id}와 연결된 음성 채널이 없습니다.")
                return
            
            logger.info(f"스레드 {thread.id}와 연결된 음성 채널 발견: {voice_channel_id}")
            
            # 음성 채널 찾기
            try:
                voice_channel = thread.guild.get_channel(int(voice_channel_id))
                if voice_channel:
                    logger.info(f"스레드 {thread.id}와 연결된 음성 채널 {voice_channel.id} 삭제 시도")
                    await voice_channel.delete(reason="연결된 스레드가 삭제됨")
                    logger.info(f"음성 채널 {voice_channel.id} 삭제 완료")
                else:
                    logger.warning(f"음성 채널 {voice_channel_id}를 찾을 수 없습니다.")
            except Exception as e:
                logger.error(f"음성 채널 삭제 중 오류 발생: {e}")
                logger.error(traceback.format_exc())
            
            # 모집 정보 업데이트 (음성 채널 정보 제거)
            try:
                update_result = await party_cog.db["recruitments"].update_one(
                    {"_id": recruitment["_id"]},
                    {"$unset": {"voice_channel_id": "", "voice_channel_name": ""},
                     "$set": {"updated_at": datetime.datetime.now().isoformat()}}
                )
                logger.info(f"모집 정보에서 음성 채널 정보 제거 완료: {update_result.modified_count}개 문서 수정됨")
            except Exception as db_error:
                logger.error(f"DB 업데이트 중 오류: {db_error}")
                logger.error(traceback.format_exc())
            
        except Exception as e:
            logger.error(f"스레드 삭제 처리 중 오류 발생: {e}")
            logger.error(traceback.format_exc())
    
    async def on_thread_update(self, before, after):
        """스레드가 아카이브되면 연결된 음성 채널을 삭제합니다."""
        try:
            # 스레드가 아카이브되었는지 확인
            if not before.archived and after.archived:
                logger.info(f"스레드 아카이브 감지: {after.name} (ID: {after.id})")
                
                # 스레드와 연결된 모집 정보 찾기
                party_cog = self.get_cog('PartyCog')
                if not party_cog or not party_cog.db:
                    logger.warning("PartyCog 또는 DB 연결을 찾을 수 없습니다.")
                    return
                
                # DB에서 스레드 ID로 모집 정보 조회
                recruitment = await party_cog.db["recruitments"].find_one({"thread_id": str(after.id)})
                if not recruitment:
                    logger.info(f"아카이브된 스레드 {after.id}와 연결된 모집 정보가 없습니다.")
                    return
                
                # 음성 채널이 있는지 확인
                voice_channel_id = recruitment.get("voice_channel_id")
                if not voice_channel_id:
                    logger.info(f"스레드 {after.id}와 연결된 음성 채널이 없습니다.")
                    
                    # 음성 채널은 없지만 스레드가 아카이브되었으므로 스레드 완전 삭제 시도
                    try:
                        # 스레드 완전 삭제
                        await after.delete()
                        logger.info(f"아카이브된 스레드 {after.id} 삭제 완료")
                        
                        # 모집 정보 업데이트
                        await party_cog.db["recruitments"].update_one(
                            {"_id": recruitment["_id"]},
                            {"$set": {
                                "thread_status": "deleted",
                                "updated_at": datetime.datetime.now().isoformat()
                            }}
                        )
                    except Exception as e:
                        logger.error(f"아카이브된 스레드 삭제 중 오류 발생: {e}")
                        logger.error(traceback.format_exc())
                    
                    return
                
                # 음성 채널 찾기
                try:
                    voice_channel = after.guild.get_channel(int(voice_channel_id))
                    if voice_channel:
                        logger.info(f"스레드 {after.id}와 연결된 음성 채널 {voice_channel.id} 삭제 시도")
                        await voice_channel.delete(reason="연결된 스레드가 아카이브됨")
                        logger.info(f"음성 채널 {voice_channel.id} 삭제 완료")
                    else:
                        logger.warning(f"음성 채널 {voice_channel_id}를 찾을 수 없습니다.")
                        
                        # 음성 채널을 찾을 수 없는 경우 재시도
                        try:
                            # 채널 ID 재확인
                            all_channels = list(after.guild.channels)
                            logger.info(f"모든 채널 목록: {[c.id for c in all_channels]}")
                            
                            # 보이스 채널 직접 검색
                            for channel in all_channels:
                                if channel.id == int(voice_channel_id):
                                    logger.info(f"보이스 채널 {channel.id} 발견, 삭제 시도")
                                    await channel.delete(reason="연결된 스레드가 아카이브됨 (재시도)")
                                    logger.info(f"보이스 채널 {channel.id} 삭제 완료")
                                    break
                        except Exception as retry_error:
                            logger.error(f"보이스 채널 재시도 삭제 중 오류: {retry_error}")
                except Exception as e:
                    logger.error(f"음성 채널 삭제 중 오류 발생: {e}")
                    logger.error(traceback.format_exc())
                
                # 모집 정보 업데이트 (음성 채널 정보 제거 및 스레드 상태 업데이트)
                await party_cog.db["recruitments"].update_one(
                    {"_id": recruitment["_id"]},
                    {"$unset": {"voice_channel_id": "", "voice_channel_name": ""},
                     "$set": {"thread_status": "archived", "updated_at": datetime.datetime.now().isoformat()}}
                )
                
                # 아카이브된 스레드 완전 삭제 시도
                try:
                    await after.delete()
                    logger.info(f"아카이브된 스레드 {after.id} 삭제 완료")
                    
                    # 모집 정보 상태 업데이트
                    await party_cog.db["recruitments"].update_one(
                        {"_id": recruitment["_id"]},
                        {"$set": {"thread_status": "deleted", "updated_at": datetime.datetime.now().isoformat()}}
                    )
                except Exception as thread_delete_error:
                    logger.error(f"아카이브된 스레드 삭제 중 오류 발생: {thread_delete_error}")
        except Exception as e:
            logger.error(f"스레드 업데이트 처리 중 오류 발생: {e}")
            logger.error(traceback.format_exc())
    
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
    
    @tasks.loop(hours=2)
    async def cleanup_old_threads_and_channels(self):
        """2시간마다 오래된 스레드와 음성 채널을 정리합니다."""
        try:
            logger.info("오래된 스레드 및 음성 채널 정리 시작")
            
            # PartyCog 가져오기
            party_cog = self.get_cog('PartyCog')
            if not party_cog or not party_cog.db:
                logger.warning("PartyCog 또는 DB 연결을 찾을 수 없어 정리 작업을 건너뜁니다.")
                return
            
            # 삭제 시간이 지난 모집 정보 찾기
            now = datetime.datetime.now().isoformat()
            query = {
                "thread_delete_at": {"$lt": now},
                "thread_status": {"$in": ["active", "archived"]},
                "thread_id": {"$exists": True}
            }
            
            old_recruitments = await party_cog.db["recruitments"].find(query).to_list(None)
            logger.info(f"삭제할 오래된 스레드 {len(old_recruitments)}개 발견")
            
            delete_count = 0
            for recruitment in old_recruitments:
                try:
                    guild_id = recruitment.get("guild_id")
                    thread_id = recruitment.get("thread_id")
                    voice_channel_id = recruitment.get("voice_channel_id")
                    
                    if not guild_id or not thread_id:
                        continue
                    
                    # 길드 찾기
                    guild = self.get_guild(int(guild_id))
                    if not guild:
                        logger.warning(f"서버를 찾을 수 없음: {guild_id}")
                        continue
                    
                    # 스레드 찾기 및 삭제
                    deleted_thread = False
                    try:
                        thread = guild.get_thread(int(thread_id))
                        if thread:
                            await thread.delete()
                            logger.info(f"오래된 스레드 {thread_id} 삭제 완료")
                            deleted_thread = True
                    except discord.NotFound:
                        logger.info(f"스레드 {thread_id}가 이미 삭제되어 있습니다.")
                        deleted_thread = True
                    except Exception as thread_error:
                        logger.error(f"스레드 {thread_id} 삭제 중 오류: {thread_error}")
                    
                    # 음성 채널 찾기 및 삭제
                    if voice_channel_id:
                        try:
                            voice_channel = guild.get_channel(int(voice_channel_id))
                            if voice_channel:
                                await voice_channel.delete(reason="오래된 스레드 정리에 의한 음성 채널 삭제")
                                logger.info(f"음성 채널 {voice_channel_id} 삭제 완료")
                        except Exception as voice_error:
                            logger.error(f"음성 채널 {voice_channel_id} 삭제 중 오류: {voice_error}")
                    
                    # 모집 정보 업데이트
                    if deleted_thread:
                        await party_cog.db["recruitments"].update_one(
                            {"_id": recruitment["_id"]},
                            {"$set": {
                                "thread_status": "deleted",
                                "updated_at": datetime.datetime.now().isoformat()
                            }, "$unset": {"voice_channel_id": "", "voice_channel_name": ""}}
                        )
                        delete_count += 1
                except Exception as e:
                    logger.error(f"모집 정보 처리 중 오류 발생: {e}")
                    continue
            
            logger.info(f"총 {delete_count}개의 오래된 스레드와 음성 채널이 정리되었습니다.")
        except Exception as e:
            logger.error(f"오래된 스레드 및 음성 채널 정리 중 오류 발생: {e}")
            logger.error(traceback.format_exc())
    
    # 봇이 준비된 후에 작업 시작
    @heartbeat_logger.before_loop
    @update_presence.before_loop
    @check_connection.before_loop
    @cleanup_old_threads_and_channels.before_loop
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
